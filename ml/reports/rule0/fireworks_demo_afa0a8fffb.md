# July 4 fireworks exodus on our network `afa0a8fffb`

> **Synthetic.** The demo's cohort (`demo/sumo/kit.py` v3, seed 42: 1000 app users) plus N assumed crowd cars leaving the seven viewing sites 21:45-22:45, rebuilt on net_v3 (`eventsim/fireworks_demo.py`). Event context: PredictHQ 300,000 expected attendance, show 21:30-21:45. No measured July 4 traffic exists.

Everything is compared at the same fixed horizon (01:00): vehicle_hours = time of every vehicle up to 01:00 (finished or not), arrived = vehicles that reached their destination by 01:00. Negative % = better; a positive `arrived diff` = more cars got home. `fw_app_100`: only the 1000 app users are coordinated (crowd cars never use the app); `fw_all_<pct>`: every car may use the app, <pct>% of them do (participation).

SUMO time-to-teleport: -1 s (no teleporting, Rule 0); teleport counts per arm are in the last column and must be 0 under Rule 0.

| experiment | crowd cars | policy | pairs | vehicle_hours (base) | vehicle_hours % | better/worse | arrived by 01:00 (base) | arrived diff | unfinished (base) | congested in-scope % | app trip mean % (completed) | non-fastest share | teleports (policy/base) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fw_all_100 | 3000 | heuristic@lam=500 | 3 | 2169 | -9.879 | 3/0 | 4000 | -55.3 | 0 | -19.8 | -15.7 | 0.589 | 0/0 |
| fw_all_100 | 3000 | rl_ppo | 3 | 2169 | -15.17 | 3/0 | 4000 | -231.3 | 0 | -27.58 | -39.97 | 0.999 | 0/0 |
| fw_all_100 | 6000 | heuristic@lam=500 | 3 | 7899 | -29.61 | 3/0 | 6264 | -81.3 | 736 | -36.03 | -41.91 | 0.675 | 0/0 |
| fw_all_100 | 6000 | rl_ppo | 3 | 7899 | -46.36 | 3/0 | 6264 | 57.3 | 736 | -54.71 | -58.84 | 0.999 | 0/0 |
| fw_all_100 | 12000 | heuristic@lam=500 | 3 | 2.32e+04 | -10.22 | 3/0 | 7148 | -940.3 | 5852 | -15.33 | -57.42 | 0.72 | 0/0 |
| fw_all_100 | 12000 | rl_ppo | 3 | 2.32e+04 | -24.76 | 3/0 | 7148 | 915.3 | 5852 | -20.27 | -46.06 | 1 | 0/0 |
| fw_all_30 | 3000 | heuristic@lam=500 | 3 | 1340 | -5.384 | 1/2 | 3958 | 41.7 | 42 | -11.59 | 1.74 | 0.4 | 0/0 |
| fw_all_30 | 3000 | rl_ppo | 3 | 1340 | 22.24 | 1/2 | 3958 | -111 | 42 | 47.17 | 4.924 | 0.997 | 0/0 |
| fw_all_30 | 6000 | heuristic@lam=500 | 3 | 3016 | 7.01 | 2/1 | 6873 | -120.3 | 127 | 7.921 | -8.551 | 0.54 | 0/0 |
| fw_all_30 | 6000 | rl_ppo | 3 | 3016 | 37.57 | 0/3 | 6873 | -581.7 | 127 | 57.45 | -19.08 | 0.999 | 0/0 |
| fw_all_30 | 12000 | heuristic@lam=500 | 3 | 1.276e+04 | -2.769 | 2/1 | 10770 | 285.3 | 2230 | -0.266 | -1.368 | 0.652 | 0/0 |
| fw_all_30 | 12000 | rl_ppo | 3 | 1.276e+04 | 17.43 | 1/2 | 10770 | -1525 | 2230 | 27.61 | -28.68 | 0.999 | 0/0 |
| fw_all_50 | 3000 | heuristic@lam=500 | 3 | 1286 | 4.893 | 0/3 | 4000 | -11.3 | 0 | 6.8 | 5.907 | 0.506 | 0/0 |
| fw_all_50 | 3000 | rl_ppo | 3 | 1286 | 24.9 | 0/3 | 4000 | -152 | 0 | 49.13 | -5.379 | 0.999 | 0/0 |
| fw_all_50 | 6000 | heuristic@lam=500 | 3 | 3486 | 6.199 | 1/2 | 6812 | -190.3 | 188 | 10 | -10.53 | 0.596 | 0/0 |
| fw_all_50 | 6000 | rl_ppo | 3 | 3486 | 5.037 | 0/3 | 6812 | -358.7 | 188 | 6.592 | -34.92 | 0.999 | 0/0 |
| fw_all_50 | 12000 | heuristic@lam=500 | 3 | 1.667e+04 | -9.317 | 3/0 | 8881 | 139.7 | 4119 | -5.888 | -29.52 | 0.697 | 0/0 |
| fw_all_50 | 12000 | rl_ppo | 3 | 1.667e+04 | -19.65 | 3/0 | 8881 | 899.7 | 4119 | -13.87 | -31.04 | 1 | 0/0 |
| fw_all_80 | 3000 | heuristic@lam=500 | 3 | 1657 | 6.585 | 0/3 | 4000 | -72.7 | 0 | 5.18 | -3.383 | 0.571 | 0/0 |
| fw_all_80 | 3000 | rl_ppo | 3 | 1657 | 6.295 | 1/2 | 4000 | -227.7 | 0 | 3.784 | -29.47 | 0.999 | 0/0 |
| fw_all_80 | 6000 | heuristic@lam=500 | 3 | 5845 | -22.58 | 3/0 | 6582 | -64.3 | 418 | -30.57 | -34.13 | 0.655 | 0/0 |
| fw_all_80 | 6000 | rl_ppo | 3 | 5845 | -26.5 | 3/0 | 6582 | -427.3 | 418 | -36.16 | -57.54 | 0.999 | 0/0 |
| fw_all_80 | 12000 | heuristic@lam=500 | 3 | 1.991e+04 | -9.156 | 3/0 | 8366 | -763.3 | 4634 | -13.4 | -46.65 | 0.706 | 0/0 |
| fw_all_80 | 12000 | rl_ppo | 3 | 1.991e+04 | -23.62 | 3/0 | 8366 | 683.3 | 4634 | -18.73 | -42.67 | 1 | 0/0 |

## Experiment reports

- fw_all_100: [coordination_benchmark_heldout_coordinated_routing_fireworks_rule0_wide_p100_c100_3447bac778.md](coordination_benchmark_heldout_coordinated_routing_fireworks_rule0_wide_p100_c100_3447bac778.md)
- fw_all_80: [coordination_benchmark_heldout_coordinated_routing_fireworks_rule0_wide_p80_c100_7e609aef9c.md](coordination_benchmark_heldout_coordinated_routing_fireworks_rule0_wide_p80_c100_7e609aef9c.md)
- fw_all_50: [coordination_benchmark_heldout_coordinated_routing_fireworks_rule0_wide_p50_c100_0f53ece854.md](coordination_benchmark_heldout_coordinated_routing_fireworks_rule0_wide_p50_c100_0f53ece854.md)
- fw_all_30: [coordination_benchmark_heldout_coordinated_routing_fireworks_rule0_wide_p30_c100_5c32ef7d82.md](coordination_benchmark_heldout_coordinated_routing_fireworks_rule0_wide_p30_c100_5c32ef7d82.md)
