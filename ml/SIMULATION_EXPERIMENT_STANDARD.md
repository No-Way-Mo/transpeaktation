# Simulation experiment standard (routing / load balancing)

The one protocol every routing experiment follows, so results from different weeks, people and nodes can be
compared. It covers SUMO closed-loop backtests of route-choice policies (`python -m coordination backtest`),
stress tests, the fireworks demo scenario and replay exports. Anything that deviates is labelled as a deviation in
its report.

> **Rule 0: DO NOT TELEPORT VEHICLES.** Every run uses `--time-to-teleport -1`
> (`env.time_to_teleport_s: -1`). A jam must stay a jam until the cars in it move. Every run must report
> `teleports = 0`; a run with any teleport is invalid and is not reported as a result.

## 1. Why the rules exist

| Rule | What went wrong without it |
|---|---|
| No teleporting | With SUMO's default (a car stuck 300 s is removed and re-inserted downstream) the fireworks baseline had 2,025 teleports vs 324 under PPO: the jam was "cleared" artificially, mostly on the *baseline* side. Results looked milder than the demo's original no-teleport run (2,504 vs 6,480 cars home by 1 AM for "fastest route for everyone") and the size of the routing gain was not measurable. |
| Same setup on both sides | Comparing the demo's original Act 1 (OSM import, no teleports) with our Act 2 (net_v3, teleports) would have claimed 2,504 -> 6,881 cars home; the like-for-like number was 6,480 -> 6,881. |
| One thread per worker | Pool workers that load PyTorch without `OMP_NUM_THREADS=1` started 188 x 192 threads on 192 cores: warm starts took 21-26 min instead of 3-4. |
| Fixed-horizon metrics | In gridlock not every car arrives; completed-trip averages alone reward policies that leave the slowest cars unfinished. |
| No CP-SAT `batch` | Dropped from test matrices (2026-09-27): weakest method everywhere, mostly its batching wait. |

## 2. Hard rules (MUST)

1. **No teleports**: `env.time_to_teleport_s: -1` in every experiment config (SUMO `--time-to-teleport -1`), and
   `--time-to-teleport -1` in `eventsim/simulate.py` for new scenario batches. Report `teleports`; must be 0.
2. **Matched arms**: within one comparison every arm shares network, demand (trip ids, origins, destinations,
   requested departures), crowd, event context, closures, simulation seed, warm state (same saved state loaded) and
   horizon. Only the routing policy differs. The runner checks demand / participant / compliance / initial-state
   digests per block; a mismatched block is excluded and listed.
3. **Baseline**: `forecast_only` (every participant takes its own fastest route on the forecast at departure).
   Non-participants keep the scenario's own routing. When comparing with an external run (e.g. the demo's OSM run),
   say that it is a different setup and give the same-setup baseline next to it.
4. **Fixed horizon**: every arm runs to the same end time. Report cars arrived by the horizon, cars still on the
   road, cars never inserted, and vehicle-hours up to the horizon (finished or not). Never drop an unfinished car.
5. **Deterministic, verified replays**: a replay (e.g. with extra outputs) must reproduce the saved run's
   vehicle-hours, unfinished count and teleport count exactly before it is used.
6. **Selection before held-out**: tuning (thresholds, lambda, search width) uses development (val) scenarios only;
   the held-out (test) comparison is run after the choice is frozen (`selection_<id>.json`).
7. **No interpolation in replays**: map positions are SUMO FCD samples; aggregates are SUMO summary / tripinfo /
   edgeData. Anything not measured is labelled.
8. **Label synthetic**: SUMO scenarios are synthetic (demand, attendance, crowd sizes are assumptions). No
   measured traffic exists for the fireworks night. Reports say so.
9. **No CP-SAT `batch`** in test matrices; test `forecast_only`, `heuristic` variants, `adaptive`, and RL
   checkpoints only if trained and compatible (`rl/checkpoint.py problems()` empty).

## 3. Scenarios

| Batch | What it tests | Scale |
|---|---|---|
| `b3_main` | Normal SF event traffic. Splits by event group: val = Bearrison (development), test = Portola (held-out), train = the rest. | 384 runs, 8 events, arrival / departure / full windows, event + control |
| `b5_stress_x150/200/300` | Same families with background demand x1.5 / x2 / x3 (`citywide_batch plan --demand-scale`, sampler seed 51 so families pair across scales) | 64 runs each (Bearrison + Portola, arrival/departure) |
| `b6_fireworks` | The demo's July 4 fireworks exodus (`eventsim/fireworks_demo.py`): 1,000 app users (kit.py v3, seed 42) + 3,000 / 6,000 / 12,000 crowd cars leaving 7 viewing sites 21:45-22:45; `_app` runs (only the 1,000 can use the app) and `_all` runs (everyone can). Horizon 01:00. | 6 runs |

