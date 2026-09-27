# Coordinated routing benchmark: `heldout` · `heldout_coordinated_routing_fireworks_rule0_wide_p80_c100_7e609aef9c`

> **Synthetic.** SUMO scenarios on the SF citywide network; demand, attendance and behaviour are assumptions.
> Differences are realized in simulation under these assumptions, not measured on real streets.

- Scenarios (3): `b6_fireworks_n12000_all_s0_event`, `b6_fireworks_n3000_all_s0_event`, `b6_fireworks_n6000_all_s0_event`
- Simulation seeds: [0, 1, 2] · policies: `forecast_only`, `heuristic@lam=500`, `rl_ppo`
- Forecast: `model` (data/forecast/experiments/event_patch_v2_main/best.pt) · participation 0.8 (cap 100000) · compliance 1.0 · batch window 60 s · drain cap 8100 s · teleport after -1 s
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
| forecast_only | b6_fireworks_n12000_all_s0_event | 0 | ok | all_in_scope_arrived | 4494 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n12000_all_s0_event | 0 | ok | all_in_scope_arrived | 5251 | 0 |  |
| rl_ppo | b6_fireworks_n12000_all_s0_event | 0 | ok | all_in_scope_arrived | 3361 | 0 |  |
| forecast_only | b6_fireworks_n12000_all_s0_event | 1 | ok | all_in_scope_arrived | 4667 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n12000_all_s0_event | 1 | ok | all_in_scope_arrived | 5437 | 0 |  |
| rl_ppo | b6_fireworks_n12000_all_s0_event | 1 | ok | all_in_scope_arrived | 3990 | 0 |  |
| forecast_only | b6_fireworks_n12000_all_s0_event | 2 | ok | all_in_scope_arrived | 4741 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n12000_all_s0_event | 2 | ok | all_in_scope_arrived | 5504 | 0 |  |
| rl_ppo | b6_fireworks_n12000_all_s0_event | 2 | ok | all_in_scope_arrived | 4501 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n3000_all_s0_event | 0 | ok | all_in_scope_arrived | 64 | 0 |  |
| rl_ppo | b6_fireworks_n3000_all_s0_event | 0 | ok | all_in_scope_arrived | 284 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n3000_all_s0_event | 1 | ok | all_in_scope_arrived | 108 | 0 |  |
| rl_ppo | b6_fireworks_n3000_all_s0_event | 1 | ok | all_in_scope_arrived | 198 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n3000_all_s0_event | 2 | ok | all_in_scope_arrived | 46 | 0 |  |
| rl_ppo | b6_fireworks_n3000_all_s0_event | 2 | ok | all_in_scope_arrived | 201 | 0 |  |
| forecast_only | b6_fireworks_n6000_all_s0_event | 0 | ok | all_in_scope_arrived | 642 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n6000_all_s0_event | 0 | ok | all_in_scope_arrived | 512 | 0 |  |
| rl_ppo | b6_fireworks_n6000_all_s0_event | 0 | ok | all_in_scope_arrived | 1130 | 0 |  |
| forecast_only | b6_fireworks_n6000_all_s0_event | 1 | ok | all_in_scope_arrived | 314 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n6000_all_s0_event | 1 | ok | all_in_scope_arrived | 428 | 0 |  |
| rl_ppo | b6_fireworks_n6000_all_s0_event | 1 | ok | all_in_scope_arrived | 755 | 0 |  |
| forecast_only | b6_fireworks_n6000_all_s0_event | 2 | ok | all_in_scope_arrived | 299 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n6000_all_s0_event | 2 | ok | all_in_scope_arrived | 508 | 0 |  |
| rl_ppo | b6_fireworks_n6000_all_s0_event | 2 | ok | all_in_scope_arrived | 652 | 0 |  |

## Mean outcomes per policy (common complete blocks)

vehicle_hours = realized time of every in-scope vehicle (participants and background, including insertion and batching waits), scored from the first decision. congested = vehicle-hours on mapped roads at speed <= 50% of the road's free-flow speed; stopped = speed < 0.1 m/s; pending = in-scope vehicles waiting off-network for insertion. Trip times count from the scheduled departure.

(no common complete blocks)

## Paired differences vs `forecast_only` on common complete blocks (policy minus baseline; negative = less)

(no pairs)

## Common-horizon check on every successful block (includes censored runs)

Vehicle-hours through the same drain cap, congested hours and unfinished backlog; a policy that leaves more vehicles unfinished is not better because its completed trips look faster.

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| heuristic@lam=500 | vehicle_hours | 9 | 9137 | -1013 | -1237 | 877.9 | -8.384 | -9.15 | 7.212 | 6 | 3 | 0 | inconclusive |
| rl_ppo | vehicle_hours | 9 | 9137 | -2045 | -1508 | 2154 | -14.61 | -20.59 | 15.35 | 7 | 2 | 0 | inconclusive |
| heuristic@lam=500 | congested_h_scope | 9 | 6140 | -1015 | -1244 | 828.5 | -12.93 | -13.39 | 5.709 | 6 | 3 | 0 | inconclusive |
| rl_ppo | congested_h_scope | 9 | 6140 | -1329 | -1519 | 1111 | -17.03 | -17.77 | 19.56 | 8 | 1 | 0 | inconclusive |
| heuristic@lam=500 | unfinished | 9 | 1684 | 300.1 | 114 | 358.6 | 22.57 | 16.67 | 69.9 | 1 | 8 | 0 | inconclusive |
| rl_ppo | unfinished | 9 | 1684 | -9.444 | 201 | 560.8 | 48.29 | 35.48 | 140.4 | 3 | 6 | 0 | inconclusive |

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
  "unfinished": 15157,
  "teleports": 0,
  "call_ms_p95_max": 0.06905199999209798
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
  "unfinished": 17858,
  "teleports": 0,
  "call_ms_p95_max": 0.38187100005870894
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
  "unfinished": 15072,
  "teleports": 0,
  "call_ms_p95_max": 2.303014650027535
 }
}
```
