# Coordinated routing benchmark: `screening` · `screening_coordinated_routing_backtest_p30_c100_7159af54b0`

> **Synthetic.** SUMO scenarios on the SF citywide network; demand, attendance and behaviour are assumptions.
> Differences are realized in simulation under these assumptions, not measured on real streets.

- Scenarios (3): `b3_main_bearrison_arrival_f048_s0_event`, `b3_main_bearrison_departure_f050_s0_event`, `b3_main_bearrison_full_f049_s0_event`
- Simulation seeds: [0, 1] · policies: `forecast_only`, `heuristic`, `batch`
- Forecast: `model` (data/forecast/experiments/event_patch_v2_main/best.pt) · participation 0.3 (cap 100000) · compliance 1.0 · batch window 60 s · drain cap 3600 s · teleport after 300 s
- RL checkpoints: {}
- Code: `{"sources_sha": "89aa667e595e8765", "files": 75, "tp_code_id": "f9ad4326a6138ada"}`
- Wall time: 1147.0 s

## Run status

| policy | ok | complete |
|---|---|---|
| batch | 6 | 5 |
| forecast_only | 6 | 6 |
| heuristic | 6 | 5 |

Common complete blocks (every policy complete, identical population): **4 of 6**: `b3_main_bearrison_arrival_f048_s0_event` s0, `b3_main_bearrison_arrival_f048_s0_event` s1, `b3_main_bearrison_full_f049_s0_event` s0, `b3_main_bearrison_full_f049_s0_event` s1

### Failed, incomplete or censored runs (kept visible, excluded from the primary ranking)

| policy | scenario | seed | status | failed_checks | unfinished | teleports | error |
|---|---|---|---|---|---|---|---|
| heuristic | b3_main_bearrison_departure_f050_s0_event | 0 | ok | all_in_scope_arrived | 1 | 165 |  |
| batch | b3_main_bearrison_departure_f050_s0_event | 1 | ok | all_in_scope_arrived | 1 | 154 |  |

## Mean outcomes per policy (common complete blocks)

vehicle_hours = realized time of every in-scope vehicle (participants and background, including insertion and batching waits), scored from the first decision. congested = vehicle-hours on mapped roads at speed <= 50% of the road's free-flow speed; stopped = speed < 0.1 m/s; pending = in-scope vehicles waiting off-network for insertion. Trip times count from the scheduled departure.

| policy | vehicle_hours | congested_h_scope | congested_h_all | stopped_h_scope | pending_h_scope | part_trip_s_mean | part_trip_s_p95 | other_trip_s_mean | other_trip_s_p95 | unfinished | teleports | decided | non_fastest_share | call_ms_p95 | batch_delay_s_mean | forecast_extra_travel_s_mean | wall_s | peak_mem_mb |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| batch | 954.7 | 277.2 | 599 | 203.9 | 0.062 | 525.5 | 1297 | 627.8 | 1550 | 0 | 34.5 | 1149 | 0.058 | 64.14 | 31.16 | 0.041 | 523.2 | 2680 |
| forecast_only | 935.9 | 274 | 586.1 | 201.1 | 0.047 | 491.8 | 1253 | 626 | 1541 | 0 | 25.25 | 1152 | 0.056 | 0.07 | 0 | 0.013 | 526 | 2655 |
| heuristic | 936.2 | 274.2 | 582.4 | 201.3 | 0.045 | 492.2 | 1248 | 626.2 | 1542 | 0 | 22 | 1156 | 0.078 | 0.258 | 0 | 0.054 | 528.2 | 2650 |

