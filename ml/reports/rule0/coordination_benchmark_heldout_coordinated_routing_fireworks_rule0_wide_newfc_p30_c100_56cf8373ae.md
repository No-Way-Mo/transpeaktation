# Coordinated routing benchmark: `heldout` · `heldout_coordinated_routing_fireworks_rule0_wide_newfc_p30_c100_56cf8373ae`

> **Synthetic.** SUMO scenarios on the SF citywide network; demand, attendance and behaviour are assumptions.
> Differences are realized in simulation under these assumptions, not measured on real streets.

- Scenarios (3): `b6_fireworks_n12000_all_s0_event`, `b6_fireworks_n3000_all_s0_event`, `b6_fireworks_n6000_all_s0_event`
- Simulation seeds: [0, 1, 2] · policies: `forecast_only`, `heuristic@lam=500`, `rl_ppo`
- Forecast: `model` (data/forecast/experiments/event_patch_x_all/best.pt) · participation 0.3 (cap 100000) · compliance 1.0 · batch window 60 s · drain cap 8100 s · teleport after -1 s
- RL checkpoints: {"rl_ppo": {"checkpoint": "data/coordination/rl/runs_async/appo_async_s0/latest", "exists": true}}
- Code: `{"sources_sha": "d0820cdea302d298", "files": 82, "tp_code_id": ""}`
- Wall time: 3184.8 s

## Run status

| policy | ok | complete |
|---|---|---|
| forecast_only | 9 | 3 |
| heuristic@lam=500 | 9 | 2 |
| rl_ppo | 9 | 2 |

Common complete blocks (every policy complete, identical population): **2 of 9**: `b6_fireworks_n3000_all_s0_event` s0, `b6_fireworks_n3000_all_s0_event` s2

### Failed, incomplete or censored runs (kept visible, excluded from the primary ranking)

| policy | scenario | seed | status | failed_checks | unfinished | teleports | error |
|---|---|---|---|---|---|---|---|
| forecast_only | b6_fireworks_n12000_all_s0_event | 0 | ok | all_in_scope_arrived | 3310 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n12000_all_s0_event | 0 | ok | all_in_scope_arrived | 3726 | 0 |  |
| rl_ppo | b6_fireworks_n12000_all_s0_event | 0 | ok | all_in_scope_arrived | 2257 | 0 |  |
| forecast_only | b6_fireworks_n12000_all_s0_event | 1 | ok | all_in_scope_arrived | 1750 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n12000_all_s0_event | 1 | ok | all_in_scope_arrived | 1612 | 0 |  |
| rl_ppo | b6_fireworks_n12000_all_s0_event | 1 | ok | all_in_scope_arrived | 4385 | 0 |  |
| forecast_only | b6_fireworks_n12000_all_s0_event | 2 | ok | all_in_scope_arrived | 1417 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n12000_all_s0_event | 2 | ok | all_in_scope_arrived | 2796 | 0 |  |
| rl_ppo | b6_fireworks_n12000_all_s0_event | 2 | ok | all_in_scope_arrived | 1666 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n3000_all_s0_event | 1 | ok | all_in_scope_arrived | 113 | 0 |  |
| rl_ppo | b6_fireworks_n3000_all_s0_event | 1 | ok | all_in_scope_arrived | 7 | 0 |  |
| forecast_only | b6_fireworks_n6000_all_s0_event | 0 | ok | all_in_scope_arrived | 452 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n6000_all_s0_event | 0 | ok | all_in_scope_arrived | 27 | 0 |  |
| rl_ppo | b6_fireworks_n6000_all_s0_event | 0 | ok | all_in_scope_arrived | 449 | 0 |  |
| forecast_only | b6_fireworks_n6000_all_s0_event | 1 | ok | all_in_scope_arrived | 332 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n6000_all_s0_event | 1 | ok | all_in_scope_arrived | 722 | 0 |  |
| rl_ppo | b6_fireworks_n6000_all_s0_event | 1 | ok | all_in_scope_arrived | 232 | 0 |  |
| forecast_only | b6_fireworks_n6000_all_s0_event | 2 | ok | all_in_scope_arrived | 65 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n6000_all_s0_event | 2 | ok | all_in_scope_arrived | 655 | 0 |  |
| rl_ppo | b6_fireworks_n6000_all_s0_event | 2 | ok | all_in_scope_arrived | 357 | 0 |  |

## Mean outcomes per policy (common complete blocks)

