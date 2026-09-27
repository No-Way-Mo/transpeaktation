# Coordinated routing benchmark: `profile` · `profile_coordinated_routing_backtest_p5_c100_9c3fe2e9a0`

> **Synthetic.** SUMO scenarios on the SF citywide network; demand, attendance and behaviour are assumptions.
> Differences are realized in simulation under these assumptions, not measured on real streets.

- Scenarios (1): `b3_main_bearrison_arrival_f048_s0_event`
- Simulation seeds: [0] · policies: `forecast_only`, `forecast_only@rep=1`, `heuristic@lam=0`, `heuristic`, `batch`
- Forecast: `model` (data/forecast/experiments/event_patch_v2_main/best.pt) · participation 0.05 (cap 100000) · compliance 1.0 · batch window 60 s · drain cap 3600 s · teleport after 300 s
- RL checkpoints: {}
- Code: `{"sources_sha": "89aa667e595e8765", "files": 75, "tp_code_id": "f9ad4326a6138ada"}`
- Wall time: 1147.0 s

## Run status

| policy | ok | complete |
|---|---|---|
| batch | 1 | 1 |
| forecast_only | 1 | 1 |
| forecast_only@rep=1 | 1 | 1 |
| heuristic | 1 | 1 |
| heuristic@lam=0 | 1 | 1 |

Common complete blocks (every policy complete, identical population): **1 of 1**: `b3_main_bearrison_arrival_f048_s0_event` s0

## Mean outcomes per policy (common complete blocks)

vehicle_hours = realized time of every in-scope vehicle (participants and background, including insertion and batching waits), scored from the first decision. congested = vehicle-hours on mapped roads at speed <= 50% of the road's free-flow speed; stopped = speed < 0.1 m/s; pending = in-scope vehicles waiting off-network for insertion. Trip times count from the scheduled departure.

| policy | vehicle_hours | congested_h_scope | congested_h_all | stopped_h_scope | pending_h_scope | part_trip_s_mean | part_trip_s_p95 | other_trip_s_mean | other_trip_s_p95 | unfinished | teleports | decided | non_fastest_share | call_ms_p95 | batch_delay_s_mean | forecast_extra_travel_s_mean | wall_s | peak_mem_mb |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| batch | 880.4 | 275.2 | 490.8 | 214.6 | 0.026 | 574.6 | 1323 | 682.4 | 1549 | 0 | 19 | 141 | 0.064 | 10.2 | 34.94 | 0.016 | 342.1 | 2611 |
| forecast_only | 878.5 | 275 | 477.5 | 214.4 | 0.023 | 541.1 | 1274 | 682.4 | 1549 | 0 | 22 | 139 | 0.072 | 0.053 | 0 | 0.016 | 338.3 | 2573 |
| forecast_only@rep=1 | 878.5 | 275 | 477.5 | 214.4 | 0.023 | 541.1 | 1274 | 682.4 | 1549 | 0 | 22 | 139 | 0.072 | 0.062 | 0 | 0.016 | 357.2 | 2586 |
| heuristic | 877.3 | 274.4 | 476.9 | 213.8 | 0.024 | 541.8 | 1276 | 681.6 | 1545 | 0 | 20 | 139 | 0.079 | 0.193 | 0 | 0.02 | 342 | 2580 |
| heuristic@lam=0 | 878.5 | 275 | 477.5 | 214.4 | 0.023 | 541.1 | 1274 | 682.4 | 1549 | 0 | 22 | 139 | 0.072 | 0.065 | 0 | 0.016 | 340.4 | 2588 |

