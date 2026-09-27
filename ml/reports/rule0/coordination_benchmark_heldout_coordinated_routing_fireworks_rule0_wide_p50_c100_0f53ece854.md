# Coordinated routing benchmark: `heldout` · `heldout_coordinated_routing_fireworks_rule0_wide_p50_c100_0f53ece854`

> **Synthetic.** SUMO scenarios on the SF citywide network; demand, attendance and behaviour are assumptions.
> Differences are realized in simulation under these assumptions, not measured on real streets.

- Scenarios (3): `b6_fireworks_n12000_all_s0_event`, `b6_fireworks_n3000_all_s0_event`, `b6_fireworks_n6000_all_s0_event`
- Simulation seeds: [0, 1, 2] · policies: `forecast_only`, `heuristic@lam=500`, `rl_ppo`
- Forecast: `model` (data/forecast/experiments/event_patch_v2_main/best.pt) · participation 0.5 (cap 100000) · compliance 1.0 · batch window 60 s · drain cap 8100 s · teleport after -1 s
- RL checkpoints: {"rl_ppo": {"checkpoint": "data/coordination/rl/runs_async/appo_async_s0/latest", "exists": true}}
- Code: `{"sources_sha": "2e0281ea7983d8d2", "files": 81, "tp_code_id": ""}`
- Wall time: 2113.1 s

## Run status

| policy | ok | complete |
|---|---|---|
| forecast_only | 9 | 3 |
| heuristic@lam=500 | 9 | 2 |
| rl_ppo | 9 | 0 |

Common complete blocks (every policy complete, identical population): **0 of 9**

### Failed, incomplete or censored runs (kept visible, excluded from the primary ranking)

| policy | scenario | seed | status | failed_checks | unfinished | teleports | error |
|---|---|---|---|---|---|---|---|
| forecast_only | b6_fireworks_n12000_all_s0_event | 0 | ok | all_in_scope_arrived | 4120 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n12000_all_s0_event | 0 | ok | all_in_scope_arrived | 4460 | 0 |  |
| rl_ppo | b6_fireworks_n12000_all_s0_event | 0 | ok | all_in_scope_arrived | 2745 | 0 |  |
| forecast_only | b6_fireworks_n12000_all_s0_event | 1 | ok | all_in_scope_arrived | 4641 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n12000_all_s0_event | 1 | ok | all_in_scope_arrived | 4163 | 0 |  |
| rl_ppo | b6_fireworks_n12000_all_s0_event | 1 | ok | all_in_scope_arrived | 3925 | 0 |  |
| forecast_only | b6_fireworks_n12000_all_s0_event | 2 | ok | all_in_scope_arrived | 3597 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n12000_all_s0_event | 2 | ok | all_in_scope_arrived | 3316 | 0 |  |
| rl_ppo | b6_fireworks_n12000_all_s0_event | 2 | ok | all_in_scope_arrived | 2989 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n3000_all_s0_event | 0 | ok | all_in_scope_arrived | 34 | 0 |  |
| rl_ppo | b6_fireworks_n3000_all_s0_event | 0 | ok | all_in_scope_arrived | 127 | 0 |  |
| rl_ppo | b6_fireworks_n3000_all_s0_event | 1 | ok | all_in_scope_arrived | 159 | 0 |  |
| rl_ppo | b6_fireworks_n3000_all_s0_event | 2 | ok | all_in_scope_arrived | 170 | 0 |  |
| forecast_only | b6_fireworks_n6000_all_s0_event | 0 | ok | all_in_scope_arrived | 253 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n6000_all_s0_event | 0 | ok | all_in_scope_arrived | 324 | 0 |  |
| rl_ppo | b6_fireworks_n6000_all_s0_event | 0 | ok | all_in_scope_arrived | 535 | 0 |  |
| forecast_only | b6_fireworks_n6000_all_s0_event | 1 | ok | all_in_scope_arrived | 157 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n6000_all_s0_event | 1 | ok | all_in_scope_arrived | 407 | 0 |  |
| rl_ppo | b6_fireworks_n6000_all_s0_event | 1 | ok | all_in_scope_arrived | 444 | 0 |  |
| forecast_only | b6_fireworks_n6000_all_s0_event | 2 | ok | all_in_scope_arrived | 155 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n6000_all_s0_event | 2 | ok | all_in_scope_arrived | 405 | 0 |  |
| rl_ppo | b6_fireworks_n6000_all_s0_event | 2 | ok | all_in_scope_arrived | 662 | 0 |  |

## Mean outcomes per policy (common complete blocks)

vehicle_hours = realized time of every in-scope vehicle (participants and background, including insertion and batching waits), scored from the first decision. congested = vehicle-hours on mapped roads at speed <= 50% of the road's free-flow speed; stopped = speed < 0.1 m/s; pending = in-scope vehicles waiting off-network for insertion. Trip times count from the scheduled departure.

(no common complete blocks)

## Paired differences vs `forecast_only` on common complete blocks (policy minus baseline; negative = less)

(no pairs)

## Common-horizon check on every successful block (includes censored runs)

Vehicle-hours through the same drain cap, congested hours and unfinished backlog; a policy that leaves more vehicles unfinished is not better because its completed trips look faster.

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| heuristic@lam=500 | vehicle_hours | 9 | 7148 | -425.7 | 39.16 | 898.5 | 0.5916 | 3.042 | 9.646 | 4 | 5 | 0 | inconclusive |
| rl_ppo | vehicle_hours | 9 | 7148 | -925.8 | 13.16 | 1794 | 3.429 | 0.3636 | 28.1 | 3 | 6 | 0 | inconclusive |
| heuristic@lam=500 | congested_h_scope | 9 | 4528 | -138 | 17.38 | 509.7 | 3.638 | 3.138 | 15.03 | 3 | 6 | 0 | inconclusive |
| rl_ppo | congested_h_scope | 9 | 4528 | -371.6 | 10.13 | 888.4 | 13.95 | 0.5068 | 56.89 | 4 | 5 | 0 | inconclusive |
| heuristic@lam=500 | unfinished | 9 | 1436 | 20.67 | 34 | 262.3 | 56.45 | 18.16 | 161.3 | 2 | 5 | 2 | inconclusive |
| rl_ppo | unfinished | 9 | 1436 | -129.7 | 159 | 623.6 | 92.61 | 48.02 | 327.1 | 3 | 6 | 0 | inconclusive |

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
  "unfinished": 12923,
  "teleports": 0,
  "call_ms_p95_max": 0.0622100000100545
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
  "unfinished": 13109,
  "teleports": 0,
  "call_ms_p95_max": 0.381309499989868
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
  "unfinished": 11756,
  "teleports": 0,
  "call_ms_p95_max": 2.341362400002822
 }
}
```
