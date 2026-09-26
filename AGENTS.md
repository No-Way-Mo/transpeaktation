# Transpeaktation

Event-aware predictive routing + autonomous fleet orchestration.
Flow: `ingest → (MongoDB / Tiger Data) → ml → api → web`

## Who owns what
One owner per folder. Only edit another folder with its owner's OK.

| Folder       | Owner | Scope | Stack |
|--------------|-------|-------|-------|
| `ingest/`    | TBD | Event, city/road, mobility/AV, map inputs → normalize, dedupe, geocode → write to DBs | Python workers, MongoDB Atlas, Tiger Data, DigitalOcean |
| `ml/`        | TBD | Event understanding, traffic + demand forecast, fleet optimizer | Python, Gemini API |
| `api/`       | TBD | Trip planner, AV fleet controller, voice → intent, confirm → Solana tx | FastAPI, ElevenLabs, Solana |
| `web/`       | TBD | Trip planning app, fleet dashboard, AI transparency / privacy page | Next.js, React, TypeScript |
| `contracts/` | everyone | Shared data shapes (events, routes, forecasts, fleet state) | JSON Schema / Pydantic |
| `demo/`      | — | Standalone RoadReady SF demo (`node demo/check.mjs`) | HTML |

## Rules
- `contracts/` is the only seam between folders. Change it in its own small PR and tell the team first.
- Talk across folders via contracts + HTTP/DB, never by importing another folder's internals.
- Branch per task: `<folder>/<short-desc>` (e.g. `ml/forecast-v1`). Small PRs, rebase on `main` often.
- Secrets live in `.env` (gitignored); add new keys to `<folder>/.env.example`.
- Each folder keeps its own deps (`package.json` / `pyproject.toml`) and a one-line run command in this file.
- Voice never authorizes spending: Solana tx requires explicit user confirmation.

## Run
<!-- add one line per folder once it runs -->
- demo: `open demo/index.html` · test: `node demo/check.mjs`
- ingest setup: `cd ingest && python -m venv .venv && .venv/Scripts/pip install -e .[osm]` (macOS/Linux: `.venv/bin/`)
- ingest pull raw data: `cd ingest && .venv/Scripts/python -m pull [static|planned|live|<source>]` · quality report: `.venv/Scripts/python -m pull.check`
- ingest DataSF live check: `cd ingest && python -m datasf` · test: `cd ingest && python -m unittest discover -s tests -t .`
- ingest data sources plan + backlog: `ingest/TODO.md`
