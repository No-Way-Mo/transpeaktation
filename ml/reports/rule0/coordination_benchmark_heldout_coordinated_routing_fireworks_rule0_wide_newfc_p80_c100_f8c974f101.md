# Coordinated routing benchmark: `heldout` · `heldout_coordinated_routing_fireworks_rule0_wide_newfc_p80_c100_f8c974f101`

> **Synthetic.** SUMO scenarios on the SF citywide network; demand, attendance and behaviour are assumptions.
> Differences are realized in simulation under these assumptions, not measured on real streets.

- Scenarios (3): `b6_fireworks_n12000_all_s0_event`, `b6_fireworks_n3000_all_s0_event`, `b6_fireworks_n6000_all_s0_event`
- Simulation seeds: [0, 1, 2] · policies: `forecast_only`, `heuristic@lam=500`, `rl_ppo`
- Forecast: `model` (data/forecast/experiments/event_patch_x_all/best.pt) · participation 0.8 (cap 100000) · compliance 1.0 · batch window 60 s · drain cap 8100 s · teleport after -1 s
- RL checkpoints: {"rl_ppo": {"checkpoint": "data/coordination/rl/runs_async/appo_async_s0/latest", "exists": true}}
- Code: `{"sources_sha": "d0820cdea302d298", "files": 82, "tp_code_id": ""}`
- Wall time: 3184.8 s

## Run status

| policy | ok | complete |
|---|---|---|
| forecast_only | 9 | 3 |
| heuristic@lam=500 | 9 | 1 |
| rl_ppo | 9 | 1 |

Common complete blocks (every policy complete, identical population): **1 of 9**: `b6_fireworks_n3000_all_s0_event` s2

### Failed, incomplete or censored runs (kept visible, excluded from the primary ranking)

| policy | scenario | seed | status | failed_checks | unfinished | teleports | error |
|---|---|---|---|---|---|---|---|
| forecast_only | b6_fireworks_n12000_all_s0_event | 0 | ok | all_in_scope_arrived | 4619 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n12000_all_s0_event | 0 | ok | all_in_scope_arrived | 4457 | 0 |  |
| rl_ppo | b6_fireworks_n12000_all_s0_event | 0 | ok | all_in_scope_arrived | 3378 | 0 |  |
| forecast_only | b6_fireworks_n12000_all_s0_event | 1 | ok | all_in_scope_arrived | 4714 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n12000_all_s0_event | 1 | ok | all_in_scope_arrived | 4727 | 0 |  |
| rl_ppo | b6_fireworks_n12000_all_s0_event | 1 | ok | all_in_scope_arrived | 2719 | 0 |  |
| forecast_only | b6_fireworks_n12000_all_s0_event | 2 | ok | all_in_scope_arrived | 4554 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n12000_all_s0_event | 2 | ok | all_in_scope_arrived | 4179 | 0 |  |
| rl_ppo | b6_fireworks_n12000_all_s0_event | 2 | ok | all_in_scope_arrived | 2949 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n3000_all_s0_event | 0 | ok | all_in_scope_arrived | 61 | 0 |  |
| rl_ppo | b6_fireworks_n3000_all_s0_event | 0 | ok | all_in_scope_arrived | 28 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n3000_all_s0_event | 1 | ok | all_in_scope_arrived | 67 | 0 |  |
| rl_ppo | b6_fireworks_n3000_all_s0_event | 1 | ok | all_in_scope_arrived | 176 | 0 |  |
| forecast_only | b6_fireworks_n6000_all_s0_event | 0 | ok | all_in_scope_arrived | 276 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n6000_all_s0_event | 0 | ok | all_in_scope_arrived | 149 | 0 |  |
| rl_ppo | b6_fireworks_n6000_all_s0_event | 0 | ok | all_in_scope_arrived | 1080 | 0 |  |
| forecast_only | b6_fireworks_n6000_all_s0_event | 1 | ok | all_in_scope_arrived | 346 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n6000_all_s0_event | 1 | ok | all_in_scope_arrived | 341 | 0 |  |
| rl_ppo | b6_fireworks_n6000_all_s0_event | 1 | ok | all_in_scope_arrived | 897 | 0 |  |
| forecast_only | b6_fireworks_n6000_all_s0_event | 2 | ok | all_in_scope_arrived | 162 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n6000_all_s0_event | 2 | ok | all_in_scope_arrived | 177 | 0 |  |
| rl_ppo | b6_fireworks_n6000_all_s0_event | 2 | ok | all_in_scope_arrived | 615 | 0 |  |

