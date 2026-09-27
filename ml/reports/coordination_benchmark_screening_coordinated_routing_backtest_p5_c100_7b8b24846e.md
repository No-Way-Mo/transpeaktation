# Coordinated routing benchmark: `screening` · `screening_coordinated_routing_backtest_p5_c100_7b8b24846e`

> **Synthetic.** SUMO scenarios on the SF citywide network; demand, attendance and behaviour are assumptions.
> Differences are realized in simulation under these assumptions, not measured on real streets.

- Scenarios (3): `b3_main_bearrison_arrival_f048_s0_event`, `b3_main_bearrison_departure_f050_s0_event`, `b3_main_bearrison_full_f049_s0_event`
- Simulation seeds: [0, 1] · policies: `forecast_only`, `heuristic`, `heuristic@lam=15`, `heuristic@lam=120`, `batch`, `batch@w=15`, `heuristic@w=60`
- Forecast: `model` (data/forecast/experiments/event_patch_v2_main/best.pt) · participation 0.05 (cap 100000) · compliance 1.0 · batch window 60 s · drain cap 3600 s · teleport after 300 s
- RL checkpoints: {}
- Code: `{"sources_sha": "89aa667e595e8765", "files": 75, "tp_code_id": "f9ad4326a6138ada"}`
- Wall time: 1147.0 s

## Run status

| policy | ok | complete |
|---|---|---|
| batch | 6 | 5 |
| batch@w=15 | 6 | 5 |
| forecast_only | 6 | 6 |
| heuristic | 6 | 5 |
| heuristic@lam=120 | 6 | 6 |
| heuristic@lam=15 | 6 | 5 |
| heuristic@w=60 | 6 | 6 |

Common complete blocks (every policy complete, identical population): **4 of 6**: `b3_main_bearrison_arrival_f048_s0_event` s0, `b3_main_bearrison_arrival_f048_s0_event` s1, `b3_main_bearrison_full_f049_s0_event` s0, `b3_main_bearrison_full_f049_s0_event` s1

### Failed, incomplete or censored runs (kept visible, excluded from the primary ranking)

| policy | scenario | seed | status | failed_checks | unfinished | teleports | error |
|---|---|---|---|---|---|---|---|
| heuristic | b3_main_bearrison_departure_f050_s0_event | 0 | ok | all_in_scope_arrived | 1 | 141 |  |
| batch | b3_main_bearrison_departure_f050_s0_event | 0 | ok | all_in_scope_arrived | 1 | 172 |  |
| batch@w=15 | b3_main_bearrison_departure_f050_s0_event | 0 | ok | all_in_scope_arrived | 1 | 178 |  |
| heuristic@lam=15 | b3_main_bearrison_departure_f050_s0_event | 1 | ok | all_in_scope_arrived | 1 | 184 |  |

## Mean outcomes per policy (common complete blocks)

vehicle_hours = realized time of every in-scope vehicle (participants and background, including insertion and batching waits), scored from the first decision. congested = vehicle-hours on mapped roads at speed <= 50% of the road's free-flow speed; stopped = speed < 0.1 m/s; pending = in-scope vehicles waiting off-network for insertion. Trip times count from the scheduled departure.

