# ml/ — event-aware traffic model (synthetic, grounded in a real SF event)

Implements `SYNTHETIC_EVENT_MODEL_INSTRUCTIONS.md` for **Castro Street Fair 2026** (DataSF permit case 1534041):

`real closures + roads + traffic context → scenarios → SUMO → training examples → residual model → held-out eval → routing replay`

> **Provenance.** The model is trained and evaluated on SUMO simulations grounded in a real permitted SF event,
> real OSM/DataSF roads and the traffic feeds we poll. Event attendance, daytime demand and signal timings are
> scenario assumptions. Nothing here is validated on measured event traffic; that is still pending.

## Setup

Any Python ≥ 3.10 environment (this machine uses the conda env `strats`):

```sh
cd ml && pip install -e .      # numpy, pandas, scikit-learn, tzdata, eclipse-sumo, sumolib, traci
```

SUMO comes from the `eclipse-sumo` wheel; no system install needed. Inputs are the snapshots `ingest/` writes
(`ingest/data/raw/*.json`, `osm_drive_graph.graphml`, `ingest/data/timeseries/*`). They are read as data files; no
`ingest` code is imported. Override with `INGEST_DATA_DIR` / `ML_DATA_DIR`.

## One command per stage

### Citywide data first (no model training)

The separate citywide pilot expands SUMO to the entire downloaded SF driving graph. It indexes all available
special-event permit cases against canonical roads and runs paired event/control arrival scenarios for Castro
and Folsom on that common city network. Background trips are identical within each pair. The public event day is
separate from the permit setup day. Run from `ml/`:

```sh
python -m eventsim.citywide prepare
python -m eventsim.citywide network
python -m eventsim.citywide simulate --workers 2
python -m eventsim.citywide report
python -m eventsim.citywide export
```

Outputs: `data/sf_citywide/` and `reports/citywide_data_report.md`. The default pilot has four three-hour runs,
12,000 assumed background departures/hour during the first two hours, and a final hour to drain traffic. It is a
coverage/connectivity diagnostic, not a training dataset or an accurate reproduction of event traffic. Trips,
10-minute segment measurements, empty-road masks, closure masks, source mappings and raw SUMO outputs are retained.
Measurements in `measurements.npz` use SUMO SI units (`speed` in m/s), with columns in sorted canonical-segment
order. The separate export stage writes compressed CSV files with canonical IDs, mph, UTC bucket timestamps,
congestion ratios, phase labels (warmup/demand/drain), run IDs and synthetic provenance. They are not rows for the
live `traffic_metrics` table. Real normalized observations remain the responsibility
of the ingestion pipeline. Provider geometry matches alone do not establish measured time coverage.

`--only castro_arrival_v1_control` selects one run. Finished runs resume without replacement. To change demand,
duration, seeds or inputs, set `ML_DATA_DIR` to a new directory and repeat preparation/network generation so that
versions remain separate. Do not run the existing dense patch feature builder on the citywide graph.

Check actual road coverage, closure matching, trip failures, teleport counts and unfinished trips before scaling
the batch. Event closure ambiguities, unresolved roads, lane defaults, signal timings and OD demand remain explicit
assumptions; the pilot does not yet enforce all concurrent non-event restrictions. Model selection and training
come after these checks. The pilot is not connected to the live API or web app.

Quality tools over the same (unchanged) pilot data:

```sh
python -m eventsim.citywide review      # closure_review_v2.json: per-row accept/needs_review/reject with reasons
python -m eventsim.citywide diagnose --only castro_arrival_v1_event   # re-run with warnings in diagnostics/,
                                        # teleports located per junction (pilot outputs untouched)
```

### Large-batch pipeline (v3, data only)

The v3 path fixes the v2 benchmark problems in new versioned artifacts. Nothing from v1/v2 is overwritten.

