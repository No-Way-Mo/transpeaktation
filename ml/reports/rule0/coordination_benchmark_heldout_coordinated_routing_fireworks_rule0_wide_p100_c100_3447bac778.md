# Coordinated routing benchmark: `heldout` · `heldout_coordinated_routing_fireworks_rule0_wide_p100_c100_3447bac778`

> **Synthetic.** SUMO scenarios on the SF citywide network; demand, attendance and behaviour are assumptions.
> Differences are realized in simulation under these assumptions, not measured on real streets.

- Scenarios (3): `b6_fireworks_n12000_all_s0_event`, `b6_fireworks_n3000_all_s0_event`, `b6_fireworks_n6000_all_s0_event`
- Simulation seeds: [0, 1, 2] · policies: `forecast_only`, `heuristic@lam=500`, `rl_ppo`
- Forecast: `model` (data/forecast/experiments/event_patch_v2_main/best.pt) · participation 1.0 (cap 100000) · compliance 1.0 · batch window 60 s · drain cap 8100 s · teleport after -1 s
- RL checkpoints: {"rl_ppo": {"checkpoint": "data/coordination/rl/runs_async/appo_async_s0/latest", "exists": true}}
- Code: `{"sources_sha": "2e0281ea7983d8d2", "files": 81, "tp_code_id": ""}`
- Wall time: 2113.1 s

## Run status

| policy | ok | complete |
|---|---|---|
| forecast_only | 9 | 3 |
| heuristic@lam=500 | 9 | 0 |
| rl_ppo | 9 | 0 |

Common complete blocks (every policy complete, identical population): **0 of 9**

### Failed, incomplete or censored runs (kept visible, excluded from the primary ranking)

| policy | scenario | seed | status | failed_checks | unfinished | teleports | error |
|---|---|---|---|---|---|---|---|
| forecast_only | b6_fireworks_n12000_all_s0_event | 0 | ok | all_in_scope_arrived | 5832 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n12000_all_s0_event | 0 | ok | all_in_scope_arrived | 6828 | 0 |  |
| rl_ppo | b6_fireworks_n12000_all_s0_event | 0 | ok | all_in_scope_arrived | 4833 | 0 |  |
| forecast_only | b6_fireworks_n12000_all_s0_event | 1 | ok | all_in_scope_arrived | 5735 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n12000_all_s0_event | 1 | ok | all_in_scope_arrived | 6488 | 0 |  |
| rl_ppo | b6_fireworks_n12000_all_s0_event | 1 | ok | all_in_scope_arrived | 4788 | 0 |  |
| forecast_only | b6_fireworks_n12000_all_s0_event | 2 | ok | all_in_scope_arrived | 5988 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n12000_all_s0_event | 2 | ok | all_in_scope_arrived | 7060 | 0 |  |
| rl_ppo | b6_fireworks_n12000_all_s0_event | 2 | ok | all_in_scope_arrived | 5188 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n3000_all_s0_event | 0 | ok | all_in_scope_arrived | 55 | 0 |  |
| rl_ppo | b6_fireworks_n3000_all_s0_event | 0 | ok | all_in_scope_arrived | 214 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n3000_all_s0_event | 1 | ok | all_in_scope_arrived | 51 | 0 |  |
| rl_ppo | b6_fireworks_n3000_all_s0_event | 1 | ok | all_in_scope_arrived | 256 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n3000_all_s0_event | 2 | ok | all_in_scope_arrived | 60 | 0 |  |
| rl_ppo | b6_fireworks_n3000_all_s0_event | 2 | ok | all_in_scope_arrived | 224 | 0 |  |
| forecast_only | b6_fireworks_n6000_all_s0_event | 0 | ok | all_in_scope_arrived | 693 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n6000_all_s0_event | 0 | ok | all_in_scope_arrived | 568 | 0 |  |
| rl_ppo | b6_fireworks_n6000_all_s0_event | 0 | ok | all_in_scope_arrived | 599 | 0 |  |
| forecast_only | b6_fireworks_n6000_all_s0_event | 1 | ok | all_in_scope_arrived | 670 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n6000_all_s0_event | 1 | ok | all_in_scope_arrived | 905 | 0 |  |
| rl_ppo | b6_fireworks_n6000_all_s0_event | 1 | ok | all_in_scope_arrived | 564 | 0 |  |
| forecast_only | b6_fireworks_n6000_all_s0_event | 2 | ok | all_in_scope_arrived | 844 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n6000_all_s0_event | 2 | ok | all_in_scope_arrived | 978 | 0 |  |
| rl_ppo | b6_fireworks_n6000_all_s0_event | 2 | ok | all_in_scope_arrived | 872 | 0 |  |

## Mean outcomes per policy (common complete blocks)

vehicle_hours = realized time of every in-scope vehicle (participants and background, including insertion and batching waits), scored from the first decision. congested = vehicle-hours on mapped roads at speed <= 50% of the road's free-flow speed; stopped = speed < 0.1 m/s; pending = in-scope vehicles waiting off-network for insertion. Trip times count from the scheduled departure.

(no common complete blocks)

## Paired differences vs `forecast_only` on common complete blocks (policy minus baseline; negative = less)

(no pairs)

## Common-horizon check on every successful block (includes censored runs)

Vehicle-hours through the same drain cap, congested hours and unfinished backlog; a policy that leaves more vehicles unfinished is not better because its completed trips look faster.

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| heuristic@lam=500 | vehicle_hours | 9 | 1.109e+04 | -1641 | -2139 | 1095 | -16.57 | -11.35 | -8.37 | 9 | 0 | 0 | better in every pair |
| rl_ppo | vehicle_hours | 9 | 1.109e+04 | -3245 | -3760 | 2377 | -28.77 | -24.96 | -11.72 | 9 | 0 | 0 | better in every pair |
| heuristic@lam=500 | congested_h_scope | 9 | 7559 | -1606 | -2116 | 1001 | -23.72 | -17.8 | -14.35 | 9 | 0 | 0 | better in every pair |
| rl_ppo | congested_h_scope | 9 | 7559 | -2277 | -3109 | 1428 | -34.19 | -29.08 | -18.82 | 9 | 0 | 0 | better in every pair |
| heuristic@lam=500 | unfinished | 9 | 2196 | 359 | 134 | 453.6 | 13.5 | 16.48 | 35.07 | 1 | 8 | 0 | inconclusive |
| rl_ppo | unfinished | 9 | 2196 | -247.1 | -94 | 520.5 | -12.18 | -14.69 | 3.317 | 5 | 4 | 0 | inconclusive |

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
  "unfinished": 19762,
  "teleports": 0,
  "call_ms_p95_max": 0.061897499989527205
 },
 "heuristic@lam=500": {
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
  "unfinished": 22993,
  "teleports": 0,
  "call_ms_p95_max": 0.38588785004662896
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
  "unfinished": 17538,
  "teleports": 0,
  "call_ms_p95_max": 2.346585350045416
 }
}
```
