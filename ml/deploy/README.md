# Forecast service deployment (DigitalOcean)

`python -m forecast serve` on the droplet `transpeaktation-forecast` (s-2vcpu-4gb, sfo3), systemd unit
`transpeaktation-forecast`, port 8200. The served model is whatever `python -m forecast promote` last pointed at
(`ml/data/forecast/serving/current.json`: checkpoint digest, who/when/why, whether it passed its validation rule).

```sh
cd ml
python -m forecast promote --checkpoint data/forecast/experiments/event_patch_v2_main/best.pt --reason "..."
python -m forecast serving-status
bash deploy/forecast_do.sh          # first run creates droplet + firewall; later runs update code/model and restart
```

Needs `doctl` (authenticated), the SSH key `~/.ssh/transpeaktation_do_ed25519` (registered as
`transpeaktation-laptop-deploy`) and `FORECAST_API_TOKEN` in `ml/.env` (gitignored; see `ml/.env.example`).
A candidate that did not pass its validation rule needs `promote --force`; the override is recorded.

## API (bearer token except /v1/health)

| Call | Who | Cost |
|---|---|---|
| `POST /v1/snapshot` (history of the last 6 completed 10-min buckets + scheduled context) | the ingest side, once per 10-min bucket | ~10 s model compute on 2 vCPU |
| `GET /v1/forecast/latest?roads=a,b&horizons=10,20&format=json\|parquet` | apps / routing | ~100 ms server time (+ network) |
| `POST /v1/forecast` | ad-hoc / tests | computes on demand (~10 s) |
| `GET /v1/health` | monitoring | model identity, promotion record, latest forecast issue time and age (`stale` after 20 min) |

The snapshot/forecast columns are those of `python -m forecast predict` (`forecast/predict.py`,
`forecast/CONTRACT_PROPOSAL.md`). Still to wire: a producer that builds the snapshot from Tiger `traffic_metrics`
every 10 min (ingest-owned; needs a contracts change first). Forecasts are trained on synthetic SUMO scenarios.

# Coordinated routing (the load balancer) on the same droplet

`python -m coordination serve --input live|replay`, systemd unit `transpeaktation-coordination`, port 8100 (bearer
`COORDINATION_API_TOKEN` from `ml/.env`, generated on first deploy; cloud firewall admits only the app droplet and the
deploying machine). Selector: `heuristic` by default; `batch` (CP-SAT) per request with `"selector": "batch"` or as the
default via `service.selector` in the config. RL selectors are not deployed.

```sh
cd ml
bash deploy/forecast_do.sh                       # forecaster first: code, model, DB URLs (TIGER_DATABASE_URL, MONGODB_URI)
bash deploy/coordination_do.sh                   # live (default); health-gated, rolls back code + unit + env on failure
COORDINATION_INPUT=replay bash deploy/coordination_do.sh   # the labeled replay demo instead (needs replay-context once)
```

## Live input (default): the congestion map, on demand

```
customer POST /v1/recommendations
  -> coordinator: my map is > 1 bucket old and I have not asked in 60 s?
       -> forecaster POST /v1/live/forecast: newest complete Tiger bucket already mapped? reuse it (< 1 s)
          else: Tiger traffic_metrics (6 buckets) + Mongo road_incidents closures/events -> model -> Tiger
          prediction_metrics rows + Mongo forecast_runs doc (status ready, exact closures)
       -> coordinator reads that map from Tiger/Mongo, validates, publishes, re-times live reservations
  -> candidates timed on the map -> heuristic/batch -> reservation -> answer
```

At most one map per 10-min bucket, and only when someone asks. A request waits for the refresh only when there is no
usable map (first request after startup or after > 45 min idle); otherwise it is routed on the current map while the
newer one loads in the background. Format of the map: `contracts/congestion_map.md`. Input rules (source priority,
Muni excluded, missing = unobserved, which closures/events reach the model): `forecast/live.py` docstring.

Measured locally against the real databases (2026-09-27 02:40 map): 36% of modelled roads observed per bucket (TomTom
covers ~8.7k roads), 299 active closures -> 966 exact closure rows, 156 cases in the event context; first request
64 s end to end (inputs 3.5 s, model 17.7 s, Tiger write 21.8 s, read-back ~20 s over a home connection); cached
requests 0.35 s (heuristic) / 0.49 s (batch). The map is issued at the newest complete bucket, ~10-25 min behind real
time, so it covers only ~35-50 min ahead: longer trips are refused as beyond the horizon. The forecaster was trained on
synthetic SUMO traffic and has not been evaluated on real traffic.

**Atlas Network Access must include the droplet's IP** (143.198.228.42), or the forecaster cannot read Mongo; the
deploy preflight checks both databases from the droplet before replacing anything.

## Replay input

The forecaster is fed one recorded synthetic run (`b3_main_portola_full_f025_s0_event`, test split of the served model)
under a replay clock; every 10 replay minutes the coordinator posts the last 6 completed buckets to
`POST /v1/forecast?format=bundle&store=0`. A session lasts ~12 h and restarts with an empty ledger; a restart resumes it.
Route choices cannot change the recorded traffic. Leave out `depart_at` (it defaults to the replay clock).

| Call (bearer token except health) | |
|---|---|
| `GET /v1/health` | input mode, forecast status/age, selector, last refresh (latency, model sha), failures |
| `POST /v1/recommendations` `{request_id, origin:[lon,lat], destination:[lon,lat], reserve?, selector?}` | route + alternatives; `reserve` (default) holds a 60 s provisional reservation |
| `POST /v1/assignments/{id}/accept\|progress\|reroute\|cancel\|complete` `{expected_version, ...}` | lifecycle |

Replay deploy (2026-09-27, s-2vcpu-4gb): refresh 15.7 s (12.2 s model), one route 250-350 ms, forecaster 0.57 GB +
coordinator 0.53 GB RSS. Logs: `journalctl -u transpeaktation-coordination` / `-u transpeaktation-forecast`.
Not yet done (MODEL_TO_ROUTING_DEPLOYMENT_PLAN.md): API/web adapter + its `contracts/` HTTP schema, selector registry
refactor, SUMO closed-loop demo, evaluation of the forecaster on real traffic.