| policy | vehicle_hours | congested_h_scope | congested_h_all | stopped_h_scope | pending_h_scope | part_trip_s_mean | part_trip_s_p95 | other_trip_s_mean | other_trip_s_p95 | unfinished | teleports | decided | non_fastest_share | call_ms_p95 | batch_delay_s_mean | forecast_extra_travel_s_mean | wall_s | peak_mem_mb |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| batch | 953.7 | 291.9 | 604 | 218.7 | 0.053 | 526.4 | 1284 | 607 | 1520 | 0 | 25.25 | 178 | 0.036 | 13.71 | 33.82 | 0.014 | 415.5 | 2662 |
| batch@w=15 | 951.8 | 291.6 | 646.6 | 218.5 | 0.049 | 505 | 1251 | 606.7 | 1517 | 0 | 27 | 179.8 | 0.03 | 4.399 | 10.2 | 0.009 | 443 | 2662 |
| forecast_only | 952.8 | 292.9 | 613 | 219.8 | 0.061 | 496.4 | 1251 | 607.5 | 1520 | 0 | 40.5 | 179.5 | 0.06 | 0.059 | 0 | 0.012 | 420.5 | 2642 |
| heuristic | 950.4 | 291.6 | 611.8 | 218.3 | 0.049 | 491.7 | 1242 | 606.5 | 1517 | 0 | 25 | 177 | 0.064 | 0.189 | 0 | 0.014 | 420 | 2636 |
| heuristic@lam=120 | 949.9 | 290.9 | 625.1 | 217.8 | 0.06 | 490.8 | 1240 | 606.2 | 1512 | 0 | 25.5 | 177.5 | 0.072 | 0.181 | 0 | 0.026 | 427.3 | 2638 |
| heuristic@lam=15 | 952.1 | 292.3 | 627.5 | 219.2 | 0.061 | 494.9 | 1249 | 607.2 | 1517 | 0 | 39.5 | 179 | 0.056 | 0.183 | 0 | 0.011 | 434.9 | 2629 |
| heuristic@w=60 | 952.5 | 291 | 599.5 | 218 | 0.048 | 526.5 | 1290 | 606.3 | 1516 | 0 | 20 | 178.8 | 0.072 | 1 | 33.82 | 0.02 | 415.2 | 2636 |