## Paired differences vs `forecast_only` on common complete blocks (policy minus baseline; negative = less)

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| batch | vehicle_hours | 1 | 878.5 | 1.874 | 1.874 |  | 0.2133 | 0.2133 | 0.2133 | 0 | 1 | 0 | worse in every pair |
| forecast_only@rep=1 | vehicle_hours | 1 | 878.5 | 0 | 0 |  | 0 | 0 | 0 | 0 | 0 | 1 | inconclusive |
| heuristic | vehicle_hours | 1 | 878.5 | -1.204 | -1.204 |  | -0.137 | -0.137 | -0.137 | 1 | 0 | 0 | better in every pair |
| heuristic@lam=0 | vehicle_hours | 1 | 878.5 | 0 | 0 |  | 0 | 0 | 0 | 0 | 0 | 1 | inconclusive |
| batch | congested_h_scope | 1 | 275 | 0.2264 | 0.2264 |  | 0.0823 | 0.0823 | 0.0823 | 0 | 1 | 0 | worse in every pair |
| forecast_only@rep=1 | congested_h_scope | 1 | 275 | 0 | 0 |  | 0 | 0 | 0 | 0 | 0 | 1 | inconclusive |
| heuristic | congested_h_scope | 1 | 275 | -0.5397 | -0.5397 |  | -0.1963 | -0.1963 | -0.1963 | 1 | 0 | 0 | better in every pair |
| heuristic@lam=0 | congested_h_scope | 1 | 275 | 0 | 0 |  | 0 | 0 | 0 | 0 | 0 | 1 | inconclusive |
| batch | congested_h_all | 1 | 477.5 | 13.31 | 13.31 |  | 2.788 | 2.788 | 2.788 | 0 | 1 | 0 | worse in every pair |
| forecast_only@rep=1 | congested_h_all | 1 | 477.5 | 0 | 0 |  | 0 | 0 | 0 | 0 | 0 | 1 | inconclusive |
| heuristic | congested_h_all | 1 | 477.5 | -0.5803 | -0.5803 |  | -0.1215 | -0.1215 | -0.1215 | 1 | 0 | 0 | better in every pair |
| heuristic@lam=0 | congested_h_all | 1 | 477.5 | 0 | 0 |  | 0 | 0 | 0 | 0 | 0 | 1 | inconclusive |
| batch | stopped_h_scope | 1 | 214.4 | 0.2319 | 0.2319 |  | 0.1082 | 0.1082 | 0.1082 | 0 | 1 | 0 | worse in every pair |
| forecast_only@rep=1 | stopped_h_scope | 1 | 214.4 | 0 | 0 |  | 0 | 0 | 0 | 0 | 0 | 1 | inconclusive |
| heuristic | stopped_h_scope | 1 | 214.4 | -0.6258 | -0.6258 |  | -0.2919 | -0.2919 | -0.2919 | 1 | 0 | 0 | better in every pair |
| heuristic@lam=0 | stopped_h_scope | 1 | 214.4 | 0 | 0 |  | 0 | 0 | 0 | 0 | 0 | 1 | inconclusive |
| batch | pending_h_scope | 1 | 0.0231 | 0.0033 | 0.0033 |  | 14.46 | 14.46 | 14.46 | 0 | 1 | 0 | worse in every pair |
| forecast_only@rep=1 | pending_h_scope | 1 | 0.0231 | 0 | 0 |  | 0 | 0 | 0 | 0 | 0 | 1 | inconclusive |
| heuristic | pending_h_scope | 1 | 0.0231 | 0.0008 | 0.0008 |  | 3.615 | 3.615 | 3.615 | 0 | 1 | 0 | worse in every pair |
| heuristic@lam=0 | pending_h_scope | 1 | 0.0231 | 0 | 0 |  | 0 | 0 | 0 | 0 | 0 | 1 | inconclusive |
| batch | part_trip_s_mean | 1 | 541.1 | 33.47 | 33.47 |  | 6.186 | 6.186 | 6.186 | 0 | 1 | 0 | worse in every pair |
| forecast_only@rep=1 | part_trip_s_mean | 1 | 541.1 | 0 | 0 |  | 0 | 0 | 0 | 0 | 0 | 1 | inconclusive |
| heuristic | part_trip_s_mean | 1 | 541.1 | 0.665 | 0.665 |  | 0.1229 | 0.1229 | 0.1229 | 0 | 1 | 0 | worse in every pair |
| heuristic@lam=0 | part_trip_s_mean | 1 | 541.1 | 0 | 0 |  | 0 | 0 | 0 | 0 | 0 | 1 | inconclusive |
| batch | part_trip_s_p95 | 1 | 1274 | 48.56 | 48.56 |  | 3.812 | 3.812 | 3.812 | 0 | 1 | 0 | worse in every pair |
| forecast_only@rep=1 | part_trip_s_p95 | 1 | 1274 | 0 | 0 |  | 0 | 0 | 0 | 0 | 0 | 1 | inconclusive |
| heuristic | part_trip_s_p95 | 1 | 1274 | 1.6 | 1.6 |  | 0.1256 | 0.1256 | 0.1256 | 0 | 1 | 0 | worse in every pair |
| heuristic@lam=0 | part_trip_s_p95 | 1 | 1274 | 0 | 0 |  | 0 | 0 | 0 | 0 | 0 | 1 | inconclusive |
| batch | other_trip_s_mean | 1 | 682.4 | 0.012 | 0.012 |  | 0.0018 | 0.0018 | 0.0018 | 0 | 1 | 0 | worse in every pair |
| forecast_only@rep=1 | other_trip_s_mean | 1 | 682.4 | 0 | 0 |  | 0 | 0 | 0 | 0 | 0 | 1 | inconclusive |
| heuristic | other_trip_s_mean | 1 | 682.4 | -0.821 | -0.821 |  | -0.1203 | -0.1203 | -0.1203 | 1 | 0 | 0 | better in every pair |
| heuristic@lam=0 | other_trip_s_mean | 1 | 682.4 | 0 | 0 |  | 0 | 0 | 0 | 0 | 0 | 1 | inconclusive |
| batch | other_trip_s_p95 | 1 | 1549 | 0.36 | 0.36 |  | 0.0232 | 0.0232 | 0.0232 | 0 | 1 | 0 | worse in every pair |
| forecast_only@rep=1 | other_trip_s_p95 | 1 | 1549 | 0 | 0 |  | 0 | 0 | 0 | 0 | 0 | 1 | inconclusive |
| heuristic | other_trip_s_p95 | 1 | 1549 | -3.6 | -3.6 |  | -0.2325 | -0.2325 | -0.2325 | 1 | 0 | 0 | better in every pair |
| heuristic@lam=0 | other_trip_s_p95 | 1 | 1549 | 0 | 0 |  | 0 | 0 | 0 | 0 | 0 | 1 | inconclusive |
| batch | part_route_m_mean | 1 | 4563 | -7.373 | -7.373 |  | -0.1616 | -0.1616 | -0.1616 | 1 | 0 | 0 | better in every pair |
| forecast_only@rep=1 | part_route_m_mean | 1 | 4563 | 0 | 0 |  | 0 | 0 | 0 | 0 | 0 | 1 | inconclusive |
| heuristic | part_route_m_mean | 1 | 4563 | -0.8278 | -0.8278 |  | -0.0181 | -0.0181 | -0.0181 | 1 | 0 | 0 | better in every pair |
| heuristic@lam=0 | part_route_m_mean | 1 | 4563 | 0 | 0 |  | 0 | 0 | 0 | 0 | 0 | 1 | inconclusive |

