# Transpeaktation

Event-aware predictive routing + autonomous fleet orchestration for San Francisco.

- How the system fits together: [`ARCHITECTURE.md`](ARCHITECTURE.md)
- Who owns which folder, team rules, database schemas: [`AGENTS.md`](AGENTS.md)

What runs today: the **demo** (`demo/`) and the **data pullers** (`ingest/`). `ml/`, `api/`, `web/` are not built yet; their owners add a run command to `AGENTS.md` when they land.

## 1. Install tools

| Tool | Needed for | macOS | Windows |
|---|---|---|---|
| Git | everything | `xcode-select --install` | [git-scm.com](https://git-scm.com) (use **Git Bash** for the commands below) |
| Node 18+ | demo | `brew install node` | [nodejs.org](https://nodejs.org) |
| Python 3.10+ | ingest, ml, api | `brew install python` | [python.org](https://www.python.org/downloads/) (tick "Add to PATH") |
| mongosh | checking MongoDB | `brew install mongosh` | [mongodb.com/try/download/shell](https://www.mongodb.com/try/download/shell) |
| psql | checking Tiger Data | `brew install libpq`, then `export PATH="$(brew --prefix libpq)/bin:$PATH"` | [postgresql.org/download](https://www.postgresql.org/download/windows/) (command line tools only) |

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
.venv/bin/python -m unittest discover -s tests -t .   # "Ran 22 tests ... OK"
.venv/bin/python -m pull              # all sources, ~1 min → ingest/data/raw/*.json
.venv/bin/python -m pull.check        # data-quality report
.venv/bin/python -m pull.poll --once  # live corridor speeds from Mapbox (needs MAPBOX_TOKEN)
```

Keep speed history growing with `.venv/bin/python -m pull.poll` (every 10 min until Ctrl+C, stays inside Mapbox's free tier) → `ingest/data/timeseries/mapbox_corridors/`. A sleeping laptop leaves gaps.

Pull a single layer with `python -m pull static|planned|live`, or name one source (`python -m pull chp_incidents`). Expect `sf511_*` to say `skip` without a 511 key, and `chp_incidents` freshness to FAIL when CHP's own feed is stale; both are normal. Source list and backlog: `ingest/TODO.md`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| mongosh hangs, then `Server selection timed out` | Your IP isn't on the Atlas access list (step 3.2). IPs change on new Wi-Fi. |
| `bad auth` / `password authentication failed` | Wrong password, or `<password>` still in `.env`. |
| `. ingest/.env` prints `command not found` or runs in the background | The URL lost its double quotes; put them back. |
| `psql: command not found` on macOS | Run the `export PATH=...libpq...` line from step 1 (add it to `~/.zshrc`). |
| `osm_drive_graph ... skip: needs osmnx` | You ran the system `python` instead of `.venv/bin/python`. |
| `CERTIFICATE_VERIFY_FAILED` to overpass-api.de (Windows) | `.venv/Scripts/pip install certifi`; the pullers use it automatically. |

## Working on the code

Branch per task (`<folder>/<short-desc>`), small PRs, and only edit folders you own. Full rules: `AGENTS.md`.
