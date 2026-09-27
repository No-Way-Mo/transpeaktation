# Held-out evaluation: Castro Street Fair 2026

Generated 2026-09-26T11:58:54+00:00 by `python -m eventsim evaluate --event castro`; model `eventsim-castro-hgb-202609261155`.

**Simulation only.** Trained and evaluated on SUMO scenarios grounded in the real permitted closure and real SF roads. Test = unseen *Castro* scenario families (same area); this is not citywide validation and not a measured-event validation.

- Families: train 57, val 12, test 31 (split by family before windowing; hard-test families forced into test: ['f005', 'f009', 'f010', 'f011', 'f013', 'f014', 'f016', 'f019', 'f020', 'f023', 'f024', 'f031', 'f038', 'f049', 'f057', 'f058', 'f059', 'f060', 'f063', 'f066', 'f073', 'f074', 'f075', 'f079', 'f081', 'f082', 'f090', 'f091', 'f094', 'f098', 'f099'])
- Test rows: 3,494,489 (segment × origin × horizon; empty/closed future buckets excluded)
- Validation MAE used for model selection (s/segment): {"learned": 2.908, "persistence": 5.033, "event_rule": 5.407}

## Segment travel-time error by horizon (test)

| h | n | persistence_mae_s | typical_mae_s | event_rule_mae_s | learned_mae_s | mean_true_s | learned_vs_persistence_% | learned_vs_rule_% | learned_vs_typical_% |
|---|---|---|---|---|---|---|---|---|---|
| 10 | 1206161 | 5.03 | 2.98 | 5.44 | 2.84 | 18.17 | 43.58 | 47.75 | 4.78 |
| 30 | 1170807 | 5.03 | 2.98 | 5.42 | 2.84 | 18.17 | 43.54 | 47.67 | 4.67 |
| 60 | 1117521 | 5.05 | 2.99 | 5.42 | 2.85 | 18.18 | 43.49 | 47.35 | 4.44 |

## Event vs ordinary periods

Event period = event runs, target time within declared hours −60 min … +90 min.

| period | h | n | persistence_mae_s | typical_mae_s | event_rule_mae_s | learned_mae_s | mean_true_s | learned_vs_persistence_% | learned_vs_rule_% | learned_vs_typical_% |
|---|---|---|---|---|---|---|---|---|---|---|
| event | 10 | 557709 | 5.44 | 3.25 | 6.31 | 3.09 | 18.40 | 43.20 | 51.03 | 4.81 |
| event | 30 | 539651 | 5.47 | 3.26 | 6.33 | 3.11 | 18.42 | 43.15 | 50.89 | 4.54 |
| event | 60 | 512808 | 5.50 | 3.26 | 6.30 | 3.13 | 18.43 | 43.05 | 50.34 | 3.92 |
| ordinary | 10 | 648452 | 4.68 | 2.76 | 4.68 | 2.63 | 17.96 | 43.95 | 43.95 | 4.76 |
| ordinary | 30 | 631156 | 4.65 | 2.74 | 4.65 | 2.61 | 17.96 | 43.93 | 43.93 | 4.81 |
| ordinary | 60 | 604713 | 4.67 | 2.75 | 4.67 | 2.62 | 17.96 | 43.92 | 43.92 | 4.96 |

## Event period by road group

approach = within 300 m of the footprint; detour = open segments with ≥1.5× and +30 veh/h vs the matched control.

| road | h | n | persistence_mae_s | typical_mae_s | event_rule_mae_s | learned_mae_s | mean_true_s | learned_vs_persistence_% | learned_vs_rule_% | learned_vs_typical_% |
|---|---|---|---|---|---|---|---|---|---|---|
| approach | 10 | 159806 | 8.12 | 5.51 | 9.75 | 5.12 | 23.43 | 36.99 | 47.50 | 7.15 |
| approach | 30 | 154932 | 8.12 | 5.51 | 9.74 | 5.13 | 23.42 | 36.82 | 47.33 | 6.98 |
| approach | 60 | 147299 | 8.17 | 5.53 | 9.66 | 5.17 | 23.43 | 36.70 | 46.51 | 6.48 |
| detour | 10 | 96646 | 3.94 | 2.10 | 5.13 | 1.91 | 17.22 | 51.50 | 62.72 | 8.72 |
| detour | 30 | 93167 | 4.05 | 2.13 | 5.21 | 1.97 | 17.29 | 51.37 | 62.24 | 7.48 |
| detour | 60 | 88208 | 4.12 | 2.14 | 5.25 | 2.02 | 17.32 | 51.03 | 61.63 | 5.88 |
| other | 10 | 301257 | 4.50 | 2.41 | 4.86 | 2.39 | 16.12 | 46.83 | 50.82 | 0.88 |
| other | 30 | 291552 | 4.51 | 2.42 | 4.88 | 2.40 | 16.12 | 46.84 | 50.79 | 0.77 |
| other | 60 | 277301 | 4.51 | 2.41 | 4.85 | 2.40 | 16.13 | 46.85 | 50.50 | 0.25 |

