# Coordinated routing benchmark: `heldout` · `heldout_coordinated_routing_backtest_p5_c100_8fd691a3e8`

> **Synthetic.** SUMO scenarios on the SF citywide network; demand, attendance and behaviour are assumptions.
> Differences are realized in simulation under these assumptions, not measured on real streets.

- Scenarios (6): `b3_main_portola_arrival_f024_s0_event`, `b3_main_portola_departure_f026_s0_event`, `b3_main_portola_full_f025_s0_event`, `b3_main_portola_arrival_f030_s0_event`, `b3_main_portola_departure_f029_s0_event`, `b3_main_portola_full_f028_s0_event`
- Simulation seeds: [0, 1, 2] · policies: `forecast_only`, `heuristic`, `heuristic@lam=120`, `batch`
- Forecast: `model` (data/forecast/experiments/event_patch_v2_main/best.pt) · participation 0.05 (cap 100000) · compliance 1.0 · batch window 60 s · drain cap 3600 s · teleport after 300 s
- RL checkpoints: {}
- Code: `{"sources_sha": "89aa667e595e8765", "files": 75, "tp_code_id": "f9ad4326a6138ada"}`
- Wall time: 949.0 s

## Run status

| policy | ok | complete |
|---|---|---|
| batch | 18 | 14 |
| forecast_only | 18 | 16 |
| heuristic | 18 | 16 |
| heuristic@lam=120 | 18 | 17 |

Common complete blocks (every policy complete, identical population): **13 of 18**: `b3_main_portola_arrival_f030_s0_event` s0, `b3_main_portola_arrival_f030_s0_event` s1, `b3_main_portola_arrival_f030_s0_event` s2, `b3_main_portola_departure_f026_s0_event` s2, `b3_main_portola_departure_f029_s0_event` s0, `b3_main_portola_departure_f029_s0_event` s1, `b3_main_portola_departure_f029_s0_event` s2, `b3_main_portola_full_f025_s0_event` s0, `b3_main_portola_full_f025_s0_event` s1, `b3_main_portola_full_f025_s0_event` s2, `b3_main_portola_full_f028_s0_event` s0, `b3_main_portola_full_f028_s0_event` s1, `b3_main_portola_full_f028_s0_event` s2

### Failed, incomplete or censored runs (kept visible, excluded from the primary ranking)

| policy | scenario | seed | status | failed_checks | unfinished | teleports | error |
|---|---|---|---|---|---|---|---|
| forecast_only | b3_main_portola_arrival_f024_s0_event | 0 | ok | all_in_scope_arrived | 1 | 153 |  |
| heuristic | b3_main_portola_arrival_f024_s0_event | 0 | ok | all_in_scope_arrived | 1 | 148 |  |
| heuristic@lam=120 | b3_main_portola_arrival_f024_s0_event | 0 | ok | all_in_scope_arrived | 1 | 161 |  |
| batch | b3_main_portola_arrival_f024_s0_event | 0 | ok | all_in_scope_arrived | 1 | 122 |  |
| forecast_only | b3_main_portola_arrival_f024_s0_event | 1 | ok | all_in_scope_arrived | 4 | 187 |  |
| batch | b3_main_portola_arrival_f024_s0_event | 1 | ok | all_in_scope_arrived | 1 | 182 |  |
| heuristic | b3_main_portola_arrival_f024_s0_event | 2 | ok | all_in_scope_arrived | 1 | 174 |  |
| batch | b3_main_portola_departure_f026_s0_event | 0 | ok | all_in_scope_arrived | 5 | 86 |  |
| batch | b3_main_portola_departure_f026_s0_event | 1 | ok | all_in_scope_arrived | 1 | 64 |  |

## Mean outcomes per policy (common complete blocks)

vehicle_hours = realized time of every in-scope vehicle (participants and background, including insertion and batching waits), scored from the first decision. congested = vehicle-hours on mapped roads at speed <= 50% of the road's free-flow speed; stopped = speed < 0.1 m/s; pending = in-scope vehicles waiting off-network for insertion. Trip times count from the scheduled departure.

