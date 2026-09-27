# `coordination/`: coordinated navigation (proof of concept)

Implements steps 1–3 and the service part of step 7 in `ml/ROUTING_IMPLEMENTATION_V2.md`:

```
forecast snapshot + exact closures + versioned net_v3 graph
  -> endpoint snapping + legal candidate routes (K <= 5)
  -> time-dependent evaluation (entry time picks the forecast interval)
  -> shared allocation ledger (5-min bins)
  -> selector: forecast_only | heuristic | batch (CP-SAT) | rl (MaskablePPO / masked Double DQN checkpoint)
  -> validation + atomic reservation (SQLite)
  -> accept / progress / reroute / cancel / complete / expiry
```

> **The forecast is a FIXTURE.** The trained forecaster's export has not been produced yet. `python -m coordination
> fixture` writes a table in the exact `forecast/CONTRACT_PROPOSAL.md` shape, built from free-flow times x a
> road-class profile x a bump around closures x seeded noise. It is labeled everywhere (`model_version =
> fixture:class_profile_v0`, `prediction_source = fixture`, `fixture_forecast` degradation flag on every response).
> The closure intervals are real: the scheduled restrictions of a b3_verify scenario run (default: Folsom Street
> Fair). To switch to the real model, point `forecast.path` at a `python -m forecast predict` output. It goes through
> the same validation. Until then, trained-forecast integration is **outstanding**.

The interactive SUMO environment, RL training and the matched benchmark are described below (`rl/`, `benchmark/`).

## Run (from `ml/`, conda env `strats`)

```sh
pip install -e .[coordination,solver]      # scipy, pyarrow, pyyaml; ortools 9.9 (numpy<2-compatible)
python -m coordination fixture             # labeled fixture forecast -> data/coordination/fixtures/
python -m coordination audit               # network + forecast validation, coverage, hashes, one real route
python -m coordination route  --origin -122.435,37.7625 --destination -122.4094,37.7726 [--selector batch] [--full]
python -m coordination demo   --users 40 --batch 8     # same users, each selector, fresh ledger each time
python -m coordination serve  --selector heuristic     # http://127.0.0.1:8100
python -m unittest tests.test_coordination
```

`--now issued` (the default) runs a replay clock that starts 60 s after the forecast's issue time and advances with
wall time. The fixture's issue time is on the event day, so the wall clock would make it stale. Use `--now wall` for
live forecasts.

## Files

| Module | Role |
|---|---|
| `config.py` | dataclass config from `configs/coordinated_routing_v2.yaml` (starting settings, not tuned) |
| `network.py` | directed canonical roads + legal arcs from `net_v3/arcs_c90.json` (never inferred from geometry); `merged_parallel` aliases share their representative's allocation resource; grid snapping to a road + fraction; sub-line geometry. Version = same hash recipe as `forecast/audit.py` |
| `forecast_store.py` | contract validation (unique keys, contiguous intervals, one issue/model/network version, positive finite usable costs, known enums), immutable snapshot, atomic publish that keeps the last good snapshot, staleness |
| `fixture.py` | the labeled fixture above + closure intervals from a scenario run |
| `timing.py` | advance the clock over a fixed path; closure semantics; per-road entry/exit; ledger cells |
| `candidates.py` | bounded fixed-weight Dijkstra (scipy C) with representative intervals + overlap penalties, dedupe, loop exclusion, detour bound, deterministic order |
| `scoring.py` | `ETA + lambda * [Phi(L + route) - Phi(L)]`, `Phi = sum w (L/B)^2` |
| `ledger.py` / `storage.py` | in-memory ledger over remaining schedules; SQLite write-before-apply; restart recovery |
| `selectors/` | `forecast_only`, `heuristic` (sequential), `batch` (CP-SAT, exact at reachable loads, heuristic hint, exact re-scoring), `rl` (raises `SelectorUnavailable`) |
| `coordinator.py` | the only mutator: recommend (single/batch, preview vs reserve), accept (incl. another displayed alternative, re-validated), progress, reroute, cancel, complete, expiry sweep, forecast refresh |
| `service.py` | stdlib HTTP service + 32-request / 250 ms micro-batcher for the batch selector |

## Semantics worth knowing

* **Costs.** Predicted travel time is the only cost. Congestion ratio is context. Horizon 10k covers
  `[issued + 10(k-1), issued + 10k)` min, UTC. A missing or unusable row means the road cannot be entered; it does
  not mean free flow. An entry or arrival past the last interval is refused (`route_beyond_forecast_horizon`); the last
  bucket is never extended.
* **Closures.** `full` (and any unknown kind, conservatively) blocks entry if the interval overlaps
  `[entry, exit)`: the road must stay clear. `partial`/`lane` only add the flag `partial_restriction_on_route`. A
  vehicle that starts on a closed road may leave it. Its remaining part is priced at free flow and flagged
  `origin_cost_free_flow`.
* **Candidates** are an approximate set, not a proof of the K best time-dependent routes. Detour bound:
  `ETA <= fastest found + min(180 s, 0.15 x fastest)`. All selectors get the same candidates.
* **Ledger.** One entry = weight 1 in the entry's 5-min bin (optional kernel, conserved). It stores participating
  allocation pressure only and is never added to forecast background traffic. Previews reserve nothing. A
  recommendation reserves one provisional route for 60 s. Accept re-validates. Progress drops passed entries and
  re-times the rest. Reroute swaps old remaining load for new in one commit. A forecast refresh re-times remaining
  schedules once and does not switch routes. The initial compliance assumption is that accepted routes are
  followed; lower compliance is not modelled yet.
* **Budgets** `B = lanes x budget_per_lane[class]` are policy assumptions, not capacity. `lambda` is in
  seconds-equivalent selection units. Responses keep `forecast_eta_sec` / `extra_travel_sec` separate from
  `allocation_diagnostics`, which is not predicted delay and not measured savings.
* **Fallbacks.** An unavailable, invalid or too-slow selector falls back to the heuristic, and the response says so
  in `selector.fallback_reason`. `rl` always falls back today.

## Status (POC, measured on this machine)

* Real `net_v3` network: 27,632 roads, 61,306 arcs, 94.6% of roads routable under the fixture. The 127
  `merged_parallel` aliases have no arcs of their own in the SUMO connectivity, so they are unroutable and are reported
  as such.
* One Castro -> SoMa request: ~95 ms (4 candidates). A 6-request HTTP batch with the CP-SAT selector: ~1.1 s
  including the 250 ms batching wait. Candidate generation is still sequential per request.
* Multi-user demo: with the default `lambda = 60` and default budgets, few users are diverted. Tuning `lambda` and
  the budgets belongs to the development-scenario benchmark stage (`benchmark --suite screening`).

## Learned route selection (`rl/`, RL_ROUTING_RESEARCH_AND_PLAN.md)

MaskablePPO (sb3-contrib) and a masked Double DQN choose one of the K = 5 candidate slots for each request. They
sit behind the same `Selector` interface and the same coordinator as `forecast_only`, `heuristic` and `batch`.

```sh
pip install -e .[rl] numpy==1.26.4 protobuf==4.25.5 torch==2.6.0   # keep the shared stack pinned
python -m coordination env-check --config configs/coordinated_routing_rl.yaml         # gate 1 (no neural net)
python -m coordination train-rl  --config configs/coordinated_routing_rl.yaml --algo ppo  --seed 0 [--resume]
python -m coordination train-rl  --config configs/coordinated_routing_rl.yaml --algo ddqn --seed 0 [--resume]
python -m coordination route --config configs/coordinated_routing_rl.yaml --selector rl   # rl.checkpoint = a best/ or latest/ dir
python -m unittest tests.test_coordination_rl tests.test_coordination_env
```

| Module | Role |
|---|---|
| `rl/features.py` | the ONLY observation encoder (training, evaluation, serving). `rl_obs_v1`: 22 features per slot + 14 global features, fixed physical scales, padded and masked slots. Raises `LeakageError` if the forecast was issued after the decision time |
| `rl/scenario.py` | frozen scenarios from a quality-gated batch (`b3_verify`). Demand = the run's exact `trips.rou.xml`. Participation and compliance are seeded per (scenario, vehicle). Splits are the forecaster's event groups (val = castro, test = portola) |
| `rl/forecast_bridge.py` | causal 10-min road measurements rebuilt like the SUMO edgeData export, plus the trained forecaster (loaded once) refreshed from each run's own history. `fixture_debug` / `persistence_debug` modes only run with `--debug-forecast` |
| `rl/rewards.py` | fixed in-scope population, negative realized vehicle-seconds (running + waiting after scheduled departure), drain to completion or a cap (truncated, censored vehicles counted and never scored) |
| `rl/sumo_env.py` | Gymnasium env: TraCI per env, simulated-time coordinator clock, participants registered before insertion and read back, `probe` type (no background rerouting), fallbacks that never delete demand, verified warm-state cache of the history period |
| `rl/ddqn.py` | masked Double DQN: masks in exploration, greedy action and the bootstrap target (online argmax, target evaluation); no bootstrap from terminal or all-invalid next states |
| `rl/train.py`, `checkpoint.py`, `policy.py`, `evaluate.py` | bounded, resumable trainers (decision and wall caps, `latest/` + validation `best/`), metadata and compatibility checks, cached inference, episode runners |
| `selectors/rl.py` | loads a checkpoint once (cached by identity) and processes a batch in order with an extra-load overlay. A missing or incompatible checkpoint raises `SelectorUnavailable`: the heuristic takes over and says so in `fallback_reason`, or it is a hard error in strict mode |

Episode = 60 min of history (simulated, or a verified saved state), a 30-min decision window, then a drain of up
to 30 min. `gamma = gae_lambda = 1` (finite request-indexed episodes). The reward is dominated by background
traffic, so credit per decision is weak by design; nothing here claims the learned policy reduces congestion.
That needs the matched comparison (`benchmark`, below).

## Proposed HTTP shape (for the later contracts PR, not applied)

`POST /v1/recommendations {request_id, origin:[lon,lat], destination:[lon,lat], depart_at?, reserve?}` returns
`assignment{assignment_id, version, status, expires_at}`, `recommended{candidate_id, forecast_eta_sec,
extra_travel_sec, distance_m, depart_at, arrive_at, road_segment_ids, geometry (GeoJSON lon,lat)}`,
`fastest_candidate`, `is_fastest`, `alternatives[]`, `reasons[]`, `selector{name, version, fallback_reason}`,
`forecast{version, issued_at, model_version, network_version, provenance}`, `degradation[]`,
`allocation_diagnostics{...}`. The lifecycle operations are `POST /v1/assignments/{id}/{accept|progress|reroute|cancel|complete}`
with `expected_version`. API/web integration (CORS, provider fallback labeled uncoordinated, "Recommended" vs
"Fastest" in the UI) belongs to their owners.

`rl.n_envs > 1` runs that many SUMO environments in parallel for both trainers (PPO: SB3 SubprocVecEnv; Double DQN:
parallel actors sharing one agent and replay, each transition keeping its own terminal/truncation flags and next
mask). A random reset that draws a scenario without any nontrivial decision drains it and draws again.

## Matched benchmark (`benchmark/`, RL_ROUTING_RESEARCH_AND_PLAN.md §7)

```sh
python -m coordination prewarm   --config configs/coordinated_routing_rl_main.yaml --splits train,val,test [--debug-forecast]
python -m coordination benchmark --config configs/coordinated_routing_rl_main.yaml --suite {static|profile|screening|heldout}
    [--policies forecast_only,heuristic,batch,rl_ppo=<ckpt>,rl_ddqn=<ckpt>] [--scenarios run,...] [--seeds 0,1] [--workers N]