vehicle_hours = realized time of every in-scope vehicle (participants and background, including insertion and batching waits), scored from the first decision. congested = vehicle-hours on mapped roads at speed <= 50% of the road's free-flow speed; stopped = speed < 0.1 m/s; pending = in-scope vehicles waiting off-network for insertion. Trip times count from the scheduled departure.

| policy | vehicle_hours | congested_h_scope | congested_h_all | stopped_h_scope | pending_h_scope | part_trip_s_mean | part_trip_s_p95 | other_trip_s_mean | other_trip_s_p95 | unfinished | teleports | decided | non_fastest_share | call_ms_p95 | batch_delay_s_mean | forecast_extra_travel_s_mean | wall_s | peak_mem_mb |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| forecast_only | 1247 | 512.2 | 512.2 | 390.7 | 0.224 | 1017 | 1475 | 1167 | 1895 | 0 | 0 | 1140 | 0.058 | 0.064 | 0 | 0.015 | 573.2 | 3159 |
| heuristic@lam=500 | 1246 | 506.3 | 506.3 | 391.1 | 0.245 | 1032 | 1466 | 1159 | 1849 | 0 | 0 | 1135 | 0.469 | 0.359 | 0 | 36.5 | 588.5 | 3144 |
| rl_ppo | 1266 | 515 | 515 | 394.9 | 0.228 | 1082 | 1551 | 1164 | 1892 | 0 | 0 | 1139 | 0.999 | 2.725 | 0 | 85.07 | 594.8 | 3152 |

## Paired differences vs `forecast_only` on common complete blocks (policy minus baseline; negative = less)

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| heuristic@lam=500 | vehicle_hours | 2 | 1247 | -1.285 | -1.285 | 2.082 | -0.1033 | -0.1033 | 0.015 | 1 | 1 | 0 | inconclusive |
| rl_ppo | vehicle_hours | 2 | 1247 | 19.28 | 19.28 | 2.932 | 1.545 | 1.545 | 1.708 | 0 | 2 | 0 | worse in every pair |
| heuristic@lam=500 | congested_h_scope | 2 | 512.2 | -5.922 | -5.922 | 2.477 | -1.158 | -1.158 | -0.8104 | 2 | 0 | 0 | better in every pair |
| rl_ppo | congested_h_scope | 2 | 512.2 | 2.72 | 2.72 | 3.89 | 0.5284 | 0.5284 | 1.063 | 1 | 1 | 0 | inconclusive |
| heuristic@lam=500 | congested_h_all | 2 | 512.2 | -5.922 | -5.922 | 2.477 | -1.158 | -1.158 | -0.8104 | 2 | 0 | 0 | better in every pair |
| rl_ppo | congested_h_all | 2 | 512.2 | 2.72 | 2.72 | 3.89 | 0.5284 | 0.5284 | 1.063 | 1 | 1 | 0 | inconclusive |
| heuristic@lam=500 | stopped_h_scope | 2 | 390.7 | 0.3971 | 0.3971 | 1.053 | 0.1003 | 0.1003 | 0.2902 | 1 | 1 | 0 | inconclusive |
| rl_ppo | stopped_h_scope | 2 | 390.7 | 4.168 | 4.168 | 1.614 | 1.065 | 1.065 | 1.349 | 0 | 2 | 0 | worse in every pair |
| heuristic@lam=500 | pending_h_scope | 2 | 0.2239 | 0.0211 | 0.0211 | 0.1124 | 13.9 | 13.9 | 51.06 | 1 | 1 | 0 | inconclusive |
| rl_ppo | pending_h_scope | 2 | 0.2239 | 0.0039 | 0.0039 | 0.0024 | 1.853 | 1.853 | 2.821 | 0 | 2 | 0 | worse in every pair |
| heuristic@lam=500 | part_trip_s_mean | 2 | 1017 | 14.81 | 14.81 | 5.742 | 1.459 | 1.459 | 1.865 | 0 | 2 | 0 | worse in every pair |
| rl_ppo | part_trip_s_mean | 2 | 1017 | 65.22 | 65.22 | 7.438 | 6.416 | 6.416 | 6.963 | 0 | 2 | 0 | worse in every pair |
| heuristic@lam=500 | part_trip_s_p95 | 2 | 1475 | -8.725 | -8.725 | 2.015 | -0.5916 | -0.5916 | -0.4946 | 2 | 0 | 0 | better in every pair |
| rl_ppo | part_trip_s_p95 | 2 | 1475 | 75.62 | 75.62 | 17.08 | 5.127 | 5.127 | 5.942 | 0 | 2 | 0 | worse in every pair |
| heuristic@lam=500 | other_trip_s_mean | 2 | 1167 | -7.871 | -7.871 | 0.2478 | -0.6748 | -0.6748 | -0.6567 | 2 | 0 | 0 | better in every pair |
| rl_ppo | other_trip_s_mean | 2 | 1167 | -2.779 | -2.779 | 0.6205 | -0.2384 | -0.2384 | -0.1997 | 2 | 0 | 0 | better in every pair |
| heuristic@lam=500 | other_trip_s_p95 | 2 | 1895 | -45.75 | -45.75 | 39.24 | -2.391 | -2.391 | -0.9661 | 2 | 0 | 0 | better in every pair |
| rl_ppo | other_trip_s_p95 | 2 | 1895 | -2.375 | -2.375 | 31.29 | -0.1059 | -0.1059 | 1.06 | 1 | 1 | 0 | inconclusive |
| heuristic@lam=500 | part_route_m_mean | 2 | 6805 | 244.3 | 244.3 | 18.77 | 3.59 | 3.59 | 3.786 | 0 | 2 | 0 | worse in every pair |
| rl_ppo | part_route_m_mean | 2 | 6805 | 221.6 | 221.6 | 9.319 | 3.257 | 3.257 | 3.355 | 0 | 2 | 0 | worse in every pair |