## Paired differences vs `forecast_only` on common complete blocks (policy minus baseline; negative = less)

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| batch | vehicle_hours | 4 | 935.9 | 18.83 | 18.25 | 8.604 | 1.964 | 1.914 | 2.832 | 0 | 4 | 0 | worse in every pair |
| heuristic | vehicle_hours | 4 | 935.9 | 0.3853 | 0.5535 | 0.6459 | 0.0446 | 0.0593 | 0.1128 | 1 | 3 | 0 | inconclusive |
| batch | congested_h_scope | 4 | 274 | 3.155 | 2.722 | 3.756 | 1.095 | 0.9712 | 2.772 | 1 | 3 | 0 | inconclusive |
| heuristic | congested_h_scope | 4 | 274 | 0.2015 | 0.4635 | 0.5826 | 0.0818 | 0.1712 | 0.2131 | 1 | 3 | 0 | inconclusive |
| batch | congested_h_all | 4 | 586.1 | 12.85 | 12.89 | 22.57 | 1.575 | 1.778 | 4.68 | 2 | 2 | 0 | inconclusive |
| heuristic | congested_h_all | 4 | 586.1 | -3.75 | -3.256 | 3.873 | -0.6879 | -0.4719 | 0.0409 | 3 | 1 | 0 | inconclusive |
| batch | stopped_h_scope | 4 | 201.1 | 2.87 | 2.556 | 3.344 | 1.402 | 1.258 | 3.501 | 1 | 3 | 0 | inconclusive |
| heuristic | stopped_h_scope | 4 | 201.1 | 0.2708 | 0.4769 | 0.6528 | 0.1398 | 0.2385 | 0.4107 | 1 | 3 | 0 | inconclusive |
| batch | pending_h_scope | 4 | 0.0467 | 0.0155 | 0.0182 | 0.0226 | 22.87 | 30.15 | 65.73 | 1 | 3 | 0 | inconclusive |
| heuristic | pending_h_scope | 4 | 0.0467 | -0.0017 | -0.0046 | 0.0121 | 4.222 | -5.08 | 47.27 | 2 | 2 | 0 | inconclusive |
| batch | part_trip_s_mean | 4 | 491.8 | 33.73 | 32.58 | 4.906 | 7.099 | 6.814 | 9.476 | 0 | 4 | 0 | worse in every pair |
| heuristic | part_trip_s_mean | 4 | 491.8 | 0.4548 | 0.4516 | 0.7394 | 0.0775 | 0.0833 | 0.2312 | 1 | 3 | 0 | inconclusive |
| batch | part_trip_s_p95 | 4 | 1253 | 44.58 | 35.66 | 33.34 | 3.65 | 2.838 | 7.789 | 0 | 4 | 0 | worse in every pair |
| heuristic | part_trip_s_p95 | 4 | 1253 | -4.965 | -3.195 | 4.564 | -0.3906 | -0.2649 | -0.1388 | 4 | 0 | 0 | better in every pair |
| batch | other_trip_s_mean | 4 | 626 | 1.763 | 2.049 | 1.635 | 0.3055 | 0.3338 | 0.6228 | 1 | 3 | 0 | inconclusive |
| heuristic | other_trip_s_mean | 4 | 626 | 0.1844 | 0.2515 | 0.2671 | 0.0275 | 0.0419 | 0.0608 | 1 | 3 | 0 | inconclusive |
| batch | other_trip_s_p95 | 4 | 1541 | 9.172 | 9.945 | 10.22 | 0.5995 | 0.642 | 1.245 | 1 | 3 | 0 | inconclusive |
| heuristic | other_trip_s_p95 | 4 | 1541 | 0.5588 | 2.025 | 4.145 | 0.037 | 0.1317 | 0.229 | 1 | 3 | 0 | inconclusive |
| batch | part_route_m_mean | 4 | 4145 | -0.3146 | 0.3751 | 2.9 | -0.002 | 0.007 | 0.0684 | 2 | 2 | 0 | inconclusive |
| heuristic | part_route_m_mean | 4 | 4145 | 0.6955 | 0.0981 | 1.683 | 0.0135 | 0.0026 | 0.0656 | 1 | 3 | 0 | inconclusive |

## Common-horizon check on every successful block (includes censored runs)

Vehicle-hours through the same drain cap, congested hours and unfinished backlog; a policy that leaves more vehicles unfinished is not better because its completed trips look faster.

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| batch | vehicle_hours | 6 | 989.4 | 19.03 | 19.43 | 6.889 | 1.9 | 1.771 | 2.832 | 0 | 6 | 0 | worse in every pair |
| heuristic | vehicle_hours | 6 | 989.4 | 2.076 | 0.7769 | 2.886 | 0.1957 | 0.0868 | 0.6584 | 1 | 5 | 0 | inconclusive |
| batch | congested_h_scope | 6 | 288.8 | 3.432 | 2.722 | 3.391 | 1.146 | 0.9712 | 2.772 | 1 | 5 | 0 | inconclusive |
| heuristic | congested_h_scope | 6 | 288.8 | 1.381 | 0.5339 | 2.111 | 0.4473 | 0.2077 | 1.659 | 1 | 5 | 0 | inconclusive |
| batch | unfinished | 6 | 0 | 0.1667 | 0 | 0.4082 |  |  |  | 0 | 1 | 5 | inconclusive |
| heuristic | unfinished | 6 | 0 | 0.1667 | 0 | 0.4082 |  |  |  | 0 | 1 | 5 | inconclusive |

## Ranking by paired total vehicle-hours (common complete blocks)

1. `forecast_only`: +0.000 veh-h (+0.00%) vs forecast_only
2. `heuristic`: +0.385 veh-h (+0.04%) vs forecast_only (inconclusive)
3. `batch`: +18.828 veh-h (+1.96%) vs forecast_only (worse in every pair)

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
   "vehicle_hours_reduction_pct": -0.044588413989632016,
   "vehicle_hours_mean_diff": 0.38534722222217965,
   "blocks_better": 1.0,
   "blocks_worse": 3.0,
   "consistent_reduction": false,
   "congested_scope_reduction_pct": -0.0817571923050458,
   "background_mean_change_pct": 0.02751221904661605,
   "participant_p95_change_pct": -0.3906466208112148,
   "meets_vehicle_hours_target": false,
   "lower_congestion": false,
   "background_ok": true,
   "participant_p95_ok": true
  },
  "batch": {
   "vehicle_hours_reduction_pct": -1.9638483975717205,
   "vehicle_hours_mean_diff": 18.827666666666232,
   "blocks_better": 0.0,
   "blocks_worse": 4.0,
   "consistent_reduction": false,
   "congested_scope_reduction_pct": -1.0949285115711187,
   "background_mean_change_pct": 0.3054619860735987,
   "participant_p95_change_pct": 3.6504255107576027,
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
  "teleports": 459,
  "call_ms_p95_max": 72.58474765000071
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
  "teleports": 321,
  "call_ms_p95_max": 0.07163524998077264
 },
 "heuristic": {
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
  "teleports": 400,
  "call_ms_p95_max": 0.2901700000251139
 }
}
```