python -m unittest tests.test_coordination_benchmark
```

* `prewarm` builds the verified warm SUMO state (end of the history period) for every scenario x simulation seed once,
  in parallel. The state does not depend on the forecast, so `--debug-forecast` may build it before a trained
  forecaster exists. Saves are atomic (temp file + rename).
* Every policy of a dynamic suite replays the same scenario, simulation seed, participants, compliance draws and
  warm state; only its route choices (and so its traffic and forecasts) differ. `static` compares choices on one
  prepared snapshot (latency, masks, allocation score) without simulating the outcome.
* `batch` decides the requests that arrived within `benchmark.batch_window_s` jointly; they depart when the batch
  is decided and that wait is counted as vehicle time. `rl_*` use their checkpoints strictly: a missing or
  incompatible checkpoint is reported as `unavailable`, never replaced by another policy.
* Outcomes come from SUMO: in-scope vehicle-hours (every vehicle, participants and background), participant and
  other trip times (from the scheduled departure), unfinished, teleports, invalid routes, selector latency, and
  congestion exposure (vehicle-hours at <= 50% of free-flow speed, stopped and insertion-queue hours; per-road totals
  and a 5-min series in the episode folder). Every run is filed under an experiment id (config + code + matrix
  digest) with a frozen `manifest.json`; reruns resume only the identical experiment. Policy variants:
  `heuristic@lam=120`, `batch@w=15`, `heuristic@w=60` (equal-timing control), `forecast_only@rep=1` (repeat).
  `reports/coordination_benchmark_<experiment>.md` pairs each policy with `forecast_only` on common complete blocks
  (every policy strictly complete: all in-scope vehicles arrived, no dropped/invalid/readback/selector/forecast
  failures, identical demand/participant/compliance digests); failures and censored runs stay listed.

### Load-balancing backtest (LOAD_BALANCING_BACKTEST_PLAN.md)

```sh
python -m coordination backtest --config configs/coordinated_routing_backtest.yaml --phase {dev|heldout|report|all} [--workers N]
```

`dev`: sanity/repeatability, screening (lam 15/60/120, batch 60/15 s, equal-timing control), adoption 5/15/30% and
compliance 100/75/50% on validation scenarios; a pre-declared rule then freezes `selection_<id>.json`; `heldout`:
forecast_only vs the selected policy and challenger on 6 test-split families x 3 seeds. Final report:
`reports/load_balancing_backtest_<id>.md`. Sized for a cloud node (~170 SUMO episodes).
