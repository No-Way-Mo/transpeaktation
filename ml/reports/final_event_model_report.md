# Final event-aware 3-hour model (overnight run)

> **Synthetic** SUMO data (b5_long_event: 20 events; b4 / b3 used for training where noted). Selection on Bearrison validation only; Portola evaluated once for the chosen system.

## Selection rule (fixed before results)

```
Final selection node (not part of the repo). Run from ml/ with PYTHONPATH=.:  python gpu_stage_final.py <bucket>

wait for the overnight training nodes (hard deadline) -> b5 caches -> pull every candidate -> (re-)evaluate on
Bearrison where missing -> ensembles of compatible top models -> choose ONE system on validation with the rule below
-> Portola once for it -> final report -> upload.

Selection rule (fixed before looking at any result): among first-hour guardrail-safe systems (not the oracle
diagnostic), the highest validation F1 for build-ups 1-3 h ahead on directly observed clear near roads
(antic cells, horizon groups 60-120 and 120-180), using the system's jam head if it has one else its calibrated point
forecast; ties -> lower validation hours-2-3 anticipation travel-time MAE.
```

## Validation (Bearrison)

| system | val_buildup_F1_1-3h | warning_source | val_antic_MAE_2-3h | first_hour_vs_v2 | guard_ok | members |
|---|---|---|---|---|---|---|
| ens3 | 0.6525 | jam head | 2.0726 | 0.0143 | yes | x_all,s_jam10,v6_route |
| ens5 | 0.6523 | jam head | 2.0719 | 0.0135 | yes | x_all,s_jam10,v6_route,v7_attn,v6_route_att |
| event_patch_x_all | 0.6520 | jam head | 2.0592 | 0.0137 | yes |  |
| event_patch_v6_heads | 0.6513 | jam head | 2.0720 | 0.0138 | yes |  |
| event_patch_s_jam10 | 0.6511 | jam head | 2.0977 | 0.0197 | yes |  |
| event_patch_v6_route | 0.6509 | jam head | 2.0839 | 0.0157 | yes |  |
| event_patch_v7_attn | 0.6508 | jam head | 2.0790 | 0.0155 | yes |  |
| event_patch_v6_route_att | 0.6501 | jam head | 2.0830 | 0.0158 | yes |  |
| event_patch_v7_multi | 0.6495 | jam head | 2.0620 | 0.0119 | yes |  |
| event_patch_v6_tuned | 0.6440 | calibrated point forecast | 2.0128 | -0.0030 | yes |  |
| event_patch_s_lr | 0.6427 | jam head | 2.0959 | 0.0227 | no |  |
| event_patch_v5_h18_full | 0.6424 | calibrated point forecast | 2.0173 | -0.0019 | yes |  |

**Chosen: `ens3`**

## Ceiling diagnostic (not deployable)

Same model as `v6_route` plus the hidden per-run event parameters: validation build-up F1 0.648 vs 0.651; anticipation MAE 2.07 vs 2.08 s. The difference is roughly what schedule-only information cannot recover (arrival timing, vehicles, parking).

## Portola (held-out test, before-start side), chosen system vs baselines

| system | 1h_city_MAE | 1h_vs_v2 | 2-3h_city_MAE | 2-3h_near_MAE | 2-3h_antic_MAE | 2-3h_antic_recall | 2-3h_antic_precision | persistence_2-3h_antic_MAE |
|---|---|---|---|---|---|---|---|---|
| chosen | 2.9761 | 0.0117 | 2.9665 | 5.3880 | 4.3012 | 0.2403 | 0.7525 | 4.8473 |
| v5 | 2.9390 | -0.0009 | 2.9253 | 5.3324 | 4.3029 | 0.2638 | 0.7325 | 4.8473 |
| v4 | 2.9398 | -0.0007 | 2.9253 | 5.3454 | 4.2804 | 0.2628 | 0.7659 | 4.8473 |

Build-up warnings on Portola, chosen (antic cells; thresholds from Bearrison):

| hgroup | labels | positives | base_precision | base_recall | f1thr_precision | f1thr_recall | f1thr_f1 | head_precision | head_recall | head_f1 | ap_point | ap_head | head_tol_precision | head_tol_recall | q_coverage |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0-60 | 73715 | 1708 | 0.6667 | 0.2845 | 0.5365 | 0.3741 | 0.4408 | 0.6061 | 0.3361 | 0.4324 | 0.3716 | 0.4037 | 0.6604 | 0.3420 | 0.7157 |
| 120-180 | 77272 | 3030 | 0.7989 | 0.2294 | 0.5231 | 0.3257 | 0.4015 | 0.7187 | 0.3010 | 0.4243 | 0.3646 | 0.4293 | 0.7362 | 0.2907 | 0.7233 |
| 60-120 | 76482 | 2285 | 0.7047 | 0.2538 | 0.5616 | 0.3532 | 0.4336 | 0.6517 | 0.3112 | 0.4212 | 0.3670 | 0.4245 | 0.7234 | 0.3055 | 0.7292 |

Build-up warnings on Portola, v5 (antic cells; thresholds from Bearrison):

| hgroup | labels | positives | base_precision | base_recall | f1thr_precision | f1thr_recall | f1thr_f1 |
|---|---|---|---|---|---|---|---|
| 0-60 | 73715 | 1708 | 0.6409 | 0.2957 | 0.4391 | 0.3923 | 0.4143 |
| 120-180 | 77272 | 3030 | 0.7713 | 0.2538 | 0.5631 | 0.3254 | 0.4125 |
| 60-120 | 76482 | 2285 | 0.6918 | 0.2770 | 0.4802 | 0.3663 | 0.4156 |

## Notes

- Other variants were also scored on Portola by their own nodes; those numbers were not used for selection.
- Model files: `results/forecast/experiments/<name>/best.pt`; selection: `experiments/final/selection.json`.
