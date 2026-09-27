# Transpeaktation

Event-aware predictive routing + autonomous fleet orchestration.
Flow: `ingest → (MongoDB / Tiger Data) → ml → api → web` · full picture: `ARCHITECTURE.md`

## Who owns what
One owner per folder. Only edit another folder with its owner's OK.

| Folder       | Owner | Scope | Stack |
|--------------|-------|-------|-------|
| `ingest/`    | TBD | Event, city/road, mobility/AV, map inputs → normalize, dedupe, geocode → write to DBs | Python workers, MongoDB Atlas, Tiger Data, DigitalOcean |
| `ml/`        | TBD | Event understanding, traffic + demand forecast, fleet optimizer | Python, Gemini API |
| `api/`       | TBD | Places + traffic-aware routes (Mapbox, OSRM fallback) with OSM segment IDs (OSMnx); trip plan `/plan` (reads Mongo/Tiger, event-aware model, logs `trips`); voice → intent; route rewards (devnet SOL for taking the recommended route, `app/rewards.py`); later: fleet controller | FastAPI, Mapbox, OSMnx, ElevenLabs, Solana |
| `web/`       | TBD | Trip planning app, fleet dashboard, AI transparency / privacy page | Next.js, React, TypeScript, Leaflet |
| `ios/`       | TBD | SwiftUI shell that loads the `web/` app (mobile layout) in a WKWebView | SwiftUI, XcodeGen |
| `contracts/` | everyone | Shared data shapes (events, routes, forecasts, fleet state) | JSON Schema / Pydantic |
| `demo/`      | — | Standalone transPEAKtation SF demo (`node demo/check.mjs`) | HTML |
| `deploy/`    | everyone | DigitalOcean droplet (https://167-172-23-38.sslip.io): Caddy, systemd units, setup + redeploy scripts | Caddy, systemd |

## Rules
- `contracts/` is the only seam between folders. Change it in its own small PR and tell the team first.
- Talk across folders via contracts + HTTP/DB, never by importing another folder's internals.
- Branch per task: `<folder>/<short-desc>` (e.g. `ml/forecast-v1`). Small PRs, rebase on `main` often.
- Secrets live in `.env` (gitignored); add new keys to `<folder>/.env.example`.
- Each folder keeps its own deps (`package.json` / `pyproject.toml`) and a one-line run command in this file.
- Voice never authorizes spending: Solana tx requires explicit user confirmation. Reward payouts come from the api's devnet treasury; riders never sign or spend.

## Data stores
Mongo = long-lived entities / nested JSON. Tiger = time-series + fast-changing numbers. Both are empty; field names below are the join keys, keep them.

**MongoDB Atlas**: org Designathon → project Transpeaktation → cluster `transpeaktation` (M0, AWS us-east-1) → db `transpeaktation`. Connect with `MONGODB_URI` (every `<folder>/.env.example`); setup + IP access: `README.md` step 3.

| Collection | Holds | Indexes |
|---|---|---|
| `events` | concerts, sports, festivals (type, time, attendance) | — |
| `venues` | venue locations, capacity | — |
| `users` | riders | — |
| `trips` | trip requests (api `/plan`, not replays): `requested_at`, `depart_at`, origin/destination rounded to ~100 m, picked route's `road_segment_ids` minus 3 at each end, `trip_id` (random, not linked to the rider), `arrived_at` (null until the app reports arrival via `POST /trips/{trip_id}/arrived`), `reward_offer` (recommended route + lamports, if /plan offered one) | — |
| `rewards` | route rewards a rider took (a little SOL for the recommended route) (`POST /trips/{trip_id}/reward`): `trip_id`, `wallet`, `lamports`, `status` accepted → paid / too_soon / failed, Solana `signature`. The only place a wallet is stored | — |
| `route_plans` | candidate / chosen routes, explanations | — |
| `bookings` | confirmed bookings + Solana tx | — |
| `privacy_settings` | per-user AI / data choices | — |
| `road_segments` | road graph edges; `segment_id` = OSM edge `u-v-key`, `cnn` = DataSF street ID | `segment_id` unique, `cnn`, `geometry` 2dsphere |
| `vehicles` | AV fleet identity + config | `vehicle_id` unique |
| `road_incidents` | closures, permits, crashes, dispatch | `source+source_id` unique, `location` 2dsphere, `start_time+end_time`, `road_segment_ids` |
| `forecast_runs` | one per congestion map (ml): `status` ready, exact `closures`, coverage, model identity (`contracts/congestion_map.md`) | `_id` = `model_version|issued_at` |

**Tiger Data**: service `transPEAKtation` (`dp0coukufh`, us-east-1), db `tsdb`. Schema: `contracts/tiger_schema.sql` (idempotent). Connect with `TIGER_DATABASE_URL`; setup: `README.md` step 3. Apply schema: `psql "$TIGER_DATABASE_URL" -f contracts/tiger_schema.sql`.

| Hypertable | One row per | Key columns |
|---|---|---|
| `traffic_metrics` | segment × time × source | `speed_mph`, `free_flow_speed_mph`, `congestion_ratio` |
| `av_positions` | vehicle × time | `lat`, `lon`, `status`, `battery_pct`, `trip_id` |
| `demand_metrics` | zone × time | `trip_requests`, `available_vehicles`, `event_id` |
| `prediction_metrics` | segment × time × model × issue time (congestion map, `contracts/congestion_map.md`) | `issued_at`, `predicted_travel_time_sec`, `predicted_speed_mph`, `predicted_congestion_ratio`, `availability`, `predicted_delay_sec`, `confidence` (NULL) |
| `simulation_metrics` | run × segment × time | `avg_speed_mph`, `avg_delay_sec`, `throughput_vph` |

## Traffic data normalization (raw feeds → `traffic_metrics`)
Forecast models need one fixed road list, one unit, and one time step. Raw feeds (`ingest/data/timeseries/`) have none of these, so the ingestion worker enforces them before anything reaches Tiger:
1. **Fixed segments.** Every reading is snapped to `road_segment_id` = OSM edge `u-v-key` (same as Mongo `road_segments.segment_id`); DataSF rows join via `cnn`. Provider geometry (TomTom/Mapbox tile lines, Mapbox route pieces, which re-split between polls, Muni GPS fixes) never leaves ingest. One row per segment × 10-min bucket × `source`.
2. **One unit.** Store `speed_mph`, `free_flow_speed_mph`, and `congestion_ratio = 1 - speed/free_flow` (0 = free flow, 1 = stopped), clamped to [0, 1]. Per source:
   - `tomtom`: absolute tiles km/h → mph; free-flow = absolute ÷ relative (relative tiles every 6 h).
   - `mapbox_route`: annotation speed m/s → mph; free-flow from TomTom on the same segment, else the posted limit (DataSF speed limits / OSM `maxspeed`; unposted = 25 mph). `duration_typical` is *typical* traffic, not free flow; don't use it as free-flow.
   - `mapbox_tiles`: congestion level only; map low/moderate/heavy/severe to a ratio calibrated per road class on segments that also have a measured speed (until calibrated: 0.1 / 0.4 / 0.65 / 0.85), and leave `speed_mph` null. Rows that average "low" aren't stored (~94% of rows, ~450 MB/day): no `mapbox_tiles` row = flowing freely or not covered.
   - `muni`: speed between consecutive fixes of an in-service vehicle; runs low (stops), so keep it its own `source`, never averaged into others.
3. **One time step.** 10-minute UTC buckets; `time` = bucket start. Within a bucket, average a source's readings. Store only observed values (the schema has no "filled" flag): 20-min Mapbox tiles land in every other bucket. Gap filling (forward-fill ≤ 2 buckets, longer stays missing) happens when `ml/` builds model inputs, not in Tiger.

## Run
<!-- add one line per folder once it runs -->
- demo: `open demo/index.html` · test: `node demo/check.mjs` · SUMO kit: `python3 demo/sumo/kit.py --help` · offline check: `python3 demo/sumo/check.py` · setup/later execution: `demo/sumo/README.md`
- ingest setup: `cd ingest && python -m venv .venv && .venv/Scripts/pip install -e .[osm]` (macOS/Linux: `.venv/bin/`)
- ingest pull raw data: `cd ingest && .venv/Scripts/python -m pull [static|planned|live|<source>]` · quality report: `.venv/Scripts/python -m pull.check`
- ingest live polling (Mapbox corridors + traffic tiles, TomTom flow tiles, Muni vehicles, 511 events; keys in `ingest/.env`): `cd ingest && .venv/Scripts/pip install -e .[live] && .venv/Scripts/python -m pull.poll` (`--once`, `--only mapbox|mapbox_tiles|tomtom|muni|events`)
- ingest worker (OSM graph → Mongo `road_segments`; `pull.poll` JSONL → Tiger `traffic_metrics` + `route_eta_metrics`, Mongo `route_plans`; closures/incidents → Mongo `road_incidents`; PredictHQ (`python -m pull predicthq_events`, `PREDICTHQ_TOKEN`) → Mongo `events` + `venues`; needs `python -m pull osm_drive_graph streets speed_limits` first): `cd ingest && .venv/Scripts/pip install -e .[osm,db]` then `.venv/Scripts/python -m worker bootstrap` · one pass: `python -m worker run traffic|incidents|events|segments [--dry-run]` · long-running: `python -m worker schedule` · past day for a replay demo (DataSF closures/permits in effect then; traffic only exists for times `pull.poll` + worker were running): `python -m worker backfill --date YYYY-MM-DD` · design: `ingest/DESIGN.md`
- ingest HTTP trigger (on-demand refresh, same code as `worker schedule`; `INGEST_TOKEN` in `ingest/.env`, localhost only by default, never called by `web/`): `cd ingest && .venv/Scripts/python -m worker serve` → `POST http://localhost:8100/ingest/refresh` with `Authorization: Bearer $INGEST_TOKEN` (202 + job id), poll `GET /ingest/status/<id>`
- ingest DataSF live check: `cd ingest && python -m datasf` · test: `cd ingest && python -m unittest discover -s tests -t .`
- ingest data sources plan + backlog: `ingest/TODO.md`
- ml (synthetic event model, `ml/README.md`): `cd ml && pip install -e .` · run stages: `python -m eventsim {prepare|network|scenarios|simulate|check|dataset|train|evaluate|replay|export} --event castro` · test: `python -m unittest discover -s tests -t .`
- ml forecasting (citywide event-conditioned patch model, `ml/forecast/README.md`): `cd ml && pip install -e .[forecast]` · `python -m forecast {audit|prepare|rebuild-cache|sanity|train|evaluate|report|snapshot|predict|finetune-preflight|finetune|evaluate-events}` (`--config configs/event_patch_v1.yaml` or `--checkpoint …`) · test: `python -m unittest tests.test_forecast tests.test_event_finetune`
- ml coordinated routing POC (`ml/coordination/README.md`; runs on a labeled FIXTURE forecast until a real forecast export exists): `cd ml && pip install -e .[coordination,solver]` · `python -m coordination {fixture|audit|route|demo|serve}` (`--config configs/coordinated_routing_v2.yaml`) → service http://127.0.0.1:8100/v1/health · test: `python -m unittest tests.test_coordination tests.test_coordination_deploy` · deployed (live Tiger/Mongo congestion map on demand, heuristic/batch): `bash deploy/forecast_do.sh && bash deploy/coordination_do.sh`, see `ml/deploy/README.md` · test: `python -m unittest tests.test_live_routing`
- ml RL route selection (MaskablePPO / masked Double DQN on SUMO, `ml/coordination/README.md`): `cd ml && pip install -e .[rl]` (keep numpy 1.26.4 / protobuf 4.25.5 / torch pinned) · `python -m coordination {env-check|prewarm|train-rl --algo ppo|ddqn [--resume]|benchmark --suite static|profile|screening|heldout} --config configs/coordinated_routing_rl_main.yaml` · test: `python -m unittest tests.test_coordination_rl tests.test_coordination_env tests.test_coordination_benchmark`
- api: `cd api && python3 -m venv .venv && .venv/bin/pip install -e .[test]` · run: `.venv/bin/uvicorn app.main:app --reload` → http://localhost:8000/docs · test: `.venv/bin/python -m unittest discover -s tests -t .`
- api rewards (devnet): `cd api && .venv/bin/python -m app.rewards keygen` → `SOLANA_TREASURY_KEY` in `api/.env`, fund it with `airdrop` or https://faucet.solana.com, check with `balance`; `/health` shows `rewards`. `REWARD_MIN_TRIP_FRACTION=0` pays on any arrival (stage demo only)
- web: `cd web && npm install && npm run dev` → http://localhost:3000 (≤760px wide = mobile layout) · test: `npm test` · build: `npm run build` · replay demo (past dates allowed; `/plan?replay=true` uses the traffic/closures stored for then): `NEXT_PUBLIC_REPLAY=1 npm run dev`
- ios: start web first, then `open ios/Transpeaktation.xcodeproj` and Run on a simulator. Web URL = `WEB_APP_URL` in `ios/project.yml`; after editing that file run `cd ios && xcodegen`.
- ci/cd: `.github/workflows/ci.yml` runs api, ingest, web (test + build) and the demo check on every PR and push; a green push to `main` runs `deploy/tp-redeploy` on the droplet (secret `DEPLOY_SSH_KEY`). Manual redeploy: `ssh tp@167.172.23.38 tp-redeploy`.