## Recovery (30 min – 3 h after declared end)

| h | n | persistence_mae_s | typical_mae_s | event_rule_mae_s | learned_mae_s | mean_true_s | learned_vs_persistence_% | learned_vs_rule_% | learned_vs_typical_% |
|---|---|---|---|---|---|---|---|---|---|
| 10 | 115097 | 5.16 | 3.11 | 6.38 | 2.93 | 18.02 | 43.19 | 54.07 | 5.80 |
| 30 | 115590 | 5.21 | 3.06 | 6.52 | 2.88 | 17.95 | 44.58 | 55.73 | 5.82 |
| 60 | 115242 | 5.44 | 3.11 | 6.85 | 2.97 | 17.96 | 45.48 | 56.69 | 4.73 |

## Congestion build-ups and false alarms

Relative to each segment's normal (typical travel time at that time from training controls): new build-up = truth ≥ 2.0× normal at t+h while the persistence value at the origin was < 1.5× normal; detected if predicted ≥ 1.75× normal; false alarm = predicted ≥ 2.0× normal on no-event runs where truth < 1.5× normal.

```
{
 "rows": 3494489,
 "new_buildups": 38309,
 "quiet_noevent_rows": 1680766,
 "persistence_recall": 0.0013834869090814169,
 "persistence_false_alarms_per_1k_noevent": 8.466377830108415,
 "typical_recall": 0.0,
 "typical_false_alarms_per_1k_noevent": 0.0,
 "event_rule_recall": 0.014330836095956563,
 "event_rule_false_alarms_per_1k_noevent": 8.466377830108415,
 "learned_recall": 0.008353128507661385,
 "learned_false_alarms_per_1k_noevent": 0.7562028265683622,
 "event_period_new_buildups": 29162,
 "persistence_event_period_recall": 0.0008915712228242233,
 "typical_event_period_recall": 0.0,
 "event_rule_event_period_recall": 0.017900006858240176,
 "learned_event_period_recall": 0.007544064193128044
}
```

## Robustness and latency

```
{
 "event_estimate_missing_mae_s": 2.8366913898919863,
 "as_stored_mae_s": 2.8438089236538047,
 "tomtom_60pct_missing_persistence_mae_s": 6.337787543564941,
 "tomtom_60pct_missing_learned_mae_s": 3.767314617905329,
 "segments": 931,
 "horizons": 3,
 "ms_per_origin_median": 85.67149999726098
}
```

## Per test family (variability, including where the model is worse)

