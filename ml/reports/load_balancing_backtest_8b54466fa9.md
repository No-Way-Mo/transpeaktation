# Load-balancing backtest `8b54466fa9`

> Provenance: dev + heldout_30 ran on node A (c8a.48xlarge), heldout_5 on node B (c8a.24xlarge), libsumo backend, identical code (sources 89aa667e595e8765), SUMO 1.27.1, forecaster and scenarios. Their experiment ids differ only because the first version of the id included the worker count (fixed); this report was assembled from both nodes' saved results (`data/coordination/backtest/backtest_combined.json`). Selection frozen from dev results at 2026-09-27T02:08:26Z. `heuristic@lam=120` was a 5%-only held-out candidate, so the 30% held-out section has no headline row by design.

> **Synthetic.** Closed-loop SUMO replays of SF event scenarios; demand, attendance, participation and compliance are assumptions. Results support claims about these simulated scenarios, not observed SF outcomes.

Question: with the same scheduled trips, event, road network and background traffic, does coordinated route selection reduce total travel burden and time in congested traffic versus independent forecast-based routing (`forecast_only`)?

Percentages below are mean paired changes vs `forecast_only` over common complete blocks (negative = less time/congestion = better). congested = vehicle-hours at speed <= 50% of free-flow on mapped roads.

## Phase 0: sanity and repeatability (one development block)

| policy | status | complete | vehicle_hours | congested_h_scope | decided | non_fastest_share | teleports | unfinished | wall_s | peak_mem_mb |
|---|---|---|---|---|---|---|---|---|---|---|
| forecast_only | ok | True | 878.5 | 275 | 139 | 0.07194 | 22 | 0 | 338.3 | 2573 |
| forecast_only@rep=1 | ok | True | 878.5 | 275 | 139 | 0.07194 | 22 | 0 | 357.2 | 2586 |
| heuristic@lam=0 | ok | True | 878.5 | 275 | 139 | 0.07194 | 22 | 0 | 340.4 | 2588 |
| heuristic | ok | True | 877.3 | 274.4 | 139 | 0.07914 | 20 | 0 | 342 | 2580 |
| batch | ok | True | 880.4 | 275.2 | 141 | 0.06383 | 19 | 0 | 342.1 | 2611 |

- Repeatability: same policy twice differs by +0.0000 veh-h (+0.0000%). Differences between policies smaller than this are noise.
- lam=0 sanity: heuristic without the load penalty vs forecast_only differs by +0.0000 veh-h (expected ~0 up to tie-breaking).

## Phase 1: screening at the base participation (validation split)

| policy | blocks | vehicle_hours % | veh-h diff | better/worse | congested_h_scope % | congested_h_all % | other_trip_s_mean % | part_trip_s_p95 % |
|---|---|---|---|---|---|---|---|---|
| heuristic | 4 | -0.24 | -2.384 | 4/0 | -0.4308 | -0.2158 | -0.1736 | -0.6804 |
| heuristic@lam=15 | 4 | -0.07385 | -0.6845 | 3/0 | -0.2028 | 3.044 | -0.05381 | -0.1744 |
| heuristic@lam=120 | 4 | -0.3017 | -2.933 | 4/0 | -0.6788 | 2.1 | -0.221 | -0.8411 |
| batch | 4 | 0.109 | 0.9593 | 1/3 | -0.3462 | -1.187 | -0.09983 | 2.658 |
| batch@w=15 | 4 | -0.1007 | -1.03 | 2/2 | -0.4226 | 5.004 | -0.1436 | 0.05347 |
| heuristic@w=60 | 4 | -0.01863 | -0.3203 | 2/2 | -0.6203 | -1.644 | -0.2122 | 3.143 |

`heuristic@w=60` is the equal-timing control for `batch` (same 60 s release groups, sequential heuristic): batch minus it isolates joint optimisation from batching delay.

## Phase 2a: adoption (heuristic and batch vs forecast_only)

| participation (of eligible) | participants / in-scope | policy | blocks | vehicle_hours % | veh-h diff | better/worse | congested_h_scope % | congested_h_all % | other_trip_s_mean % | part_trip_s_p95 % |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.05 | 0.0169 | heuristic | 4 | -0.24 | -2.384 | 4/0 | -0.4308 | -0.2158 | -0.1736 | -0.6804 |
| 0.05 | 0.0169 | batch | 4 | 0.109 | 0.9593 | 1/3 | -0.3462 | -1.187 | -0.09983 | 2.658 |
| 0.15 | 0.0519 | heuristic | 4 | 0.2093 | 2.089 | 2/2 | 0.4982 | -1.36 | 0.1658 | 0.6681 |
| 0.15 | 0.0519 | batch | 4 | 0.8758 | 8.545 | 0/4 | 0.3459 | -0.7065 | 0.1203 | 1.626 |
| 0.3 | 0.1028 | heuristic | 4 | 0.04459 | 0.3853 | 1/3 | 0.08176 | -0.6879 | 0.02751 | -0.3906 |
| 0.3 | 0.1028 | batch | 4 | 1.964 | 18.83 | 0/4 | 1.095 | 1.575 | 0.3055 | 3.65 |

