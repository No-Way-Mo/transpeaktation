# Coordinated routing benchmark: `screening` · `screening_coordinated_routing_backtest_p15_c50_332d08c687`

> **Synthetic.** SUMO scenarios on the SF citywide network; demand, attendance and behaviour are assumptions.
> Differences are realized in simulation under these assumptions, not measured on real streets.

- Scenarios (3): `b3_main_bearrison_arrival_f048_s0_event`, `b3_main_bearrison_departure_f050_s0_event`, `b3_main_bearrison_full_f049_s0_event`
- Simulation seeds: [0, 1] · policies: `forecast_only`, `heuristic`, `batch`
- Forecast: `model` (data/forecast/experiments/event_patch_v2_main/best.pt) · participation 0.15 (cap 100000) · compliance 0.5 · batch window 60 s · drain cap 3600 s · teleport after 300 s
- RL checkpoints: {}
- Code: `{"sources_sha": "89aa667e595e8765", "files": 75, "tp_code_id": "f9ad4326a6138ada"}`
- Wall time: 1147.0 s

## Run status

| policy | ok | complete |
|---|---|---|
| batch | 6 | 5 |
| forecast_only | 6 | 6 |
| heuristic | 6 | 4 |

Common complete blocks (every policy complete, identical population): **4 of 6**: `b3_main_bearrison_arrival_f048_s0_event` s0, `b3_main_bearrison_arrival_f048_s0_event` s1, `b3_main_bearrison_full_f049_s0_event` s0, `b3_main_bearrison_full_f049_s0_event` s1

### Failed, incomplete or censored runs (kept visible, excluded from the primary ranking)

| policy | scenario | seed | status | failed_checks | unfinished | teleports | error |
|---|---|---|---|---|---|---|---|
| heuristic | b3_main_bearrison_departure_f050_s0_event | 0 | ok | all_in_scope_arrived | 1 | 133 |  |
| batch | b3_main_bearrison_departure_f050_s0_event | 0 | ok | all_in_scope_arrived | 1 | 134 |  |
| heuristic | b3_main_bearrison_departure_f050_s0_event | 1 | ok | all_in_scope_arrived | 1 | 152 |  |

## Mean outcomes per policy (common complete blocks)

vehicle_hours = realized time of every in-scope vehicle (participants and background, including insertion and batching waits), scored from the first decision. congested = vehicle-hours on mapped roads at speed <= 50% of the road's free-flow speed; stopped = speed < 0.1 m/s; pending = in-scope vehicles waiting off-network for insertion. Trip times count from the scheduled departure.

| policy | vehicle_hours | congested_h_scope | congested_h_all | stopped_h_scope | pending_h_scope | part_trip_s_mean | part_trip_s_p95 | other_trip_s_mean | other_trip_s_p95 | unfinished | teleports | decided | non_fastest_share | call_ms_p95 | batch_delay_s_mean | forecast_extra_travel_s_mean | wall_s | peak_mem_mb |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| batch | 958.6 | 291.7 | 624.2 | 218.7 | 0.049 | 542.1 | 1353 | 614.8 | 1539 | 0 | 38.5 | 578.5 | 0.036 | 34.59 | 31.52 | 0.014 | 477 | 2673 |
| forecast_only | 949.3 | 290.1 | 583 | 217.3 | 0.042 | 509.2 | 1321 | 614 | 1530 | 0 | 25.5 | 574.5 | 0.057 | 0.066 | 0 | 0.013 | 452.8 | 2644 |
| heuristic | 949.7 | 290.4 | 568.1 | 217.4 | 0.044 | 509.9 | 1332 | 614.3 | 1532 | 0 | 24.5 | 575.5 | 0.061 | 0.213 | 0 | 0.026 | 449.7 | 2655 |