| family | n | persistence_mae_s | typical_mae_s | event_rule_mae_s | learned_mae_s | mean_true_s | learned_vs_persistence_% | learned_vs_rule_% | learned_vs_typical_% |
|---|---|---|---|---|---|---|---|---|---|
| f005 | 86267 | 6.71 | 4.04 | 7.17 | 4.02 | 19.20 | 40.11 | 43.93 | 0.61 |
| f009 | 107988 | 5.29 | 3.04 | 5.65 | 3.03 | 18.43 | 42.80 | 46.47 | 0.46 |
| f010 | 113159 | 4.34 | 3.04 | 4.75 | 2.73 | 17.52 | 37.06 | 42.43 | 10.20 |
| f011 | 118334 | 4.58 | 2.60 | 4.94 | 2.34 | 17.87 | 48.97 | 52.71 | 10.09 |
| f013 | 112829 | 5.14 | 2.98 | 5.52 | 2.87 | 17.61 | 44.26 | 48.07 | 3.64 |
| f014 | 115374 | 3.98 | 2.16 | 4.32 | 2.04 | 17.32 | 48.62 | 52.65 | 5.36 |
| f016 | 120201 | 5.73 | 3.04 | 6.17 | 3.01 | 19.20 | 47.39 | 51.13 | 0.86 |
| f019 | 115888 | 5.47 | 3.04 | 5.87 | 3.09 | 18.82 | 43.60 | 47.37 | -1.51 |
| f020 | 113726 | 5.99 | 3.60 | 6.44 | 3.38 | 18.54 | 43.51 | 47.49 | 5.93 |
| f023 | 107854 | 5.27 | 2.83 | 5.63 | 2.84 | 17.72 | 46.12 | 49.56 | -0.31 |
| f024 | 106535 | 4.89 | 2.70 | 5.24 | 2.66 | 17.81 | 45.55 | 49.18 | 1.23 |
| f031 | 114767 | 4.05 | 2.63 | 4.47 | 2.30 | 17.35 | 43.18 | 48.47 | 12.50 |
| f038 | 84660 | 6.98 | 4.57 | 7.41 | 4.65 | 19.28 | 33.33 | 37.24 | -1.89 |
| f049 | 109626 | 5.94 | 3.32 | 6.36 | 3.32 | 19.19 | 44.18 | 47.82 | 0.04 |
| f057 | 120952 | 5.35 | 3.02 | 5.77 | 3.00 | 18.91 | 43.97 | 48.05 | 0.81 |
| f058 | 114844 | 4.27 | 2.51 | 4.62 | 2.42 | 17.69 | 43.41 | 47.75 | 3.75 |
| f059 | 109576 | 5.33 | 3.25 | 5.68 | 3.25 | 18.59 | 39.05 | 42.87 | 0.12 |
| f060 | 115061 | 4.61 | 2.87 | 5.05 | 2.62 | 18.01 | 43.13 | 48.04 | 8.63 |
| f063 | 111926 | 4.27 | 2.68 | 4.62 | 2.41 | 17.32 | 43.47 | 47.76 | 9.85 |
| f066 | 115055 | 3.77 | 2.32 | 4.13 | 2.08 | 17.06 | 44.80 | 49.63 | 10.15 |
| f073 | 114598 | 5.08 | 3.08 | 5.47 | 3.12 | 18.54 | 38.62 | 43.02 | -1.04 |
| f074 | 109873 | 5.67 | 3.21 | 6.06 | 3.16 | 18.56 | 44.27 | 47.88 | 1.66 |
| f075 | 118184 | 5.14 | 3.08 | 5.48 | 2.86 | 18.30 | 44.27 | 47.75 | 7.17 |
| f079 | 116812 | 5.16 | 3.39 | 5.58 | 3.16 | 18.18 | 38.77 | 43.41 | 6.86 |
| f081 | 111531 | 5.04 | 3.08 | 5.45 | 2.83 | 17.94 | 43.96 | 48.17 | 8.35 |
| f082 | 120045 | 4.44 | 2.78 | 4.83 | 2.36 | 17.33 | 46.86 | 51.10 | 15.04 |
| f090 | 118422 | 5.49 | 3.39 | 5.91 | 3.15 | 18.92 | 42.52 | 46.68 | 7.07 |
| f091 | 118991 | 4.73 | 2.67 | 5.09 | 2.48 | 17.65 | 47.71 | 51.41 | 7.39 |
| f094 | 114593 | 4.20 | 2.75 | 4.60 | 2.48 | 17.88 | 40.94 | 46.05 | 9.90 |
| f098 | 115619 | 4.78 | 2.64 | 5.11 | 2.52 | 17.85 | 47.20 | 50.66 | 4.40 |
| f099 | 121199 | 5.42 | 2.84 | 5.83 | 2.82 | 19.18 | 47.97 | 51.61 | 0.71 |

Learned model worse than the event rule in 0/31 test families and worse than persistence in 0/31.

## Decision

The learned correction beats both required baselines at every horizon on all held-out families (vs persistence 44%, vs event rule 48% lower MAE), so it can back the demo with the simulation caveat. Most of that gain is denoising provider-like observations: a typical-for-this-time baseline gets close, and the learned model's margin over it is 4.4% in event periods (5.9–8.7% on approach/detour roads), with 4/31 test families where it is worse than typical. Sudden build-ups (≥2× normal) are not predicted by any method (learned recall 0.8%, event rule 1.4%); treat forecasts as expected travel times, not congestion alarms.

Complete-route outcomes (travel time, delay, completed/unfinished trips) are in the routing replay report.
