# Transpeaktation

Event-aware predictive routing + autonomous fleet orchestration for San Francisco.

- How the system fits together: [`ARCHITECTURE.md`](ARCHITECTURE.md)
- Who owns which folder, team rules, database schemas: [`AGENTS.md`](AGENTS.md)

What runs today: the **demo** (`demo/`), the **data pullers and ingestion worker** (`ingest/`), the **event-aware forecaster and coordinated-routing load balancer** (`ml/`), the **routing API** (`api/`), the **route map web app** (`web/`), and the **iOS app** (`ios/`) that wraps it.

Live: https://yowaymo.us (web app; the API is under `/api`, e.g. `/api/health`). Showcase page: `/about`.

## 1. Install tools

| Tool | Needed for | macOS | Windows |
|---|---|---|---|
| Git | everything | `xcode-select --install` | [git-scm.com](https://git-scm.com) (use **Git Bash** for the commands below) |
| Node 18+ | demo | `brew install node` | [nodejs.org](https://nodejs.org) |
| Python 3.10+ | ingest, ml, api | `brew install python` | [python.org](https://www.python.org/downloads/) (tick "Add to PATH") |
| mongosh | checking MongoDB | `brew install mongosh` | [mongodb.com/try/download/shell](https://www.mongodb.com/try/download/shell) |
| psql | checking Tiger Data | `brew install libpq`, then `export PATH="$(brew --prefix libpq)/bin:$PATH"` | [postgresql.org/download](https://www.postgresql.org/download/windows/) (command line tools only) |
| Xcode 16+ | iOS app (macOS only) | App Store | — |

## 2. Clone and run the demo (no keys needed)

```bash
git clone https://github.com/No-Way-Mo/transpeaktation.git
cd transpeaktation
node demo/check.mjs      # prints stats, ends with "ok"
open demo/index.html     # Windows: start demo/index.html
```

## 3. Set up secrets

Every folder has a `.env.example`. Copy each one to `.env` (gitignored, never commit it):

```bash
for d in ingest ml api web; do cp -n $d/.env.example $d/.env; done
```

Then fill them in:

1. **Database passwords.** Ask the team admin in a DM (not the group chat) for the MongoDB and Tiger Data passwords, and replace both `<password>` placeholders. Keep the double quotes around the URLs: they contain `&`.
2. **Get your IP allowed on MongoDB.** Atlas only accepts connections from listed IPs. Send the admin the output of `curl -s https://checkip.amazonaws.com`. Admin: `atlas accessLists create <ip> --projectId 6ab779947130c8fd8f092be3`. (Tiger Data accepts any IP.)
3. **API keys**, only for the folder you work on. Each key has a comment with where to get it. Everything in `ingest/` except speed polling works without keys: the two 511 sources are skipped until you add `SF511_API_KEY`, and `pull.poll` needs `MAPBOX_TOKEN`.

## 4. Check the databases

```bash
set -a; . ingest/.env; set +a
mongosh "$MONGODB_URI" --quiet --eval 'db.getCollectionNames().sort().join(", ")'
psql "$TIGER_DATABASE_URL" -Atc "SELECT string_agg(hypertable_name, ', ' ORDER BY hypertable_name) FROM timescaledb_information.hypertables"
```

Expected:

```
bookings, events, privacy_settings, road_incidents, road_segments, route_plans, trips, users, vehicles, venues
av_positions, demand_metrics, prediction_metrics, simulation_metrics, traffic_metrics
```

Both are empty for now. What each collection and table holds: `AGENTS.md` → Data stores.

## 5. Run ingest

```bash
cd ingest
python3 -m venv .venv                 # Windows: python -m venv .venv
.venv/bin/pip install -e '.[osm]'     # Windows: .venv/Scripts/pip install -e .[osm]
.venv/bin/python -m unittest discover -s tests -t .   # ends with "OK"
.venv/bin/python -m pull              # all sources, ~1 min → ingest/data/raw/*.json
.venv/bin/python -m pull.check        # data-quality report
.venv/bin/python -m pull.poll --once  # live corridor speeds from Mapbox (needs MAPBOX_TOKEN)
```

Keep speed history growing with `.venv/bin/python -m pull.poll` (every 10 min until Ctrl+C, stays inside Mapbox's free tier) → `ingest/data/timeseries/mapbox_corridors/`. A sleeping laptop leaves gaps.

Pull a single layer with `python -m pull static|planned|live`, or name one source (`python -m pull chp_incidents`). Expect `sf511_*` to say `skip` without a 511 key, and `chp_incidents` freshness to FAIL when CHP's own feed is stale; both are normal. Source list and backlog: `ingest/TODO.md`.

The ingestion worker loads the pulled data into the databases (road segments, traffic, closures/incidents, PredictHQ events):

```bash
.venv/bin/pip install -e '.[osm,db]'
.venv/bin/python -m pull osm_drive_graph streets speed_limits   # the worker needs these first
.venv/bin/python -m worker bootstrap                            # one full load
.venv/bin/python -m worker schedule                             # keep it running
```

One job at a time: `python -m worker run traffic|incidents|events|segments [--dry-run]`. A past day for a replay demo: `python -m worker backfill --date YYYY-MM-DD`. Design: `ingest/DESIGN.md`.

## 6. Run ml (optional)

The API works without `ml/` (it falls back to its own heuristic). `ml/` holds the SUMO event simulations, the event-aware traffic forecaster and the coordinated-routing load balancer; both services are deployed on their own droplet.

```bash
cd ml
pip install -e '.[forecast,coordination,solver]'
python -m unittest discover -s tests -t .
```

Stages, configs and deployment: `ml/README.md`, `ml/forecast/README.md`, `ml/coordination/README.md`, `ml/deploy/README.md`. How `api/` calls it: `contracts/route_decision.md` (`ML_URL`) and `contracts/congestion_map.md`.

## 7. Run the API

```bash
cd api
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/python -m unittest discover -s tests -t .   # ends with "OK"
.venv/bin/uvicorn app.main:app --reload               # http://localhost:8000/docs
```

- `GET /plan?from=lon,lat&to=lon,lat[&depart_at|arrive_by=ISO]` is what the web app calls: candidate routes + the events, closures, live traffic and forecasts that `ingest/` / `ml/` stored for their road segments (Mongo / Tiger) + the event-aware model → pick, explanation, better departure time. Each request is logged to Mongo `trips` (area-level, no user identity) unless `save=false`; `ai_text=false` keeps trip facts away from Gemini (the web app's AI & privacy panel sets both, and shows `data.trip_record`, exactly what was logged). Without databases it still works, with demo events and no closures/traffic (`data` in the response says which inputs were live).
- `GET /events` today's events for search suggestions, `GET /places?q=...` place search, `GET /routes?...` raw candidate routes, `GET /road-conditions` / `GET /traffic` map layers from the databases, `GET /health` (includes Mongo / Tiger / road graph / rewards status).
- Trip lifecycle (the web app calls these during navigation): `POST /trips/{trip_id}/start`, `/cancel`, `/arrived`, and `/reward` to claim the route reward. `POST /voice` turns a spoken request into a trip (voice only plans, never pays).
- Databases: `MONGODB_URI` / `TIGER_DATABASE_URL` in `api/.env`; locally, values in `ingest/.env` are used when `api/.env` still has the `<password>` placeholder.
- Put `MAPBOX_TOKEN` in `api/.env` for live-traffic ETAs (`dur_typical`, `congestion`); locally the API also picks it up from `ingest/.env` if `api/.env` doesn't set it. Without it the API uses the free OSRM + Nominatim services and says `"source": "osrm"`.
- Optional keys in `api/.env` (each feature switches off cleanly without its key):
  - `ML_URL`: route decision by `ml/` (`contracts/route_decision.md`); `COORDINATION_URL` + `COORDINATION_API_TOKEN`: `ml/`'s load balancer for trips leaving now. Without them `/plan` uses its own heuristic and `data.decision` says so.
  - `GEMINI_API_KEY`: short congestion notes on the route cards (only trip facts are sent, never coordinates).
  - `ELEVENLABS_API_KEY`: speech-to-text for `/voice`.
  - `SOLANA_TREASURY_KEY` (+ `SOLANA_RPC_URL`): devnet SOL reward for taking the recommended route. Create and fund the treasury with `.venv/bin/python -m app.rewards keygen | airdrop | balance`. Riders never sign or spend.
- Each route also carries `road_segment_ids`: the OSM road edges it drives, same IDs as our databases. The first start downloads the SF road graph (~15 s) into `api/data/`; `/health` shows `road_graph: loading` until then.

## 8. Run the web app

Start the API first (step 7); the web app gets places and routes from it.

```bash
cd web
npm install
npm test          # ends with "fail 0"
npm run dev       # http://localhost:3000
```

Wide window = desktop layout (sidebar + map). Narrow the window to 760px or less, or open it on a phone, for the mobile layout. The API address defaults to `http://localhost:8000`; set `NEXT_PUBLIC_API_URL` in `web/.env` to change it. `/about` is the project showcase page (it plays the `demo/`). Replay demo with past dates: `NEXT_PUBLIC_REPLAY=1 npm run dev`.

## 9. Run the iOS app

The iOS app is a SwiftUI shell that shows the web app's mobile layout, so **start the API and web app first** (steps 7–8).

```bash
open ios/Transpeaktation.xcodeproj   # pick an iPhone simulator, press Run (⌘R)
```

- The app loads `http://localhost:3000`, which works in the Simulator. On a real iPhone, set `WEB_APP_URL` in `ios/project.yml` to your Mac's LAN address (e.g. `http://192.168.1.20:3000`, same Wi-Fi) or the deployed URL (and point `NEXT_PUBLIC_API_URL` at the Mac's LAN address too), then run `cd ios && xcodegen` (`brew install xcodegen`).
- If the web app isn't running, the app shows a "Can't reach transPEAKtation" screen with Retry.
- Debug the page inside the app: Safari → Develop → Simulator → localhost.

## Deployment

- One DigitalOcean droplet serves https://yowaymo.us (also reachable at https://167-172-23-38.sslip.io): Caddy (HTTPS) proxies `/api/*` to uvicorn and everything else to Next.js; systemd runs `tp-api`, `tp-web`, `tp-poll` (live polling) and `tp-worker` (ingestion schedule). Files and setup: `deploy/`.
- CI (`.github/workflows/ci.yml`) runs the api, ingest and web tests, the web build and the demo check on every PR and push. A green push to `main` redeploys the droplet automatically. Manual redeploy: `ssh tp@167.172.23.38 tp-redeploy`.
- `ml/`'s forecaster and load balancer run on a separate droplet: `ml/deploy/README.md`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| mongosh hangs, then `Server selection timed out` | Your IP isn't on the Atlas access list (step 3.2). IPs change on new Wi-Fi. |
| `bad auth` / `password authentication failed` | Wrong password, or `<password>` still in `.env`. |
| `. ingest/.env` prints `command not found` or runs in the background | The URL lost its double quotes; put them back. |
| `psql: command not found` on macOS | Run the `export PATH=...libpq...` line from step 1 (add it to `~/.zshrc`). |
| `osm_drive_graph ... skip: needs osmnx` | You ran the system `python` instead of `.venv/bin/python`. |
| Web app says "Couldn't load routes." | The API isn't running (step 7); check http://localhost:8000/health. |
| iOS app stuck on "Can't reach transPEAKtation" | `npm run dev` isn't running in `web/`, or on a real iPhone `WEB_APP_URL` still says `localhost`. |
| `CERTIFICATE_VERIFY_FAILED` to overpass-api.de (Windows) | `.venv/Scripts/pip install certifi`; the pullers use it automatically. |

## Working on the code

Branch per task (`<folder>/<short-desc>`), small PRs, and only edit folders you own. Full rules: `AGENTS.md`.
