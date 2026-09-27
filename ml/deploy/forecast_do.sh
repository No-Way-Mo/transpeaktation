#!/usr/bin/env bash
# Deploy the promoted forecaster (ml/data/forecast/serving/current.json) to a DigitalOcean droplet as an HTTP service.
#
#   cd ml && bash deploy/forecast_do.sh            # create (first run) or update (later runs) and restart
#
# Needs: doctl (authenticated), ssh/scp, the key ~/.ssh/transpeaktation_do_ed25519 registered in DigitalOcean as
# "transpeaktation-laptop-deploy", FORECAST_API_TOKEN in ml/.env. Serves `python -m forecast serve` on port 8200
# (bearer token required) under systemd. To change the model: `python -m forecast promote ...` then rerun this script.
set -euo pipefail
cd "$(dirname "$0")/.."                                    # ml/

NAME=${FORECAST_DROPLET:-transpeaktation-forecast}
REGION=${FORECAST_REGION:-sfo3}
SIZE=${FORECAST_SIZE:-s-2vcpu-4gb}
KEY=${FORECAST_SSH_KEY:-$HOME/.ssh/transpeaktation_do_ed25519}
KEY_NAME=transpeaktation-laptop-deploy
PORT=8200
SSH="ssh -i $KEY -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15"

TOKEN=$(grep -m1 '^FORECAST_API_TOKEN=' .env | cut -d= -f2- | tr -d '\r')
[ -n "$TOKEN" ] || { echo "FORECAST_API_TOKEN missing in ml/.env" >&2; exit 1; }
[ -f data/forecast/serving/current.json ] || { echo "nothing promoted: python -m forecast promote ..." >&2; exit 1; }
CKPT=$(python -c "import json;print(json.load(open('data/forecast/serving/current.json'))['checkpoint'])")
DATASET=$(python -c "import json;print(json.load(open('data/forecast/serving/current.json'))['dataset_id'])")

# ---- droplet (created once, with the Python environment installed by cloud-init)
if ! doctl compute droplet list --format Name --no-header | grep -qx "$NAME"; then
  cat > /tmp/forecast_cloud_init.yaml <<'EOF'
#cloud-config
runcmd:
  - export HOME=/root
  - useradd --system --create-home --shell /usr/sbin/nologin forecast
  - curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
  - mkdir -p /opt/transpeaktation /etc/transpeaktation
  - UV_PYTHON_INSTALL_DIR=/opt/transpeaktation/python /usr/local/bin/uv python install 3.10
  - UV_PYTHON_INSTALL_DIR=/opt/transpeaktation/python /usr/local/bin/uv venv --python 3.10 /opt/transpeaktation/.venv
  - /usr/local/bin/uv pip install --python /opt/transpeaktation/.venv/bin/python torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
  - /usr/local/bin/uv pip install --python /opt/transpeaktation/.venv/bin/python numpy==1.26.4 pandas==2.2.3 scipy==1.15.1 pyarrow==23.0.1 pyyaml tzdata
  - /usr/local/bin/uv pip install --python /opt/transpeaktation/.venv/bin/python pymongo==4.10.1 dnspython==2.7.0 psycopg2-binary==2.9.10 numpy==1.26.4
  - touch /opt/transpeaktation/.env-ready
EOF
  KEY_ID=$(doctl compute ssh-key list --format ID,Name --no-header | awk -v n="$KEY_NAME" '$2==n{print $1}')
  doctl compute droplet create "$NAME" --region "$REGION" --size "$SIZE" --image ubuntu-24-04-x64 \
    --ssh-keys "$KEY_ID" --tag-names transpeaktation,forecast --user-data-file /tmp/forecast_cloud_init.yaml --wait \
    --format ID,Name,PublicIPv4 --no-header
fi
DROPLET_ID=$(doctl compute droplet list --format ID,Name --no-header | awk -v n="$NAME" '$2==n{print $1}')
IP=$(doctl compute droplet get "$DROPLET_ID" --format PublicIPv4 --no-header)