| Problem in v2 | v3 fix | Where |
|---|---|---|
| Parallel OSM edges (Ocean Ave etc.) deadlock junctions and cause teleports | `net_v3/`: 127 parallel edges merged into one edge carrying both carriageways' lanes (`segments.parquet` gap `merged_parallel`, `represented_by`) | `citywide_batch network-v3` |
| Closure pieces absorbed into merged junctions | accepted closure segments are never absorbed (0 of them now) | `net_v3/network.json` |
| Extreme event load overwhelms SoMa | ≤ 12,000 event vehicles; arrival/departure spreads widened to ≤ 4,000 / 5,000 veh/h peak | sampler v3 |
| Ride-hail stops block a lane | stops pull off the lane (`parking="true"`) | sampler v3 |
| Mid-run closures leak (vehicles past the rerouting point) | rerouter triggers on every edge within 1.5 km | batch `trigger_radius_m` |
| 30 unresolved closure rows | review v3 (spacing-insensitive names; alleys/plazas with no drivable road), then the last 8 decided by one rule (permit's own street + type; other name only if ≥80% of the line; else no closure), labelled `decided_by: claude (rule-based, not human-verified)` in `closure_review_v3_decisions.csv` | `citywide review --review-version closure_review_v3` |
| Public hours unverified | web-sourced with URL + confidence per event (`EVENT_POOL_V3`) | sampler v3 |
| Event demand guessed | event demand = the event's **attendance** (API later; `prepared/event_attendance_v1.csv` now: published figure or category estimate for all verified events) × drive share ÷ occupancy, capped at 12,000 vehicles | `citywide_demand attendance`, sampler v3.1 |
| Background demand guessed | all non-event demand is a set of **trip requests** (origin lon/lat, destination lon/lat, departure time), snapped to roads; synthetic stand-in requests until client requests exist, then `--requests file.parquet` | sampler v3.1 (`runs/<run>/requests.parquet`) |
| Network speeds unverified | TomTom-vs-SUMO comparison (+6% at every demand level; volume not identifiable from early-morning data) | `citywide_calibrate run` |
| Fixed 90 s signals | signal regime varied: fixed 90 s vs actuated | sampler v3 |

```sh
python -m eventsim.citywide review --review-version closure_review_v3
python -m eventsim.citywide_batch network-v3
python -m eventsim.citywide_demand attendance              # attendance per verified event (API stand-in)
python -m eventsim.citywide_calibrate run                  # optional: stand-in volume vs TomTom (busier --hours later)
python -m eventsim.citywide_pipeline verify --workers 8    # small v3 batch + quality gate
python -m eventsim.citywide_pipeline preflight --batch b3_main --families-per-event 12 --seeds 2 --workers 6
python -m eventsim.citywide_pipeline run --batch b3_main --families-per-event 12 --seeds 2 --workers 6   # resumable
```

Add `--requests client_requests.parquet` to `run` to use real client requests instead of the stand-in
(columns: `request_id, depart_utc | depart_local_s, origin_lon, origin_lat, dest_lon, dest_lat`, optional `kind`).

`run` refuses to start unless preflight passes (SUMO, v3 network/review, disk/RAM for the estimate) and the
verification batch passed the gate. The gate checks unfinished/not-inserted trips, teleports per 1,000 trips,
steady-state closed-road entries and review flags. `--force-gate` overrides it, and the override is recorded.
Report: `reports/citywide_data_readiness_v3.md`.

### Citywide scenario batches (schema v2, data only)

Diverse, versioned batches on the same citywide network. Each batch has its own folder
`data/sf_citywide/batches/<batch>/`, and a batch's `scenarios.json` is frozen once planned (a new plan needs a new
batch id). The v1 pilot at the dataset root is never modified.

```sh
python -m eventsim.citywide_batch plan      --batch b2_bench --families-per-event 1 --seeds 1 --seed 7
python -m eventsim.citywide_batch simulate  --batch b2_bench --workers 6      # resumes; --keep-raw keeps XML
python -m eventsim.citywide_batch report    --batch b2_bench                  # quality.csv/json, teleport hotspots
python -m eventsim.citywide_batch export    --batch b2_bench                  # parquet grid + segments + manifest
python -m eventsim.citywide_batch readiness --batch b2_bench --target-families 100 --target-seeds 2
```

- **Families:** one verified event location (closure review v2) plus sampled assumptions: time window
  (arrival / departure + 3 h recovery / full day), background demand level and profile, OD structure, and
  attendance-derived event vehicles. Arrival and departure surges, ride-hail stops, parking radius, driver/routing
  parameters and the seed are sampled too. Every seed variant is an event run plus a no-event control with identical
  background trips. `family_id` and `family_group` are kept for grouped splits later.
- **Concurrent restrictions:** other verified permitted closures that day apply to both runs of a pair.
- **Network correction v2:** cars are barred from `highway=busway` / `access=no` segments (the pilot allowed them).
- **Exports:** a dense segment × 10-min UTC grid with `observed`/`closed`/`in_sumo` masks, `phase`, run/family
  IDs and `synthetic=True`. Null means not observed; nothing is filled.
- **Readiness report:** `reports/citywide_data_readiness.md` (coverage, scenario inventory, quality problems, cost
  estimate, remaining gaps).

