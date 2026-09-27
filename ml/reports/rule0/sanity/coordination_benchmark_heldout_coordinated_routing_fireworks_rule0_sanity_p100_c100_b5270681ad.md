# Coordinated routing benchmark: `heldout` · `heldout_coordinated_routing_fireworks_rule0_sanity_p100_c100_b5270681ad`

> **Synthetic.** SUMO scenarios on the SF citywide network; demand, attendance and behaviour are assumptions.
> Differences are realized in simulation under these assumptions, not measured on real streets.

- Scenarios (3): `b6_fireworks_n12000_all_s0_event`, `b6_fireworks_n3000_all_s0_event`, `b6_fireworks_n6000_all_s0_event`
- Simulation seeds: [0, 1, 2] · policies: `forecast_only`, `heuristic@lam=0`
- Forecast: `model` (data/forecast/experiments/event_patch_v2_main/best.pt) · participation 1.0 (cap 100000) · compliance 1.0 · batch window 60 s · drain cap 8100 s · teleport after -1 s
- RL checkpoints: {}
- Code: `{"sources_sha": "2e0281ea7983d8d2", "files": 81, "tp_code_id": ""}`
- Wall time: 1950.1 s

## Run status

| policy | ok | complete |
|---|---|---|
| forecast_only | 9 | 3 |
| heuristic@lam=0 | 9 | 3 |

Common complete blocks (every policy complete, identical population): **3 of 9**: `b6_fireworks_n3000_all_s0_event` s0, `b6_fireworks_n3000_all_s0_event` s1, `b6_fireworks_n3000_all_s0_event` s2

### Failed, incomplete or censored runs (kept visible, excluded from the primary ranking)

| policy | scenario | seed | status | failed_checks | unfinished | teleports | error |
|---|---|---|---|---|---|---|---|
| forecast_only | b6_fireworks_n12000_all_s0_event | 0 | ok | all_in_scope_arrived | 5832 | 0 |  |
| heuristic@lam=0 | b6_fireworks_n12000_all_s0_event | 0 | ok | all_in_scope_arrived | 5832 | 0 |  |
| forecast_only | b6_fireworks_n12000_all_s0_event | 1 | ok | all_in_scope_arrived | 5735 | 0 |  |
| heuristic@lam=0 | b6_fireworks_n12000_all_s0_event | 1 | ok | all_in_scope_arrived | 5735 | 0 |  |
| forecast_only | b6_fireworks_n12000_all_s0_event | 2 | ok | all_in_scope_arrived | 5988 | 0 |  |
| heuristic@lam=0 | b6_fireworks_n12000_all_s0_event | 2 | ok | all_in_scope_arrived | 5988 | 0 |  |
| forecast_only | b6_fireworks_n6000_all_s0_event | 0 | ok | all_in_scope_arrived | 693 | 0 |  |
| heuristic@lam=0 | b6_fireworks_n6000_all_s0_event | 0 | ok | all_in_scope_arrived | 693 | 0 |  |
| forecast_only | b6_fireworks_n6000_all_s0_event | 1 | ok | all_in_scope_arrived | 670 | 0 |  |
| heuristic@lam=0 | b6_fireworks_n6000_all_s0_event | 1 | ok | all_in_scope_arrived | 670 | 0 |  |
| forecast_only | b6_fireworks_n6000_all_s0_event | 2 | ok | all_in_scope_arrived | 844 | 0 |  |
| heuristic@lam=0 | b6_fireworks_n6000_all_s0_event | 2 | ok | all_in_scope_arrived | 844 | 0 |  |

## Mean outcomes per policy (common complete blocks)

vehicle_hours = realized time of every in-scope vehicle (participants and background, including insertion and batching waits), scored from the first decision. congested = vehicle-hours on mapped roads at speed <= 50% of the road's free-flow speed; stopped = speed < 0.1 m/s; pending = in-scope vehicles waiting off-network for insertion. Trip times count from the scheduled departure.

| policy | vehicle_hours | congested_h_scope | congested_h_all | stopped_h_scope | pending_h_scope | part_trip_s_mean | part_trip_s_p95 | other_trip_s_mean | other_trip_s_p95 | unfinished | teleports | decided | non_fastest_share | call_ms_p95 | batch_delay_s_mean | forecast_extra_travel_s_mean | wall_s | peak_mem_mb |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| forecast_only | 2169 | 1430 | 1430 | 1084 | 14.16 | 1952 | 4951 |  |  | 0 | 0 | 3819 | 0.036 | 0.05 | 0 | 0.007 | 614.4 | 2507 |
| heuristic@lam=0 | 2169 | 1430 | 1430 | 1084 | 14.16 | 1952 | 4951 |  |  | 0 | 0 | 3819 | 0.036 | 0.048 | 0 | 0.007 | 600.8 | 2508 |

## Paired differences vs `forecast_only` on common complete blocks (policy minus baseline; negative = less)

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| heuristic@lam=0 | vehicle_hours | 3 | 2169 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | inconclusive |
| heuristic@lam=0 | congested_h_scope | 3 | 1430 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | inconclusive |
| heuristic@lam=0 | congested_h_all | 3 | 1430 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | inconclusive |
| heuristic@lam=0 | stopped_h_scope | 3 | 1084 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | inconclusive |
| heuristic@lam=0 | pending_h_scope | 3 | 14.16 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | inconclusive |
| heuristic@lam=0 | part_trip_s_mean | 3 | 1952 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | inconclusive |
| heuristic@lam=0 | part_trip_s_p95 | 3 | 4951 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | inconclusive |
| heuristic@lam=0 | part_route_m_mean | 3 | 6661 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | inconclusive |

## Common-horizon check on every successful block (includes censored runs)

Vehicle-hours through the same drain cap, congested hours and unfinished backlog; a policy that leaves more vehicles unfinished is not better because its completed trips look faster.

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| heuristic@lam=0 | vehicle_hours | 9 | 1.109e+04 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 9 | inconclusive |
| heuristic@lam=0 | congested_h_scope | 9 | 7559 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 9 | inconclusive |
| heuristic@lam=0 | unfinished | 9 | 2196 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 9 | inconclusive |

## Ranking by paired total vehicle-hours (common complete blocks)

1. `forecast_only`: +0.000 veh-h (+0.00%) vs forecast_only
2. `heuristic@lam=0`: +0.000 veh-h (+0.00%) vs forecast_only (inconclusive)

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
  "heuristic@lam=0": {
   "vehicle_hours_reduction_pct": -0.0,
   "vehicle_hours_mean_diff": 0.0,
   "blocks_better": 0.0,
   "blocks_worse": 0.0,
   "consistent_reduction": false,
   "congested_scope_reduction_pct": -0.0,
   "background_mean_change_pct": null,
   "participant_p95_change_pct": 0.0,
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
  "unfinished": 19762,
  "teleports": 0,
  "call_ms_p95_max": 0.05103020000660763
 },
 "heuristic@lam=0": {
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
  "unfinished": 19762,
  "teleports": 0,
  "call_ms_p95_max": 0.05311015001723263
 }
}
```
