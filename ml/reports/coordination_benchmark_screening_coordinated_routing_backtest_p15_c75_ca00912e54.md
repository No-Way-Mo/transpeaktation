# Coordinated routing benchmark: `screening` · `screening_coordinated_routing_backtest_p15_c75_ca00912e54`

> **Synthetic.** SUMO scenarios on the SF citywide network; demand, attendance and behaviour are assumptions.
> Differences are realized in simulation under these assumptions, not measured on real streets.

- Scenarios (3): `b3_main_bearrison_arrival_f048_s0_event`, `b3_main_bearrison_departure_f050_s0_event`, `b3_main_bearrison_full_f049_s0_event`
- Simulation seeds: [0, 1] · policies: `forecast_only`, `heuristic`, `batch`
- Forecast: `model` (data/forecast/experiments/event_patch_v2_main/best.pt) · participation 0.15 (cap 100000) · compliance 0.75 · batch window 60 s · drain cap 3600 s · teleport after 300 s
- RL checkpoints: {}
- Code: `{"sources_sha": "89aa667e595e8765", "files": 75, "tp_code_id": "f9ad4326a6138ada"}`
- Wall time: 1147.0 s

## Run status

| policy | ok | complete |
|---|---|---|
| batch | 6 | 5 |
| forecast_only | 6 | 4 |
| heuristic | 6 | 4 |

Common complete blocks (every policy complete, identical population): **3 of 6**: `b3_main_bearrison_arrival_f048_s0_event` s0, `b3_main_bearrison_arrival_f048_s0_event` s1, `b3_main_bearrison_full_f049_s0_event` s0

### Failed, incomplete or censored runs (kept visible, excluded from the primary ranking)

| policy | scenario | seed | status | failed_checks | unfinished | teleports | error |
|---|---|---|---|---|---|---|---|
| forecast_only | b3_main_bearrison_departure_f050_s0_event | 0 | ok | all_in_scope_arrived | 2 | 154 |  |
| heuristic | b3_main_bearrison_departure_f050_s0_event | 0 | ok | all_in_scope_arrived | 1 | 131 |  |
| forecast_only | b3_main_bearrison_departure_f050_s0_event | 1 | ok | all_in_scope_arrived | 1 | 162 |  |
| heuristic | b3_main_bearrison_departure_f050_s0_event | 1 | ok | all_in_scope_arrived | 1 | 154 |  |
| batch | b3_main_bearrison_full_f049_s0_event | 1 | ok | all_in_scope_arrived | 1 | 55 |  |

## Mean outcomes per policy (common complete blocks)

vehicle_hours = realized time of every in-scope vehicle (participants and background, including insertion and batching waits), scored from the first decision. congested = vehicle-hours on mapped roads at speed <= 50% of the road's free-flow speed; stopped = speed < 0.1 m/s; pending = in-scope vehicles waiting off-network for insertion. Trip times count from the scheduled departure.

| policy | vehicle_hours | congested_h_scope | congested_h_all | stopped_h_scope | pending_h_scope | part_trip_s_mean | part_trip_s_p95 | other_trip_s_mean | other_trip_s_p95 | unfinished | teleports | decided | non_fastest_share | call_ms_p95 | batch_delay_s_mean | forecast_extra_travel_s_mean | wall_s | peak_mem_mb |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| batch | 930.8 | 282.8 | 527.9 | 214 | 0.04 | 554.3 | 1329 | 640 | 1532 | 0 | 23 | 536.3 | 0.043 | 39.66 | 31.49 | 0.015 | 417.9 | 2656 |
| forecast_only | 922.6 | 282.3 | 529.3 | 213.3 | 0.035 | 523.2 | 1303 | 638.9 | 1535 | 0 | 18.67 | 530.7 | 0.066 | 0.066 | 0 | 0.015 | 424.2 | 2635 |
| heuristic | 923.1 | 282.6 | 519.1 | 213.5 | 0.031 | 522.8 | 1303 | 639.2 | 1532 | 0 | 19 | 533 | 0.076 | 0.225 | 0 | 0.03 | 420.8 | 2634 |