### Citywide event-conditioned forecasting (`forecast/`)

This is a separate package trained on the exported citywide batches. It never edits generator outputs. It
predicts travel time, speed and congestion for every modelled road in 10-min buckets over the next 60 min, and
exports a fleet-facing table with explicit availability. Install with `pip install -e .[forecast]`. Architecture,
data definition and commands are in `forecast/README.md`. Results are in `reports/forecast_event_patch_v1.md`. The
proposed shared contract (not applied) is in `forecast/CONTRACT_PROPOSAL.md`.

```sh
python -m forecast audit   --config configs/event_patch_v1.yaml
python -m forecast prepare --config configs/event_patch_v1.yaml
python -m forecast train   --config configs/event_patch_v1.yaml     # + configs/event_patch_v1_noevent.yaml
python -m forecast evaluate --checkpoint data/forecast/experiments/event_patch_v1/best.pt --partition test
python -m forecast report  --experiments event_patch_v1 event_patch_v1_noevent
```

### Existing Castro model experiment

Run from `ml/`. Everything is written under `ml/data/<event>/` (gitignored) except the readable reports in `ml/reports/`.

| # | Command | Output | Notes |
|---|---|---|---|
| 1 | `python -m eventsim prepare --event castro` | `prepared/{event,patch}.json`, `observations.csv`, `reports/castro_join_report.md` | closure rows → directed OSM edges (overlap + name + direction), 700 m patch, turn bans, cnn/limits, TomTom/Mapbox joined to segments |
| 2 | `python -m eventsim network --event castro` | `net/net_c{70,90,110}.net.xml`, `crosswalk.csv`, `routable_edges.json` | plain-XML build: SUMO edge id = `u-v-key`; one net per signal-cycle assumption |
| 3 | `python -m eventsim scenarios --event castro --families 100 --seeds 2 --seed 7` | `scenarios.json` | families × seeds × {event, no-event control} |
| 4 | `python -m eventsim simulate --event castro --workers 12` | `runs/<run>/{measurements.npz, trips.csv, summary.json}` | skips finished runs; `--force` to redo |
| 5 | `python -m eventsim check --event castro` | `reports/castro_sim_checks.md`, `checks.csv` | closures, lost/unfinished/teleported vehicles, queues, detours, recovery |
| 6 | `python -m eventsim dataset --event castro --row-frac 0.12` | `dataset/<run>.npz`, `splits.json`, `feature_schema.json` | family-level split *before* windowing |
| 7 | `python -m eventsim train --event castro` | `model/{model.pkl, model_card.json}` | HistGradientBoosting residual, tuned on validation families |
| 8 | `python -m eventsim evaluate --event castro` | `reports/castro_evaluation.md`, `model/evaluation.json` | test families only |
| 9 | `python -m eventsim replay --event castro --runs 3 --probe-share 0.3` | `replay/…`, `reports/castro_replay.md` | re-simulates each policy (TraCI) |
| 10 | `python -m eventsim export --event castro` | `export/{simulation,prediction}_metrics_<run>.csv` | Tiger-table-shaped, run-tagged, synthetic |

Tests: `python -m unittest discover -s tests -t .`

## What the pieces do

**Join (prepare).** Selects the permit case, keeps closure vs public hours separate (public hours 11:00–18:00 are an
explicit *assumption*), checks UTC vs local fields with `America/Los_Angeles` rules, and maps each closure line to
directed OSM edges by overlap along the line, street identity and heading. It also picks up other permitted
restrictions in the patch on the event day (e.g. the Noe St shared space from 11:30), which the simulator enforces.
Real TomTom lines are snapped to segments in the same direction. Free flow = absolute ÷ relative from readings
≤ 20 min apart, cached per line. Mapbox categories stay categories.

**Network.** Built from plain XML so every SUMO edge *is* a canonical `u-v-key`. Signal nodes linked by very short
edges (divided roads such as Dolores St, the Market/Noe/16th complex) are merged into one junction to avoid SUMO
deadlocks. The short connectors inside them are recorded as `absorbed_junction` in `crosswalk.csv` and have no
measurements. Trip endpoints come from the SUMO network's strongly connected edge set with all restricted edges
removed, so every trip has a route in every scenario.

