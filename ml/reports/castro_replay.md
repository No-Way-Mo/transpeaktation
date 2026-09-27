# Routing replay: Castro Street Fair 2026

Generated 2026-09-26T12:09:25+00:00 by `python -m eventsim replay --event castro`.

**Simulated outcomes.** Each held-out test scenario is re-simulated once per policy with identical demand, restrictions and seed; 30% of trips (the same vehicles in every policy) are routed by the policy, at departure and at each new 10-min bucket. Route choices change congestion, so every number below comes from its own simulation, not from re-scoring paths on a fixed trace. Durations are actual simulated vehicle traversal times.

| run_id | policy | mean_duration_probe_s | mean_timeloss_probe_s | mean_duration_nonprobe_s | mean_duration_all_s | total_timeloss_veh_h | arrived | unfinished | unfinished_probe | teleports | runtime_s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| f005_s0_ev | event_rule | 335.7 | 138.2 | 339.9 | 338.6 | 313.0 | 7804 | 0 | 0 | 12 | 450.1 |
| f005_s0_ev | learned | 323.5 | 131.0 | 340.6 | 335.4 | 309.4 | 7804 | 0 | 0 | 7 | 616.8 |
| f005_s0_ev | no_info | 339.6 | 150.9 | 340.7 | 340.4 | 322.5 | 7804 | 0 | 0 | 28 | 445.7 |
| f005_s0_ev | persistence | 335.1 | 138.3 | 340.3 | 338.7 | 313.7 | 7804 | 0 | 0 | 8 | 450.5 |
| f009_s0_ev | event_rule | 308.5 | 121.9 | 306.0 | 306.8 | 343.0 | 9788 | 0 | 0 | 20 | 458.0 |
| f009_s0_ev | learned | 297.7 | 115.8 | 306.6 | 303.9 | 338.9 | 9788 | 0 | 0 | 22 | 619.1 |
| f009_s0_ev | no_info | 308.3 | 130.9 | 305.2 | 306.1 | 348.6 | 9788 | 0 | 0 | 17 | 446.0 |
| f009_s0_ev | persistence | 307.9 | 123.1 | 305.6 | 306.3 | 343.2 | 9788 | 0 | 0 | 18 | 457.3 |
| f010_s0_ev | event_rule | 295.7 | 108.9 | 301.8 | 300.0 | 417.4 | 12997 | 0 | 0 | 27 | 471.0 |
| f010_s0_ev | learned | 286.9 | 104.4 | 301.6 | 297.2 | 411.8 | 12997 | 0 | 0 | 15 | 622.2 |
| f010_s0_ev | no_info | 295.6 | 117.1 | 301.7 | 299.9 | 425.2 | 12997 | 0 | 0 | 17 | 468.2 |
| f010_s0_ev | persistence | 293.5 | 108.5 | 301.6 | 299.2 | 415.8 | 12997 | 0 | 0 | 20 | 472.6 |

## Relative to persistence routing (probe mean duration)

- no_info: probes +0.7% (per run: +1.3%, +0.1%, +0.7%); all vehicles +0.2%
- event_rule: probes +0.4% (per run: +0.2%, +0.2%, +0.7%); all vehicles +0.1%
- learned: probes -3.0% (per run: -3.5%, -3.3%, -2.3%); all vehicles -0.8%

Negative = faster than persistence. Results vary by scenario and include runs where a policy is worse.