## Paired differences vs `forecast_only` on common complete blocks (policy minus baseline; negative = less)

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| batch | vehicle_hours | 3 | 922.6 | 8.197 | 8.041 | 0.8379 | 0.8944 | 0.8525 | 1.045 | 0 | 3 | 0 | worse in every pair |
| heuristic | vehicle_hours | 3 | 922.6 | 0.4687 | 0.6806 | 0.791 | 0.05 | 0.0665 | 0.13 | 1 | 2 | 0 | inconclusive |
| batch | congested_h_scope | 3 | 282.3 | 0.4955 | 0.8022 | 0.6846 | 0.1875 | 0.2961 | 0.3609 | 1 | 2 | 0 | inconclusive |
| heuristic | congested_h_scope | 3 | 282.3 | 0.2743 | 0.5792 | 0.6042 | 0.0921 | 0.2148 | 0.2172 | 1 | 2 | 0 | inconclusive |
| batch | congested_h_all | 3 | 529.3 | -1.432 | -4.831 | 6.203 | -0.2085 | -0.725 | 1.234 | 2 | 1 | 0 | inconclusive |
| heuristic | congested_h_all | 3 | 529.3 | -10.21 | -6.83 | 11.85 | -1.69 | -1.472 | -0.0899 | 3 | 0 | 0 | better in every pair |
| batch | stopped_h_scope | 3 | 213.3 | 0.6956 | 0.8322 | 0.4613 | 0.3304 | 0.3956 | 0.5133 | 0 | 3 | 0 | worse in every pair |
| heuristic | stopped_h_scope | 3 | 213.3 | 0.1521 | 0.4108 | 0.5295 | 0.0691 | 0.1965 | 0.2279 | 1 | 2 | 0 | inconclusive |
| batch | pending_h_scope | 3 | 0.0345 | 0.0054 | 0.0006 | 0.0086 | 26.87 | 1.111 | 78.57 | 0 | 3 | 0 | worse in every pair |
| heuristic | pending_h_scope | 3 | 0.0345 | -0.0039 | -0.0031 | 0.0046 | -16.93 | -15.71 | 0.4695 | 2 | 1 | 0 | inconclusive |
| batch | part_trip_s_mean | 3 | 523.2 | 31.07 | 30.54 | 1.559 | 6.01 | 5.802 | 6.854 | 0 | 3 | 0 | worse in every pair |
| heuristic | part_trip_s_mean | 3 | 523.2 | -0.3727 | -0.1226 | 0.8219 | -0.0677 | -0.0282 | 0.0522 | 2 | 1 | 0 | inconclusive |
| batch | part_trip_s_p95 | 3 | 1303 | 25.95 | 26.43 | 2.245 | 1.989 | 1.977 | 2.08 | 0 | 3 | 0 | worse in every pair |
| heuristic | part_trip_s_p95 | 3 | 1303 | -0.0533 | 1.065 | 3.141 | -0.0118 | 0.0793 | 0.1777 | 1 | 2 | 0 | inconclusive |
| batch | other_trip_s_mean | 3 | 638.9 | 1.111 | 1.315 | 1.22 | 0.1587 | 0.1911 | 0.3219 | 1 | 2 | 0 | inconclusive |
| heuristic | other_trip_s_mean | 3 | 638.9 | 0.3379 | 0.3567 | 0.4533 | 0.0538 | 0.066 | 0.1136 | 1 | 2 | 0 | inconclusive |
| batch | other_trip_s_p95 | 3 | 1535 | -2.75 | -2.345 | 5.668 | -0.1814 | -0.1513 | 0.1757 | 2 | 1 | 0 | inconclusive |
| heuristic | other_trip_s_p95 | 3 | 1535 | -2.597 | -1.59 | 4.466 | -0.1671 | -0.1033 | 0.0845 | 2 | 1 | 0 | inconclusive |
| batch | part_route_m_mean | 3 | 4303 | 4.297 | 4.109 | 4.93 | 0.0893 | 0.0867 | 0.1967 | 1 | 2 | 0 | inconclusive |
| heuristic | part_route_m_mean | 3 | 4303 | 5.857 | 7.479 | 3.771 | 0.1277 | 0.1578 | 0.1804 | 0 | 3 | 0 | worse in every pair |

## Common-horizon check on every successful block (includes censored runs)

Vehicle-hours through the same drain cap, congested hours and unfinished backlog; a policy that leaves more vehicles unfinished is not better because its completed trips look faster.

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| batch | vehicle_hours | 6 | 999.2 | 8.448 | 8.309 | 2.808 | 0.8574 | 0.8192 | 1.281 | 0 | 6 | 0 | worse in every pair |
| heuristic | vehicle_hours | 6 | 999.2 | 0.2857 | 0.5654 | 0.8323 | 0.0308 | 0.0537 | 0.13 | 2 | 4 | 0 | inconclusive |
| batch | congested_h_scope | 6 | 301.5 | 0.4466 | 0.5768 | 2.349 | 0.1728 | 0.2019 | 1.34 | 2 | 4 | 0 | inconclusive |
| heuristic | congested_h_scope | 6 | 301.5 | 0.3665 | 0.6222 | 0.5967 | 0.1197 | 0.216 | 0.2784 | 2 | 4 | 0 | inconclusive |
| batch | unfinished | 6 | 0.5 | -0.3333 | 0 | 1.033 | -100 | -100 | -100 | 2 | 1 | 3 | inconclusive |
| heuristic | unfinished | 6 | 0.5 | -0.1667 | 0 | 0.4082 | -25 | -25 | 0 | 1 | 0 | 5 | inconclusive |

## Ranking by paired total vehicle-hours (common complete blocks)

1. `forecast_only`: +0.000 veh-h (+0.00%) vs forecast_only
2. `heuristic`: +0.469 veh-h (+0.05%) vs forecast_only (inconclusive)
3. `batch`: +8.197 veh-h (+0.89%) vs forecast_only (worse in every pair)

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
   "vehicle_hours_reduction_pct": -0.0499828224619153,
   "vehicle_hours_mean_diff": 0.46870370370371955,
   "blocks_better": 1.0,
   "blocks_worse": 2.0,
   "consistent_reduction": false,
   "congested_scope_reduction_pct": -0.09210975546063942,
   "background_mean_change_pct": 0.05383219521949297,
   "participant_p95_change_pct": -0.011844186647699725,
   "meets_vehicle_hours_target": false,
   "lower_congestion": false,
   "background_ok": true,
   "participant_p95_ok": true
  },
  "batch": {
   "vehicle_hours_reduction_pct": -0.8944363985809103,
   "vehicle_hours_mean_diff": 8.196750000000103,
   "blocks_better": 0.0,
   "blocks_worse": 3.0,
   "consistent_reduction": false,
   "congested_scope_reduction_pct": -0.18754943510446545,
   "background_mean_change_pct": 0.15872125986573188,
   "participant_p95_change_pct": 1.9892068171388757,
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
  "teleports": 336,
  "call_ms_p95_max": 40.94797160000773
 },
 "forecast_only": {
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
  "unfinished": 3,
  "teleports": 416,
  "call_ms_p95_max": 0.07180249996281417
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
  "teleports": 392,
  "call_ms_p95_max": 0.23882600001456894
 }
}
```
