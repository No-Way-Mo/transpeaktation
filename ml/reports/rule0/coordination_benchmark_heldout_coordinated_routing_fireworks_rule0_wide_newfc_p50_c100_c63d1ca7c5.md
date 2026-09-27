# Coordinated routing benchmark: `heldout` · `heldout_coordinated_routing_fireworks_rule0_wide_newfc_p50_c100_c63d1ca7c5`

> **Synthetic.** SUMO scenarios on the SF citywide network; demand, attendance and behaviour are assumptions.
> Differences are realized in simulation under these assumptions, not measured on real streets.

- Scenarios (3): `b6_fireworks_n12000_all_s0_event`, `b6_fireworks_n3000_all_s0_event`, `b6_fireworks_n6000_all_s0_event`
- Simulation seeds: [0, 1, 2] · policies: `forecast_only`, `heuristic@lam=500`, `rl_ppo`
- Forecast: `model` (data/forecast/experiments/event_patch_x_all/best.pt) · participation 0.5 (cap 100000) · compliance 1.0 · batch window 60 s · drain cap 8100 s · teleport after -1 s
- RL checkpoints: {"rl_ppo": {"checkpoint": "data/coordination/rl/runs_async/appo_async_s0/latest", "exists": true}}
- Code: `{"sources_sha": "d0820cdea302d298", "files": 82, "tp_code_id": ""}`
- Wall time: 3184.8 s

## Run status

| policy | ok | complete |
|---|---|---|
| forecast_only | 9 | 3 |
| heuristic@lam=500 | 9 | 1 |
| rl_ppo | 9 | 2 |

Common complete blocks (every policy complete, identical population): **1 of 9**: `b6_fireworks_n3000_all_s0_event` s1

### Failed, incomplete or censored runs (kept visible, excluded from the primary ranking)

| policy | scenario | seed | status | failed_checks | unfinished | teleports | error |
|---|---|---|---|---|---|---|---|
| forecast_only | b6_fireworks_n12000_all_s0_event | 0 | ok | all_in_scope_arrived | 2354 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n12000_all_s0_event | 0 | ok | all_in_scope_arrived | 2646 | 0 |  |
| rl_ppo | b6_fireworks_n12000_all_s0_event | 0 | ok | all_in_scope_arrived | 4585 | 0 |  |
| forecast_only | b6_fireworks_n12000_all_s0_event | 1 | ok | all_in_scope_arrived | 3962 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n12000_all_s0_event | 1 | ok | all_in_scope_arrived | 2594 | 0 |  |
| rl_ppo | b6_fireworks_n12000_all_s0_event | 1 | ok | all_in_scope_arrived | 2962 | 0 |  |
| forecast_only | b6_fireworks_n12000_all_s0_event | 2 | ok | all_in_scope_arrived | 5118 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n12000_all_s0_event | 2 | ok | all_in_scope_arrived | 1928 | 0 |  |
| rl_ppo | b6_fireworks_n12000_all_s0_event | 2 | ok | all_in_scope_arrived | 2003 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n3000_all_s0_event | 0 | ok | all_in_scope_arrived | 182 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n3000_all_s0_event | 2 | ok | all_in_scope_arrived | 19 | 0 |  |
| rl_ppo | b6_fireworks_n3000_all_s0_event | 2 | ok | all_in_scope_arrived | 132 | 0 |  |
| forecast_only | b6_fireworks_n6000_all_s0_event | 0 | ok | all_in_scope_arrived | 675 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n6000_all_s0_event | 0 | ok | all_in_scope_arrived | 344 | 0 |  |
| rl_ppo | b6_fireworks_n6000_all_s0_event | 0 | ok | all_in_scope_arrived | 488 | 0 |  |
| forecast_only | b6_fireworks_n6000_all_s0_event | 1 | ok | all_in_scope_arrived | 116 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n6000_all_s0_event | 1 | ok | all_in_scope_arrived | 56 | 0 |  |
| rl_ppo | b6_fireworks_n6000_all_s0_event | 1 | ok | all_in_scope_arrived | 943 | 0 |  |
| forecast_only | b6_fireworks_n6000_all_s0_event | 2 | ok | all_in_scope_arrived | 238 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n6000_all_s0_event | 2 | ok | all_in_scope_arrived | 1090 | 0 |  |
| rl_ppo | b6_fireworks_n6000_all_s0_event | 2 | ok | all_in_scope_arrived | 255 | 0 |  |

## Mean outcomes per policy (common complete blocks)

vehicle_hours = realized time of every in-scope vehicle (participants and background, including insertion and batching waits), scored from the first decision. congested = vehicle-hours on mapped roads at speed <= 50% of the road's free-flow speed; stopped = speed < 0.1 m/s; pending = in-scope vehicles waiting off-network for insertion. Trip times count from the scheduled departure.