| policy | vehicle_hours | congested_h_scope | congested_h_all | stopped_h_scope | pending_h_scope | part_trip_s_mean | part_trip_s_p95 | other_trip_s_mean | other_trip_s_p95 | unfinished | teleports | decided | non_fastest_share | call_ms_p95 | batch_delay_s_mean | forecast_extra_travel_s_mean | wall_s | peak_mem_mb |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| batch | 918.4 | 191.3 | 373.1 | 118.3 | 0.04 | 454.3 | 1130 | 514.4 | 1305 | 0 | 42.15 | 190.5 | 0.026 | 8.577 | 33.55 | 0.013 | 379.9 | 2637 |
| forecast_only | 916.1 | 191.6 | 371.8 | 118.6 | 0.038 | 422.2 | 1113 | 514.6 | 1309 | 0 | 32.69 | 190.3 | 0.044 | 0.05 | 0 | 0.01 | 381.9 | 2613 |
| heuristic | 916.3 | 191.7 | 368.4 | 118.6 | 0.033 | 422.8 | 1126 | 514.6 | 1306 | 0 | 37.08 | 189.9 | 0.045 | 0.162 | 0 | 0.017 | 379.3 | 2610 |
| heuristic@lam=120 | 916.3 | 191.5 | 373.6 | 118.6 | 0.037 | 423.3 | 1125 | 514.5 | 1306 | 0 | 37.69 | 190.1 | 0.055 | 0.156 | 0 | 0.032 | 381.1 | 2614 |

## Paired differences vs `forecast_only` on common complete blocks (policy minus baseline; negative = less)

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| batch | vehicle_hours | 13 | 916.1 | 2.365 | 2.486 | 3.136 | 0.2263 | 0.2803 | 0.7253 | 3 | 10 | 0 | inconclusive |
| heuristic | vehicle_hours | 13 | 916.1 | 0.1703 | 0 | 2.88 | -0.0154 | 0 | 0.5028 | 6 | 6 | 1 | inconclusive |
| heuristic@lam=120 | vehicle_hours | 13 | 916.1 | 0.1741 | -0.2522 | 3.321 | -0.0115 | -0.023 | 0.8466 | 7 | 6 | 0 | inconclusive |
| batch | congested_h_scope | 13 | 191.6 | -0.3115 | 0.4569 | 2.161 | -0.3491 | 0.1972 | 1.67 | 6 | 7 | 0 | inconclusive |
| heuristic | congested_h_scope | 13 | 191.6 | 0.0508 | 0 | 2.068 | -0.0792 | 0 | 2.349 | 6 | 6 | 1 | inconclusive |
| heuristic@lam=120 | congested_h_scope | 13 | 191.6 | -0.0966 | -0.1611 | 2.339 | -0.1742 | -0.0475 | 3.189 | 7 | 6 | 0 | inconclusive |
| batch | congested_h_all | 13 | 371.8 | 1.252 | -1.127 | 6.526 | 0.6268 | -0.31 | 6.149 | 7 | 6 | 0 | inconclusive |
| heuristic | congested_h_all | 13 | 371.8 | -3.443 | 1.747 | 15.28 | -0.3055 | 0.4981 | 2.771 | 5 | 7 | 1 | inconclusive |
| heuristic@lam=120 | congested_h_all | 13 | 371.8 | 1.771 | 3.022 | 8.131 | 0.4077 | 1.246 | 3.901 | 5 | 8 | 0 | inconclusive |
| batch | stopped_h_scope | 13 | 118.6 | -0.3388 | 0.0839 | 2.061 | -0.7088 | 0.1128 | 3.05 | 6 | 7 | 0 | inconclusive |
| heuristic | stopped_h_scope | 13 | 118.6 | 0.0099 | 0.1158 | 1.95 | -0.1661 | 0.132 | 3.681 | 5 | 7 | 1 | inconclusive |
| heuristic@lam=120 | stopped_h_scope | 13 | 118.6 | -0.0149 | 0.1286 | 2.186 | -0.2362 | 0.0713 | 5.863 | 6 | 7 | 0 | inconclusive |
| batch | pending_h_scope | 13 | 0.0384 | 0.0014 | 0 | 0.0287 | 15.88 | 0 | 214.2 | 6 | 6 | 1 | inconclusive |
| heuristic | pending_h_scope | 13 | 0.0384 | -0.0051 | 0.0006 | 0.0184 | -1.482 | 2.857 | 35.29 | 5 | 7 | 1 | inconclusive |
| heuristic@lam=120 | pending_h_scope | 13 | 0.0384 | -0.0011 | 0 | 0.0076 | 2.702 | 0 | 40.79 | 6 | 6 | 1 | inconclusive |
| batch | part_trip_s_mean | 13 | 422.2 | 32.07 | 33.54 | 4.447 | 7.971 | 8.344 | 10.97 | 0 | 13 | 0 | worse in every pair |
| heuristic | part_trip_s_mean | 13 | 422.2 | 0.6433 | 0.1641 | 2.049 | 0.1343 | 0.0414 | 0.8843 | 4 | 8 | 1 | inconclusive |
| heuristic@lam=120 | part_trip_s_mean | 13 | 422.2 | 1.084 | 1.095 | 2.239 | 0.2441 | 0.2061 | 1.281 | 4 | 9 | 0 | inconclusive |
| batch | part_trip_s_p95 | 13 | 1113 | 16.66 | 20.22 | 31.96 | 1.53 | 1.768 | 6.989 | 3 | 10 | 0 | inconclusive |
| heuristic | part_trip_s_p95 | 13 | 1113 | 13.17 | 3.41 | 24.82 | 1.206 | 0.2982 | 6.867 | 3 | 9 | 1 | inconclusive |
| heuristic@lam=120 | part_trip_s_p95 | 13 | 1113 | 11.89 | 5.825 | 21.14 | 1.126 | 0.5807 | 4.776 | 3 | 10 | 0 | inconclusive |
| batch | other_trip_s_mean | 13 | 514.6 | -0.2429 | 0.0725 | 1.474 | -0.0523 | 0.0148 | 0.3456 | 6 | 7 | 0 | inconclusive |
| heuristic | other_trip_s_mean | 13 | 514.6 | -0.0209 | 0 | 1.653 | -0.0183 | 0 | 0.4295 | 6 | 6 | 1 | inconclusive |
| heuristic@lam=120 | other_trip_s_mean | 13 | 514.6 | -0.1322 | 0.0129 | 1.699 | -0.0169 | 0.0026 | 0.7505 | 6 | 7 | 0 | inconclusive |
| batch | other_trip_s_p95 | 13 | 1309 | -4.502 | -3.79 | 7.559 | -0.3374 | -0.2644 | 0.8121 | 8 | 5 | 0 | inconclusive |
| heuristic | other_trip_s_p95 | 13 | 1309 | -3.368 | -3.28 | 8.378 | -0.2573 | -0.2653 | 1.064 | 10 | 2 | 1 | inconclusive |
| heuristic@lam=120 | other_trip_s_p95 | 13 | 1309 | -3.678 | -2.775 | 7.389 | -0.2744 | -0.2274 | 1.022 | 11 | 2 | 0 | inconclusive |
| batch | part_route_m_mean | 13 | 4021 | 2.387 | 1.347 | 7.786 | 0.0583 | 0.0409 | 0.5079 | 4 | 9 | 0 | inconclusive |
| heuristic | part_route_m_mean | 13 | 4021 | 1.972 | 0.4924 | 6.104 | 0.0474 | 0.0149 | 0.5105 | 4 | 8 | 1 | inconclusive |
| heuristic@lam=120 | part_route_m_mean | 13 | 4021 | 2.781 | 1.006 | 6.343 | 0.0711 | 0.0314 | 0.5105 | 2 | 11 | 0 | inconclusive |

