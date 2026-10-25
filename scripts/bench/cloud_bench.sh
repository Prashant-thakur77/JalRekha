#!/usr/bin/env bash
# Run bench/cool_bench.py on a fresh, temporary EC2 instance and fetch the JSON.
#
#   scripts/bench/cloud_bench.sh B   # stock OpenCV 5 wheel on Graviton4 c8g.xlarge
#   scripts/bench/cloud_bench.sh C   # stock OpenCV 5 wheel on x86 c7i.xlarge
#   scripts/bench/cloud_bench.sh A   # COOL AMI (OpenCV 5 + KleidiCV) on c8g.xlarge (needs the Marketplace subscription)
#
# Same 4 vCPUs, same frames, same pipeline. The instance runs the benchmark from
# user-data, uploads bench/results/<label>.json to the stack bucket and powers
# off (shutdown behaviour = terminate), so nothing is left running.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
CFG=${1:?usage: cloud_bench.sh A|B|C}
STACK=${STACK_NAME:-nadisaathi}
export AWS_REGION=${AWS_REGION:-us-east-1} AWS_DEFAULT_REGION=${AWS_REGION:-us-east-1}
COOL_AMI=${COOL_AMI:-ami-01db31139bc5615d8}   # COOL-Graviton4-v2 (Marketplace)
REPEATS=${REPEATS:-5}

case "$CFG" in
  A) LABEL=A-cool-c8g.xlarge; ITYPE=c8g.xlarge; AMI=$COOL_AMI; MODE=system; PRICE=${PRICE_A:-0.15952}; FEE=${COOL_FEE:-0} ;;
  B) LABEL=B-stock-wheel-c8g.xlarge; ITYPE=c8g.xlarge; MODE=wheel; PRICE=0.15952; FEE=0
     AMI=$(aws ssm get-parameter --name /aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id --query Parameter.Value --output text) ;;
  C) LABEL=C-stock-wheel-c7i.xlarge; ITYPE=c7i.xlarge; MODE=wheel; PRICE=0.1785; FEE=0
     AMI=$(aws ssm get-parameter --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id --query Parameter.Value --output text) ;;
  *) echo "unknown config $CFG"; exit 2 ;;
esac

out() { aws cloudformation describe-stack-resources --stack-name "$STACK" --logical-resource-id "$1" --query 'StackResources[0].PhysicalResourceId' --output text; }
BUCKET=$(aws cloudformation describe-stacks --stack-name "$STACK" --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue" --output text)
PROFILE=$(out InstanceProfile)
read -r SUBNET SG < <(aws ec2 describe-instances --instance-ids "$(out Instance)" --query 'Reservations[0].Instances[0].[SubnetId,SecurityGroups[0].GroupId]' --output text)
echo "[bench] $LABEL on $ITYPE ($AMI), mode=$MODE, bucket=$BUCKET"

# Fresh code bundle: just what the benchmark needs.
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
tar -C "$ROOT" -czf "$TMP/bench.tgz" bench/cool_bench.py backend/src/jalrekha/__init__.py backend/src/jalrekha/vision backend/src/jalrekha/core
aws s3 cp --only-show-errors "$TMP/bench.tgz" "s3://$BUCKET/bench/bench-src.tgz"

cat >"$TMP/ud.sh" <<EOF
#!/bin/bash
exec >/var/log/nadisaathi-bench.log 2>&1
set -x
export HOME=/root DEBIAN_FRONTEND=noninteractive
apt-get update -y && apt-get install -y unzip curl python3-venv python3-pip >/dev/null
command -v aws || (curl -sSL "https://awscli.amazonaws.com/awscli-exe-linux-\$(uname -m).zip" -o /tmp/a.zip && unzip -q /tmp/a.zip -d /tmp && /tmp/aws/install)
mkdir -p /opt/b && cd /opt/b
aws s3 cp s3://$BUCKET/bench/bench-src.tgz . && tar xzf bench-src.tgz
if [ "$MODE" = wheel ]; then
  python3 -m venv /opt/venv && /opt/venv/bin/pip install -q "numpy>=1.26,<3" "opencv-python-headless==5.0.0.93" boto3
else
  # COOL: use the AMI's own OpenCV 5 + KleidiCV build (system site-packages), never the pip wheel.
  python3 -m venv --system-site-packages /opt/venv && /opt/venv/bin/pip install -q boto3 || true
  /opt/venv/bin/python -c "import numpy" 2>/dev/null || /opt/venv/bin/pip install -q "numpy>=1.26,<3"
fi
/opt/venv/bin/python -c "import cv2,sys; print('cv2', cv2.__version__, cv2.__file__)"
/opt/venv/bin/python -c "import sys; sys.path.insert(0,'backend/src'); import jalrekha.vision.models as m; [m.fetch(k) for k in m.MODELS]" || true
PYTHONPATH=backend/src JALREKHA_DATA_DIR=/opt/b/data /opt/venv/bin/python bench/cool_bench.py --label $LABEL --out /opt/b/$LABEL.json --repeats $REPEATS --price $PRICE --software-fee $FEE
aws s3 cp /opt/b/$LABEL.json s3://$BUCKET/bench/results/$LABEL.json
aws s3 cp /var/log/nadisaathi-bench.log s3://$BUCKET/bench/results/$LABEL.log
shutdown -h now
EOF

IID=$(aws ec2 run-instances --image-id "$AMI" --instance-type "$ITYPE" --subnet-id "$SUBNET" --security-group-ids "$SG" \
  --iam-instance-profile Name="$PROFILE" --instance-initiated-shutdown-behavior terminate \
  --metadata-options HttpTokens=required,HttpEndpoint=enabled \
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":20,"VolumeType":"gp3","DeleteOnTermination":true}}]' \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=nadisaathi-bench-$CFG},{Key=Project,Value=nadisaathi}]" \
  --user-data "file://$TMP/ud.sh" --query 'Instances[0].InstanceId' --output text)
echo "[bench] launched $IID; waiting for s3://$BUCKET/bench/results/$LABEL.json"
aws s3 rm --only-show-errors "s3://$BUCKET/bench/results/$LABEL.json" || true
for i in $(seq 1 120); do
  if aws s3 ls "s3://$BUCKET/bench/results/$LABEL.json" >/dev/null 2>&1; then break; fi
  sleep 15
done
mkdir -p "$ROOT/bench/results"
aws s3 cp --only-show-errors "s3://$BUCKET/bench/results/$LABEL.json" "$ROOT/bench/results/$LABEL.json" || { echo "[bench] no result; log:"; aws s3 cp "s3://$BUCKET/bench/results/$LABEL.log" - | tail -40; }
aws s3 cp --only-show-errors "s3://$BUCKET/bench/results/$LABEL.log" "$ROOT/bench/results/$LABEL.log" || true
aws ec2 terminate-instances --instance-ids "$IID" >/dev/null 2>&1 || true
echo "[bench] done: bench/results/$LABEL.json (instance $IID terminated)"