## Mean outcomes per policy (common complete blocks)

vehicle_hours = realized time of every in-scope vehicle (participants and background, including insertion and batching waits), scored from the first decision. congested = vehicle-hours on mapped roads at speed <= 50% of the road's free-flow speed; stopped = speed < 0.1 m/s; pending = in-scope vehicles waiting off-network for insertion. Trip times count from the scheduled departure.

| policy | vehicle_hours | congested_h_scope | congested_h_all | stopped_h_scope | pending_h_scope | part_trip_s_mean | part_trip_s_p95 | other_trip_s_mean | other_trip_s_p95 | unfinished | teleports | decided | non_fastest_share | call_ms_p95 | batch_delay_s_mean | forecast_extra_travel_s_mean | wall_s | peak_mem_mb |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| forecast_only | 1492 | 754.4 | 754.4 | 548.5 | 3.063 | 1395 | 3167 | 1144 | 1773 | 0 | 0 | 3021 | 0.048 | 0.07 | 0 | 0.012 | 913.6 | 3223 |
| heuristic@lam=500 | 1386 | 612.5 | 612.5 | 468.3 | 7.521 | 1278 | 2555 | 1135 | 1751 | 0 | 0 | 3043 | 0.635 | 0.408 | 0 | 62.39 | 908.2 | 3204 |
| rl_ppo | 1251 | 465.4 | 465.4 | 332 | 0.27 | 1128 | 1657 | 1118 | 1710 | 0 | 0 | 3007 | 0.999 | 2.693 | 0 | 100.5 | 904.8 | 3211 |

## Paired differences vs `forecast_only` on common complete blocks (policy minus baseline; negative = less)

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| heuristic@lam=500 | vehicle_hours | 1 | 1492 | -105.4 | -105.4 |  | -7.068 | -7.068 | -7.068 | 1 | 0 | 0 | better in every pair |
| rl_ppo | vehicle_hours | 1 | 1492 | -241 | -241 |  | -16.15 | -16.15 | -16.15 | 1 | 0 | 0 | better in every pair |
| heuristic@lam=500 | congested_h_scope | 1 | 754.4 | -142 | -142 |  | -18.82 | -18.82 | -18.82 | 1 | 0 | 0 | better in every pair |
| rl_ppo | congested_h_scope | 1 | 754.4 | -289.1 | -289.1 |  | -38.31 | -38.31 | -38.31 | 1 | 0 | 0 | better in every pair |
| heuristic@lam=500 | congested_h_all | 1 | 754.4 | -142 | -142 |  | -18.82 | -18.82 | -18.82 | 1 | 0 | 0 | better in every pair |
| rl_ppo | congested_h_all | 1 | 754.4 | -289.1 | -289.1 |  | -38.31 | -38.31 | -38.31 | 1 | 0 | 0 | better in every pair |
| heuristic@lam=500 | stopped_h_scope | 1 | 548.5 | -80.22 | -80.22 |  | -14.62 | -14.62 | -14.62 | 1 | 0 | 0 | better in every pair |
| rl_ppo | stopped_h_scope | 1 | 548.5 | -216.5 | -216.5 |  | -39.47 | -39.47 | -39.47 | 1 | 0 | 0 | better in every pair |
| heuristic@lam=500 | pending_h_scope | 1 | 3.063 | 4.457 | 4.457 |  | 145.5 | 145.5 | 145.5 | 0 | 1 | 0 | worse in every pair |
| rl_ppo | pending_h_scope | 1 | 3.063 | -2.793 | -2.793 |  | -91.18 | -91.18 | -91.18 | 1 | 0 | 0 | better in every pair |
| heuristic@lam=500 | part_trip_s_mean | 1 | 1395 | -117.9 | -117.9 |  | -8.449 | -8.449 | -8.449 | 1 | 0 | 0 | better in every pair |
| rl_ppo | part_trip_s_mean | 1 | 1395 | -267.8 | -267.8 |  | -19.19 | -19.19 | -19.19 | 1 | 0 | 0 | better in every pair |
| heuristic@lam=500 | part_trip_s_p95 | 1 | 3167 | -611.4 | -611.4 |  | -19.31 | -19.31 | -19.31 | 1 | 0 | 0 | better in every pair |
| rl_ppo | part_trip_s_p95 | 1 | 3167 | -1510 | -1510 |  | -47.67 | -47.67 | -47.67 | 1 | 0 | 0 | better in every pair |
| heuristic@lam=500 | other_trip_s_mean | 1 | 1144 | -8.587 | -8.587 |  | -0.7506 | -0.7506 | -0.7506 | 1 | 0 | 0 | better in every pair |
| rl_ppo | other_trip_s_mean | 1 | 1144 | -26.08 | -26.08 |  | -2.28 | -2.28 | -2.28 | 1 | 0 | 0 | better in every pair |
| heuristic@lam=500 | other_trip_s_p95 | 1 | 1773 | -22.15 | -22.15 |  | -1.249 | -1.249 | -1.249 | 1 | 0 | 0 | better in every pair |
| rl_ppo | other_trip_s_p95 | 1 | 1773 | -62.95 | -62.95 |  | -3.551 | -3.551 | -3.551 | 1 | 0 | 0 | better in every pair |
| heuristic@lam=500 | part_route_m_mean | 1 | 6758 | 325.4 | 325.4 |  | 4.815 | 4.815 | 4.815 | 0 | 1 | 0 | worse in every pair |
| rl_ppo | part_route_m_mean | 1 | 6758 | 270.5 | 270.5 |  | 4.002 | 4.002 | 4.002 | 0 | 1 | 0 | worse in every pair |