## Paired differences vs `forecast_only` on common complete blocks (policy minus baseline; negative = less)

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| batch | vehicle_hours | 4 | 952.8 | 0.9593 | 1.612 | 1.499 | 0.109 | 0.1726 | 0.2133 | 1 | 3 | 0 | inconclusive |
| batch@w=15 | vehicle_hours | 4 | 952.8 | -1.03 | -0.0712 | 2.221 | -0.1007 | -0.0081 | 0.0354 | 2 | 2 | 0 | inconclusive |
| heuristic | vehicle_hours | 4 | 952.8 | -2.384 | -1.174 | 2.696 | -0.24 | -0.1242 | -0.088 | 4 | 0 | 0 | better in every pair |
| heuristic@lam=120 | vehicle_hours | 4 | 952.8 | -2.933 | -1.99 | 2.659 | -0.3017 | -0.2268 | -0.0901 | 4 | 0 | 0 | better in every pair |
| heuristic@lam=15 | vehicle_hours | 4 | 952.8 | -0.6845 | -0.5906 | 0.7234 | -0.0739 | -0.0591 | 0 | 3 | 0 | 1 | inconclusive |
| heuristic@w=60 | vehicle_hours | 4 | 952.8 | -0.3203 | 0.0941 | 2.211 | -0.0186 | 0.0212 | 0.1745 | 2 | 2 | 0 | inconclusive |
| batch | congested_h_scope | 4 | 292.9 | -1.067 | -0.8968 | 1.245 | -0.3462 | -0.3009 | 0.0823 | 3 | 1 | 0 | inconclusive |
| batch@w=15 | congested_h_scope | 4 | 292.9 | -1.274 | -1.06 | 1.08 | -0.4226 | -0.3642 | -0.073 | 4 | 0 | 0 | better in every pair |
| heuristic | congested_h_scope | 4 | 292.9 | -1.311 | -0.8686 | 1.256 | -0.4308 | -0.2916 | -0.1409 | 4 | 0 | 0 | better in every pair |
| heuristic@lam=120 | congested_h_scope | 4 | 292.9 | -2.012 | -1.543 | 1.085 | -0.6788 | -0.5601 | -0.4367 | 4 | 0 | 0 | better in every pair |
| heuristic@lam=15 | congested_h_scope | 4 | 292.9 | -0.5815 | -0.6474 | 0.4594 | -0.2028 | -0.2181 | 0 | 3 | 0 | 1 | inconclusive |
| heuristic@w=60 | congested_h_scope | 4 | 292.9 | -1.902 | -1.896 | 1.739 | -0.6203 | -0.6183 | -0.1072 | 4 | 0 | 0 | better in every pair |
| batch | congested_h_all | 4 | 613 | -9.028 | -6.612 | 21.05 | -1.187 | -1.329 | 2.788 | 3 | 1 | 0 | inconclusive |
| batch@w=15 | congested_h_all | 4 | 613 | 33.55 | 25.02 | 36.82 | 5.004 | 4.354 | 11.58 | 1 | 3 | 0 | inconclusive |
| heuristic | congested_h_all | 4 | 613 | -1.24 | -1.528 | 21.03 | -0.2158 | -0.3114 | 3.355 | 3 | 1 | 0 | inconclusive |
| heuristic@lam=120 | congested_h_all | 4 | 613 | 12.03 | 11.21 | 18.48 | 2.1 | 1.422 | 6.266 | 2 | 2 | 0 | inconclusive |
| heuristic@lam=15 | congested_h_all | 4 | 613 | 14.43 | 8.804 | 21.03 | 3.044 | 1.783 | 8.988 | 1 | 2 | 1 | inconclusive |
| heuristic@w=60 | congested_h_all | 4 | 613 | -13.48 | -0.4443 | 30.13 | -1.644 | 0.0959 | 1.057 | 2 | 2 | 0 | inconclusive |
| batch | stopped_h_scope | 4 | 219.8 | -1.125 | -0.9353 | 1.325 | -0.5001 | -0.4233 | 0.1082 | 3 | 1 | 0 | inconclusive |
| batch@w=15 | stopped_h_scope | 4 | 219.8 | -1.251 | -1.008 | 1.199 | -0.56 | -0.4607 | -0.031 | 4 | 0 | 0 | better in every pair |
| heuristic | stopped_h_scope | 4 | 219.8 | -1.487 | -1.018 | 1.508 | -0.6635 | -0.4614 | -0.129 | 4 | 0 | 0 | better in every pair |
| heuristic@lam=120 | stopped_h_scope | 4 | 219.8 | -2.031 | -1.512 | 1.196 | -0.9151 | -0.6895 | -0.6003 | 4 | 0 | 0 | better in every pair |
| heuristic@lam=15 | stopped_h_scope | 4 | 219.8 | -0.5795 | -0.6607 | 0.4839 | -0.2657 | -0.2989 | 0 | 3 | 0 | 1 | inconclusive |
| heuristic@w=60 | stopped_h_scope | 4 | 219.8 | -1.802 | -1.784 | 1.683 | -0.8037 | -0.8031 | -0.079 | 4 | 0 | 0 | better in every pair |
| batch | pending_h_scope | 4 | 0.0608 | -0.0078 | -0.0064 | 0.0116 | -5.22 | -7.107 | 14.46 | 3 | 1 | 0 | inconclusive |
| batch@w=15 | pending_h_scope | 4 | 0.0608 | -0.0117 | -0.0074 | 0.0188 | -5.263 | -10.07 | 35.19 | 3 | 1 | 0 | inconclusive |
| heuristic | pending_h_scope | 4 | 0.0608 | -0.0114 | -0.0029 | 0.0229 | -2.777 | -1.49 | 35.19 | 2 | 2 | 0 | inconclusive |
| heuristic@lam=120 | pending_h_scope | 4 | 0.0608 | -0.0006 | -0.0008 | 0.0042 | 6.164 | -0.8021 | 31.48 | 2 | 1 | 1 | inconclusive |
| heuristic@lam=15 | pending_h_scope | 4 | 0.0608 | -0.0001 | 0.0008 | 0.0056 | 9.143 | 3.615 | 37.04 | 1 | 2 | 1 | inconclusive |
| heuristic@w=60 | pending_h_scope | 4 | 0.0608 | -0.0126 | -0.0049 | 0.0193 | -13.02 | -6.385 | 0 | 3 | 0 | 1 | inconclusive |
| batch | part_trip_s_mean | 4 | 496.4 | 29.97 | 31.07 | 7.314 | 5.993 | 6.272 | 6.982 | 0 | 4 | 0 | worse in every pair |
| batch@w=15 | part_trip_s_mean | 4 | 496.4 | 8.583 | 10.87 | 6.594 | 1.69 | 2.219 | 2.557 | 1 | 3 | 0 | inconclusive |
| heuristic | part_trip_s_mean | 4 | 496.4 | -4.718 | -2.533 | 6.714 | -1.025 | -0.5334 | 0.1229 | 3 | 1 | 0 | inconclusive |
| heuristic@lam=120 | part_trip_s_mean | 4 | 496.4 | -5.632 | -3.491 | 6.342 | -1.201 | -0.7182 | -0.1154 | 4 | 0 | 0 | better in every pair |
| heuristic@lam=15 | part_trip_s_mean | 4 | 496.4 | -1.514 | -1.428 | 2.143 | -0.3082 | -0.3169 | 0.1107 | 2 | 1 | 1 | inconclusive |
| heuristic@w=60 | part_trip_s_mean | 4 | 496.4 | 30.09 | 29.97 | 6.809 | 6.012 | 6.022 | 7.02 | 0 | 4 | 0 | worse in every pair |
| batch | part_trip_s_p95 | 4 | 1251 | 33.18 | 32.34 | 28.85 | 2.658 | 2.56 | 5.303 | 0 | 4 | 0 | worse in every pair |
| batch@w=15 | part_trip_s_p95 | 4 | 1251 | 0.2375 | -0.4725 | 34.23 | 0.0535 | -0.0187 | 3.104 | 2 | 2 | 0 | inconclusive |
| heuristic | part_trip_s_p95 | 4 | 1251 | -8.438 | -5.082 | 12.49 | -0.6804 | -0.4015 | 0.1256 | 2 | 2 | 0 | inconclusive |
| heuristic@lam=120 | part_trip_s_p95 | 4 | 1251 | -10.37 | -5.628 | 14.35 | -0.8411 | -0.454 | 0.0628 | 3 | 1 | 0 | inconclusive |
| heuristic@lam=15 | part_trip_s_p95 | 4 | 1251 | -2.131 | 0 | 6.522 | -0.1744 | 0 | 0.248 | 1 | 1 | 2 | inconclusive |
| heuristic@w=60 | part_trip_s_p95 | 4 | 1251 | 39.17 | 44.24 | 26.55 | 3.143 | 3.524 | 5.287 | 0 | 4 | 0 | worse in every pair |
| batch | other_trip_s_mean | 4 | 607.5 | -0.5385 | -0.3624 | 0.6545 | -0.0998 | -0.0654 | 0.0018 | 3 | 1 | 0 | inconclusive |
| batch@w=15 | other_trip_s_mean | 4 | 607.5 | -0.8199 | -0.4995 | 0.7728 | -0.1436 | -0.079 | -0.0495 | 4 | 0 | 0 | better in every pair |
| heuristic | other_trip_s_mean | 4 | 607.5 | -0.995 | -0.6369 | 0.909 | -0.1736 | -0.0958 | -0.0663 | 4 | 0 | 0 | better in every pair |
| heuristic@lam=120 | other_trip_s_mean | 4 | 607.5 | -1.315 | -1.249 | 0.9399 | -0.221 | -0.183 | -0.05 | 4 | 0 | 0 | better in every pair |
| heuristic@lam=15 | other_trip_s_mean | 4 | 607.5 | -0.3435 | -0.167 | 0.4992 | -0.0538 | -0.0314 | 0.0018 | 2 | 1 | 1 | inconclusive |
| heuristic@w=60 | other_trip_s_mean | 4 | 607.5 | -1.165 | -1.024 | 1.011 | -0.2122 | -0.1849 | -0.0407 | 4 | 0 | 0 | better in every pair |
| batch | other_trip_s_p95 | 4 | 1520 | -0.2675 | -0.54 | 2.38 | -0.0167 | -0.0366 | 0.1839 | 2 | 2 | 0 | inconclusive |
| batch@w=15 | other_trip_s_p95 | 4 | 1520 | -2.681 | -3.31 | 5.577 | -0.1759 | -0.2144 | 0.3099 | 3 | 1 | 0 | inconclusive |
| heuristic | other_trip_s_p95 | 4 | 1520 | -3.099 | -2.66 | 4.314 | -0.2044 | -0.172 | 0.1087 | 3 | 1 | 0 | inconclusive |
| heuristic@lam=120 | other_trip_s_p95 | 4 | 1520 | -7.871 | -7.822 | 5.027 | -0.52 | -0.5121 | -0.131 | 4 | 0 | 0 | better in every pair |
| heuristic@lam=15 | other_trip_s_p95 | 4 | 1520 | -3.17 | -1.48 | 4.426 | -0.2055 | -0.0972 | 0 | 3 | 0 | 1 | inconclusive |
| heuristic@w=60 | other_trip_s_p95 | 4 | 1520 | -4.315 | -3.43 | 4.27 | -0.2871 | -0.2264 | -0.009 | 4 | 0 | 0 | better in every pair |
| batch | part_route_m_mean | 4 | 4163 | 6.772 | 4.734 | 14.22 | 0.16 | 0.1254 | 0.5506 | 2 | 2 | 0 | inconclusive |
| batch@w=15 | part_route_m_mean | 4 | 4163 | 5.641 | 2.276 | 13.76 | 0.1295 | 0.0603 | 0.5533 | 1 | 3 | 0 | inconclusive |
| heuristic | part_route_m_mean | 4 | 4163 | 8.211 | 3.981 | 12.35 | 0.1898 | 0.1055 | 0.5663 | 2 | 2 | 0 | inconclusive |
| heuristic@lam=120 | part_route_m_mean | 4 | 4163 | 9.321 | 4.524 | 14.05 | 0.2154 | 0.1198 | 0.6416 | 2 | 2 | 0 | inconclusive |
| heuristic@lam=15 | part_route_m_mean | 4 | 4163 | 6.262 | -0.0186 | 12.65 | 0.1378 | -0.0004 | 0.5558 | 2 | 1 | 1 | inconclusive |
| heuristic@w=60 | part_route_m_mean | 4 | 4163 | 8.397 | 4.427 | 11.83 | 0.1949 | 0.1173 | 0.5605 | 1 | 3 | 0 | inconclusive |