## Common-horizon check on every successful block (includes censored runs)

Vehicle-hours through the same drain cap, congested hours and unfinished backlog; a policy that leaves more vehicles unfinished is not better because its completed trips look faster.

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| heuristic@lam=500 | vehicle_hours | 9 | 5724 | 315.6 | 234.7 | 949.8 | 7.352 | 1.649 | 39.22 | 3 | 6 | 0 | inconclusive |
| rl_ppo | vehicle_hours | 9 | 5724 | 341.6 | 21.35 | 1384 | 4.543 | 1.708 | 31.81 | 3 | 6 | 0 | inconclusive |
| heuristic@lam=500 | congested_h_scope | 9 | 3567 | 274.6 | 251.5 | 670.6 | 12.73 | 10.42 | 57.5 | 4 | 5 | 0 | inconclusive |
| rl_ppo | congested_h_scope | 9 | 3567 | 473.7 | 19.83 | 883.8 | 7.479 | 3.9 | 32.3 | 3 | 6 | 0 | inconclusive |
| heuristic@lam=500 | unfinished | 9 | 814 | 258.3 | 113 | 522.8 | 172.2 | 54.94 | 907.7 | 2 | 5 | 2 | inconclusive |
| rl_ppo | unfinished | 9 | 814 | 225.2 | 0 | 984.4 | 92.46 | 8.454 | 449.2 | 3 | 4 | 2 | inconclusive |

## Ranking by paired total vehicle-hours (common complete blocks)

1. `heuristic@lam=500`: -1.285 veh-h (-0.10%) vs forecast_only (inconclusive)
2. `forecast_only`: +0.000 veh-h (+0.00%) vs forecast_only
3. `rl_ppo`: +19.275 veh-h (+1.55%) vs forecast_only (worse in every pair)

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
   "vehicle_hours_reduction_pct": 0.10328061134929045,
   "vehicle_hours_mean_diff": -1.2848611111111268,
   "blocks_better": 1.0,
   "blocks_worse": 1.0,
   "consistent_reduction": false,
   "congested_scope_reduction_pct": 1.1577536424564328,
   "background_mean_change_pct": -0.6747820967068825,
   "participant_p95_change_pct": -0.5916262350702441,
   "meets_vehicle_hours_target": false,
   "lower_congestion": true,
   "background_ok": true,
   "participant_p95_ok": true
  },
  "rl_ppo": {
   "vehicle_hours_reduction_pct": -1.5454488949407623,
   "vehicle_hours_mean_diff": 19.275277777777774,
   "blocks_better": 0.0,
   "blocks_worse": 2.0,
   "consistent_reduction": false,
   "congested_scope_reduction_pct": -0.5283981412506251,
   "background_mean_change_pct": -0.23838684320310066,
   "participant_p95_change_pct": 5.126785382163268,
   "meets_vehicle_hours_target": false,
   "lower_congestion": false,
   "background_ok": true,
   "participant_p95_ok": false
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
  "unfinished": 7326,
  "teleports": 0,
  "call_ms_p95_max": 0.07627449994060953
 },
 "heuristic@lam=500": {
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
  "unfinished": 9651,
  "teleports": 0,
  "call_ms_p95_max": 0.4710329999966234
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
  "unfinished": 9353,
  "teleports": 0,
  "call_ms_p95_max": 2.897177050033406
 }
}
```
