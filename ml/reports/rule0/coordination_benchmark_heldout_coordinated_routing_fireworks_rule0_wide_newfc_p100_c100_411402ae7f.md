# Coordinated routing benchmark: `heldout` · `heldout_coordinated_routing_fireworks_rule0_wide_newfc_p100_c100_411402ae7f`

> **Synthetic.** SUMO scenarios on the SF citywide network; demand, attendance and behaviour are assumptions.
> Differences are realized in simulation under these assumptions, not measured on real streets.

- Scenarios (3): `b6_fireworks_n12000_all_s0_event`, `b6_fireworks_n3000_all_s0_event`, `b6_fireworks_n6000_all_s0_event`
- Simulation seeds: [0, 1, 2] · policies: `forecast_only`, `heuristic@lam=500`, `rl_ppo`
- Forecast: `model` (data/forecast/experiments/event_patch_x_all/best.pt) · participation 1.0 (cap 100000) · compliance 1.0 · batch window 60 s · drain cap 8100 s · teleport after -1 s
- RL checkpoints: {"rl_ppo": {"checkpoint": "data/coordination/rl/runs_async/appo_async_s0/latest", "exists": true}}
- Code: `{"sources_sha": "d0820cdea302d298", "files": 82, "tp_code_id": ""}`
- Wall time: 3184.8 s

## Run status

| policy | ok | complete |
|---|---|---|
| forecast_only | 9 | 3 |
| heuristic@lam=500 | 9 | 1 |
| rl_ppo | 9 | 2 |

Common complete blocks (every policy complete, identical population): **0 of 9**

### Failed, incomplete or censored runs (kept visible, excluded from the primary ranking)

| policy | scenario | seed | status | failed_checks | unfinished | teleports | error |
|---|---|---|---|---|---|---|---|
| forecast_only | b6_fireworks_n12000_all_s0_event | 0 | ok | all_in_scope_arrived | 4457 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n12000_all_s0_event | 0 | ok | all_in_scope_arrived | 6452 | 0 |  |
| rl_ppo | b6_fireworks_n12000_all_s0_event | 0 | ok | all_in_scope_arrived | 4772 | 0 |  |
| forecast_only | b6_fireworks_n12000_all_s0_event | 1 | ok | all_in_scope_arrived | 5397 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n12000_all_s0_event | 1 | ok | all_in_scope_arrived | 5709 | 0 |  |
| rl_ppo | b6_fireworks_n12000_all_s0_event | 1 | ok | all_in_scope_arrived | 3500 | 0 |  |
| forecast_only | b6_fireworks_n12000_all_s0_event | 2 | ok | all_in_scope_arrived | 5912 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n12000_all_s0_event | 2 | ok | all_in_scope_arrived | 4906 | 0 |  |
| rl_ppo | b6_fireworks_n12000_all_s0_event | 2 | ok | all_in_scope_arrived | 4263 | 0 |  |
| rl_ppo | b6_fireworks_n3000_all_s0_event | 0 | ok | all_in_scope_arrived | 25 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n3000_all_s0_event | 1 | ok | all_in_scope_arrived | 49 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n3000_all_s0_event | 2 | ok | all_in_scope_arrived | 65 | 0 |  |
| forecast_only | b6_fireworks_n6000_all_s0_event | 0 | ok | all_in_scope_arrived | 235 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n6000_all_s0_event | 0 | ok | all_in_scope_arrived | 320 | 0 |  |
| rl_ppo | b6_fireworks_n6000_all_s0_event | 0 | ok | all_in_scope_arrived | 806 | 0 |  |
| forecast_only | b6_fireworks_n6000_all_s0_event | 1 | ok | all_in_scope_arrived | 112 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n6000_all_s0_event | 1 | ok | all_in_scope_arrived | 144 | 0 |  |
| rl_ppo | b6_fireworks_n6000_all_s0_event | 1 | ok | all_in_scope_arrived | 382 | 0 |  |
| forecast_only | b6_fireworks_n6000_all_s0_event | 2 | ok | all_in_scope_arrived | 97 | 0 |  |
| heuristic@lam=500 | b6_fireworks_n6000_all_s0_event | 2 | ok | all_in_scope_arrived | 57 | 0 |  |
| rl_ppo | b6_fireworks_n6000_all_s0_event | 2 | ok | all_in_scope_arrived | 717 | 0 |  |

## Mean outcomes per policy (common complete blocks)

vehicle_hours = realized time of every in-scope vehicle (participants and background, including insertion and batching waits), scored from the first decision. congested = vehicle-hours on mapped roads at speed <= 50% of the road's free-flow speed; stopped = speed < 0.1 m/s; pending = in-scope vehicles waiting off-network for insertion. Trip times count from the scheduled departure.

(no common complete blocks)

## Paired differences vs `forecast_only` on common complete blocks (policy minus baseline; negative = less)

(no pairs)

## Common-horizon check on every successful block (includes censored runs)

Vehicle-hours through the same drain cap, congested hours and unfinished backlog; a policy that leaves more vehicles unfinished is not better because its completed trips look faster.

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| heuristic@lam=500 | vehicle_hours | 9 | 9776 | -1670 | -1643 | 1698 | -17.28 | -15.88 | -3.699 | 9 | 0 | 0 | better in every pair |
| rl_ppo | vehicle_hours | 9 | 9776 | -2230 | -1504 | 2218 | -22.11 | -23.66 | -15.52 | 9 | 0 | 0 | better in every pair |
| heuristic@lam=500 | congested_h_scope | 9 | 6513 | -1420 | -1622 | 1073 | -25.73 | -22.55 | -10.59 | 9 | 0 | 0 | better in every pair |
| rl_ppo | congested_h_scope | 9 | 6513 | -1461 | -1440 | 1055 | -30.74 | -31.49 | -13.66 | 9 | 0 | 0 | better in every pair |
| heuristic@lam=500 | unfinished | 9 | 1801 | 165.8 | 49 | 779.3 | 9.505 | 17.18 | 44.76 | 2 | 6 | 1 | inconclusive |
| rl_ppo | unfinished | 9 | 1801 | -193.9 | 25 | 926.2 | 177.9 | 124.1 | 639.2 | 2 | 5 | 2 | inconclusive |

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
  "unfinished": 16210,
  "teleports": 0,
  "call_ms_p95_max": 0.07666075021006691
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
  "unfinished": 17702,
  "teleports": 0,
  "call_ms_p95_max": 0.5066115001795879
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
  "unfinished": 14465,
  "teleports": 0,
  "call_ms_p95_max": 2.757679000023926
 }
}
```