## Common-horizon check on every successful block (includes censored runs)

Vehicle-hours through the same drain cap, congested hours and unfinished backlog; a policy that leaves more vehicles unfinished is not better because its completed trips look faster.

| policy | metric | pairs | base_mean | mean_diff | median_diff | std_diff | mean_rel_pct | median_rel_pct | worst_rel_pct | better | worse | tied | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| batch | vehicle_hours | 6 | 1005 | 2.735 | 1.871 | 3.42 | 0.2619 | 0.2132 | 0.8065 | 1 | 5 | 0 | inconclusive |
| batch@w=15 | vehicle_hours | 6 | 1005 | 0.3143 | -0.0712 | 4.161 | 0.0235 | -0.0081 | 0.7236 | 3 | 3 | 0 | inconclusive |
| heuristic | vehicle_hours | 6 | 1005 | -1.157 | -0.9575 | 2.849 | -0.121 | -0.0997 | 0.1702 | 4 | 2 | 0 | inconclusive |
| heuristic@lam=120 | vehicle_hours | 6 | 1005 | -1.902 | -1.286 | 2.607 | -0.1963 | -0.139 | 0.0188 | 4 | 2 | 0 | inconclusive |
| heuristic@lam=15 | vehicle_hours | 6 | 1005 | -0.0108 | -0.0944 | 1.455 | -0.0091 | -0.0108 | 0.2409 | 3 | 1 | 2 | inconclusive |
| heuristic@w=60 | vehicle_hours | 6 | 1005 | 1.83 | 0.8757 | 5.26 | 0.1723 | 0.0962 | 1.082 | 2 | 4 | 0 | inconclusive |
| batch | congested_h_scope | 6 | 307 | -0.0774 | -0.1646 | 2.101 | -0.0409 | -0.0671 | 1.075 | 3 | 3 | 0 | inconclusive |
| batch@w=15 | congested_h_scope | 6 | 307 | -0.5301 | -1.06 | 2.547 | -0.185 | -0.3642 | 1.288 | 5 | 1 | 0 | inconclusive |
| heuristic | congested_h_scope | 6 | 307 | -0.6904 | -0.4636 | 1.384 | -0.2326 | -0.1686 | 0.2627 | 4 | 2 | 0 | inconclusive |
| heuristic@lam=120 | congested_h_scope | 6 | 307 | -1.354 | -1.349 | 1.323 | -0.4565 | -0.4632 | 0.0308 | 5 | 1 | 0 | inconclusive |
| heuristic@lam=15 | congested_h_scope | 6 | 307 | -0.051 | -0.2211 | 1.1 | -0.0352 | -0.0804 | 0.5998 | 3 | 1 | 2 | inconclusive |
| heuristic@w=60 | congested_h_scope | 6 | 307 | -0.2784 | -1.235 | 4.228 | -0.1162 | -0.3837 | 2.368 | 5 | 1 | 0 | inconclusive |
| batch | unfinished | 6 | 0 | 0.1667 | 0 | 0.4082 |  |  |  | 0 | 1 | 5 | inconclusive |
| batch@w=15 | unfinished | 6 | 0 | 0.1667 | 0 | 0.4082 |  |  |  | 0 | 1 | 5 | inconclusive |
| heuristic | unfinished | 6 | 0 | 0.1667 | 0 | 0.4082 |  |  |  | 0 | 1 | 5 | inconclusive |
| heuristic@lam=120 | unfinished | 6 | 0 | 0 | 0 | 0 |  |  |  | 0 | 0 | 6 | inconclusive |
| heuristic@lam=15 | unfinished | 6 | 0 | 0.1667 | 0 | 0.4082 |  |  |  | 0 | 1 | 5 | inconclusive |
| heuristic@w=60 | unfinished | 6 | 0 | 0 | 0 | 0 |  |  |  | 0 | 0 | 6 | inconclusive |

