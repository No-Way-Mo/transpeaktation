# July 4 fireworks exodus on our network `7e44eeb42e`

> **Synthetic.** The demo's cohort (`demo/sumo/kit.py` v3, seed 42: 1000 app users) plus N assumed crowd cars leaving the seven viewing sites 21:45-22:45, rebuilt on net_v3 (`eventsim/fireworks_demo.py`). Event context: PredictHQ 300,000 expected attendance, show 21:30-21:45. No measured July 4 traffic exists.

Everything is compared at the same fixed horizon (01:00): vehicle_hours = time of every vehicle up to 01:00 (finished or not), arrived = vehicles that reached their destination by 01:00. Negative % = better; a positive `arrived diff` = more cars got home. `fw_app_100`: only the 1000 app users are coordinated (crowd cars never use the app); `fw_all_<pct>`: every car may use the app, <pct>% of them do (participation).

SUMO time-to-teleport: -1 s (no teleporting, Rule 0); teleport counts per arm are in the last column and must be 0 under Rule 0.

| experiment | crowd cars | policy | pairs | vehicle_hours (base) | vehicle_hours % | better/worse | arrived by 01:00 (base) | arrived diff | unfinished (base) | congested in-scope % | app trip mean % (completed) | non-fastest share | teleports (policy/base) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fw_all_100 | 3000 | heuristic@lam=0 | 3 | 2169 | 0 | 0/0 | 4000 | 0 | 0 | 0 | 0 | 0.036 | 0/0 |
| fw_all_100 | 6000 | heuristic@lam=0 | 3 | 7899 | 0 | 0/0 | 6264 | 0 | 736 | 0 | 0 | 0.033 | 0/0 |
| fw_all_100 | 12000 | heuristic@lam=0 | 3 | 2.32e+04 | 0 | 0/0 | 7148 | 0 | 5852 | 0 | 0 | 0.029 | 0/0 |

## Experiment reports

- fw_all_100: [coordination_benchmark_heldout_coordinated_routing_fireworks_rule0_sanity_p100_c100_b5270681ad.md](coordination_benchmark_heldout_coordinated_routing_fireworks_rule0_sanity_p100_c100_b5270681ad.md)
