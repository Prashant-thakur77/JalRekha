#!/usr/bin/env bash
# One-command deploy of NadiSaathi (FastAPI backend + PWA) to AWS.
#
#   scripts/deploy/deploy.sh            (or: make deploy)
#
# Steps: build PWA -> bundle working tree -> create/update the CloudFormation stack ->
# upload bundle to S3 -> (update) SSM Run Command on the instance -> verify via CloudFront.
#
# Optional env:
#   STACK_NAME (nadisaathi)  AWS_REGION (us-east-1)  INSTANCE_TYPE  USE_COOL_AMI=true|false
#   ALERT_EMAIL  BUDGET_EMAIL  BUDGET_LIMIT_USD  SKIP_WEB=1 (API-only bundle)
#   ENABLE_CLOUDFRONT=true|false  ENABLE_APIGW=true|false   (public HTTPS front door(s))
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
STACK=${STACK_NAME:-nadisaathi}
export AWS_REGION=${AWS_REGION:-us-east-1}
export AWS_DEFAULT_REGION=$AWS_REGION
CACHE=${XDG_CACHE_HOME:-$HOME/.cache}/nadisaathi
TEMPLATE=$ROOT/infra/nadisaathi.yaml
PIN_PARAM=/nadisaathi/operator_pin
DATASET_IMAGES=datasets/usgs_hivis_stage/images
DATASET_IMAGES_MAX_MB=40
T0=$(date +%s)

log()  { printf '\033[1;34m[deploy %4ss]\033[0m %s\n' "$(( $(date +%s) - T0 ))" "$*"; }
warn() { printf '\033[1;33m[deploy WARN]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[deploy FAIL]\033[0m %s\n' "$*" >&2; exit 1; }

for bin in aws tar rsync curl python3; do command -v "$bin" >/dev/null || die "missing $bin"; done
aws sts get-caller-identity --query Account --output text >/dev/null || die "AWS credentials not configured"
mkdir -p "$CACHE"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