## Ranking by paired total vehicle-hours (common complete blocks)

1. `heuristic@lam=120`: -2.933 veh-h (-0.30%) vs forecast_only (better in every pair)
2. `heuristic`: -2.384 veh-h (-0.24%) vs forecast_only (better in every pair)
3. `batch@w=15`: -1.030 veh-h (-0.10%) vs forecast_only (inconclusive)
4. `heuristic@lam=15`: -0.685 veh-h (-0.07%) vs forecast_only (inconclusive)
5. `heuristic@w=60`: -0.320 veh-h (-0.02%) vs forecast_only (inconclusive)
6. `forecast_only`: +0.000 veh-h (+0.00%) vs forecast_only
7. `batch`: +0.959 veh-h (+0.11%) vs forecast_only (inconclusive)

**Best eligible policy on this suite: `heuristic@lam=120`**
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
  "heuristic": {
   "vehicle_hours_reduction_pct": 0.23996801585703048,
   "vehicle_hours_mean_diff": -2.3842361111110506,
   "blocks_better": 4.0,
   "blocks_worse": 0.0,
   "consistent_reduction": true,
   "congested_scope_reduction_pct": 0.4308400849247127,
   "background_mean_change_pct": -0.17361590598246934,
   "participant_p95_change_pct": -0.6804282555752625,
   "meets_vehicle_hours_target": false,
   "lower_congestion": true,
   "background_ok": true,
   "participant_p95_ok": true
  },
  "heuristic@lam=15": {
   "vehicle_hours_reduction_pct": 0.07385436425756146,
   "vehicle_hours_mean_diff": -0.6845138888888584,
   "blocks_better": 3.0,
   "blocks_worse": 0.0,
   "consistent_reduction": true,
   "congested_scope_reduction_pct": 0.20280494543232205,
   "background_mean_change_pct": -0.05380740559686632,
   "participant_p95_change_pct": -0.17442400095239763,
   "meets_vehicle_hours_target": false,
   "lower_congestion": true,
   "background_ok": true,
   "participant_p95_ok": true
  },
  "heuristic@lam=120": {
   "vehicle_hours_reduction_pct": 0.3016753036483105,
   "vehicle_hours_mean_diff": -2.932916666666614,
   "blocks_better": 4.0,
   "blocks_worse": 0.0,
   "consistent_reduction": true,
   "congested_scope_reduction_pct": 0.6787793133735622,
   "background_mean_change_pct": -0.22099723632116183,
   "participant_p95_change_pct": -0.8411320253083124,
   "meets_vehicle_hours_target": false,
   "lower_congestion": true,
   "background_ok": true,
   "participant_p95_ok": true
  },
  "batch": {
   "vehicle_hours_reduction_pct": -0.10900948254147352,
   "vehicle_hours_mean_diff": 0.9593055555554031,
   "blocks_better": 1.0,
   "blocks_worse": 3.0,
   "consistent_reduction": false,
   "congested_scope_reduction_pct": 0.3462094724610246,
   "background_mean_change_pct": -0.09983355116438639,
   "participant_p95_change_pct": 2.6581213728121793,
   "meets_vehicle_hours_target": false,
   "lower_congestion": true,
   "background_ok": true,
   "participant_p95_ok": true
  },
  "batch@w=15": {
   "vehicle_hours_reduction_pct": 0.10068446553635053,
   "vehicle_hours_mean_diff": -1.0304861111111165,
   "blocks_better": 2.0,
   "blocks_worse": 2.0,
   "consistent_reduction": false,
   "congested_scope_reduction_pct": 0.4225785565449335,
   "background_mean_change_pct": -0.14357482325007226,
   "participant_p95_change_pct": 0.0534661395541316,
   "meets_vehicle_hours_target": false,
   "lower_congestion": true,
   "background_ok": true,
   "participant_p95_ok": true
  },
  "heuristic@w=60": {
   "vehicle_hours_reduction_pct": 0.018627345010642365,
   "vehicle_hours_mean_diff": -0.3202777777779602,
   "blocks_better": 2.0,
   "blocks_worse": 2.0,
   "consistent_reduction": false,
   "congested_scope_reduction_pct": 0.6202697220196738,
   "background_mean_change_pct": -0.2122177862612032,
   "participant_p95_change_pct": 3.1427668223655405,
   "meets_vehicle_hours_target": false,
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
 "batch": {
  "runs": 6,
  "ok": 6,
  "complete": 5,
  "unavailable": 0,
  "failed": 0,
  "invalid_routes": 0,
  "selector_failures": 0,
  "unchosen_fallbacks": 0,
  "dropped_trips": 0,
  "readback_mismatch": 0,
  "unfinished": 1,
  "teleports": 341,
  "call_ms_p95_max": 16.280646900025868
 },
 "batch@w=15": {
  "runs": 6,
  "ok": 6,
  "complete": 5,
  "unavailable": 0,
  "failed": 0,
  "invalid_routes": 0,
  "selector_failures": 0,
  "unchosen_fallbacks": 0,
  "dropped_trips": 0,
  "readback_mismatch": 0,
  "unfinished": 1,
  "teleports": 362,
  "call_ms_p95_max": 5.33128560001614
 },
 "forecast_only": {
  "runs": 6,
  "ok": 6,
  "complete": 6,
  "unavailable": 0,
  "failed": 0,
  "invalid_routes": 0,
  "selector_failures": 0,
  "unchosen_fallbacks": 0,
  "dropped_trips": 0,
  "readback_mismatch": 0,
  "unfinished": 0,
  "teleports": 370,
  "call_ms_p95_max": 0.0651399999583191
 },
 "heuristic": {
  "runs": 6,
  "ok": 6,
  "complete": 5,
  "unavailable": 0,
  "failed": 0,
  "invalid_routes": 0,
  "selector_failures": 0,
  "unchosen_fallbacks": 0,
  "dropped_trips": 0,
  "readback_mismatch": 0,
  "unfinished": 1,
  "teleports": 364,
  "call_ms_p95_max": 0.2003059000230678
 },
 "heuristic@lam=120": {
  "runs": 6,
  "ok": 6,
  "complete": 6,
  "unavailable": 0,
  "failed": 0,
  "invalid_routes": 0,
  "selector_failures": 0,
  "unchosen_fallbacks": 0,
  "dropped_trips": 0,
  "readback_mismatch": 0,
  "unfinished": 0,
  "teleports": 370,
  "call_ms_p95_max": 0.19469150001327756
 },
 "heuristic@lam=15": {
  "runs": 6,
  "ok": 6,
  "complete": 5,
  "unavailable": 0,
  "failed": 0,
  "invalid_routes": 0,
  "selector_failures": 0,
  "unchosen_fallbacks": 0,
  "dropped_trips": 0,
  "readback_mismatch": 0,
  "unfinished": 1,
  "teleports": 464,
  "call_ms_p95_max": 0.19130500006383494
 },
 "heuristic@w=60": {
  "runs": 6,
  "ok": 6,
  "complete": 6,
  "unavailable": 0,
  "failed": 0,
  "invalid_routes": 0,
  "selector_failures": 0,
  "unchosen_fallbacks": 0,
  "dropped_trips": 0,
  "readback_mismatch": 0,
  "unfinished": 0,
  "teleports": 290,
  "call_ms_p95_max": 1.0979366500350805
 }
}
```