**Scenarios.** Varied per family: background OD demand level/through share, event vehicle trips (300–3000; no
attendance data exists, so vehicles are varied directly), turnout/cancellation, ride-hail share and curb dwell,
arrival/departure peak time and width, destination radius, signal cycle, driver parameters, rerouting share/period,
observation noise/missingness/staleness, and hypothetical closure variants (`permit` = the real footprint;
`permit_market_open`, `permit_market_one_lane` are labelled what-ifs). Some families are low-demand controls. Every
seed has an event run and a no-event control with identical background demand.

**Simulation.** Closures active for the whole simulated window are baked into the run's network as lane
permissions, so routes can never use them. Mid-day closures use SUMO rerouters with `disallow="passenger"`. Outputs
are aggregated to the 10-min grid on canonical segments. Every trip is recorded, including unfinished ones, and
teleports are counted per run.

**Model.** For each origin t, segment and horizon (10/30/60 min), the target is *future simulated segment travel time
minus the persistence forecast*. Persistence uses only provider-like observations ≤ t: noisy TomTom speeds on
segments that really have TomTom coverage, 20-min Mapbox categories, missing and stale samples, forward-filled at
most 2 buckets. Features are recent speed/category lags and trends, observation age, road attributes, neighbour and
area history, time of day, the *declared* event hours, the published closure schedule and a noisy, sometimes
missing, event-vehicle estimate. The model never sees the realised arrival curve or the exact generated demand. One
pooled HistGradientBoosting model covers all segments and horizons. Closed roads are a routing rule, not a
prediction.

**Evaluation.** Test = unseen *Castro* scenario families (same area, not citywide). It compares persistence,
typical-for-this-time, the hand-written event rule and the learned model: error by horizon, event vs ordinary
periods, approach/detour roads, recovery, build-ups/false alarms, robustness to missing data, latency, and
per-family variability.

**Replay.** Re-runs SUMO once per policy (`no_info`, `persistence`, `event_rule`, `learned`) with the same demand,
restrictions and seed. The same 30% of vehicles are routed by the policy at departure and every 10 min, using only
their own run's past observations.

## Results (Castro, 2026-09-26 build)

Details: `reports/castro_{join_report,sim_checks,evaluation,replay}.md`.

- **Join:** 16/16 permit rows resolved to 39 directed edges (7 flagged for review: Market St rows with `undefined`
  direction are treated as closed both ways). Patch: 931 segments (77 absorbed into merged signal junctions);
  TomTom covers 62%, Mapbox 100%. Saved traffic is overnight and does not overlap the closure window.
- **Simulation:** 100 families × 2 seeds × {event, control} = 400 runs, 34 min wall on 12 workers (median 67 s per
  event run, SUMO 1.27.1). No unfinished or unroutable trips. Teleports median 26 per event run (~0.2% of trips).
  10 vehicles across 200 event runs entered a closed edge more than 20 min after it closed. All were on one Noe St
  edge, from the queue left when that closure opened at 11:30.
- **Held-out test (31 families):** segment travel-time MAE is 2.84 s for the learned model vs 5.03 s persistence,
  5.44 s event rule and 2.98 s typical-for-this-time, at every horizon. The learned model beats persistence and
  the event rule in 31/31 families. Its margin over *typical* is small: 4–9% in event periods on approach/detour
  roads, and it is worse than typical in 4/31 families. Most of the gain is denoising, not event insight. No method
  predicts sudden build-ups (recall < 2%). Latency is ~90 ms per origin for 931 segments × 3 horizons.
- **Routing replay (3 test scenarios, 30% probes, each policy re-simulated):** learned routing cuts probe trip
  time by 2.3–3.5% vs persistence (−0.8% for all vehicles). The event rule and no-info policies are flat or slightly
  worse. No unfinished trips under any policy. Three scenarios is a small sample.

## Not done / next

- Folsom Street Fair: `prepare`/`network` run (1,075 segments, 94 closed edges). 35/55 closure rows are ambiguous
  and 1 is unmatched (`reports/folsom_join_report.md`), so they must be reviewed before simulating.
- Real validation opportunity: Folsom Street Fair is **2026-09-27**. If the poller runs through it, that is the
  first measured event traffic to test against.
- Contracts: `prediction_metrics` rows can already be produced (`export`), but loading synthetic predictions into
  Tiger or serving them from `api/` needs an agreed `contracts/` change (e.g. a `synthetic`/`run_id` marker so they
  can't be mistaken for real forecasts). Not changed here.
- `web/` / `demo/`: showing the replay and forecast provenance is for those owners, consuming the exported files.
- Calibration: overnight TomTom speeds are only a units/free-flow check. Daytime demand, signal plans and lane
  counts (57% assumed) remain uncalibrated.