## Common-horizon check on every successful block (includes censored runs)

Vehicle-hours through the same drain cap, congested hours and unfinished backlog; a policy that leaves more vehicles unfinished is not better because its completed trips look faster.

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| batch | vehicle_hours | 18 | 958.3 | 2.033 | 2.465 | 5.396 | 0.2606 | 0.3013 | 1.907 | 5 | 13 | 0 | inconclusive |
| heuristic | vehicle_hours | 18 | 958.3 | -1.644 | -0.7817 | 4.735 | -0.1742 | -0.0803 | 0.5028 | 11 | 6 | 1 | inconclusive |
| heuristic@lam=120 | vehicle_hours | 18 | 958.3 | -1.088 | -0.3233 | 5.181 | -0.1321 | -0.0296 | 0.8466 | 10 | 8 | 0 | inconclusive |
| batch | congested_h_scope | 18 | 219.7 | -0.371 | -0.2019 | 3.938 | -0.0162 | -0.0447 | 7.319 | 9 | 9 | 0 | inconclusive |
| heuristic | congested_h_scope | 18 | 219.7 | -1.173 | -0.1697 | 3.503 | -0.517 | -0.0581 | 2.349 | 10 | 7 | 1 | inconclusive |
| heuristic@lam=120 | congested_h_scope | 18 | 219.7 | -0.9645 | -0.3192 | 3.824 | -0.5307 | -0.1858 | 3.189 | 11 | 7 | 0 | inconclusive |
| batch | unfinished | 18 | 0.2778 | 0.1667 | 0 | 1.425 | -37.5 | -37.5 | 0 | 1 | 2 | 15 | inconclusive |
| heuristic | unfinished | 18 | 0.2778 | -0.1667 | 0 | 0.9852 | -50 | -50 | 0 | 1 | 1 | 16 | inconclusive |
| heuristic@lam=120 | unfinished | 18 | 0.2778 | -0.2222 | 0 | 0.9428 | -50 | -50 | 0 | 1 | 0 | 17 | inconclusive |

