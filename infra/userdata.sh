#!/bin/bash
# NadiSaathi instance provisioner (Ubuntu 24.04 arm64).
#
# Shipped inside the code bundle and run as root by /usr/local/bin/nadisaathi-deploy,
# which the EC2 UserData installs. It runs on first boot and again on every update
# (deploy.sh -> SSM Run Command), so every step is idempotent.
#
#   usage: userdata.sh <extracted-bundle-dir>
set -euo pipefail

SRC=${1:?usage: userdata.sh <extracted-bundle-dir>}
set -a; . /etc/nadisaathi/stack.env; set +a

APP=/opt/nadisaathi/app          # code (replaced on each deploy)
VENV=/opt/nadisaathi/venv        # Python env (kept across deploys, synced from uv.lock)
DATA=/var/lib/nadisaathi         # SQLite DBs, uploads, model caches (persistent)
UV_VERSION=0.10.9
SVC=nadisaathi
log() { echo "[nadisaathi $(date -u +%H:%M:%S)] $*"; }

export DEBIAN_FRONTEND=noninteractive

# ---------------------------------------------------------------- packages
log "system packages"
want=(ffmpeg espeak-ng git curl unzip rsync ca-certificates rsyslog python3)
need=()
for p in "${want[@]}"; do dpkg -s "$p" >/dev/null 2>&1 || need+=("$p"); done
if ((${#need[@]})); then
  apt-get update -y
  apt-get install -y --no-install-recommends "${need[@]}"
fi

if [ ! -x /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl ]; then
  log "CloudWatch agent"
  curl -fsSL -o /tmp/amazon-cloudwatch-agent.deb \
    https://amazoncloudwatch-agent.s3.amazonaws.com/ubuntu/arm64/latest/amazon-cloudwatch-agent.deb
  dpkg -i -E /tmp/amazon-cloudwatch-agent.deb
fi

if ! /usr/local/bin/uv --version 2>/dev/null | grep -q "$UV_VERSION"; then
  log "uv $UV_VERSION"
  curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" \
    | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
fi

# ------------------------------------------------------------- user + dirs
id "$SVC" >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin "$SVC"
install -d -m 0755 /opt/nadisaathi
install -d -m 0750 -o "$SVC" -g "$SVC" "$DATA"
install -d -m 0755 -o syslog -g adm /var/log/nadisaathi

# --------------------------------------------------------------------- code
log "code -> $APP"
rsync -a --delete "$SRC/" "$APP/"
chown -R root:root "$APP"
chmod -R a+rX "$APP"

# historical-context store ships with the repo; seed it into the data dir once.
if [ -f "$APP/backend/data/historical_context.sqlite" ] && [ ! -f "$DATA/historical_context.sqlite" ]; then
  install -m 0640 -o "$SVC" -g "$SVC" "$APP/backend/data/historical_context.sqlite" "$DATA/"
fi

# ----------------------------------------------------------------- Python
log "uv sync --frozen"
export UV_PROJECT_ENVIRONMENT="$VENV" UV_CACHE_DIR=/var/cache/uv UV_PYTHON_INSTALL_DIR=/opt/nadisaathi/python
/usr/local/bin/uv sync --frozen --no-dev --compile-bytecode --project "$APP/backend"
"$VENV/bin/python" -c "import cv2, jalrekha; print('opencv', cv2.__version__)"

ASR=0
if "$VENV/bin/python" -c "import faster_whisper" 2>/dev/null; then ASR=1; fi
log "faster-whisper importable: $ASR"

# --------------------------------------------------------------- env file
ANTHROPIC_KEY=$(aws ssm get-parameter --name /nadisaathi/anthropic_api_key --with-decryption --query Parameter.Value --output text 2>/dev/null || true)
[ "$ANTHROPIC_KEY" = "None" ] && ANTHROPIC_KEY=""
OPPINS=$(aws ssm get-parameter --name /nadisaathi/operator_pins --with-decryption --query Parameter.Value --output text 2>/dev/null || true)
[ "$OPPINS" = "None" ] && OPPINS=""
CAMKEY=$(aws ssm get-parameter --name /nadisaathi/camera_key --with-decryption --query Parameter.Value --output text 2>/dev/null || true)
[ "$CAMKEY" = "None" ] && CAMKEY=""
PIN=$(aws ssm get-parameter --name /nadisaathi/operator_pin --with-decryption \
        --query Parameter.Value --output text 2>/dev/null || true)
if [ -z "$PIN" ] || [ "$PIN" = "None" ]; then
  log "WARNING: /nadisaathi/operator_pin not readable; operator routes will use the app default"
fi

WEB_DIST="$APP/web/dist"
tmp=$(mktemp)
cat >"$tmp" <<EOF
# Managed by infra/userdata.sh - regenerated on every deploy.
JALREKHA_DATA_DIR=$DATA
JALREKHA_WEB_DIST=$WEB_DIST
JALREKHA_LLM_ENABLED=0
JALREKHA_MULTIMODAL_ENABLED=0
JALREKHA_NODE_PROVIDER=ollama
JALREKHA_ASR_ENABLED=$ASR
JALREKHA_VISION_MODE=inprocess
JALREKHA_OPERATOR_PIN=$PIN
NADISAATHI_CAMERA_KEY=$CAMKEY
JALREKHA_OPERATOR_PINS=$OPPINS
NADISAATHI_STACK=$NADISAATHI_STACK
NADISAATHI_S3_BUCKET=$NADISAATHI_S3_BUCKET
NADISAATHI_SNS_TOPIC_ARN=$NADISAATHI_SNS_TOPIC_ARN
NADISAATHI_BEDROCK_MODEL=us.amazon.nova-lite-v1:0
NADISAATHI_TTS_ENABLED=1
NADISAATHI_AWS_ENABLED=1
JALREKHA_PROTECT_WRITES=1
JALREKHA_VOLUNTEER_IMAGE_ENABLED=1
ANTHROPIC_API_KEY=$ANTHROPIC_KEY
JALREKHA_NODE_PROFILE=aws-graviton-cloud
AWS_REGION=$AWS_REGION
AWS_DEFAULT_REGION=$AWS_REGION
HF_HOME=$DATA/hf
HOME=$DATA
PYTHONUNBUFFERED=1
EOF
[ -n "$PIN" ] && [ "$PIN" != "None" ] || sed -i '/^JALREKHA_OPERATOR_PIN=/d' "$tmp"
[ -n "$CAMKEY" ] || sed -i '/^NADISAATHI_CAMERA_KEY=/d' "$tmp"
[ -n "$OPPINS" ] || sed -i '/^JALREKHA_OPERATOR_PINS=/d' "$tmp"
[ -n "$ANTHROPIC_KEY" ] || sed -i '/^ANTHROPIC_API_KEY=/d' "$tmp"
install -m 0640 -o root -g "$SVC" "$tmp" /etc/nadisaathi.env
rm -f "$tmp"

# ----------------------------------------------------- OpenCV ONNX models
# YuNet face/plate, ALIKED, LightGlue (~55 MB, SHA-1 checked) into $DATA/models/opencv.
# Runs as the service user with the service env; already-present files are kept.
log "fetching OpenCV models"
if ! systemd-run --quiet --wait --pipe --collect -p User="$SVC" -p Group="$SVC" \
     -p EnvironmentFile=/etc/nadisaathi.env -p WorkingDirectory="$APP/backend" \
     "$VENV/bin/python" -m jalrekha.vision.models; then
  log "WARNING: OpenCV model fetch failed; the vision pipeline falls back to the repo path if present"
fi

# ------------------------------------------- original demo clip (USGS, public domain)
# Kept in the data dir so redeploys do not download it again; fixtures/media links to it.
mkdir -p "$DATA/fixtures-media" "$DATA/fixtures-frames"
chown -R "$SVC:$SVC" "$DATA/fixtures-media" "$DATA/fixtures-frames"
mkdir -p "$APP/fixtures"
ln -sfn "$DATA/fixtures-media" "$APP/fixtures/media"
ln -sfn "$DATA/fixtures-frames" "$APP/fixtures/frames"
if ! systemd-run --quiet --wait --pipe --collect -p User="$SVC" -p Group="$SVC" \
     -p WorkingDirectory="$APP" "$VENV/bin/python" scripts/fetch_demo_assets.py; then
  log "WARNING: demo clip fetch failed; /api/sites/{id}/sample-node-analysis will return 404"
fi

# ------------------------------------------------------------------ systemd
cat >/etc/systemd/system/$SVC.service <<EOF
[Unit]
Description=NadiSaathi API + PWA
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SVC
Group=$SVC
EnvironmentFile=/etc/nadisaathi.env
WorkingDirectory=$APP/backend
# Seeding is an idempotent upsert; a failure must not keep the API down.
ExecStartPre=-$VENV/bin/python -m jalrekha.scripts.seed
ExecStart=$VENV/bin/uvicorn jalrekha.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=*
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal
SyslogIdentifier=$SVC
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=full
ProtectHome=yes
ReadWritePaths=$DATA
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

# journald -> rsyslog -> /var/log/nadisaathi/app.log -> CloudWatch agent
cat >/etc/rsyslog.d/30-nadisaathi.conf <<'EOF'
if $programname == 'nadisaathi' then {
  action(type="omfile" file="/var/log/nadisaathi/app.log" fileOwner="syslog" fileGroup="adm" fileCreateMode="0640")
  stop
}
EOF
cat >/etc/logrotate.d/nadisaathi <<'EOF'
/var/log/nadisaathi/*.log {
  daily
  rotate 3
  compress
  missingok
  notifempty
  postrotate
    /usr/lib/rsyslog/rsyslog-rotate
  endscript
}
EOF
systemctl restart rsyslog

# ------------------------------------------------------- CloudWatch agent
cat >/opt/aws/amazon-cloudwatch-agent/etc/nadisaathi.json <<EOF
{
  "agent": { "metrics_collection_interval": 60, "run_as_user": "root" },
  "metrics": {
    "namespace": "CWAgent",
    "append_dimensions": { "InstanceId": "\${aws:InstanceId}" },
    "metrics_collected": {
      "mem": { "measurement": ["mem_used_percent"] },
      "disk": { "measurement": ["used_percent"], "resources": ["/"] }
    }
  },
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          { "file_path": "/var/log/nadisaathi/app.log", "log_group_name": "$NADISAATHI_LOG_GROUP", "log_stream_name": "{instance_id}/app" },
          { "file_path": "/var/log/nadisaathi-bootstrap.log", "log_group_name": "$NADISAATHI_LOG_GROUP", "log_stream_name": "{instance_id}/bootstrap" },
          { "file_path": "/var/log/cloud-init-output.log", "log_group_name": "$NADISAATHI_LOG_GROUP", "log_stream_name": "{instance_id}/cloud-init" }
        ]
      }
    }
  }
}
EOF
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 \
  -c file:/opt/aws/amazon-cloudwatch-agent/etc/nadisaathi.json -s >/dev/null

# ------------------------------------------------------------------- start
systemctl daemon-reload
systemctl enable "$SVC" >/dev/null 2>&1
systemctl restart "$SVC"

log "waiting for local health"
for _ in $(seq 1 60); do
  if curl -fsS -m 3 http://127.0.0.1:8000/api/health >/dev/null; then
    log "healthy: $(curl -fsS -m 3 http://127.0.0.1:8000/api/health)"
    [ -f "$APP/web/BUILD_STATUS" ] && log "web: $(cat "$APP/web/BUILD_STATUS")"
    exit 0
  fi
  sleep 2
done
log "service did not become healthy"
journalctl -u "$SVC" -n 80 --no-pager || true
exit 1
