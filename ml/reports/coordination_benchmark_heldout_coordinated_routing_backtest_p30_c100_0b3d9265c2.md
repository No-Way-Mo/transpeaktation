# Coordinated routing benchmark: `heldout` · `heldout_coordinated_routing_backtest_p30_c100_0b3d9265c2`

> **Synthetic.** SUMO scenarios on the SF citywide network; demand, attendance and behaviour are assumptions.
> Differences are realized in simulation under these assumptions, not measured on real streets.

- Scenarios (6): `b3_main_portola_arrival_f024_s0_event`, `b3_main_portola_departure_f026_s0_event`, `b3_main_portola_full_f025_s0_event`, `b3_main_portola_arrival_f030_s0_event`, `b3_main_portola_departure_f029_s0_event`, `b3_main_portola_full_f028_s0_event`
- Simulation seeds: [0, 1, 2] · policies: `forecast_only`, `heuristic`, `batch`
- Forecast: `model` (data/forecast/experiments/event_patch_v2_main/best.pt) · participation 0.3 (cap 100000) · compliance 1.0 · batch window 60 s · drain cap 3600 s · teleport after 300 s
- RL checkpoints: {}
- Code: `{"sources_sha": "89aa667e595e8765", "files": 75, "tp_code_id": "f9ad4326a6138ada"}`
- Wall time: 1147.0 s

## Run status

| policy | ok | complete |
|---|---|---|
| batch | 18 | 16 |
| forecast_only | 18 | 16 |
| heuristic | 18 | 16 |

Common complete blocks (every policy complete, identical population): **15 of 18**: `b3_main_portola_arrival_f030_s0_event` s0, `b3_main_portola_arrival_f030_s0_event` s1, `b3_main_portola_arrival_f030_s0_event` s2, `b3_main_portola_departure_f026_s0_event` s0, `b3_main_portola_departure_f026_s0_event` s1, `b3_main_portola_departure_f026_s0_event` s2, `b3_main_portola_departure_f029_s0_event` s0, `b3_main_portola_departure_f029_s0_event` s1, `b3_main_portola_departure_f029_s0_event` s2, `b3_main_portola_full_f025_s0_event` s0, `b3_main_portola_full_f025_s0_event` s1, `b3_main_portola_full_f025_s0_event` s2, `b3_main_portola_full_f028_s0_event` s0, `b3_main_portola_full_f028_s0_event` s1, `b3_main_portola_full_f028_s0_event` s2

### Failed, incomplete or censored runs (kept visible, excluded from the primary ranking)

| policy | scenario | seed | status | failed_checks | unfinished | teleports | error |
|---|---|---|---|---|---|---|---|
| forecast_only | b3_main_portola_arrival_f024_s0_event | 0 | ok | all_in_scope_arrived | 1 | 156 |  |
| heuristic | b3_main_portola_arrival_f024_s0_event | 0 | ok | all_in_scope_arrived | 1 | 198 |  |
| batch | b3_main_portola_arrival_f024_s0_event | 0 | ok | all_in_scope_arrived | 5 | 196 |  |
| heuristic | b3_main_portola_arrival_f024_s0_event | 1 | ok | all_in_scope_arrived | 1 | 166 |  |
| forecast_only | b3_main_portola_arrival_f024_s0_event | 2 | ok | all_in_scope_arrived | 1 | 194 |  |
| batch | b3_main_portola_arrival_f024_s0_event | 2 | ok | all_in_scope_arrived | 2 | 209 |  |

## Mean outcomes per policy (common complete blocks)

vehicle_hours = realized time of every in-scope vehicle (participants and background, including insertion and batching waits), scored from the first decision. congested = vehicle-hours on mapped roads at speed <= 50% of the road's free-flow speed; stopped = speed < 0.1 m/s; pending = in-scope vehicles waiting off-network for insertion. Trip times count from the scheduled departure.