## Phase 2b: compliance at 15% participation

| compliance | policy | blocks | vehicle_hours % | veh-h diff | better/worse | congested_h_scope % | congested_h_all % | other_trip_s_mean % | part_trip_s_p95 % |
|---|---|---|---|---|---|---|---|---|---|
| 0.75 | heuristic | 3 | 0.04998 | 0.4687 | 1/2 | 0.09211 | -1.69 | 0.05383 | -0.01184 |
| 0.75 | batch | 3 | 0.8944 | 8.197 | 0/3 | 0.1875 | -0.2085 | 0.1587 | 1.989 |
| 0.5 | heuristic | 4 | 0.05426 | 0.4501 | 1/3 | 0.1076 | -2.06 | 0.03538 | 0.8996 |
| 0.5 | batch | 4 | 0.96 | 9.312 | 0/4 | 0.5329 | 8.525 | 0.1487 | 2.424 |

## Frozen selection (from development data only)

```json
{
 "best": "heuristic@lam=120",
 "challenger": null,
 "candidates": [
  "heuristic",
  "heuristic@lam=120",
  "batch"
 ],
 "eligible": [
  "heuristic@lam=120",
  "heuristic@w=60",
  "forecast_only"
 ],
 "dev_adoption_mean_rel_pct": {
  "heuristic": {
   "0.05": -0.23996801585703048,
   "0.15": 0.20933443704336469,
   "0.3": 0.044588413989632016
  },
  "batch": {
   "0.05": 0.10900948254147352,
   "0.15": 0.8757733658448663,
   "0.3": 1.9638483975717205
  }
 },
 "notes": [],
 "rule": "best = lowest mean paired vehicle-hours among strictly complete held-out candidates on common complete screening blocks; challenger = best candidate of the other family; decided from dev results only",
 "frozen_at": "2026-09-27T02:08:26Z"
}
```

## Phase 3: held-out (5% participation, test split, 6 scenario families x seeds [0, 1, 2])

Selected on development data (best, challenger):

| policy | blocks | vehicle_hours % | veh-h diff | better/worse | congested_h_scope % | congested_h_all % | other_trip_s_mean % | part_trip_s_p95 % |
|---|---|---|---|---|---|---|---|---|
| heuristic@lam=120 | 13 | -0.01147 | 0.1741 | 7/6 | -0.1742 | 0.4077 | -0.01692 | 1.126 |

Development targets:

```json
{
 "heuristic@lam=120": {
  "vehicle_hours_reduction_pct": 0.01146626447404486,
  "vehicle_hours_mean_diff": 0.17414529914530108,
  "blocks_better": 7.0,
  "blocks_worse": 6.0,
  "consistent_reduction": false,
  "congested_scope_reduction_pct": 0.1741817169685684,
  "background_mean_change_pct": -0.016918152762952568,
  "participant_p95_change_pct": 1.1256420118527108,
  "meets_vehicle_hours_target": false,
  "lower_congestion": true,
  "background_ok": true,
  "participant_p95_ok": true
 }
}
```

Other pre-declared held-out candidates (not selected; listed for completeness, never used to pick a winner):

| policy | blocks | vehicle_hours % | veh-h diff | better/worse | congested_h_scope % | congested_h_all % | other_trip_s_mean % | part_trip_s_p95 % |
|---|---|---|---|---|---|---|---|---|
| heuristic | 13 | -0.01538 | 0.1703 | 6/6 | -0.07918 | -0.3055 | -0.01828 | 1.206 |
| batch | 13 | 0.2263 | 2.365 | 3/10 | -0.3491 | 0.6268 | -0.05225 | 1.531 |

## Phase 3: held-out (30% participation, test split, 6 scenario families x seeds [0, 1, 2])

Other pre-declared held-out candidates (not selected; listed for completeness, never used to pick a winner):

| policy | blocks | vehicle_hours % | veh-h diff | better/worse | congested_h_scope % | congested_h_all % | other_trip_s_mean % | part_trip_s_p95 % |
|---|---|---|---|---|---|---|---|---|
| heuristic | 15 | 0.03946 | 0.7652 | 4/11 | 0.2652 | 0.1529 | 0.0008483 | 0.1496 |
| batch | 15 | 2.153 | 17.82 | 0/15 | 1.706 | 1.555 | 0.3048 | 2.556 |

## Mechanism: how much the coordinator actually changes

