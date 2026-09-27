#!/usr/bin/env bash
# Deploy the coordinated-routing service (the load balancer) next to the forecaster on the DigitalOcean droplet
# made by deploy/forecast_do.sh. Run that script first (it ships forecast/serve.py + forecast/live.py and the DB URLs).
#
#   cd ml && bash deploy/coordination_do.sh                 # LIVE input (default), health-gated, rolls back on failure
#   cd ml && COORDINATION_INPUT=replay bash deploy/coordination_do.sh     # the labeled replay demo instead
#
# live   (configs/coordinated_routing_live.yaml): a customer request whose congestion map is over a bucket old asks the
#        forecaster for the newest one; the forecaster builds it from Tiger traffic_metrics + Mongo closures/events
#        once per 10-min bucket and writes it to Tiger prediction_metrics + Mongo forecast_runs; routing reads it there.
# replay (configs/coordinated_routing_deploy.yaml): one held-out recorded synthetic run under a replay clock.
# Selector: heuristic by default, batch (CP-SAT) per request or via config. Port 8100, bearer token
# COORDINATION_API_TOKEN (ml/.env; generated on first run), reachable only from the app droplet and this machine.
# State (ledger sqlite, replay session) lives in /var/lib/transpeaktation/coordination and survives updates.
set -euo pipefail
cd "$(dirname "$0")/.."                                    # ml/

NAME=${FORECAST_DROPLET:-transpeaktation-forecast}
APP_DROPLET=${APP_DROPLET:-transpeaktation}
KEY=${FORECAST_SSH_KEY:-$HOME/.ssh/transpeaktation_do_ed25519}
PORT=8100
INPUT=${COORDINATION_INPUT:-live}
RUN=b3_main_portola_full_f025_s0_event
SSH="ssh -i $KEY -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15"
PY=${PYTHON:-python}
case "$INPUT" in
  live) CONFIG=configs/coordinated_routing_live.yaml ;;
  replay) CONFIG=configs/coordinated_routing_deploy.yaml ;;
  *) echo "COORDINATION_INPUT must be live or replay" >&2; exit 1 ;;
esac

touch .env
if ! grep -q '^COORDINATION_API_TOKEN=.' .env; then
  sed -i '/^COORDINATION_API_TOKEN=/d' .env
  printf 'COORDINATION_API_TOKEN=%s\n' "$(openssl rand -hex 32)" >> .env
  echo "generated COORDINATION_API_TOKEN in ml/.env"
fi
TOKEN=$(grep -m1 '^COORDINATION_API_TOKEN=' .env | cut -d= -f2- | tr -d '\r')
FTOKEN=$(grep -m1 '^FORECAST_API_TOKEN=' .env | cut -d= -f2- | tr -d '\r')
[ -n "$FTOKEN" ] || { echo "FORECAST_API_TOKEN missing in ml/.env (deploy/forecast_do.sh first)" >&2; exit 1; }
DBENV=$(grep -E '^(TIGER_DATABASE_URL|MONGODB_URI)=' .env | tr -d '\r' || true)
if [ "$INPUT" = live ] && [ "$(printf '%s\n' "$DBENV" | grep -c .)" -ne 2 ]; then
  echo "live input needs TIGER_DATABASE_URL and MONGODB_URI in ml/.env" >&2; exit 1
fi
EXTRA=()
if [ "$INPUT" = replay ]; then
  [ -f "data/coordination/replay/$RUN.parquet" ] || {
    echo "package the replay run first: python -m coordination replay-context --run $RUN" >&2; exit 1; }
  EXTRA=("data/coordination/replay/$RUN.parquet" "data/coordination/replay/$RUN.context.json")
fi

