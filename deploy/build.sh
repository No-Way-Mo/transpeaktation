#!/bin/bash
# First build, once, as tp: venvs, web build, raw data pulls. Needs api/.env and ingest/.env on the droplet.
set -euxo pipefail
cd /opt/transpeaktation
python3 -m venv api/.venv && api/.venv/bin/pip install -q --upgrade pip && api/.venv/bin/pip install -q -e api
python3 -m venv ingest/.venv && ingest/.venv/bin/pip install -q --upgrade pip && ingest/.venv/bin/pip install -q -e 'ingest[osm,live,db]'
cd web && npm ci --no-audit --no-fund --loglevel=error
NEXT_PUBLIC_API_URL=https://167-172-23-38.sslip.io/api NEXT_PUBLIC_REPLAY=1 npm run build > /tmp/next-build.log 2>&1 || { tail -30 /tmp/next-build.log; exit 1; }
cd ../ingest && .venv/bin/python -m pull osm_drive_graph streets speed_limits street_closures street_use_permits excavation_permits police_dispatch caltrans_lane_closures chp_incidents
echo BUILD_DONE