## Common-horizon check on every successful block (includes censored runs)

Vehicle-hours through the same drain cap, congested hours and unfinished backlog; a policy that leaves more vehicles unfinished is not better because its completed trips look faster.

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| batch | vehicle_hours | 1 | 878.5 | 1.874 | 1.874 |  | 0.2133 | 0.2133 | 0.2133 | 0 | 1 | 0 | worse in every pair |
| forecast_only@rep=1 | vehicle_hours | 1 | 878.5 | 0 | 0 |  | 0 | 0 | 0 | 0 | 0 | 1 | inconclusive |
| heuristic | vehicle_hours | 1 | 878.5 | -1.204 | -1.204 |  | -0.137 | -0.137 | -0.137 | 1 | 0 | 0 | better in every pair |
| heuristic@lam=0 | vehicle_hours | 1 | 878.5 | 0 | 0 |  | 0 | 0 | 0 | 0 | 0 | 1 | inconclusive |
| batch | congested_h_scope | 1 | 275 | 0.2264 | 0.2264 |  | 0.0823 | 0.0823 | 0.0823 | 0 | 1 | 0 | worse in every pair |
| forecast_only@rep=1 | congested_h_scope | 1 | 275 | 0 | 0 |  | 0 | 0 | 0 | 0 | 0 | 1 | inconclusive |
| heuristic | congested_h_scope | 1 | 275 | -0.5397 | -0.5397 |  | -0.1963 | -0.1963 | -0.1963 | 1 | 0 | 0 | better in every pair |
| heuristic@lam=0 | congested_h_scope | 1 | 275 | 0 | 0 |  | 0 | 0 | 0 | 0 | 0 | 1 | inconclusive |
| batch | unfinished | 1 | 0 | 0 | 0 |  |  |  |  | 0 | 0 | 1 | inconclusive |
| forecast_only@rep=1 | unfinished | 1 | 0 | 0 | 0 |  |  |  |  | 0 | 0 | 1 | inconclusive |
| heuristic | unfinished | 1 | 0 | 0 | 0 |  |  |  |  | 0 | 0 | 1 | inconclusive |
| heuristic@lam=0 | unfinished | 1 | 0 | 0 | 0 |  |  |  |  | 0 | 0 | 1 | inconclusive |

## Ranking by paired total vehicle-hours (common complete blocks)

1. `heuristic`: -1.204 veh-h (-0.14%) vs forecast_only (better in every pair)
2. `forecast_only`: +0.000 veh-h (+0.00%) vs forecast_only
3. `forecast_only@rep=1`: +0.000 veh-h (+0.00%) vs forecast_only (inconclusive)
4. `heuristic@lam=0`: +0.000 veh-h (+0.00%) vs forecast_only (inconclusive)
5. `batch`: +1.874 veh-h (+0.21%) vs forecast_only (worse in every pair)