DROPLET_ID=$(doctl compute droplet list --format ID,Name --no-header | awk -v n="$NAME" '$2==n{print $1}')
[ -n "$DROPLET_ID" ] || { echo "droplet $NAME not found: run deploy/forecast_do.sh first" >&2; exit 1; }
IP=$(doctl compute droplet get "$DROPLET_ID" --format PublicIPv4 --no-header)
APP_ID=$(doctl compute droplet list --format ID,Name --no-header | awk -v n="$APP_DROPLET" '$2==n{print $1}')
APP_IP=$(doctl compute droplet get "$APP_ID" --format PublicIPv4 --no-header)

# ---- firewall: 8100 only from the app droplet (the API will call it) and this machine; SSH from this machine
MYIP=$(curl -s https://checkip.amazonaws.com)
FW=$(doctl compute firewall list --format ID,Name --no-header | awk -v n="$NAME" '$2==n{print $1}')
doctl compute firewall add-rules "$FW" --inbound-rules \
  "protocol:tcp,ports:22,address:$MYIP/32 protocol:tcp,ports:$PORT,address:$APP_IP/32 protocol:tcp,ports:$PORT,address:$MYIP/32" \
  >/dev/null 2>&1 || true

# ---- preflight (live): the droplet must reach both databases before anything is replaced
if [ "$INPUT" = live ]; then
  printf '%s\n' "$DBENV" | $SSH root@"$IP" 'set -a; . /dev/stdin; set +a; /opt/transpeaktation/.venv/bin/python -c "
import os, sys, psycopg2, pymongo
try:
    c = psycopg2.connect(os.environ[\"TIGER_DATABASE_URL\"], connect_timeout=15); c.close()
    pymongo.MongoClient(os.environ[\"MONGODB_URI\"], serverSelectionTimeoutMS=15000).admin.command(\"ping\")
except Exception as e:
    sys.exit(f\"database unreachable from the droplet: {type(e).__name__}: {str(e)[:200]}\")
print(\"preflight: Tiger + Mongo reachable\")"' || {
    echo "(an Atlas TLS 'internal error' means this droplet's IP $IP is not in Atlas Network Access)" >&2; exit 1; }
fi

# ---- bundle: code + config + the network artifacts routing reads (+ the packaged replay run)
tar czf /tmp/coordination_bundle.tgz --exclude=__pycache__ coordination "$CONFIG" \
  data/sf_citywide/net_v3/network.json data/sf_citywide/net_v3/crosswalk.csv data/sf_citywide/net_v3/arcs_c90.json \
  data/sf_citywide/net_v3/patch.con.xml data/sf_citywide/net_v3/net_c90.net.xml \
  data/sf_citywide/batches/b3_verify/export/segments.parquet data/sf_citywide/prepared/patch.json "${EXTRA[@]}"
echo "bundle $(du -h /tmp/coordination_bundle.tgz | cut -f1)"
scp -i "$KEY" -o StrictHostKeyChecking=accept-new /tmp/coordination_bundle.tgz root@"$IP":/tmp/coordination_bundle.tgz
{ printf 'COORDINATION_API_TOKEN=%s\nFORECAST_API_TOKEN=%s\n' "$TOKEN" "$FTOKEN"; [ "$INPUT" = live ] && printf '%s\n' "$DBENV"; } \
  | $SSH root@"$IP" "umask 077 && (id coordination >/dev/null 2>&1 || useradd --system --create-home \
     --shell /usr/sbin/nologin coordination) && cat > /etc/transpeaktation/coordination.env.new"

$SSH root@"$IP" bash -s <<EOF
set -e
V=/opt/transpeaktation/.venv/bin/python
# OR-Tools for the batch selector, pinned to the tested version; keep numpy/protobuf pins
\$V -c "import ortools" 2>/dev/null || /usr/local/bin/uv pip install --python \$V ortools==9.9.3963 protobuf==4.25.5 numpy==1.26.4 >/dev/null
rm -rf /opt/transpeaktation/coord.new && mkdir -p /opt/transpeaktation/coord.new
tar xzf /tmp/coordination_bundle.tgz -C /opt/transpeaktation/coord.new
cd /opt/transpeaktation/coord.new && PYTHONPATH=. \$V -c "import coordination.live, coordination.replay, coordination.service, ortools.sat.python.cp_model, pymongo, psycopg2"
# keep the previous code, unit and env for rollback
U=/etc/systemd/system/transpeaktation-coordination.service
E=/etc/transpeaktation/coordination.env
rm -rf /opt/transpeaktation/coord.old; [ -d /opt/transpeaktation/coord ] && mv /opt/transpeaktation/coord /opt/transpeaktation/coord.old
[ -f \$U ] && cp \$U \$U.old || true
[ -f \$E ] && cp \$E \$E.old || true
mv /opt/transpeaktation/coord.new /opt/transpeaktation/coord && chown -R root:root /opt/transpeaktation/coord
mv \$E.new \$E && chown root:coordination \$E && chmod 640 \$E
cat > \$U <<UNIT
[Unit]
Description=transpeaktation coordinated routing (python -m coordination serve --input $INPUT)
After=network-online.target transpeaktation-forecast.service
Wants=transpeaktation-forecast.service
[Service]
User=coordination
WorkingDirectory=/opt/transpeaktation/coord
EnvironmentFile=/etc/transpeaktation/coordination.env
Environment=PYTHONPATH=/opt/transpeaktation/coord OMP_NUM_THREADS=1
# ProtectHome hides ~/.postgresql: libpq would fail on "permission denied" instead of skipping the client cert
Environment=PGSSLCERT=/nonexistent/postgresql.crt PGSSLKEY=/nonexistent/postgresql.key
ExecStart=\$V -m coordination serve --config $CONFIG --input $INPUT
StateDirectory=transpeaktation/coordination
Restart=always
RestartSec=5
MemoryMax=1500M
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload && systemctl enable transpeaktation-coordination >/dev/null && systemctl restart transpeaktation-coordination
EOF

# ---- health gate: the coordinator serves with a valid forecast within ~4 min, else roll back code + unit + env.
# live: nothing refreshes without a request, so a preview request (reserves nothing) triggers the first map.
echo "waiting for the coordinator's first forecast..."
ok=0
for i in $(seq 1 48); do
  if [ "$INPUT" = live ] && curl -sf -m 3 "http://$IP:$PORT/v1/health" >/dev/null; then
    curl -s -m 200 -H "Authorization: Bearer $TOKEN" -X POST "http://$IP:$PORT/v1/recommendations" \
      -d '{"request_id":"deploy-healthcheck","origin":[-122.4255,37.724],"destination":[-122.418,37.76],"reserve":false}' \
      >/dev/null || true
  fi
  if curl -sf -m 5 "http://$IP:$PORT/v1/health" | grep -q '"forecast_status": "ok"'; then ok=1; break; fi
  sleep 5
done
if [ $ok -ne 1 ]; then
  echo "health gate FAILED; journal:" >&2
  $SSH root@"$IP" "journalctl -u transpeaktation-coordination -n 30 --no-pager" >&2 || true
  $SSH root@"$IP" "U=/etc/systemd/system/transpeaktation-coordination.service; E=/etc/transpeaktation/coordination.env; \
    [ -d /opt/transpeaktation/coord.old ] && rm -rf /opt/transpeaktation/coord && \
    mv /opt/transpeaktation/coord.old /opt/transpeaktation/coord && { [ -f \$U.old ] && mv \$U.old \$U || true; } && \
    { [ -f \$E.old ] && mv \$E.old \$E || true; } && systemctl daemon-reload && \
    systemctl restart transpeaktation-coordination && echo 'rolled back to the previous release'" >&2 || true
  exit 1
fi
curl -sf "http://$IP:$PORT/v1/health" | $PY -c "import json,sys;d=json.load(sys.stdin);print(json.dumps({k:d.get(k) for k in ('status','forecast_status','forecast_age_min','selector','input_mode','run_id','session_id','replay_now','last_refresh')},indent=1))"
echo "COORDINATION_URL=http://$IP:$PORT   (Authorization: Bearer \$COORDINATION_API_TOKEN from ml/.env)"