Network: `net_v3` (the forecaster's road graph). Forecaster: `event_patch_v2_main`. Event context: scheduled only
(public hours, declared attendance, closures).

## 4. Arms (policies)

| Name | Meaning |
|---|---|
| `forecast_only` | Baseline: fastest forecast route per participant |
| `heuristic` (`@lam=60`) | Sequential reservation-aware heuristic, load penalty lambda 60 |
| `heuristic@lam=500` / `@lam=2000` | Stronger load penalty |
| `rl_ppo`, `rl_ddqn` | PPO v2 / masked DDQN checkpoints (`data/coordination/rl/runs_async/{appo,ddqn}_async_s0/latest`) |
| `adaptive` (`@stress=0.5@load=1.0`) | Deployed default: heuristic; PPO when the fastest route's predicted congestion >= stress or reservation load >= load |

Candidate search: **normal** detour <= min(180 s, 15%), 12 searches; **wide** detour <= min(300 s, 25%), 20
searches (the deployed setting). K = 5 candidates per request.

Participation = share of eligible trips (car point-to-point trips departing in the decision window) that use the
app; report it also as a share of all in-scope vehicles. Compliance 100% unless stated.

## 5. Metrics (per matched block, then paired vs `forecast_only`)

| Metric | Definition |
|---|---|
| Vehicle-hours | Time of every in-scope vehicle (participants and background, incl. insertion and batching waits) from the first decision to arrival or the horizon |
| Arrived by horizon | Cars that reached their destination by the horizon |
| Still on the road / never inserted | Backlog at the horizon (on a road / waiting to enter) |
| Congested hours | Vehicle-hours on mapped roads at speed <= 50% of free-flow (congestion ratio >= 0.5) |
| Stopped hours | Speed < 0.1 m/s |
| Trip time | Participants and background separately; mean and nearest-rank p95 of arrived trips, counted from the scheduled departure |
| Diversion | Share of decided requests not given their fastest candidate; predicted extra seconds per decision |

Paired change = (policy - baseline) / baseline per block; report mean, better/worse block counts and the worst
block. **Consistent reduction** = absolute and relative means agree and the policy wins >= 2/3 of blocks. "Better
in every pair" is not a significance test; with few scenario families, uncertainty is broad.

## 6. How to run (AWS)

- Nodes: m8a.48xlarge / .24xlarge (us-west-2 or us-east-1; see the `aws-sim-nodes` notes), Ubuntu 24.04, venv
  with pinned `numpy==1.26.4 protobuf==4.25.5 pandas==2.2.3 scipy==1.15.1 scikit-learn==1.5.2 pyarrow==23.0.1
  ortools==9.9.3963 eclipse-sumo==1.27.1 sumolib==1.27.1 traci==1.27.1 libsumo==1.27.1 torch (cpu)`, plus
  `libxrender1 libxext6 libxft2 libgl1 libglu1-mesa libgomp1 libatomic1 ...` for the SUMO wheels.
- Environment: `TP_SUMO_BACKEND=libsumo`, `OMP_NUM_THREADS=MKL_NUM_THREADS=OPENBLAS_NUM_THREADS=1` **in every
  worker process** (set before the pool is created), `AWS_DEFAULT_REGION=us-west-2` for the bucket.
- Gate: `python -m unittest tests.test_coordination tests.test_coordination_env tests.test_coordination_benchmark`
  must pass on the node before any episode runs.
- Commands (from `ml/`):
  - development + held-out backtest: `python -m coordination backtest --config configs/<cfg>.yaml --phase dev|heldout|report|all --workers N`
  - adoption sweep: `... --phase sweep --levels 0.8,0.9,1.0 --sweep-policies forecast_only,heuristic,adaptive`
  - fireworks scenario: `python -m eventsim.fireworks_demo build`, then `... backtest --config configs/coordinated_routing_fireworks*.yaml --phase fireworks`
  - stress batch: `python -m eventsim.citywide_batch plan --batch b5_stress_x<N> --demand-scale <x> ...`, simulate, `report`, then the sweep on it
- Outputs: S3 `s3://transpeaktation-sim-692859931626-usw2/results/...` (run records, manifests, reports,
  episode outputs with `keep_outputs`), warm states under `simcache/episodes/cache/`.
- Every experiment has an id (digest of config + code + matrix); reruns resume the identical experiment only.

## 7. Validity checklist (every report)

- [ ] `teleports = 0` in every episode (Rule 0)
- [ ] every arm complete or censored at the same horizon; failures listed, not dropped
- [ ] population digests match within each block
- [ ] repeatability: the same policy twice gives identical vehicle-hours
- [ ] `heuristic@lam=0` reproduces `forecast_only` (sanity)
- [ ] same-setup baseline shown next to any external comparison
- [ ] participation reported as share of eligible trips and of all vehicles
- [ ] synthetic label; scenario, network, forecaster, checkpoint and code digests in the manifest

## 8. Demo replay (`demo/index.html`, `demo/baseline.data.js`)

1. Re-run the chosen episodes with `keep_outputs: true`, `TP_FCD_PERIOD_S=1`, `TP_FCD_PREFIX=user-` from the saved
   warm state; confirm they reproduce the saved runs (Rule 5).
2. `python -m coordination.demo_replay --baseline <episode dir> --coordinated <episode dir> --label ml:<model> --out <file>`
   (converts net_v3 metres to lon/lat; net_v3 has no geo projection, so SUMO's `--fcd-output.geo` writes metres).
3. `node demo/check.mjs` must pass; open `demo/index.html` and check no script errors, dots on streets, counters
   summing to all cars every second.

## 9. Status of existing results (2026-09-27)

All routing results so far (`ml/reports/load_balancing_backtest_*`, `adoption_sweep_*`, `stress_x*`,
`fireworks_*`, the adaptive validation and the demo's Act 2) were produced **with teleporting on (300 s)**, i.e.
before Rule 0. They are useful for direction (coordination only helps under real overload with high adoption;
the heuristic is safe in light traffic; PPO and a wider search help most in heavy jams) but **must be re-run under
this standard before any number is quoted as a result.** The configs in `ml/configs/` still say
`time_to_teleport_s: 300` and `eventsim/simulate.py` hard-codes 300; switch them to -1 when re-running.

Expect longer runtimes and unfinished cars without teleports: gridlock can persist to the horizon, which is what
the fixed-horizon metrics are for.