**Best eligible policy on this suite: `heuristic`**
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
  "forecast_only@rep=1": {
   "vehicle_hours_reduction_pct": -0.0,
   "vehicle_hours_mean_diff": 0.0,
   "blocks_better": 0.0,
   "blocks_worse": 0.0,
   "consistent_reduction": false,
   "congested_scope_reduction_pct": -0.0,
   "background_mean_change_pct": 0.0,
   "participant_p95_change_pct": 0.0,
   "meets_vehicle_hours_target": false,
   "lower_congestion": false,
   "background_ok": true,
   "participant_p95_ok": true
  },
  "heuristic@lam=0": {
   "vehicle_hours_reduction_pct": -0.0,
   "vehicle_hours_mean_diff": 0.0,
   "blocks_better": 0.0,
   "blocks_worse": 0.0,
   "consistent_reduction": false,
   "congested_scope_reduction_pct": -0.0,
   "background_mean_change_pct": 0.0,
   "participant_p95_change_pct": 0.0,
   "meets_vehicle_hours_target": false,
   "lower_congestion": false,
   "background_ok": true,
   "participant_p95_ok": true
  },
  "heuristic": {
   "vehicle_hours_reduction_pct": 0.13700042115060784,
   "vehicle_hours_mean_diff": -1.2036111111110586,
   "blocks_better": 1.0,
   "blocks_worse": 0.0,
   "consistent_reduction": true,
   "congested_scope_reduction_pct": 0.19627432341927514,
   "background_mean_change_pct": -0.12031972054774875,
   "participant_p95_change_pct": 0.12558869701726103,
   "meets_vehicle_hours_target": false,
   "lower_congestion": true,
   "background_ok": true,
   "participant_p95_ok": true
  },
  "batch": {
   "vehicle_hours_reduction_pct": -0.2132565060181375,
   "vehicle_hours_mean_diff": 1.8735555555554129,
   "blocks_better": 0.0,
   "blocks_worse": 1.0,
   "consistent_reduction": false,
   "congested_scope_reduction_pct": -0.08232813874766366,
   "background_mean_change_pct": 0.001751967257088102,
   "participant_p95_change_pct": 3.8116169544737994,
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
  "runs": 1,
  "ok": 1,
  "complete": 1,
  "unavailable": 0,
  "failed": 0,
  "invalid_routes": 0,
  "selector_failures": 0,
  "unchosen_fallbacks": 0,
  "dropped_trips": 0,
  "readback_mismatch": 0,
  "unfinished": 0,
  "teleports": 19,
  "call_ms_p95_max": 10.200364600018474
 },
 "forecast_only": {
  "runs": 1,
  "ok": 1,
  "complete": 1,
  "unavailable": 0,
  "failed": 0,
  "invalid_routes": 0,
  "selector_failures": 0,
  "unchosen_fallbacks": 0,
  "dropped_trips": 0,
  "readback_mismatch": 0,
  "unfinished": 0,
  "teleports": 22,
  "call_ms_p95_max": 0.052945099980661325
 },
 "forecast_only@rep=1": {
  "runs": 1,
  "ok": 1,
  "complete": 1,
  "unavailable": 0,
  "failed": 0,
  "invalid_routes": 0,
  "selector_failures": 0,
  "unchosen_fallbacks": 0,
  "dropped_trips": 0,
  "readback_mismatch": 0,
  "unfinished": 0,
  "teleports": 22,
  "call_ms_p95_max": 0.06166600002188715
 },
 "heuristic": {
  "runs": 1,
  "ok": 1,
  "complete": 1,
  "unavailable": 0,
  "failed": 0,
  "invalid_routes": 0,
  "selector_failures": 0,
  "unchosen_fallbacks": 0,
  "dropped_trips": 0,
  "readback_mismatch": 0,
  "unfinished": 0,
  "teleports": 20,
  "call_ms_p95_max": 0.1927839000302356
 },
 "heuristic@lam=0": {
  "runs": 1,
  "ok": 1,
  "complete": 1,
  "unavailable": 0,
  "failed": 0,
  "invalid_routes": 0,
  "selector_failures": 0,
  "unchosen_fallbacks": 0,
  "dropped_trips": 0,
  "readback_mismatch": 0,
  "unfinished": 0,
  "teleports": 22,
  "call_ms_p95_max": 0.06476399998405212
 }
}
```
