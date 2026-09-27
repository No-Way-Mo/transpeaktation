# July 4 fireworks exodus on our network `959116f708`

> **Synthetic.** The demo's cohort (`demo/sumo/kit.py` v3, seed 42: 1000 app users) plus N assumed crowd cars leaving the seven viewing sites 21:45-22:45, rebuilt on net_v3 (`eventsim/fireworks_demo.py`). Event context: PredictHQ 300,000 expected attendance, show 21:30-21:45. No measured July 4 traffic exists.

Everything is compared at the same fixed horizon (01:00): vehicle_hours = time of every vehicle up to 01:00 (finished or not), arrived = vehicles that reached their destination by 01:00. Negative % = better; a positive `arrived diff` = more cars got home. `fw_app_100`: only the 1000 app users are coordinated (crowd cars never use the app); `fw_all_<pct>`: every car may use the app, <pct>% of them do (participation).

SUMO time-to-teleport: -1 s (no teleporting, Rule 0); teleport counts per arm are in the last column and must be 0 under Rule 0.

| experiment | crowd cars | policy | pairs | vehicle_hours (base) | vehicle_hours % | better/worse | arrived by 01:00 (base) | arrived diff | unfinished (base) | congested in-scope % | app trip mean % (completed) | non-fastest share | teleports (policy/base) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fw_all_100 | 3000 | heuristic@lam=500 | 3 | 1640 | -7.799 | 3/0 | 4000 | -38 | 0 | -21.14 | -12.76 | 0.667 | 0/0 |
| fw_all_100 | 3000 | rl_ppo | 3 | 1640 | -19.36 | 3/0 | 4000 | -8.3 | 0 | -42.52 | -20.38 | 0.999 | 0/0 |
| fw_all_100 | 6000 | heuristic@lam=500 | 3 | 5858 | -30 | 3/0 | 6852 | -25.7 | 148 | -39.65 | -32.59 | 0.731 | 0/0 |
| fw_all_100 | 6000 | rl_ppo | 3 | 5858 | -24.52 | 3/0 | 6852 | -487 | 148 | -31.34 | -44.97 | 0.999 | 0/0 |
| fw_all_100 | 12000 | heuristic@lam=500 | 3 | 2.183e+04 | -14.05 | 3/0 | 7745 | -433.7 | 5255 | -16.4 | -49.13 | 0.781 | 0/0 |
| fw_all_100 | 12000 | rl_ppo | 3 | 2.183e+04 | -22.44 | 3/0 | 7745 | 1077 | 5255 | -18.37 | -32.47 | 1 | 0/0 |
| fw_all_30 | 3000 | heuristic@lam=500 | 3 | 1245 | 6.65 | 1/2 | 4000 | -37.7 | 0 | 15.72 | 1.561 | 0.472 | 0/0 |
| fw_all_30 | 3000 | rl_ppo | 3 | 1245 | 2.065 | 0/3 | 4000 | -2.3 | 0 | 1.652 | 6.524 | 0.999 | 0/0 |
| fw_all_30 | 6000 | heuristic@lam=500 | 3 | 3286 | 10.43 | 1/2 | 6717 | -185 | 283 | 16.25 | -12.85 | 0.594 | 0/0 |
| fw_all_30 | 6000 | rl_ppo | 3 | 3286 | 3.128 | 2/1 | 6717 | -63 | 283 | 4.257 | -7.763 | 0.999 | 0/0 |
| fw_all_30 | 12000 | heuristic@lam=500 | 3 | 1.264e+04 | 4.98 | 1/2 | 10841 | -552.3 | 2159 | 6.206 | -24.1 | 0.713 | 0/0 |
| fw_all_30 | 12000 | rl_ppo | 3 | 1.264e+04 | 8.435 | 1/2 | 10841 | -610.3 | 2159 | 16.53 | -15.26 | 0.999 | 0/0 |
| fw_all_50 | 3000 | heuristic@lam=500 | 3 | 1256 | 10.44 | 1/2 | 4000 | -67 | 0 | 22.89 | -1.99 | 0.546 | 0/0 |
| fw_all_50 | 3000 | rl_ppo | 3 | 1256 | 7.365 | 2/1 | 4000 | -44 | 0 | 10.66 | -0.589 | 0.999 | 0/0 |
| fw_all_50 | 6000 | heuristic@lam=500 | 3 | 3638 | 0.165 | 2/1 | 6657 | -153.7 | 343 | 0.013 | -23.42 | 0.663 | 0/0 |
| fw_all_50 | 6000 | rl_ppo | 3 | 3638 | 3.419 | 2/1 | 6657 | -219 | 343 | 7.687 | -25.34 | 0.999 | 0/0 |
| fw_all_50 | 12000 | heuristic@lam=500 | 3 | 1.571e+04 | -21.47 | 3/0 | 9189 | 1422 | 3811 | -21.24 | -18.42 | 0.757 | 0/0 |
| fw_all_50 | 12000 | rl_ppo | 3 | 1.571e+04 | -12.73 | 2/1 | 9189 | 628 | 3811 | -6.71 | -24.29 | 0.999 | 0/0 |
| fw_all_80 | 3000 | heuristic@lam=500 | 3 | 1487 | -0.706 | 2/1 | 4000 | -42.7 | 0 | -7.002 | -8.195 | 0.634 | 0/0 |
| fw_all_80 | 3000 | rl_ppo | 3 | 1487 | -5.735 | 2/1 | 4000 | -68 | 0 | -19.04 | -19.19 | 0.999 | 0/0 |
| fw_all_80 | 6000 | heuristic@lam=500 | 3 | 4674 | -27.01 | 3/0 | 6739 | 39 | 261 | -38.31 | -32.42 | 0.715 | 0/0 |
| fw_all_80 | 6000 | rl_ppo | 3 | 4674 | -4.482 | 2/1 | 6739 | -602.7 | 261 | -12.39 | -42.13 | 0.999 | 0/0 |
| fw_all_80 | 12000 | heuristic@lam=500 | 3 | 2.02e+04 | -20.37 | 3/0 | 8371 | 174.7 | 4629 | -20.07 | -47.85 | 0.78 | 0/0 |
| fw_all_80 | 12000 | rl_ppo | 3 | 2.02e+04 | -30.45 | 3/0 | 8371 | 1614 | 4629 | -22.98 | -35.56 | 0.999 | 0/0 |

## Experiment reports

- fw_all_100: [coordination_benchmark_heldout_coordinated_routing_fireworks_rule0_wide_newfc_p100_c100_411402ae7f.md](coordination_benchmark_heldout_coordinated_routing_fireworks_rule0_wide_newfc_p100_c100_411402ae7f.md)
- fw_all_80: [coordination_benchmark_heldout_coordinated_routing_fireworks_rule0_wide_newfc_p80_c100_f8c974f101.md](coordination_benchmark_heldout_coordinated_routing_fireworks_rule0_wide_newfc_p80_c100_f8c974f101.md)
- fw_all_50: [coordination_benchmark_heldout_coordinated_routing_fireworks_rule0_wide_newfc_p50_c100_c63d1ca7c5.md](coordination_benchmark_heldout_coordinated_routing_fireworks_rule0_wide_newfc_p50_c100_c63d1ca7c5.md)
- fw_all_30: [coordination_benchmark_heldout_coordinated_routing_fireworks_rule0_wide_newfc_p30_c100_56cf8373ae.md](coordination_benchmark_heldout_coordinated_routing_fireworks_rule0_wide_newfc_p30_c100_56cf8373ae.md)
