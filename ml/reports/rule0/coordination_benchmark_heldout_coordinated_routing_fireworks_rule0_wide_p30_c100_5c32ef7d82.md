# Coordinated routing benchmark: `heldout` · `heldout_coordinated_routing_fireworks_rule0_wide_p30_c100_5c32ef7d82`

> **Synthetic.** SUMO scenarios on the SF citywide network; demand, attendance and behaviour are assumptions.
> Differences are realized in simulation under these assumptions, not measured on real streets.

- Scenarios (3): `b6_fireworks_n12000_all_s0_event`, `b6_fireworks_n3000_all_s0_event`, `b6_fireworks_n6000_all_s0_event`
- Simulation seeds: [0, 1, 2] · policies: `forecast_only`, `heuristic@lam=500`, `rl_ppo`
- Forecast: `model` (data/forecast/experiments/event_patch_v2_main/best.pt) · participation 0.3 (cap 100000) · compliance 1.0 · batch window 60 s · drain cap 8100 s · teleport after -1 s
- RL checkpoints: {"rl_ppo": {"checkpoint": "data/coordination/rl/runs_async/appo_async_s0/latest", "exists": true}}
- Code: `{"sources_sha": "2e0281ea7983d8d2", "files": 81, "tp_code_id": ""}`
- Wall time: 2113.1 s

## Run status

| policy | ok | complete |
|---|---|---|
| forecast_only | 9 | 3 |
| heuristic@lam=500 | 9 | 3 |
| rl_ppo | 9 | 0 |

Common complete blocks (every policy complete, identical population): **0 of 9**

### Failed, incomplete or censored runs (kept visible, excluded from the primary ranking)

| policy | scenario | seed | status | failed_checks | unfinished | teleports | error |
|---|---|---|---|---|---|---|---|
| forecast_only | b6_fireworks_n12000_all_s0_event | 0 | ok | all_in_scope_arrived | 1953 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n12000_all_s0_event | 0 | ok | all_in_scope_arrived | 1749 | 0 |  |
| rl_ppo | b6_fireworks_n12000_all_s0_event | 0 | ok | all_in_scope_arrived | 4211 | 0 |  |
| forecast_only | b6_fireworks_n12000_all_s0_event | 1 | ok | all_in_scope_arrived | 3684 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n12000_all_s0_event | 1 | ok | all_in_scope_arrived | 1685 | 0 |  |
| rl_ppo | b6_fireworks_n12000_all_s0_event | 1 | ok | all_in_scope_arrived | 2594 | 0 |  |
| forecast_only | b6_fireworks_n12000_all_s0_event | 2 | ok | all_in_scope_arrived | 1052 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n12000_all_s0_event | 2 | ok | all_in_scope_arrived | 2399 | 0 |  |
| rl_ppo | b6_fireworks_n12000_all_s0_event | 2 | ok | all_in_scope_arrived | 4458 | 0 |  |
| forecast_only | b6_fireworks_n3000_all_s0_event | 0 | ok | all_in_scope_arrived | 125 | 0 |  |
| rl_ppo | b6_fireworks_n3000_all_s0_event | 0 | ok | all_in_scope_arrived | 72 | 0 |  |
| rl_ppo | b6_fireworks_n3000_all_s0_event | 1 | ok | all_in_scope_arrived | 177 | 0 |  |
| rl_ppo | b6_fireworks_n3000_all_s0_event | 2 | ok | all_in_scope_arrived | 209 | 0 |  |
| forecast_only | b6_fireworks_n6000_all_s0_event | 0 | ok | all_in_scope_arrived | 257 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n6000_all_s0_event | 0 | ok | all_in_scope_arrived | 84 | 0 |  |
| rl_ppo | b6_fireworks_n6000_all_s0_event | 0 | ok | all_in_scope_arrived | 702 | 0 |  |
| forecast_only | b6_fireworks_n6000_all_s0_event | 1 | ok | all_in_scope_arrived | 125 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n6000_all_s0_event | 1 | ok | all_in_scope_arrived | 3 | 0 |  |
| rl_ppo | b6_fireworks_n6000_all_s0_event | 1 | ok | all_in_scope_arrived | 640 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n6000_all_s0_event | 2 | ok | all_in_scope_arrived | 656 | 0 |  |
| rl_ppo | b6_fireworks_n6000_all_s0_event | 2 | ok | all_in_scope_arrived | 785 | 0 |  |

## Mean outcomes per policy (common complete blocks)

vehicle_hours = realized time of every in-scope vehicle (participants and background, including insertion and batching waits), scored from the first decision. congested = vehicle-hours on mapped roads at speed <= 50% of the road's free-flow speed; stopped = speed < 0.1 m/s; pending = in-scope vehicles waiting off-network for insertion. Trip times count from the scheduled departure.

(no common complete blocks)

## Paired differences vs `forecast_only` on common complete blocks (policy minus baseline; negative = less)

(no pairs)

## Common-horizon check on every successful block (includes censored runs)

Vehicle-hours through the same drain cap, congested hours and unfinished backlog; a policy that leaves more vehicles unfinished is not better because its completed trips look faster.

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| heuristic@lam=500 | vehicle_hours | 9 | 5704 | -138.3 | -95.47 | 1150 | -0.3811 | -0.7915 | 45.24 | 5 | 4 | 0 | inconclusive |
| rl_ppo | vehicle_hours | 9 | 5704 | 1123 | 775.7 | 1648 | 25.75 | 32.76 | 56.29 | 2 | 7 | 0 | inconclusive |
| heuristic@lam=500 | congested_h_scope | 9 | 3686 | -67.85 | -3.85 | 973.8 | -1.311 | -0.7454 | 64.55 | 5 | 4 | 0 | inconclusive |
| rl_ppo | congested_h_scope | 9 | 3686 | 1101 | 761.6 | 1483 | 44.08 | 46.17 | 86.66 | 2 | 7 | 0 | inconclusive |
| heuristic@lam=500 | unfinished | 9 | 799.6 | -68.89 | -122 | 887.4 | -33.6 | -60.79 | 128 | 5 | 2 | 2 | inconclusive |
| rl_ppo | unfinished | 9 | 799.6 | 739.1 | 445 | 1329 | 158.8 | 144.4 | 412 | 2 | 7 | 0 | inconclusive |

## Ranking by paired total vehicle-hours (common complete blocks)


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
 "per_policy": {}
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
  "unfinished": 7196,
  "teleports": 0,
  "call_ms_p95_max": 0.06804799994597487
 },
 "heuristic@lam=500": {
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
  "unfinished": 6576,
  "teleports": 0,
  "call_ms_p95_max": 0.3700684999870418
 },
 "rl_ppo": {
  "runs": 9,
  "ok": 9,
  "complete": 0,
  "unavailable": 0,
  "failed": 0,
  "invalid_routes": 0,
  "selector_failures": 0,
  "unchosen_fallbacks": 0,
  "dropped_trips": 0,
  "readback_mismatch": 0,
  "unfinished": 13848,
  "teleports": 0,
  "call_ms_p95_max": 2.3451260999536316
 }
}
```