# ---- firewall: SSH from this machine only; the API port is public but token-protected
MYIP=$(curl -s https://checkip.amazonaws.com)
if ! doctl compute firewall list --format Name --no-header | grep -qx "$NAME"; then
  doctl compute firewall create --name "$NAME" --droplet-ids "$DROPLET_ID" \
    --inbound-rules "protocol:tcp,ports:22,address:$MYIP/32 protocol:tcp,ports:$PORT,address:0.0.0.0/0,address:::/0" \
    --outbound-rules "protocol:tcp,ports:all,address:0.0.0.0/0,address:::/0 protocol:udp,ports:all,address:0.0.0.0/0,address:::/0 protocol:icmp,address:0.0.0.0/0,address:::/0" \
    --format ID,Name --no-header
else
  FW=$(doctl compute firewall list --format ID,Name --no-header | awk -v n="$NAME" '$2==n{print $1}')
  doctl compute firewall add-rules "$FW" --inbound-rules "protocol:tcp,ports:22,address:$MYIP/32" >/dev/null 2>&1 || true
fi

echo "waiting for $IP (ssh + cloud-init environment)..."
for i in $(seq 1 90); do $SSH root@"$IP" test -f /opt/transpeaktation/.env-ready 2>/dev/null && break; sleep 10; done
$SSH root@"$IP" test -f /opt/transpeaktation/.env-ready

# ---- code + the promoted model + the dataset metadata the predictor reads (graph, manifest)
tar czf /tmp/forecast_bundle.tgz --exclude=__pycache__ forecast \
  data/forecast/serving/current.json "data/forecast/serving/$CKPT" \
  "data/forecast/datasets/$DATASET/graph" "data/forecast/datasets/$DATASET/manifest.json"
scp -i "$KEY" -o StrictHostKeyChecking=accept-new /tmp/forecast_bundle.tgz root@"$IP":/tmp/forecast_bundle.tgz
# live congestion maps (POST /v1/live/forecast) read/write Tiger + Mongo: their URLs go in the same env file
{ printf 'FORECAST_API_TOKEN=%s\n' "$TOKEN"; grep -E '^(TIGER_DATABASE_URL|MONGODB_URI)=' .env | tr -d '\r' || true; } \
  | $SSH root@"$IP" "umask 077 && cat > /etc/transpeaktation/forecast.env && chown root:forecast /etc/transpeaktation/forecast.env && chmod 640 /etc/transpeaktation/forecast.env"
$SSH root@"$IP" bash -s <<EOF
set -e
/opt/transpeaktation/.venv/bin/python -c "import pymongo, psycopg2" 2>/dev/null || /usr/local/bin/uv pip install \
  --python /opt/transpeaktation/.venv/bin/python pymongo==4.10.1 dnspython==2.7.0 psycopg2-binary==2.9.10 numpy==1.26.4
rm -rf /opt/transpeaktation/ml.new && mkdir -p /opt/transpeaktation/ml.new
tar xzf /tmp/forecast_bundle.tgz -C /opt/transpeaktation/ml.new
rm -rf /opt/transpeaktation/ml.old; [ -d /opt/transpeaktation/ml ] && mv /opt/transpeaktation/ml /opt/transpeaktation/ml.old
mv /opt/transpeaktation/ml.new /opt/transpeaktation/ml && chown -R forecast:forecast /opt/transpeaktation/ml
cat > /etc/systemd/system/transpeaktation-forecast.service <<UNIT
[Unit]
Description=transpeaktation forecaster (python -m forecast serve)
After=network-online.target
[Service]
User=forecast
WorkingDirectory=/opt/transpeaktation/ml
EnvironmentFile=/etc/transpeaktation/forecast.env
Environment=PYTHONPATH=/opt/transpeaktation/ml OMP_NUM_THREADS=2
ExecStart=/opt/transpeaktation/.venv/bin/python -m forecast serve --host 0.0.0.0 --port $PORT --device cpu
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload && systemctl enable --now transpeaktation-forecast && systemctl restart transpeaktation-forecast
EOF

echo "waiting for the service..."
for i in $(seq 1 60); do curl -sf -m 5 "http://$IP:$PORT/v1/health" >/dev/null && break; sleep 5; done
curl -sf "http://$IP:$PORT/v1/health" | python -c "import json,sys;d=json.load(sys.stdin);print(json.dumps({k:d[k] for k in ('status','model_version','checkpoint','roads')}))"
echo "FORECAST_API_URL=http://$IP:$PORT"
