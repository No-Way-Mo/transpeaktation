# Transpeaktation

Event-aware predictive routing + autonomous fleet orchestration.
Flow: `ingest → (MongoDB / Tiger Data) → ml → api → web` · full picture: `ARCHITECTURE.md`

## Who owns what
One owner per folder. Only edit another folder with its owner's OK.

| Folder       | Owner | Scope | Stack |
|--------------|-------|-------|-------|
| `ingest/`    | TBD | Event, city/road, mobility/AV, map inputs → normalize, dedupe, geocode → write to DBs | Python workers, MongoDB Atlas, Tiger Data, DigitalOcean |
| `ml/`        | TBD | Event understanding, traffic + demand forecast, fleet optimizer | Python, Gemini API |
| `api/`       | TBD | Trip planner, AV fleet controller, voice → intent, confirm → Solana tx | FastAPI, ElevenLabs, Solana |
| `web/`       | TBD | Trip planning app, fleet dashboard, AI transparency / privacy page | Next.js, React, TypeScript, Leaflet |
| `ios/`       | TBD | SwiftUI shell that loads the `web/` app (mobile layout) in a WKWebView | SwiftUI, XcodeGen |
| `contracts/` | everyone | Shared data shapes (events, routes, forecasts, fleet state) | JSON Schema / Pydantic |
| `demo/`      | — | Standalone transPEAKtation SF demo (`node demo/check.mjs`) | HTML |

## Rules
- `contracts/` is the only seam between folders. Change it in its own small PR and tell the team first.
- Talk across folders via contracts + HTTP/DB, never by importing another folder's internals.
- Branch per task: `<folder>/<short-desc>` (e.g. `ml/forecast-v1`). Small PRs, rebase on `main` often.
- Secrets live in `.env` (gitignored); add new keys to `<folder>/.env.example`.
- Each folder keeps its own deps (`package.json` / `pyproject.toml`) and a one-line run command in this file.
- Voice never authorizes spending: Solana tx requires explicit user confirmation.

## Data stores
Mongo = long-lived entities / nested JSON. Tiger = time-series + fast-changing numbers. Both are empty; field names below are the join keys, keep them.

**MongoDB Atlas**: org Designathon → project Transpeaktation → cluster `transpeaktation` (M0, AWS us-east-1) → db `transpeaktation`. Connect with `MONGODB_URI` (every `<folder>/.env.example`); setup + IP access: `README.md` step 3.

| Collection | Holds | Indexes |
|---|---|---|
| `events` | concerts, sports, festivals (type, time, attendance) | — |
| `venues` | venue locations, capacity | — |
| `users` | riders | — |
| `trips` | trip requests + status | — |
| `route_plans` | candidate / chosen routes, explanations | — |
| `bookings` | confirmed bookings + Solana tx | — |
| `privacy_settings` | per-user AI / data choices | — |
| `road_segments` | road graph edges; `segment_id` = OSM edge `u-v-key`, `cnn` = DataSF street ID | `segment_id` unique, `cnn`, `geometry` 2dsphere |
| `vehicles` | AV fleet identity + config | `vehicle_id` unique |
| `road_incidents` | closures, permits, crashes, dispatch | `source+source_id` unique, `location` 2dsphere, `start_time+end_time`, `road_segment_ids` |

**Tiger Data**: service `transPEAKtation` (`dp0coukufh`, us-east-1), db `tsdb`. Schema: `contracts/tiger_schema.sql` (idempotent). Connect with `TIGER_DATABASE_URL`; setup: `README.md` step 3. Apply schema: `psql "$TIGER_DATABASE_URL" -f contracts/tiger_schema.sql`.

| Hypertable | One row per | Key columns |
|---|---|---|
| `traffic_metrics` | segment × time × source | `speed_mph`, `free_flow_speed_mph`, `congestion_ratio` |
| `av_positions` | vehicle × time | `lat`, `lon`, `status`, `battery_pct`, `trip_id` |
| `demand_metrics` | zone × time | `trip_requests`, `available_vehicles`, `event_id` |
| `prediction_metrics` | segment × time × model | `predicted_speed_mph`, `predicted_delay_sec`, `predicted_demand`, `confidence` |
| `simulation_metrics` | run × segment × time | `avg_speed_mph`, `avg_delay_sec`, `throughput_vph` |

## Run
<!-- add one line per folder once it runs -->
- demo: `open demo/index.html` · test: `node demo/check.mjs`
- ingest setup: `cd ingest && python -m venv .venv && .venv/Scripts/pip install -e .[osm]` (macOS/Linux: `.venv/bin/`)
- ingest pull raw data: `cd ingest && .venv/Scripts/python -m pull [static|planned|live|<source>]` · quality report: `.venv/Scripts/python -m pull.check`
- ingest speed polling (needs `MAPBOX_TOKEN`): `cd ingest && python -m pull.poll` (every 10 min; `--once` for one round)
- ingest DataSF live check: `cd ingest && python -m datasf` · test: `cd ingest && python -m unittest discover -s tests -t .`
- ingest data sources plan + backlog: `ingest/TODO.md`
- web: `cd web && npm install && npm run dev` → http://localhost:3000 (≤760px wide = mobile layout) · test: `npm test` · build: `npm run build`
- ios: start web first, then `open ios/Transpeaktation.xcodeproj` and Run on a simulator. Web URL = `WEB_APP_URL` in `ios/project.yml`; after editing that file run `cd ios && xcodegen`.