## Common-horizon check on every successful block (includes censored runs)

Vehicle-hours through the same drain cap, congested hours and unfinished backlog; a policy that leaves more vehicles unfinished is not better because its completed trips look faster.

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| heuristic@lam=500 | vehicle_hours | 9 | 8787 | -1796 | -1318 | 1826 | -16.03 | -20.44 | 6.623 | 8 | 1 | 0 | inconclusive |
| rl_ppo | vehicle_hours | 9 | 8787 | -2147 | -241 | 3030 | -13.55 | -12.01 | 8.068 | 7 | 2 | 0 | inconclusive |
| heuristic@lam=500 | congested_h_scope | 9 | 5696 | -1309 | -1320 | 1135 | -21.79 | -20.47 | 6.832 | 8 | 1 | 0 | inconclusive |
| rl_ppo | congested_h_scope | 9 | 5696 | -1184 | -377.9 | 1416 | -18.14 | -21.62 | 7.369 | 8 | 1 | 0 | inconclusive |
| heuristic@lam=500 | unfinished | 9 | 1630 | -57 | 0 | 142.5 | -8.278 | -2.476 | 9.259 | 4 | 4 | 1 | inconclusive |
| rl_ppo | unfinished | 9 | 1630 | -314.3 | 28 | 1024 | 104.3 | 66.19 | 291.3 | 3 | 5 | 1 | inconclusive |

## Ranking by paired total vehicle-hours (common complete blocks)

1. `rl_ppo`: -240.981 veh-h (-16.15%) vs forecast_only (better in every pair)
2. `heuristic@lam=500`: -105.434 veh-h (-7.07%) vs forecast_only (better in every pair)
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
   "vehicle_hours_reduction_pct": 7.068053955127769,
   "vehicle_hours_mean_diff": -105.43361111111108,
   "blocks_better": 1.0,
   "blocks_worse": 0.0,
   "consistent_reduction": true,
   "congested_scope_reduction_pct": 18.820915278138298,
   "background_mean_change_pct": -0.750559805498078,
   "participant_p95_change_pct": -19.305891083637203,
   "meets_vehicle_hours_target": true,
   "lower_congestion": true,
   "background_ok": true,
   "participant_p95_ok": true
  },
  "rl_ppo": {
   "vehicle_hours_reduction_pct": 16.15488151785853,
   "vehicle_hours_mean_diff": -240.98111111111098,
   "blocks_better": 1.0,
   "blocks_worse": 0.0,
   "consistent_reduction": true,
   "congested_scope_reduction_pct": 38.31403108609888,
   "background_mean_change_pct": -2.279604808980976,
   "participant_p95_change_pct": -47.67340880741471,
   "meets_vehicle_hours_target": true,
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
  "unfinished": 14671,
  "teleports": 0,
  "call_ms_p95_max": 0.07792999986122595
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
  "unfinished": 14158,
  "teleports": 0,
  "call_ms_p95_max": 0.5178379999506433
 },
 "rl_ppo": {
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
  "unfinished": 11842,
  "teleports": 0,
  "call_ms_p95_max": 2.856036250022953
 }
}
```