| policy | vehicle_hours | congested_h_scope | congested_h_all | stopped_h_scope | pending_h_scope | part_trip_s_mean | part_trip_s_p95 | other_trip_s_mean | other_trip_s_p95 | unfinished | teleports | decided | non_fastest_share | call_ms_p95 | batch_delay_s_mean | forecast_extra_travel_s_mean | wall_s | peak_mem_mb |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| batch | 883.3 | 175.5 | 352.3 | 106.5 | 0.033 | 439.6 | 1124 | 523.7 | 1332 | 0 | 46.47 | 1191 | 0.044 | 74.88 | 31.48 | 0.031 | 518.2 | 2626 |
| forecast_only | 865.4 | 173.4 | 347.9 | 104.6 | 0.034 | 407.2 | 1096 | 522.2 | 1329 | 0 | 48.93 | 1190 | 0.054 | 0.069 | 0 | 0.012 | 519.1 | 2601 |
| heuristic | 866.2 | 174 | 350 | 105.2 | 0.035 | 407.9 | 1098 | 522.3 | 1327 | 0 | 45.73 | 1188 | 0.063 | 0.246 | 0 | 0.04 | 520.3 | 2599 |

## Paired differences vs `forecast_only` on common complete blocks (policy minus baseline; negative = less)

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| batch | vehicle_hours | 15 | 865.4 | 17.82 | 18.13 | 5.42 | 2.153 | 2.006 | 5.41 | 0 | 15 | 0 | worse in every pair |
| heuristic | vehicle_hours | 15 | 865.4 | 0.7652 | 0.4692 | 3.848 | 0.0395 | 0.0489 | 1.023 | 4 | 11 | 0 | inconclusive |
| batch | congested_h_scope | 15 | 173.4 | 2.139 | 1.584 | 4.328 | 1.706 | 0.5066 | 15 | 5 | 10 | 0 | inconclusive |
| heuristic | congested_h_scope | 15 | 173.4 | 0.5947 | 0.1619 | 2.576 | 0.2652 | 0.1179 | 4.007 | 4 | 11 | 0 | inconclusive |
| batch | congested_h_all | 15 | 347.9 | 4.407 | -3.107 | 18.68 | 1.555 | -0.948 | 13.33 | 8 | 7 | 0 | inconclusive |
| heuristic | congested_h_all | 15 | 347.9 | 2.046 | 0.4944 | 21.87 | 0.1529 | 0.2564 | 10.84 | 7 | 8 | 0 | inconclusive |
| batch | stopped_h_scope | 15 | 104.6 | 1.901 | 1.383 | 4.232 | 2.882 | 0.6332 | 27.37 | 6 | 9 | 0 | inconclusive |
| heuristic | stopped_h_scope | 15 | 104.6 | 0.5325 | 0.2275 | 2.401 | 0.4556 | 0.3029 | 7.01 | 4 | 11 | 0 | inconclusive |
| batch | pending_h_scope | 15 | 0.0341 | -0.0007 | -0.0006 | 0.0088 | 1.395 | -0.8772 | 59.05 | 8 | 6 | 1 | inconclusive |
| heuristic | pending_h_scope | 15 | 0.0341 | 0.0006 | -0.0014 | 0.01 | 6.508 | -3.448 | 145.8 | 8 | 7 | 0 | inconclusive |
| batch | part_trip_s_mean | 15 | 407.2 | 32.37 | 31.61 | 2.668 | 8.193 | 8.139 | 11 | 0 | 15 | 0 | worse in every pair |
| heuristic | part_trip_s_mean | 15 | 407.2 | 0.7263 | 0.7941 | 1.981 | 0.1601 | 0.2325 | 0.995 | 4 | 11 | 0 | inconclusive |
| batch | part_trip_s_p95 | 15 | 1096 | 27.58 | 24.59 | 18.5 | 2.556 | 2.348 | 5.32 | 1 | 14 | 0 | inconclusive |
| heuristic | part_trip_s_p95 | 15 | 1096 | 1.653 | 1.17 | 15.18 | 0.1496 | 0.114 | 2.238 | 5 | 10 | 0 | inconclusive |
| batch | other_trip_s_mean | 15 | 522.2 | 1.487 | 0.4454 | 4.05 | 0.3048 | 0.0879 | 3.428 | 6 | 9 | 0 | inconclusive |
| heuristic | other_trip_s_mean | 15 | 522.2 | 0.0972 | 0.1473 | 2.397 | 0.0008 | 0.0291 | 0.8905 | 5 | 10 | 0 | inconclusive |
| batch | other_trip_s_p95 | 15 | 1329 | 2.74 | 2.05 | 12.11 | 0.1907 | 0.1565 | 2.81 | 7 | 8 | 0 | inconclusive |
| heuristic | other_trip_s_p95 | 15 | 1329 | -2.143 | -0.2 | 13.87 | -0.1724 | -0.0161 | 1.92 | 8 | 7 | 0 | inconclusive |
| batch | part_route_m_mean | 15 | 3832 | 1.417 | 1.006 | 2.266 | 0.04 | 0.0291 | 0.1911 | 3 | 12 | 0 | inconclusive |
| heuristic | part_route_m_mean | 15 | 3832 | 0.7043 | 1.111 | 1.906 | 0.0209 | 0.0329 | 0.1091 | 4 | 11 | 0 | inconclusive |

