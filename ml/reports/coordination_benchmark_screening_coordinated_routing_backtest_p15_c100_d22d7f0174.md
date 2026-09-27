# Coordinated routing benchmark: `screening` · `screening_coordinated_routing_backtest_p15_c100_d22d7f0174`

> **Synthetic.** SUMO scenarios on the SF citywide network; demand, attendance and behaviour are assumptions.
> Differences are realized in simulation under these assumptions, not measured on real streets.

- Scenarios (3): `b3_main_bearrison_arrival_f048_s0_event`, `b3_main_bearrison_departure_f050_s0_event`, `b3_main_bearrison_full_f049_s0_event`
- Simulation seeds: [0, 1] · policies: `forecast_only`, `heuristic`, `batch`
- Forecast: `model` (data/forecast/experiments/event_patch_v2_main/best.pt) · participation 0.15 (cap 100000) · compliance 1.0 · batch window 60 s · drain cap 3600 s · teleport after 300 s
- RL checkpoints: {}
- Code: `{"sources_sha": "89aa667e595e8765", "files": 75, "tp_code_id": "f9ad4326a6138ada"}`
- Wall time: 1147.0 s

## Run status

| policy | ok | complete |
|---|---|---|
| batch | 6 | 5 |
| forecast_only | 6 | 5 |
| heuristic | 6 | 4 |

Common complete blocks (every policy complete, identical population): **4 of 6**: `b3_main_bearrison_arrival_f048_s0_event` s0, `b3_main_bearrison_arrival_f048_s0_event` s1, `b3_main_bearrison_departure_f050_s0_event` s0, `b3_main_bearrison_full_f049_s0_event` s1

### Failed, incomplete or censored runs (kept visible, excluded from the primary ranking)

| policy | scenario | seed | status | failed_checks | unfinished | teleports | error |
|---|---|---|---|---|---|---|---|
| forecast_only | b3_main_bearrison_departure_f050_s0_event | 1 | ok | all_in_scope_arrived | 2 | 131 |  |
| heuristic | b3_main_bearrison_departure_f050_s0_event | 1 | ok | all_in_scope_arrived | 1 | 141 |  |
| batch | b3_main_bearrison_departure_f050_s0_event | 1 | ok | all_in_scope_arrived | 2 | 105 |  |
| heuristic | b3_main_bearrison_full_f049_s0_event | 0 | ok | all_in_scope_arrived | 1 | 68 |  |

## Mean outcomes per policy (common complete blocks)

vehicle_hours = realized time of every in-scope vehicle (participants and background, including insertion and batching waits), scored from the first decision. congested = vehicle-hours on mapped roads at speed <= 50% of the road's free-flow speed; stopped = speed < 0.1 m/s; pending = in-scope vehicles waiting off-network for insertion. Trip times count from the scheduled departure.

| policy | vehicle_hours | congested_h_scope | congested_h_all | stopped_h_scope | pending_h_scope | part_trip_s_mean | part_trip_s_p95 | other_trip_s_mean | other_trip_s_p95 | unfinished | teleports | decided | non_fastest_share | call_ms_p95 | batch_delay_s_mean | forecast_extra_travel_s_mean | wall_s | peak_mem_mb |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| batch | 974.2 | 291.5 | 672.7 | 220.8 | 0.07 | 538.5 | 1307 | 641.2 | 1566 | 0 | 44.25 | 551 | 0.04 | 32.7 | 31.56 | 0.019 | 484.1 | 2638 |
| forecast_only | 965.6 | 290.5 | 676.3 | 219.8 | 0.047 | 506.3 | 1286 | 640.5 | 1562 | 0 | 45 | 550 | 0.056 | 0.065 | 0 | 0.014 | 492.1 | 2614 |
| heuristic | 967.7 | 292 | 661 | 221.1 | 0.047 | 507.5 | 1295 | 641.5 | 1565 | 0 | 42 | 549.8 | 0.068 | 0.232 | 0 | 0.035 | 492.6 | 2611 |