stack_output() {
  aws cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

# ----------------------------------------------------------------- 1. PWA
# Built in a private copy of frontend/ so a running dev server or someone else's
# node_modules is never touched. A failed build falls back to the last good dist.
WEB_STATUS="none"
WEB_DIST=""
build_web() {
  command -v npm >/dev/null || { warn "npm not found"; return 1; }
  local bdir=$CACHE/frontend-build
  mkdir -p "$bdir"
  rsync -a --delete --exclude node_modules --exclude dist "$ROOT/frontend/" "$bdir/"
  local lockhash
  lockhash=$(cat "$bdir/package.json" "$bdir/package-lock.json" 2>/dev/null | sha256sum | cut -c1-16)
  if [ ! -d "$bdir/node_modules" ] || [ "$(cat "$CACHE/frontend-lock.hash" 2>/dev/null)" != "$lockhash" ]; then
    log "npm ci --legacy-peer-deps"
    (cd "$bdir" && npm ci --legacy-peer-deps --no-audit --no-fund --loglevel=error) || return 1
    echo "$lockhash" >"$CACHE/frontend-lock.hash"
  fi
  log "VITE_API_BASE=/api npm run build"
  rm -rf "$WORK/dist"
  (cd "$bdir" && VITE_API_BASE=/api npm run build -- --outDir "$WORK/dist" --emptyOutDir) >"$WORK/web-build.log" 2>&1 \
    || { tail -n 25 "$WORK/web-build.log" >&2; return 1; }
  [ -f "$WORK/dist/index.html" ] || return 1
  rm -rf "$CACHE/web-dist.new" && cp -a "$WORK/dist" "$CACHE/web-dist.new"
  rm -rf "$CACHE/web-dist" && mv "$CACHE/web-dist.new" "$CACHE/web-dist"
  date -u +%FT%TZ >"$CACHE/web-dist.built"
}

if [ "${SKIP_WEB:-0}" = 1 ]; then
  WEB_STATUS="skipped (SKIP_WEB=1): API-only"
elif build_web; then
  WEB_STATUS="fresh build $(cat "$CACHE/web-dist.built")"
  WEB_DIST=$CACHE/web-dist
elif [ -f "$CACHE/web-dist/index.html" ]; then
  WEB_STATUS="FALLBACK: frontend build failed, using last good dist from $(cat "$CACHE/web-dist.built" 2>/dev/null || echo unknown)"
  WEB_DIST=$CACHE/web-dist
  warn "$WEB_STATUS"
else
  WEB_STATUS="FALLBACK: frontend build failed and no previous dist: API-only deploy"
  warn "$WEB_STATUS"
fi
log "web: $WEB_STATUS"

# -------------------------------------------------------------- 2. bundle
log "bundling working tree"
STAGE=$WORK/stage
mkdir -p "$STAGE"
excludes=(
  --exclude=.git --exclude=node_modules --exclude=.venv --exclude=__pycache__ --exclude='*.pyc'
  --exclude=.pytest_cache --exclude=.ruff_cache --exclude=.mypy_cache --exclude=.uv-cache
  --exclude=/demo-artifacts --exclude=/android
  --exclude=/frontend  # sources stay local; the built PWA ships as web/dist
  --exclude=/ANALYSIS.md --exclude=/PLAN.md --exclude=/LOOP.md --exclude=/AGENTS.md --exclude=/.rtk
  --exclude='/backend/data/*.db' --exclude=/backend/data/models --exclude=/backend/data/litert-cache
  --exclude=/backend/data/uploads --exclude=/backend/data/logs --exclude=/backend/data/whisper-models
  --exclude=/backend/data/ollama-models
  # secrets never leave the machine
  --exclude=.env --exclude='.env.*' --exclude='*.pem' --exclude='*.key' --exclude='*.p12'
  --exclude='*.keystore' --exclude=secrets --exclude='credentials*.json' --exclude='service-account*.json'
)
img_mb=$(du -sm "$ROOT/$DATASET_IMAGES" 2>/dev/null | cut -f1 || echo 0)
if [ "${img_mb:-0}" -gt "$DATASET_IMAGES_MAX_MB" ]; then
  excludes+=(--exclude="/$DATASET_IMAGES")
  log "excluding $DATASET_IMAGES (${img_mb} MB > ${DATASET_IMAGES_MAX_MB} MB)"
else
  log "including $DATASET_IMAGES (${img_mb} MB)"
fi
rsync -a "${excludes[@]}" "$ROOT/" "$STAGE/"
mkdir -p "$STAGE/web"
[ -n "$WEB_DIST" ] && cp -a "$WEB_DIST" "$STAGE/web/dist"
echo "$WEB_STATUS" >"$STAGE/web/BUILD_STATUS"
date -u +%FT%TZ >"$STAGE/BUNDLE_BUILT_AT"
BUNDLE=$WORK/bundle.tar.gz
tar -C "$STAGE" -czf "$BUNDLE" .
log "bundle $(du -h "$BUNDLE" | cut -f1)"

# ----------------------------------------------------- 3. operator PIN (SSM)
if ! aws ssm get-parameter --name "$PIN_PARAM" >/dev/null 2>&1; then
  pin=$(python3 -c 'import secrets; print(f"{secrets.randbelow(10**6):06d}")')
  aws ssm put-parameter --name "$PIN_PARAM" --type SecureString --value "$pin" \
    --description "NadiSaathi operator PIN" >/dev/null
  unset pin
  log "created SecureString $PIN_PARAM"
fi

# ------------------------------------------------------------ 4. stack
STACK_EXISTED=0
status=$(aws cloudformation describe-stacks --stack-name "$STACK" --query 'Stacks[0].StackStatus' --output text 2>/dev/null || true)
case "$status" in
  "") ;;
  ROLLBACK_COMPLETE) die "stack $STACK is ROLLBACK_COMPLETE; run make destroy first" ;;
  *_IN_PROGRESS) die "stack $STACK is $status; wait and retry" ;;
  *) STACK_EXISTED=1 ;;
esac

params=()
[ -n "${INSTANCE_TYPE:-}" ] && params+=("InstanceType=$INSTANCE_TYPE")
[ -n "${USE_COOL_AMI:-}" ] && params+=("UseCoolAmi=$USE_COOL_AMI")
[ -n "${ALERT_EMAIL+x}" ] && params+=("AlertEmail=$ALERT_EMAIL")
[ -n "${BUDGET_EMAIL+x}" ] && params+=("BudgetEmail=$BUDGET_EMAIL")
[ -n "${BUDGET_LIMIT_USD:-}" ] && params+=("BudgetLimitUsd=$BUDGET_LIMIT_USD")
[ -n "${ENABLE_CLOUDFRONT:-}" ] && params+=("EnableCloudFront=$ENABLE_CLOUDFRONT")
[ -n "${ENABLE_APIGW:-}" ] && params+=("EnableApiGateway=$ENABLE_APIGW")
if [ "$STACK_EXISTED" = 0 ] || [ "${ENABLE_APIGW:-}" = true ]; then
  # Default-VPC subnets in AZs that actually offer the instance type.
  itype=${INSTANCE_TYPE:-c8g.xlarge}
  azs=$(aws ec2 describe-instance-type-offerings --location-type availability-zone \
          --filters Name=instance-type,Values="$itype" --query 'InstanceTypeOfferings[].Location' --output text | tr '\t' ' ')
  subnets=$(aws ec2 describe-subnets --filters Name=default-for-az,Values=true \
             --query 'Subnets[].[AvailabilityZone,SubnetId]' --output text \
           | sort | awk -v azs=" $azs " 'index(azs, " " $1 " ") {print $2}')
  [ -n "$subnets" ] || die "no default subnet offers $itype"
  [ "$STACK_EXISTED" = 0 ] && params+=("SubnetId=$(head -n1 <<<"$subnets")")
  params+=("VpcLinkSubnetIds=$(paste -sd, <<<"$subnets")")