## Paired differences vs `forecast_only` on common complete blocks (policy minus baseline; negative = less)

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| batch | vehicle_hours | 4 | 949.3 | 9.312 | 7.995 | 4.593 | 0.96 | 0.8346 | 1.54 | 0 | 4 | 0 | worse in every pair |
| heuristic | vehicle_hours | 4 | 949.3 | 0.4501 | 0.3999 | 1.476 | 0.0543 | 0.0404 | 0.2619 | 1 | 3 | 0 | inconclusive |
| batch | congested_h_scope | 4 | 290.1 | 1.609 | 0.6578 | 2.067 | 0.5329 | 0.2272 | 1.524 | 0 | 4 | 0 | worse in every pair |
| heuristic | congested_h_scope | 4 | 290.1 | 0.2743 | 0.4529 | 1.092 | 0.1076 | 0.1535 | 0.5157 | 1 | 3 | 0 | inconclusive |
| batch | congested_h_all | 4 | 583 | 41.17 | 52.99 | 59.36 | 8.525 | 9.377 | 20.94 | 1 | 3 | 0 | inconclusive |
| heuristic | congested_h_all | 4 | 583 | -14.91 | -1.938 | 27.36 | -2.06 | -0.2903 | 0.0218 | 3 | 1 | 0 | inconclusive |
| batch | stopped_h_scope | 4 | 217.3 | 1.375 | 0.5861 | 1.8 | 0.6229 | 0.2773 | 1.82 | 0 | 4 | 0 | worse in every pair |
| heuristic | stopped_h_scope | 4 | 217.3 | 0.0921 | 0.2489 | 1.003 | 0.0497 | 0.1139 | 0.541 | 1 | 3 | 0 | inconclusive |
| batch | pending_h_scope | 4 | 0.0423 | 0.0063 | 0.0035 | 0.0134 | 9.879 | 14.46 | 32.72 | 1 | 3 | 0 | inconclusive |
| heuristic | pending_h_scope | 4 | 0.0423 | 0.0013 | 0.0019 | 0.0065 | 6.231 | 3.227 | 26.92 | 2 | 2 | 0 | inconclusive |
| batch | part_trip_s_mean | 4 | 509.2 | 32.88 | 31.87 | 3.102 | 6.596 | 6.352 | 8.385 | 0 | 4 | 0 | worse in every pair |
| heuristic | part_trip_s_mean | 4 | 509.2 | 0.7359 | 1.489 | 2.216 | 0.1268 | 0.2586 | 0.559 | 1 | 3 | 0 | inconclusive |
| batch | part_trip_s_p95 | 4 | 1321 | 31.76 | 44.86 | 48.62 | 2.424 | 3.347 | 5.655 | 1 | 3 | 0 | inconclusive |
| heuristic | part_trip_s_p95 | 4 | 1321 | 11.49 | 10.16 | 36.09 | 0.8996 | 0.7663 | 4.055 | 2 | 2 | 0 | inconclusive |
| batch | other_trip_s_mean | 4 | 614 | 0.8149 | 0.528 | 1.293 | 0.1487 | 0.0843 | 0.4874 | 1 | 3 | 0 | inconclusive |
| heuristic | other_trip_s_mean | 4 | 614 | 0.2649 | -0.0537 | 0.8057 | 0.0354 | -0.0083 | 0.2124 | 3 | 1 | 0 | inconclusive |
| batch | other_trip_s_p95 | 4 | 1530 | 8.759 | 6.468 | 13.49 | 0.5758 | 0.4328 | 1.645 | 2 | 2 | 0 | inconclusive |
| heuristic | other_trip_s_p95 | 4 | 1530 | 2.374 | 0.7575 | 5.533 | 0.1538 | 0.0486 | 0.668 | 2 | 2 | 0 | inconclusive |
| batch | part_route_m_mean | 4 | 4037 | -2.319 | 0.6336 | 8.984 | -0.0438 | 0.0054 | 0.1355 | 2 | 2 | 0 | inconclusive |
| heuristic | part_route_m_mean | 4 | 4037 | -1.147 | -0.0314 | 4.722 | -0.0245 | -0.0077 | 0.0718 | 2 | 2 | 0 | inconclusive |

## Common-horizon check on every successful block (includes censored runs)