| policy | vehicle_hours | congested_h_scope | congested_h_all | stopped_h_scope | pending_h_scope | part_trip_s_mean | part_trip_s_p95 | other_trip_s_mean | other_trip_s_p95 | unfinished | teleports | decided | non_fastest_share | call_ms_p95 | batch_delay_s_mean | forecast_extra_travel_s_mean | wall_s | peak_mem_mb |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| forecast_only | 1261 | 527.3 | 527.3 | 391.9 | 0.242 | 1114 | 1847 | 1155 | 1838 | 0 | 0 | 1929 | 0.044 | 0.073 | 0 | 0.01 | 687 | 3172 |
| heuristic@lam=500 | 1245 | 498.4 | 498.4 | 380.4 | 0.672 | 1096 | 1609 | 1146 | 1819 | 0 | 0 | 1936 | 0.548 | 0.375 | 0 | 49.05 | 688.3 | 3167 |
| rl_ppo | 1257 | 490.7 | 490.7 | 369 | 0.221 | 1120 | 1646 | 1142 | 1851 | 0 | 0 | 1922 | 0.999 | 2.748 | 0 | 100.3 | 713.1 | 3175 |

## Paired differences vs `forecast_only` on common complete blocks (policy minus baseline; negative = less)

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| heuristic@lam=500 | vehicle_hours | 1 | 1261 | -15.18 | -15.18 |  | -1.204 | -1.204 | -1.204 | 1 | 0 | 0 | better in every pair |
| rl_ppo | vehicle_hours | 1 | 1261 | -3.858 | -3.858 |  | -0.306 | -0.306 | -0.306 | 1 | 0 | 0 | better in every pair |
| heuristic@lam=500 | congested_h_scope | 1 | 527.3 | -28.89 | -28.89 |  | -5.478 | -5.478 | -5.478 | 1 | 0 | 0 | better in every pair |
| rl_ppo | congested_h_scope | 1 | 527.3 | -36.52 | -36.52 |  | -6.926 | -6.926 | -6.926 | 1 | 0 | 0 | better in every pair |
| heuristic@lam=500 | congested_h_all | 1 | 527.3 | -28.89 | -28.89 |  | -5.478 | -5.478 | -5.478 | 1 | 0 | 0 | better in every pair |
| rl_ppo | congested_h_all | 1 | 527.3 | -36.52 | -36.52 |  | -6.926 | -6.926 | -6.926 | 1 | 0 | 0 | better in every pair |
| heuristic@lam=500 | stopped_h_scope | 1 | 391.9 | -11.51 | -11.51 |  | -2.937 | -2.937 | -2.937 | 1 | 0 | 0 | better in every pair |
| rl_ppo | stopped_h_scope | 1 | 391.9 | -22.86 | -22.86 |  | -5.835 | -5.835 | -5.835 | 1 | 0 | 0 | better in every pair |
| heuristic@lam=500 | pending_h_scope | 1 | 0.2422 | 0.4303 | 0.4303 |  | 177.6 | 177.6 | 177.6 | 0 | 1 | 0 | worse in every pair |
| rl_ppo | pending_h_scope | 1 | 0.2422 | -0.0217 | -0.0217 |  | -8.945 | -8.945 | -8.945 | 1 | 0 | 0 | better in every pair |
| heuristic@lam=500 | part_trip_s_mean | 1 | 1114 | -17.93 | -17.93 |  | -1.609 | -1.609 | -1.609 | 1 | 0 | 0 | better in every pair |
| rl_ppo | part_trip_s_mean | 1 | 1114 | 6.017 | 6.017 |  | 0.54 | 0.54 | 0.54 | 0 | 1 | 0 | worse in every pair |
| heuristic@lam=500 | part_trip_s_p95 | 1 | 1847 | -238 | -238 |  | -12.89 | -12.89 | -12.89 | 1 | 0 | 0 | better in every pair |
| rl_ppo | part_trip_s_p95 | 1 | 1847 | -200.8 | -200.8 |  | -10.87 | -10.87 | -10.87 | 1 | 0 | 0 | better in every pair |
| heuristic@lam=500 | other_trip_s_mean | 1 | 1155 | -9.391 | -9.391 |  | -0.813 | -0.813 | -0.813 | 1 | 0 | 0 | better in every pair |
| rl_ppo | other_trip_s_mean | 1 | 1155 | -12.99 | -12.99 |  | -1.125 | -1.125 | -1.125 | 1 | 0 | 0 | better in every pair |
| heuristic@lam=500 | other_trip_s_p95 | 1 | 1838 | -19 | -19 |  | -1.034 | -1.034 | -1.034 | 1 | 0 | 0 | better in every pair |
| rl_ppo | other_trip_s_p95 | 1 | 1838 | 12.8 | 12.8 |  | 0.6963 | 0.6963 | 0.6963 | 0 | 1 | 0 | worse in every pair |
| heuristic@lam=500 | part_route_m_mean | 1 | 6796 | 306.4 | 306.4 |  | 4.508 | 4.508 | 4.508 | 0 | 1 | 0 | worse in every pair |
| rl_ppo | part_route_m_mean | 1 | 6796 | 293.9 | 293.9 |  | 4.325 | 4.325 | 4.325 | 0 | 1 | 0 | worse in every pair |