## Paired differences vs `forecast_only` on common complete blocks (policy minus baseline; negative = less)

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| batch | vehicle_hours | 4 | 965.6 | 8.545 | 7.638 | 3.014 | 0.8758 | 0.7739 | 1.25 | 0 | 4 | 0 | worse in every pair |
| heuristic | vehicle_hours | 4 | 965.6 | 2.089 | 0.5708 | 4.096 | 0.2093 | 0.0723 | 0.7832 | 2 | 2 | 0 | inconclusive |
| batch | congested_h_scope | 4 | 290.5 | 1.025 | 0.4131 | 1.288 | 0.3459 | 0.1517 | 0.9762 | 0 | 4 | 0 | worse in every pair |
| heuristic | congested_h_scope | 4 | 290.5 | 1.446 | 0.6639 | 2.77 | 0.4982 | 0.2495 | 1.755 | 2 | 2 | 0 | inconclusive |
| batch | congested_h_all | 4 | 676.3 | -3.648 | -12.72 | 26.31 | -0.7065 | -1.556 | 5.013 | 3 | 1 | 0 | inconclusive |
| heuristic | congested_h_all | 4 | 676.3 | -15.33 | 0.4356 | 35.39 | -1.36 | 0.0878 | 0.889 | 2 | 2 | 0 | inconclusive |
| batch | stopped_h_scope | 4 | 219.8 | 1.032 | 0.6004 | 1 | 0.4702 | 0.2618 | 1.159 | 0 | 4 | 0 | worse in every pair |
| heuristic | stopped_h_scope | 4 | 219.8 | 1.294 | 0.645 | 2.313 | 0.6125 | 0.3135 | 2.06 | 2 | 2 | 0 | inconclusive |
| batch | pending_h_scope | 4 | 0.0474 | 0.0224 | 0.0183 | 0.0139 | 56.8 | 54.58 | 84.31 | 0 | 4 | 0 | worse in every pair |
| heuristic | pending_h_scope | 4 | 0.0474 | -0.0003 | -0.0003 | 0.0015 | -0.5348 | -0.3378 | 9.804 | 2 | 1 | 1 | inconclusive |
| batch | part_trip_s_mean | 4 | 506.3 | 32.13 | 31.64 | 2.357 | 6.453 | 5.876 | 8.342 | 0 | 4 | 0 | worse in every pair |
| heuristic | part_trip_s_mean | 4 | 506.3 | 1.165 | 0.224 | 3.305 | 0.2805 | 0.0407 | 1.334 | 2 | 2 | 0 | inconclusive |
| batch | part_trip_s_p95 | 4 | 1286 | 20.88 | 21.18 | 9.916 | 1.626 | 1.693 | 2.356 | 0 | 4 | 0 | worse in every pair |
| heuristic | part_trip_s_p95 | 4 | 1286 | 8.36 | 7.22 | 8.501 | 0.6681 | 0.5595 | 1.509 | 0 | 4 | 0 | worse in every pair |
| batch | other_trip_s_mean | 4 | 640.5 | 0.7219 | 0.6429 | 0.4878 | 0.1203 | 0.0967 | 0.2564 | 0 | 4 | 0 | worse in every pair |
| heuristic | other_trip_s_mean | 4 | 640.5 | 0.9237 | 0.4525 | 1.64 | 0.1658 | 0.0653 | 0.593 | 2 | 2 | 0 | inconclusive |
| batch | other_trip_s_p95 | 4 | 1562 | 3.93 | 4.1 | 7.008 | 0.2605 | 0.2663 | 0.798 | 1 | 3 | 0 | inconclusive |
| heuristic | other_trip_s_p95 | 4 | 1562 | 3.038 | -1.025 | 11.26 | 0.1993 | -0.065 | 1.28 | 3 | 1 | 0 | inconclusive |
| batch | part_route_m_mean | 4 | 4379 | -0.907 | 0.1637 | 3.675 | -0.0191 | 0.009 | 0.0432 | 2 | 2 | 0 | inconclusive |
| heuristic | part_route_m_mean | 4 | 4379 | 1.526 | 1.882 | 3.389 | 0.033 | 0.0417 | 0.0958 | 2 | 2 | 0 | inconclusive |

## Common-horizon check on every successful block (includes censored runs)

Vehicle-hours through the same drain cap, congested hours and unfinished backlog; a policy that leaves more vehicles unfinished is not better because its completed trips look faster.

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| batch | vehicle_hours | 6 | 996.5 | 8.576 | 8.038 | 2.454 | 0.8577 | 0.7739 | 1.25 | 0 | 6 | 0 | worse in every pair |
| heuristic | vehicle_hours | 6 | 996.5 | 1.828 | 0.715 | 3.349 | 0.1826 | 0.0853 | 0.7832 | 3 | 3 | 0 | inconclusive |
| batch | congested_h_scope | 6 | 298.2 | 0.8518 | 0.4131 | 1.071 | 0.2861 | 0.1517 | 0.9762 | 0 | 6 | 0 | worse in every pair |
| heuristic | congested_h_scope | 6 | 298.2 | 1.203 | 0.6639 | 2.259 | 0.4123 | 0.2404 | 1.755 | 3 | 3 | 0 | inconclusive |
| batch | unfinished | 6 | 0.3333 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6 | inconclusive |
| heuristic | unfinished | 6 | 0.3333 | 0 | 0 | 0.6325 | -50 | -50 | -50 | 1 | 1 | 4 | inconclusive |

## Ranking by paired total vehicle-hours (common complete blocks)

1. `forecast_only`: +0.000 veh-h (+0.00%) vs forecast_only
2. `heuristic`: +2.089 veh-h (+0.21%) vs forecast_only (inconclusive)
3. `batch`: +8.545 veh-h (+0.88%) vs forecast_only (worse in every pair)

**No eligible policy.**
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
   "vehicle_hours_reduction_pct": -0.20933443704336469,
   "vehicle_hours_mean_diff": 2.0890277777777726,
   "blocks_better": 2.0,
   "blocks_worse": 2.0,
   "consistent_reduction": false,
   "congested_scope_reduction_pct": -0.49819581551125813,
   "background_mean_change_pct": 0.16582286592087594,
   "participant_p95_change_pct": 0.6680633183185788,
   "meets_vehicle_hours_target": false,
   "lower_congestion": false,
   "background_ok": true,
   "participant_p95_ok": true
  },
  "batch": {
   "vehicle_hours_reduction_pct": -0.8757733658448663,
   "vehicle_hours_mean_diff": 8.544986111111172,
   "blocks_better": 0.0,
   "blocks_worse": 4.0,
   "consistent_reduction": false,
   "congested_scope_reduction_pct": -0.3458797158734603,
   "background_mean_change_pct": 0.12029850408444773,
   "participant_p95_change_pct": 1.6263597549794029,
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
  "unfinished": 2,
  "teleports": 328,
  "call_ms_p95_max": 49.42803544998918
 },
 "forecast_only": {
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
  "unfinished": 2,
  "teleports": 330,
  "call_ms_p95_max": 0.06983100003026266
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
  "teleports": 377,
  "call_ms_p95_max": 0.2373879999595374
 }
}
```