Vehicle-hours through the same drain cap, congested hours and unfinished backlog; a policy that leaves more vehicles unfinished is not better because its completed trips look faster.

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| batch | vehicle_hours | 6 | 1001 | 8.547 | 7.995 | 4.109 | 0.8517 | 0.813 | 1.54 | 0 | 6 | 0 | worse in every pair |
| heuristic | vehicle_hours | 6 | 1001 | 0.1225 | -0.0901 | 1.257 | 0.0201 | -0.0063 | 0.2619 | 3 | 3 | 0 | inconclusive |
| batch | congested_h_scope | 6 | 303.9 | 1.05 | 0.6578 | 2.173 | 0.3485 | 0.2272 | 1.524 | 1 | 5 | 0 | inconclusive |
| heuristic | congested_h_scope | 6 | 303.9 | 0.2302 | 0.3974 | 0.8761 | 0.086 | 0.13 | 0.5157 | 2 | 4 | 0 | inconclusive |
| batch | unfinished | 6 | 0 | 0.1667 | 0 | 0.4082 |  |  |  | 0 | 1 | 5 | inconclusive |
| heuristic | unfinished | 6 | 0 | 0.3333 | 0 | 0.5164 |  |  |  | 0 | 2 | 4 | inconclusive |

## Ranking by paired total vehicle-hours (common complete blocks)

1. `forecast_only`: +0.000 veh-h (+0.00%) vs forecast_only
2. `heuristic`: +0.450 veh-h (+0.05%) vs forecast_only (inconclusive)
3. `batch`: +9.312 veh-h (+0.96%) vs forecast_only (worse in every pair)

**Best eligible policy on this suite: `forecast_only`**
(eligible = every run of the policy completed strictly). With this few blocks a small mean difference that is not consistent across pairs is inconclusive; 'better in every pair' is not a significance test.

## Development targets (plan §7, fixed before the runs)

```json
{
 "targets": {
  "vehicle_hours_reduction_pct_min": 5.0,
  "background_mean_worse_pct_max": 2.0,
  "participant_p95_worse_pct_max": 5.0
 },
 "per_policy": {
  "heuristic": {
   "vehicle_hours_reduction_pct": -0.0542558306304321,
   "vehicle_hours_mean_diff": 0.45006944444446617,
   "blocks_better": 1.0,
   "blocks_worse": 3.0,
   "consistent_reduction": false,
   "congested_scope_reduction_pct": -0.10760622562009708,
   "background_mean_change_pct": 0.035380041750484696,
   "participant_p95_change_pct": 0.8995952529857807,
   "meets_vehicle_hours_target": false,
   "lower_congestion": false,
   "background_ok": true,
   "participant_p95_ok": true
  },
  "batch": {
   "vehicle_hours_reduction_pct": -0.9600137607412451,
   "vehicle_hours_mean_diff": 9.312097222222349,
   "blocks_better": 0.0,
   "blocks_worse": 4.0,
   "consistent_reduction": false,
   "congested_scope_reduction_pct": -0.5329456777663769,
   "background_mean_change_pct": 0.1487195160096949,
   "participant_p95_change_pct": 2.4236181009204634,
   "meets_vehicle_hours_target": false,
   "lower_congestion": false,
   "background_ok": true,
   "participant_p95_ok": true
  }
 }
}
```

## Constraints

```json
{
 "batch": {
  "runs": 6,
  "ok": 6,
  "complete": 5,
  "unavailable": 0,
  "failed": 0,
  "invalid_routes": 0,
  "selector_failures": 0,
  "unchosen_fallbacks": 0,
  "dropped_trips": 0,
  "readback_mismatch": 0,
  "unfinished": 1,
  "teleports": 383,
  "call_ms_p95_max": 43.848695099981654
 },
 "forecast_only": {
  "runs": 6,
  "ok": 6,
  "complete": 6,
  "unavailable": 0,
  "failed": 0,
  "invalid_routes": 0,
  "selector_failures": 0,
  "unchosen_fallbacks": 0,
  "dropped_trips": 0,
  "readback_mismatch": 0,
  "unfinished": 0,
  "teleports": 348,
  "call_ms_p95_max": 0.07023215000856452
 },
 "heuristic": {
  "runs": 6,
  "ok": 6,
  "complete": 4,
  "unavailable": 0,
  "failed": 0,
  "invalid_routes": 0,
  "selector_failures": 0,
  "unchosen_fallbacks": 0,
  "dropped_trips": 0,
  "readback_mismatch": 0,
  "unfinished": 2,
  "teleports": 383,
  "call_ms_p95_max": 0.23690399998486103
 }
}
```