## Ranking by paired total vehicle-hours (common complete blocks)

1. `forecast_only`: +0.000 veh-h (+0.00%) vs forecast_only
2. `heuristic`: +0.170 veh-h (-0.02%) vs forecast_only (inconclusive)
3. `heuristic@lam=120`: +0.174 veh-h (-0.01%) vs forecast_only (inconclusive)
4. `batch`: +2.365 veh-h (+0.23%) vs forecast_only (inconclusive)

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
   "vehicle_hours_reduction_pct": 0.015381583519121918,
   "vehicle_hours_mean_diff": 0.1702564102564041,
   "blocks_better": 6.0,
   "blocks_worse": 6.0,
   "consistent_reduction": false,
   "congested_scope_reduction_pct": 0.07917560332032549,
   "background_mean_change_pct": -0.01828270055397702,
   "participant_p95_change_pct": 1.2055349622131362,
   "meets_vehicle_hours_target": false,
   "lower_congestion": true,
   "background_ok": true,
   "participant_p95_ok": true
  },
  "heuristic@lam=120": {
   "vehicle_hours_reduction_pct": 0.01146626447404486,
   "vehicle_hours_mean_diff": 0.17414529914530108,
   "blocks_better": 7.0,
   "blocks_worse": 6.0,
   "consistent_reduction": false,
   "congested_scope_reduction_pct": 0.1741817169685684,
   "background_mean_change_pct": -0.016918152762952568,
   "participant_p95_change_pct": 1.1256420118527108,
   "meets_vehicle_hours_target": false,
   "lower_congestion": true,
   "background_ok": true,
   "participant_p95_ok": true
  },
  "batch": {
   "vehicle_hours_reduction_pct": -0.22625952062426616,
   "vehicle_hours_mean_diff": 2.365459401709271,
   "blocks_better": 3.0,
   "blocks_worse": 10.0,
   "consistent_reduction": false,
   "congested_scope_reduction_pct": 0.3491423287648414,
   "background_mean_change_pct": -0.05225216821951632,
   "participant_p95_change_pct": 1.5305221589271818,
   "meets_vehicle_hours_target": false,
   "lower_congestion": true,
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
  "runs": 18,
  "ok": 18,
  "complete": 14,
  "unavailable": 0,
  "failed": 0,
  "invalid_routes": 0,
  "selector_failures": 0,
  "unchosen_fallbacks": 0,
  "dropped_trips": 0,
  "readback_mismatch": 0,
  "unfinished": 8,
  "teleports": 1186,
  "call_ms_p95_max": 13.911441799987744
 },
 "forecast_only": {
  "runs": 18,
  "ok": 18,
  "complete": 16,
  "unavailable": 0,
  "failed": 0,
  "invalid_routes": 0,
  "selector_failures": 0,
  "unchosen_fallbacks": 0,
  "dropped_trips": 0,
  "readback_mismatch": 0,
  "unfinished": 5,
  "teleports": 990,
  "call_ms_p95_max": 0.056183999981840295
 },
 "heuristic": {
  "runs": 18,
  "ok": 18,
  "complete": 16,
  "unavailable": 0,
  "failed": 0,
  "invalid_routes": 0,
  "selector_failures": 0,
  "unchosen_fallbacks": 0,
  "dropped_trips": 0,
  "readback_mismatch": 0,
  "unfinished": 2,
  "teleports": 992,
  "call_ms_p95_max": 0.24802399998407032
 },
 "heuristic@lam=120": {
  "runs": 18,
  "ok": 18,
  "complete": 17,
  "unavailable": 0,
  "failed": 0,
  "invalid_routes": 0,
  "selector_failures": 0,
  "unchosen_fallbacks": 0,
  "dropped_trips": 0,
  "readback_mismatch": 0,
  "unfinished": 1,
  "teleports": 1018,
  "call_ms_p95_max": 0.22632000001294722
 }
}
```