`forecast_only` also shows a small non-fastest share (near-ties broken by the seeded hash). A policy can only move congestion through the drivers it diverts; compare its non-fastest share with the baseline's.

| experiment | policy | participants / in-scope | single-option share | non-fastest share of decided | predicted extra s per decision | batch wait s | congested share of vehicle time |
|---|---|---|---|---|---|---|---|
| screen | batch | 0.0169 | 0.324 | 0.034 | 0.013 | 33.7 | 0.305 |
| screen | forecast_only | 0.0169 | 0.315 | 0.066 | 0.013 | 0 | 0.306 |
| screen | heuristic | 0.0169 | 0.321 | 0.067 | 0.017 | 0 | 0.306 |
| screen | heuristic@lam=120 | 0.0169 | 0.319 | 0.072 | 0.025 | 0 | 0.305 |
| adopt_30 | batch | 0.1028 | 0.304 | 0.058 | 0.049 | 31.1 | 0.29 |
| adopt_30 | forecast_only | 0.1028 | 0.303 | 0.055 | 0.013 | 0 | 0.292 |
| adopt_30 | heuristic | 0.1028 | 0.302 | 0.077 | 0.058 | 0 | 0.293 |
| heldout_5 | batch | 0.0162 | 0.327 | 0.029 | 0.015 | 33.5 | 0.216 |
| heldout_5 | forecast_only | 0.0162 | 0.329 | 0.052 | 0.012 | 0 | 0.217 |
| heldout_5 | heuristic | 0.0162 | 0.33 | 0.054 | 0.02 | 0 | 0.216 |
| heldout_5 | heuristic@lam=120 | 0.0162 | 0.329 | 0.063 | 0.035 | 0 | 0.216 |
| heldout_30 | batch | 0.0996 | 0.325 | 0.046 | 0.035 | 31.5 | 0.209 |
| heldout_30 | forecast_only | 0.0996 | 0.325 | 0.055 | 0.012 | 0 | 0.21 |
| heldout_30 | heuristic | 0.0996 | 0.326 | 0.065 | 0.043 | 0 | 0.211 |

## Experiment reports

- profile: [coordination_benchmark_profile_coordinated_routing_backtest_p5_c100_9c3fe2e9a0.md](coordination_benchmark_profile_coordinated_routing_backtest_p5_c100_9c3fe2e9a0.md) · 1 complete blocks · best `heuristic`
- screen: [coordination_benchmark_screening_coordinated_routing_backtest_p5_c100_7b8b24846e.md](coordination_benchmark_screening_coordinated_routing_backtest_p5_c100_7b8b24846e.md) · 4 complete blocks · best `heuristic@lam=120`
- adopt_15: [coordination_benchmark_screening_coordinated_routing_backtest_p15_c100_d22d7f0174.md](coordination_benchmark_screening_coordinated_routing_backtest_p15_c100_d22d7f0174.md) · 4 complete blocks · best `None`
- adopt_30: [coordination_benchmark_screening_coordinated_routing_backtest_p30_c100_7159af54b0.md](coordination_benchmark_screening_coordinated_routing_backtest_p30_c100_7159af54b0.md) · 4 complete blocks · best `forecast_only`
- comply_75: [coordination_benchmark_screening_coordinated_routing_backtest_p15_c75_ca00912e54.md](coordination_benchmark_screening_coordinated_routing_backtest_p15_c75_ca00912e54.md) · 3 complete blocks · best `None`
- comply_50: [coordination_benchmark_screening_coordinated_routing_backtest_p15_c50_332d08c687.md](coordination_benchmark_screening_coordinated_routing_backtest_p15_c50_332d08c687.md) · 4 complete blocks · best `forecast_only`
- heldout_5: [coordination_benchmark_heldout_coordinated_routing_backtest_p5_c100_8fd691a3e8.md](coordination_benchmark_heldout_coordinated_routing_backtest_p5_c100_8fd691a3e8.md) · 13 complete blocks · best `None`
- heldout_30: [coordination_benchmark_heldout_coordinated_routing_backtest_p30_c100_0b3d9265c2.md](coordination_benchmark_heldout_coordinated_routing_backtest_p30_c100_0b3d9265c2.md) · 15 complete blocks · best `None`

## Recommendation

No measurable held-out reduction: `heuristic@lam=120` (heldout_5) changed total vehicle time by -0.011% (+0.17 veh-h, better in 7.0 / worse in 6.0 blocks). Retain independent routing as the default; see the mechanism table for why.

## Limitations

- One held-out event group (Portola) and one development group (Bearrison): families are not independent event types; uncertainty is broad.
- Participants are a small share of all in-scope vehicles (see adoption table); full compliance is a controlled setting, not a deployment assumption.
- Teleports are allowed after the configured time and counted (run CSVs); they can relieve simulated gridlock.
- RL policies are not in this matrix unless listed; see the RL benchmark for them.