fi

log "cloudformation deploy ($([ "$STACK_EXISTED" = 1 ] && echo update || echo create)) ${params[*]:-}"
aws cloudformation deploy --stack-name "$STACK" --template-file "$TEMPLATE" \
  --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset \
  --tags app=nadisaathi \
  ${params[@]:+--parameter-overrides "${params[@]}"} \
  || { aws cloudformation describe-stack-events --stack-name "$STACK" --max-items 15 \
         --query 'StackEvents[?contains(ResourceStatus, `FAILED`)].[LogicalResourceId,ResourceStatusReason]' --output text >&2; die "stack deploy failed"; }

BUCKET=$(stack_output BucketName)
INSTANCE=$(stack_output InstanceId)
CF_URL=$(stack_output PublicUrl)
LOG_GROUP=$(stack_output LogGroupName)

# ----------------------------------------------------------- 5. upload
log "upload s3://$BUCKET/deploy/bundle.tar.gz"
aws s3 cp --only-show-errors "s3://$BUCKET/deploy/bundle.tar.gz" "s3://$BUCKET/deploy/bundle.prev.tar.gz" 2>/dev/null || true
aws s3 cp --only-show-errors "$BUNDLE" "s3://$BUCKET/deploy/bundle.tar.gz"

# ----------------------------------------------- 6. roll out on the instance
if [ "$STACK_EXISTED" = 1 ]; then
  log "waiting for SSM agent on $INSTANCE"
  for _ in $(seq 1 60); do
    ping=$(aws ssm describe-instance-information --filters Key=InstanceIds,Values="$INSTANCE" \
             --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || true)
    [ "$ping" = Online ] && break
    sleep 5
  done
  [ "$ping" = Online ] || die "instance $INSTANCE not reachable via SSM"
  log "ssm send-command: nadisaathi-deploy"
  cmd_id=$(aws ssm send-command --instance-ids "$INSTANCE" --document-name AWS-RunShellScript \
    --comment "nadisaathi deploy" --timeout-seconds 1200 \
    --parameters 'commands=["/usr/local/bin/nadisaathi-deploy"],executionTimeout=["1200"]' \
    --cloud-watch-output-config "CloudWatchOutputEnabled=true,CloudWatchLogGroupName=$LOG_GROUP" \
    --query Command.CommandId --output text)
  while :; do
    st=$(aws ssm get-command-invocation --command-id "$cmd_id" --instance-id "$INSTANCE" \
           --query Status --output text 2>/dev/null || echo Pending)
    case "$st" in Pending|InProgress|Delayed) sleep 5 ;; *) break ;; esac
  done
  aws ssm get-command-invocation --command-id "$cmd_id" --instance-id "$INSTANCE" \
    --query StandardOutputContent --output text | tail -n 8
  if [ "$st" != Success ]; then
    aws ssm get-command-invocation --command-id "$cmd_id" --instance-id "$INSTANCE" \
      --query StandardErrorContent --output text | tail -n 30 >&2
    die "remote deploy $st (command $cmd_id)"
  fi
  wait_s=300
else
  log "first boot: instance installs from the bundle (typically 4-8 min)"
  wait_s=1500
fi

# -------------------------------------------------------------- 7. verify
log "verifying $CF_URL/api/health"
deadline=$(( $(date +%s) + wait_s ))
until body=$(curl -fsS -m 10 "$CF_URL/api/health" 2>/dev/null) && grep -q '"status":"ok"' <<<"$body"; do
  [ "$(date +%s)" -lt "$deadline" ] || die "health check did not pass within ${wait_s}s (see: make logs)"
  sleep 10
done
log "health: $body"
lat=$(curl -s -o /dev/null -m 10 -w '%{time_total}' "$CF_URL/api/health")
sites=$(curl -fsS -m 10 "$CF_URL/api/sites" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d))' 2>/dev/null || echo "?")
root_ok=$(curl -fsS -m 10 "$CF_URL/" 2>/dev/null | grep -qi '<div id="root"' && echo yes || echo no)
log "api/sites: $sites sites | / serves PWA: $root_ok | health latency: ${lat}s"
[ "$root_ok" = yes ] || [ -z "$WEB_DIST" ] || warn "PWA did not render at /"

cat <<EOF

  NadiSaathi deployed in $(( $(date +%s) - T0 ))s
  URL        $CF_URL
  Instance   $INSTANCE ($(stack_output InstanceType), $(stack_output AmiId))
  Web        $WEB_STATUS
  PIN        SSM SecureString $PIN_PARAM (aws ssm get-parameter --name $PIN_PARAM --with-decryption)
  Dashboard  $(stack_output DashboardUrl)
EOF