## Common-horizon check on every successful block (includes censored runs)

Vehicle-hours through the same drain cap, congested hours and unfinished backlog; a policy that leaves more vehicles unfinished is not better because its completed trips look faster.

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| batch | vehicle_hours | 18 | 951.2 | 19.03 | 18.59 | 5.749 | 2.097 | 1.99 | 5.41 | 0 | 18 | 0 | worse in every pair |
| heuristic | vehicle_hours | 18 | 951.2 | 1.461 | 0.3922 | 5.623 | 0.0926 | 0.0427 | 1.345 | 5 | 13 | 0 | inconclusive |
| batch | congested_h_scope | 18 | 210.7 | 2.531 | 1.608 | 4.184 | 1.61 | 0.9713 | 15 | 5 | 13 | 0 | inconclusive |
| heuristic | congested_h_scope | 18 | 210.7 | 1.117 | 0.2796 | 3.875 | 0.3781 | 0.1089 | 4.007 | 5 | 13 | 0 | inconclusive |
| batch | unfinished | 18 | 0.1111 | 0.2778 | 0 | 0.9583 | 250 | 250 | 400 | 0 | 2 | 16 | inconclusive |
| heuristic | unfinished | 18 | 0.1111 | 0 | 0 | 0.343 | -50 | -50 | 0 | 1 | 1 | 16 | inconclusive |

## Ranking by paired total vehicle-hours (common complete blocks)

1. `forecast_only`: +0.000 veh-h (+0.00%) vs forecast_only
2. `heuristic`: +0.765 veh-h (+0.04%) vs forecast_only (inconclusive)
3. `batch`: +17.816 veh-h (+2.15%) vs forecast_only (worse in every pair)

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
   "vehicle_hours_reduction_pct": -0.039460256412304696,
   "vehicle_hours_mean_diff": 0.7652037037037037,
   "blocks_better": 4.0,
   "blocks_worse": 11.0,
   "consistent_reduction": false,
   "congested_scope_reduction_pct": -0.2651568651680552,
   "background_mean_change_pct": 0.0008482869811230031,
   "participant_p95_change_pct": 0.14959936337605279,
   "meets_vehicle_hours_target": false,
   "lower_congestion": false,
   "background_ok": true,
   "participant_p95_ok": true
  },
  "batch": {
   "vehicle_hours_reduction_pct": -2.1525733347480593,
   "vehicle_hours_mean_diff": 17.816094444444122,
   "blocks_better": 0.0,
   "blocks_worse": 15.0,
   "consistent_reduction": false,
   "congested_scope_reduction_pct": -1.7057755771216765,
   "background_mean_change_pct": 0.30483898807275595,
   "participant_p95_change_pct": 2.556213532260253,
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
  "unfinished": 7,
  "teleports": 1297,
  "call_ms_p95_max": 209.85506329995405
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
  "unfinished": 2,
  "teleports": 1198,
  "call_ms_p95_max": 0.07600700002967642
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
  "teleports": 1182,
  "call_ms_p95_max": 0.29715014993598743
 }
}
```