## Common-horizon check on every successful block (includes censored runs)

Vehicle-hours through the same drain cap, congested hours and unfinished backlog; a policy that leaves more vehicles unfinished is not better because its completed trips look faster.

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| heuristic@lam=500 | vehicle_hours | 9 | 6869 | -1155 | -592 | 2277 | -3.623 | -8.245 | 41.73 | 6 | 3 | 0 | inconclusive |
| rl_ppo | vehicle_hours | 9 | 6869 | -734.7 | -8.081 | 2478 | -0.6492 | -0.6445 | 38.89 | 6 | 3 | 0 | inconclusive |
| heuristic@lam=500 | congested_h_scope | 9 | 4326 | -742.6 | -550.3 | 1518 | 0.5542 | -7.11 | 68.73 | 6 | 3 | 0 | inconclusive |
| rl_ppo | congested_h_scope | 9 | 4326 | -254.3 | -41.04 | 1532 | 3.878 | -7.892 | 57.04 | 6 | 3 | 0 | inconclusive |
| heuristic@lam=500 | unfinished | 9 | 1385 | -400.4 | 0 | 1202 | 28.79 | -41.78 | 358 | 4 | 4 | 1 | inconclusive |
| rl_ppo | unfinished | 9 | 1385 | -121.7 | 0 | 1427 | 116.8 | -9.049 | 712.9 | 3 | 4 | 2 | inconclusive |

## Ranking by paired total vehicle-hours (common complete blocks)

1. `heuristic@lam=500`: -15.184 veh-h (-1.20%) vs forecast_only (better in every pair)
2. `rl_ppo`: -3.858 veh-h (-0.31%) vs forecast_only (better in every pair)
3. `forecast_only`: +0.000 veh-h (+0.00%) vs forecast_only

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
  "heuristic@lam=500": {
   "vehicle_hours_reduction_pct": 1.204430095813257,
   "vehicle_hours_mean_diff": -15.183888888888987,
   "blocks_better": 1.0,
   "blocks_worse": 0.0,
   "consistent_reduction": true,
   "congested_scope_reduction_pct": 5.478409939825362,
   "background_mean_change_pct": -0.8129612546125267,
   "participant_p95_change_pct": -12.88785400985542,
   "meets_vehicle_hours_target": false,
   "lower_congestion": true,
   "background_ok": true,
   "participant_p95_ok": true
  },
  "rl_ppo": {
   "vehicle_hours_reduction_pct": 0.3060321539780962,
   "vehicle_hours_mean_diff": -3.8580555555556657,
   "blocks_better": 1.0,
   "blocks_worse": 0.0,
   "consistent_reduction": true,
   "congested_scope_reduction_pct": 6.926036092136412,
   "background_mean_change_pct": -1.1245682240656878,
   "participant_p95_change_pct": -10.873449937726743,
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
 "forecast_only": {
  "runs": 9,
  "ok": 9,
  "complete": 3,
  "unavailable": 0,
  "failed": 0,
  "invalid_routes": 0,
  "selector_failures": 0,
  "unchosen_fallbacks": 0,
  "dropped_trips": 0,
  "readback_mismatch": 0,
  "unfinished": 12463,
  "teleports": 0,
  "call_ms_p95_max": 0.07734484995580711
 },
 "heuristic@lam=500": {
  "runs": 9,
  "ok": 9,
  "complete": 1,
  "unavailable": 0,
  "failed": 0,
  "invalid_routes": 0,
  "selector_failures": 0,
  "unchosen_fallbacks": 0,
  "dropped_trips": 0,
  "readback_mismatch": 0,
  "unfinished": 8859,
  "teleports": 0,
  "call_ms_p95_max": 0.49958219997279224
 },
 "rl_ppo": {
  "runs": 9,
  "ok": 9,
  "complete": 2,
  "unavailable": 0,
  "failed": 0,
  "invalid_routes": 0,
  "selector_failures": 0,
  "unchosen_fallbacks": 0,
  "dropped_trips": 0,
  "readback_mismatch": 0,
  "unfinished": 11368,
  "teleports": 0,
  "call_ms_p95_max": 2.9524059997129366
 }
}
```
