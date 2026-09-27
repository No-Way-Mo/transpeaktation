# Long-horizon retraining: 180 min (18 buckets)

> **Synthetic.** SUMO scenarios on real SF roads/permits; demand and attendance are assumptions. Road/bucket labels overlap and are not independent trials.

## Identity

- Experiment `event_patch_v4_h18_full`; parent `/opt/tp/transpeaktation/ml/data/forecast/experiments/event_patch_v2_main/best.pt` (sha256 `45e075b4befa7d5e…`, H=6); migration: 156 tensors copied exactly, grown `{"hor.weight": {"parent_rows": 6, "new_rows": 12, "init": "parent last row + N(0, 0.01) seed 0"}}`; all 372,865 parameters trained.
- Dataset `b4_long_h18_v1` from batch `b4_long_event` (manifest `e57e39c4e49c…`, windows `cc4aed0d269c…`); split {"train": ["sunday_streets_excelsior", "folsom", "halloween_cortland", "chinatown_night_market", "potrero_hill_festival"], "val": ["bearrison"], "test": ["portola"]}; 216 runs selected, 8 excluded.
- Normalisation: parent checkpoint norm (dataset norm.json not used). Retrain settings digest `fdfd15e0fbe3836b`: `{"lr_backbone": 0.0001, "lr_event": 0.0003, "weight_decay": 0.0001, "grad_clip": 1.0, "max_epochs": 30, "patience": 5, "per_family": 24, "seed": 0, "new_row_noise": 0.01, "weights": {"global": 1.0, "event_near": 1.0, "anticipation": 2.0}, "horizon_groups": [[0, 6, 0.5], [6, 18, 0.5]], "lead_bands_min": [0, 60, 120, 180], "other_share": 0.25, "val_stride": 2, "prefetch": 6, "guardrails": {"first_hour_citywide_max_rel": 0.02, "first_hour_control_max_rel": 0.02, "first_hour_severe_max_rel": 0.02}}`
- Code: `{"revision": null, "dirty_files": []}`

Excluded runs by event group: folsom 4, portola 4

## Window coverage (issue time relative to the focal event's public start/end)

| lead_cat | test | train | val |
|---|---|---|---|
| end_0_60 | 0 | 360 | 96 |
| end_120_180 | 0 | 472 | 96 |
| end_60_120 | 0 | 456 | 96 |
| other | 48 | 480 | 128 |
| start_0_60 | 72 | 480 | 96 |
| start_120_180 | 72 | 480 | 96 |
| start_60_120 | 72 | 480 | 96 |

No run crosses midnight (user decision): boundaries late in the day have truncated or no long-lead windows (Portola's 23:00 end has none).

## Training

- 11 epochs (early stop), selected epoch 6, 2059 s on NVIDIA L40S, peak GPU 8701.1 MB.
- Selection: lowest validation objective (Bearrison), patience 5, max 30 epochs.

| epoch | steps | s_per_step | train_total | train_global | train_event_near | train_anticipation | val_total | val_first_hour_z_mae | val_all_z_mae | seconds |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 936 | 0.1984 | 0.0599 | 0.0290 | 0.0157 | 0.0076 | 0.0663 | 0.1317 | 0.1317 | 209.6 |
| 2 | 936 | 0.1764 | 0.0591 | 0.0289 | 0.0154 | 0.0074 | 0.0663 | 0.1315 | 0.1315 | 184.7 |
| 3 | 936 | 0.1764 | 0.0592 | 0.0289 | 0.0154 | 0.0074 | 0.0662 | 0.1318 | 0.1318 | 184.8 |
| 4 | 936 | 0.1764 | 0.0592 | 0.0289 | 0.0154 | 0.0075 | 0.0660 | 0.1314 | 0.1314 | 184.7 |
| 5 | 936 | 0.1764 | 0.0590 | 0.0289 | 0.0153 | 0.0074 | 0.0661 | 0.1316 | 0.1316 | 184.8 |
| 6 | 936 | 0.1764 | 0.0588 | 0.0288 | 0.0152 | 0.0074 | 0.0660 | 0.1316 | 0.1316 | 184.7 |
| 7 | 936 | 0.1764 | 0.0589 | 0.0288 | 0.0152 | 0.0074 | 0.0661 | 0.1314 | 0.1314 | 184.8 |
| 8 | 936 | 0.1764 | 0.0587 | 0.0288 | 0.0151 | 0.0074 | 0.0663 | 0.1321 | 0.1320 | 184.8 |
| 9 | 936 | 0.1765 | 0.0585 | 0.0288 | 0.0151 | 0.0073 | 0.0662 | 0.1317 | 0.1317 | 184.8 |
| 10 | 936 | 0.1772 | 0.0587 | 0.0288 | 0.0152 | 0.0074 | 0.0669 | 0.1318 | 0.1319 | 185.5 |
| 11 | 936 | 0.1772 | 0.0585 | 0.0288 | 0.0150 | 0.0073 | 0.0660 | 0.1314 | 0.1314 | 185.5 |

Measured wall times: pull 1.4 min, report_export 0.4 min, audit 4.6 min, prepare 0.5 min, train 35.1 min, evaluate_val 3.7 min, evaluate_test 1.4 min

## Bearrison validation

First-hour guardrail vs the parent (same windows, its own 6 horizons): `{"first_hour_citywide_rel": -0.0027722712446647687, "first_hour_control_rel": -0.002824450382357494, "first_hour_severe_rel": -0.002119565574740564, "first_hour_safe": true}`

First hour (horizons 10-60 min):

| stratum | system | labels | tt_mae_s | tt_wape | speed_mae_mph | cong_mae | positives | precision | recall | f1 |
|---|---|---|---|---|---|---|---|---|---|---|
| all | candidate | 65307009.0 | 2.6558 | 0.1595 | 1.7769 | 0.0699 | 15401836.0 | 0.8478 | 0.7933 | 0.8196 |
| all | parent | 65307009.0 | 2.6632 | 0.1600 | 1.7814 | 0.0701 | 15401836.0 | 0.8486 | 0.7905 | 0.8185 |
| all | persistence | 65307009.0 | 4.0558 | 0.2436 | 2.9719 | 0.1169 | 15401836.0 | 0.7652 | 0.7124 | 0.7378 |
| antic | candidate | 643255.0 | 1.8263 | 0.1444 | 1.6986 | 0.0670 | 37906.0 | 0.6544 | 0.4882 | 0.5592 |
| antic | parent | 643255.0 | 1.8246 | 0.1442 | 1.6937 | 0.0668 | 37906.0 | 0.6554 | 0.4860 | 0.5581 |
| antic | persistence | 643255.0 | 2.3642 | 0.1869 | 2.4584 | 0.0962 | 37906.0 | – | 0.0000 | – |
| antic_pre_end | candidate | 351397.0 | 1.7497 | 0.1353 | 1.5742 | 0.0626 | 19630.0 | 0.6686 | 0.4862 | 0.5630 |
| antic_pre_end | parent | 351397.0 | 1.7440 | 0.1349 | 1.5614 | 0.0620 | 19630.0 | 0.6686 | 0.4913 | 0.5664 |
| antic_pre_end | persistence | 351397.0 | 2.2976 | 0.1777 | 2.2943 | 0.0908 | 19630.0 | – | 0.0000 | – |
| antic_pre_start | candidate | 291858.0 | 1.9186 | 0.1558 | 1.8484 | 0.0722 | 18276.0 | 0.6400 | 0.4904 | 0.5553 |
| antic_pre_start | parent | 291858.0 | 1.9218 | 0.1561 | 1.8530 | 0.0724 | 18276.0 | 0.6416 | 0.4803 | 0.5493 |
| antic_pre_start | persistence | 291858.0 | 2.4445 | 0.1986 | 2.6560 | 0.1026 | 18276.0 | – | 0.0000 | – |
| antic_strict | candidate | 493659.0 | 1.0571 | 0.0967 | 1.3978 | 0.0541 | 11136.0 | 0.5721 | 0.3165 | 0.4076 |
| antic_strict | parent | 493659.0 | 1.0512 | 0.0962 | 1.3878 | 0.0537 | 11136.0 | 0.5741 | 0.3115 | 0.4039 |
| antic_strict | persistence | 493659.0 | 1.2624 | 0.1155 | 1.7850 | 0.0683 | 11136.0 | – | 0.0000 | – |
| control_runs | candidate | 32340216.0 | 2.6567 | 0.1600 | 1.7927 | 0.0705 | 7609374.0 | 0.8469 | 0.7918 | 0.8184 |
| control_runs | parent | 32340216.0 | 2.6642 | 0.1604 | 1.7966 | 0.0707 | 7609374.0 | 0.8482 | 0.7884 | 0.8172 |
| control_runs | persistence | 32340216.0 | 4.0619 | 0.2446 | 2.9963 | 0.1178 | 7609374.0 | 0.7633 | 0.7102 | 0.7358 |
| event_far | candidate | 22040075.0 | 2.1797 | 0.1362 | 1.6324 | 0.0631 | 4914066.0 | 0.8640 | 0.8084 | 0.8353 |
| event_far | parent | 22040075.0 | 2.1872 | 0.1366 | 1.6374 | 0.0633 | 4914066.0 | 0.8652 | 0.8051 | 0.8341 |
| event_far | persistence | 22040075.0 | 3.4256 | 0.2140 | 2.9021 | 0.1127 | 4914066.0 | 0.7831 | 0.7163 | 0.7482 |
| event_near | candidate | 1943226.0 | 3.8287 | 0.2165 | 1.9112 | 0.0767 | 549223.0 | 0.8383 | 0.8086 | 0.8232 |
| event_near | parent | 1943226.0 | 3.8325 | 0.2167 | 1.9119 | 0.0767 | 549223.0 | 0.8371 | 0.8106 | 0.8236 |
| event_near | persistence | 1943226.0 | 5.5705 | 0.3150 | 2.8073 | 0.1124 | 549223.0 | 0.7750 | 0.7470 | 0.7607 |
| event_runs | candidate | 32966793.0 | 2.6550 | 0.1591 | 1.7614 | 0.0693 | 7792462.0 | 0.8487 | 0.7947 | 0.8208 |
| event_runs | parent | 32966793.0 | 2.6622 | 0.1596 | 1.7665 | 0.0695 | 7792462.0 | 0.8490 | 0.7927 | 0.8199 |
| event_runs | persistence | 32966793.0 | 4.0498 | 0.2427 | 2.9479 | 0.1160 | 7792462.0 | 0.7670 | 0.7145 | 0.7398 |
| near_missing_history | candidate | 284503.0 | 3.4389 | 0.2082 | 2.1472 | 0.0885 | 63138.0 | 0.8077 | 0.6928 | 0.7459 |
| near_missing_history | parent | 284503.0 | 3.4374 | 0.2081 | 2.1454 | 0.0885 | 63138.0 | 0.8076 | 0.6984 | 0.7490 |
| near_missing_history | persistence | 284503.0 | 5.4890 | 0.3323 | 4.4557 | 0.1818 | 63138.0 | 0.6965 | 0.5073 | 0.5870 |
| severe | candidate | 15401836.0 | 6.2785 | 0.2951 | 1.7685 | 0.0709 | 15401836.0 | 1.0000 | 0.7933 | 0.8847 |
| severe | parent | 15401836.0 | 6.2918 | 0.2957 | 1.7827 | 0.0715 | 15401836.0 | 1.0000 | 0.7905 | 0.8830 |
| severe | persistence | 15401836.0 | 8.4464 | 0.3970 | 3.7267 | 0.1489 | 15401836.0 | 1.0000 | 0.7124 | 0.8320 |

Hours 2-3 (horizons 70-180 min; the parent has no forecast here):

| stratum | system | labels | tt_mae_s | tt_wape | speed_mae_mph | cong_mae | positives | precision | recall | f1 |
|---|---|---|---|---|---|---|---|---|---|---|
| all | candidate | 130256414.0 | 2.6717 | 0.1605 | 1.7850 | 0.0702 | 30667743.0 | 0.8460 | 0.7933 | 0.8188 |
| all | persistence | 130256414.0 | 4.0913 | 0.2458 | 3.0065 | 0.1182 | 30667743.0 | 0.7629 | 0.7094 | 0.7352 |
| antic | candidate | 1305168.0 | 1.9110 | 0.1488 | 1.6564 | 0.0654 | 81403.0 | 0.6844 | 0.4966 | 0.5755 |
| antic | persistence | 1305168.0 | 2.5351 | 0.1974 | 2.5449 | 0.0997 | 81403.0 | – | 0.0000 | – |
| antic_pre_end | candidate | 683899.0 | 1.8116 | 0.1408 | 1.6155 | 0.0638 | 37591.0 | 0.6627 | 0.4714 | 0.5510 |
| antic_pre_end | persistence | 683899.0 | 2.3308 | 0.1812 | 2.3098 | 0.0910 | 37591.0 | – | 0.0000 | – |
| antic_pre_start | candidate | 621269.0 | 2.0205 | 0.1577 | 1.7015 | 0.0671 | 43812.0 | 0.7023 | 0.5181 | 0.5963 |
| antic_pre_start | persistence | 621269.0 | 2.7601 | 0.2154 | 2.8037 | 0.1092 | 43812.0 | – | 0.0000 | – |
| antic_strict | candidate | 992539.0 | 1.1400 | 0.1030 | 1.3743 | 0.0532 | 24860.0 | 0.6208 | 0.3240 | 0.4258 |
| antic_strict | persistence | 992539.0 | 1.3980 | 0.1263 | 1.8495 | 0.0709 | 24860.0 | – | 0.0000 | – |
| control_runs | candidate | 64336834.0 | 2.6707 | 0.1609 | 1.8033 | 0.0709 | 15116657.0 | 0.8448 | 0.7918 | 0.8174 |
| control_runs | persistence | 64336834.0 | 4.0828 | 0.2460 | 3.0227 | 0.1188 | 15116657.0 | 0.7614 | 0.7082 | 0.7339 |
| event_far | candidate | 43932462.0 | 2.1884 | 0.1367 | 1.6371 | 0.0633 | 9781667.0 | 0.8620 | 0.8096 | 0.8350 |
| event_far | persistence | 43932462.0 | 3.4444 | 0.2152 | 2.9332 | 0.1139 | 9781667.0 | 0.7815 | 0.7135 | 0.7460 |
| event_near | candidate | 3941476.0 | 3.9103 | 0.2203 | 1.9089 | 0.0767 | 1108199.0 | 0.8385 | 0.8067 | 0.8223 |
| event_near | persistence | 3941476.0 | 5.8342 | 0.3287 | 2.9540 | 0.1183 | 1108199.0 | 0.7684 | 0.7334 | 0.7505 |
| event_runs | candidate | 65919580.0 | 2.6726 | 0.1602 | 1.7671 | 0.0696 | 15551086.0 | 0.8472 | 0.7947 | 0.8201 |
| event_runs | persistence | 65919580.0 | 4.0996 | 0.2457 | 2.9906 | 0.1177 | 15551086.0 | 0.7644 | 0.7105 | 0.7365 |
| near_missing_history | candidate | 645364.0 | 3.4719 | 0.2069 | 2.0528 | 0.0848 | 146976.0 | 0.8187 | 0.7006 | 0.7550 |
| near_missing_history | persistence | 645364.0 | 5.6763 | 0.3383 | 4.6655 | 0.1905 | 146976.0 | 0.7083 | 0.4827 | 0.5741 |
| severe | candidate | 30667743.0 | 6.3327 | 0.2969 | 1.7717 | 0.0711 | 30667743.0 | 1.0000 | 0.7933 | 0.8847 |
| severe | persistence | 30667743.0 | 8.5390 | 0.4003 | 3.7741 | 0.1508 | 30667743.0 | 1.0000 | 0.7094 | 0.8300 |

By target horizon (selected):

| stratum | horizon_min | system | labels | tt_mae_s | precision | recall | f1 |
|---|---|---|---|---|---|---|---|
| all | 10 | candidate | 10821912.0 | 2.6551 | 0.8461 | 0.7946 | 0.8195 |
| all | 10 | parent | 10821912.0 | 2.6622 | 0.8478 | 0.7908 | 0.8183 |
| all | 10 | persistence | 10821912.0 | 4.0405 | 0.7649 | 0.7131 | 0.7381 |
| all | 30 | candidate | 10884548.0 | 2.6568 | 0.8481 | 0.7933 | 0.8198 |
| all | 30 | parent | 10884548.0 | 2.6638 | 0.8485 | 0.7914 | 0.8189 |
| all | 30 | persistence | 10884548.0 | 4.0442 | 0.7656 | 0.7126 | 0.7381 |
| all | 60 | candidate | 10926849.0 | 2.6582 | 0.8477 | 0.7938 | 0.8199 |
| all | 60 | parent | 10926849.0 | 2.6664 | 0.8487 | 0.7904 | 0.8185 |
| all | 60 | persistence | 10926849.0 | 4.0579 | 0.7654 | 0.7118 | 0.7376 |
| all | 120 | candidate | 10888716.0 | 2.6691 | 0.8463 | 0.7939 | 0.8192 |
| all | 120 | persistence | 10888716.0 | 4.0744 | 0.7641 | 0.7103 | 0.7362 |
| all | 180 | candidate | 10683795.0 | 2.7056 | 0.8443 | 0.7915 | 0.8170 |
| all | 180 | persistence | 10683795.0 | 4.1128 | 0.7612 | 0.7086 | 0.7340 |
| antic | 10 | candidate | 106340.0 | 1.8136 | 0.6425 | 0.4652 | 0.5396 |
| antic | 10 | parent | 106340.0 | 1.8156 | 0.6391 | 0.4756 | 0.5453 |
| antic | 10 | persistence | 106340.0 | 2.3169 | – | 0.0000 | – |
| antic | 30 | candidate | 107148.0 | 1.8514 | 0.6540 | 0.4904 | 0.5605 |
| antic | 30 | parent | 107148.0 | 1.8486 | 0.6577 | 0.4913 | 0.5625 |
| antic | 30 | persistence | 107148.0 | 2.3721 | – | 0.0000 | – |
| antic | 60 | candidate | 108118.0 | 1.8338 | 0.6644 | 0.5026 | 0.5723 |
| antic | 60 | parent | 108118.0 | 1.8266 | 0.6718 | 0.4920 | 0.5680 |
| antic | 60 | persistence | 108118.0 | 2.4200 | – | 0.0000 | – |
| antic | 120 | candidate | 109147.0 | 1.9191 | 0.6823 | 0.4960 | 0.5744 |
| antic | 120 | persistence | 109147.0 | 2.5407 | – | 0.0000 | – |
| antic | 180 | candidate | 108017.0 | 1.9614 | 0.6960 | 0.4974 | 0.5802 |
| antic | 180 | persistence | 108017.0 | 2.5875 | – | 0.0000 | – |
| event_near | 10 | candidate | 319998.0 | 3.8325 | 0.8384 | 0.8067 | 0.8222 |
| event_near | 10 | parent | 319998.0 | 3.8413 | 0.8364 | 0.8097 | 0.8228 |
| event_near | 10 | persistence | 319998.0 | 5.4328 | 0.7758 | 0.7528 | 0.7641 |
| event_near | 30 | candidate | 323359.0 | 3.8387 | 0.8378 | 0.8089 | 0.8231 |
| event_near | 30 | parent | 323359.0 | 3.8370 | 0.8364 | 0.8124 | 0.8242 |
| event_near | 30 | persistence | 323359.0 | 5.5498 | 0.7765 | 0.7489 | 0.7625 |
| event_near | 60 | candidate | 327124.0 | 3.8266 | 0.8383 | 0.8103 | 0.8241 |
| event_near | 60 | parent | 327124.0 | 3.8357 | 0.8380 | 0.8083 | 0.8229 |
| event_near | 60 | persistence | 327124.0 | 5.6406 | 0.7728 | 0.7398 | 0.7559 |
| event_near | 120 | candidate | 329675.0 | 3.9180 | 0.8386 | 0.8075 | 0.8228 |
| event_near | 120 | persistence | 329675.0 | 5.7906 | 0.7698 | 0.7338 | 0.7514 |
| event_near | 180 | candidate | 324674.0 | 3.9714 | 0.8381 | 0.8001 | 0.8186 |
| event_near | 180 | persistence | 324674.0 | 5.9286 | 0.7641 | 0.7305 | 0.7469 |
| severe | 10 | candidate | 2551200.0 | 6.2530 | 1.0000 | 0.7946 | 0.8855 |
| severe | 10 | parent | 2551200.0 | 6.2657 | 1.0000 | 0.7908 | 0.8832 |
| severe | 10 | persistence | 2551200.0 | 8.4153 | 1.0000 | 0.7131 | 0.8325 |
| severe | 30 | candidate | 2567781.0 | 6.2846 | 1.0000 | 0.7933 | 0.8847 |
| severe | 30 | parent | 2567781.0 | 6.2956 | 1.0000 | 0.7914 | 0.8835 |
| severe | 30 | persistence | 2567781.0 | 8.4055 | 1.0000 | 0.7126 | 0.8322 |
| severe | 60 | candidate | 2577253.0 | 6.2895 | 1.0000 | 0.7938 | 0.8851 |
| severe | 60 | parent | 2577253.0 | 6.3114 | 1.0000 | 0.7904 | 0.8829 |
| severe | 60 | persistence | 2577253.0 | 8.4530 | 1.0000 | 0.7118 | 0.8317 |
| severe | 120 | candidate | 2565162.0 | 6.3270 | 1.0000 | 0.7939 | 0.8851 |
| severe | 120 | persistence | 2565162.0 | 8.4996 | 1.0000 | 0.7103 | 0.8306 |
| severe | 180 | candidate | 2512639.0 | 6.4432 | 1.0000 | 0.7915 | 0.8836 |
| severe | 180 | persistence | 2512639.0 | 8.5944 | 1.0000 | 0.7086 | 0.8295 |

Anticipation (clear near roads, issued up to 3 h before start/end) by event lead at issue x target horizon; a +180 min target issued 10 min before opening is not a 3-hour warning:

| lead_cat | hgroup | system | labels | tt_mae_s | positives | precision | recall | f1 |
|---|---|---|---|---|---|---|---|---|
| end_0_60 | 0-60 | candidate | 119500.0 | 1.8083 | 7389.0 | 0.6970 | 0.5109 | 0.5896 |
| end_0_60 | 0-60 | parent | 119500.0 | 1.7972 | 7389.0 | 0.6982 | 0.5013 | 0.5836 |
| end_0_60 | 0-60 | persistence | 119500.0 | 2.4550 | 7389.0 | – | 0.0000 | – |
| end_0_60 | 60-120 | candidate | 111760.0 | 1.8889 | 5963.0 | 0.6461 | 0.4546 | 0.5337 |
| end_0_60 | 60-120 | parent | 0.0000 | – | 0.0000 | – | – | – |
| end_0_60 | 60-120 | persistence | 111760.0 | 2.3739 | 5963.0 | – | 0.0000 | – |
| end_0_60 | 120-180 | candidate | 104286.0 | 1.6952 | 4425.0 | 0.5868 | 0.4079 | 0.4813 |
| end_0_60 | 120-180 | parent | 0.0000 | – | 0.0000 | – | – | – |
| end_0_60 | 120-180 | persistence | 104286.0 | 1.9927 | 4425.0 | – | 0.0000 | – |
| end_0_60 | 180-240 | candidate | 0.0000 | – | 0.0000 | – | – | – |
| end_0_60 | 180-240 | parent | 0.0000 | – | 0.0000 | – | – | – |
| end_0_60 | 180-240 | persistence | 0.0000 | – | 0.0000 | – | – | – |
| end_0_60 | 240-300 | candidate | 0.0000 | – | 0.0000 | – | – | – |
| end_0_60 | 240-300 | parent | 0.0000 | – | 0.0000 | – | – | – |
| end_0_60 | 240-300 | persistence | 0.0000 | – | 0.0000 | – | – | – |
| end_120_180 | 0-60 | candidate | 116295.0 | 1.6690 | 5901.0 | 0.6564 | 0.4623 | 0.5425 |
| end_120_180 | 0-60 | parent | 116295.0 | 1.6651 | 5901.0 | 0.6519 | 0.4764 | 0.5505 |
| end_120_180 | 0-60 | persistence | 116295.0 | 2.1567 | 5901.0 | – | 0.0000 | – |
| end_120_180 | 60-120 | candidate | 115396.0 | 1.7457 | 5851.0 | 0.6412 | 0.4724 | 0.5440 |
| end_120_180 | 60-120 | parent | 0.0000 | – | 0.0000 | – | – | – |
| end_120_180 | 60-120 | persistence | 115396.0 | 2.2073 | 5851.0 | – | 0.0000 | – |
| end_120_180 | 120-180 | candidate | 119962.0 | 1.8009 | 7264.0 | 0.6963 | 0.4986 | 0.5811 |
| end_120_180 | 120-180 | parent | 0.0000 | – | 0.0000 | – | – | – |
| end_120_180 | 120-180 | persistence | 119962.0 | 2.4440 | 7264.0 | – | 0.0000 | – |
| end_120_180 | 180-240 | candidate | 0.0000 | – | 0.0000 | – | – | – |
| end_120_180 | 180-240 | parent | 0.0000 | – | 0.0000 | – | – | – |
| end_120_180 | 180-240 | persistence | 0.0000 | – | 0.0000 | – | – | – |
| end_120_180 | 240-300 | candidate | 0.0000 | – | 0.0000 | – | – | – |
| end_120_180 | 240-300 | parent | 0.0000 | – | 0.0000 | – | – | – |
| end_120_180 | 240-300 | persistence | 0.0000 | – | 0.0000 | – | – | – |
| end_60_120 | 0-60 | candidate | 115602.0 | 1.7703 | 6340.0 | 0.6465 | 0.4798 | 0.5508 |
| end_60_120 | 0-60 | parent | 115602.0 | 1.7682 | 6340.0 | 0.6509 | 0.4935 | 0.5614 |
| end_60_120 | 0-60 | persistence | 115602.0 | 2.2767 | 6340.0 | – | 0.0000 | – |
| end_60_120 | 60-120 | candidate | 119960.0 | 1.8232 | 7832.0 | 0.7080 | 0.5101 | 0.5929 |
| end_60_120 | 60-120 | parent | 0.0000 | – | 0.0000 | – | – | – |
| end_60_120 | 60-120 | persistence | 119960.0 | 2.5138 | 7832.0 | – | 0.0000 | – |
| end_60_120 | 120-180 | candidate | 112535.0 | 1.9095 | 6256.0 | 0.6550 | 0.4516 | 0.5346 |
| end_60_120 | 120-180 | parent | 0.0000 | – | 0.0000 | – | – | – |
| end_60_120 | 120-180 | persistence | 112535.0 | 2.4121 | 6256.0 | – | 0.0000 | – |
| end_60_120 | 180-240 | candidate | 0.0000 | – | 0.0000 | – | – | – |
| end_60_120 | 180-240 | parent | 0.0000 | – | 0.0000 | – | – | – |
| end_60_120 | 180-240 | persistence | 0.0000 | – | 0.0000 | – | – | – |
| end_60_120 | 240-300 | candidate | 0.0000 | – | 0.0000 | – | – | – |
| end_60_120 | 240-300 | parent | 0.0000 | – | 0.0000 | – | – | – |
| end_60_120 | 240-300 | persistence | 0.0000 | – | 0.0000 | – | – | – |
| start_0_60 | 0-60 | candidate | 103604.0 | 1.7934 | 6384.0 | 0.6483 | 0.4900 | 0.5581 |
| start_0_60 | 0-60 | parent | 103604.0 | 1.7937 | 6384.0 | 0.6565 | 0.4712 | 0.5486 |
| start_0_60 | 0-60 | persistence | 103604.0 | 2.3556 | 6384.0 | – | 0.0000 | – |
| start_0_60 | 60-120 | candidate | 110104.0 | 1.9945 | 7652.0 | 0.7163 | 0.5078 | 0.5943 |
| start_0_60 | 60-120 | parent | 0.0000 | – | 0.0000 | – | – | – |
| start_0_60 | 60-120 | persistence | 110104.0 | 2.7978 | 7652.0 | – | 0.0000 | – |
| start_0_60 | 120-180 | candidate | 108701.0 | 2.2729 | 7562.0 | 0.7304 | 0.5094 | 0.6002 |
| start_0_60 | 120-180 | parent | 0.0000 | – | 0.0000 | – | – | – |
| start_0_60 | 120-180 | persistence | 108701.0 | 3.0514 | 7562.0 | – | 0.0000 | – |
| start_0_60 | 180-240 | candidate | 0.0000 | – | 0.0000 | – | – | – |
| start_0_60 | 180-240 | parent | 0.0000 | – | 0.0000 | – | – | – |
| start_0_60 | 180-240 | persistence | 0.0000 | – | 0.0000 | – | – | – |
| start_0_60 | 240-300 | candidate | 0.0000 | – | 0.0000 | – | – | – |
| start_0_60 | 240-300 | parent | 0.0000 | – | 0.0000 | – | – | – |
| start_0_60 | 240-300 | persistence | 0.0000 | – | 0.0000 | – | – | – |
| start_120_180 | 0-60 | candidate | 91602.0 | 2.0284 | 5948.0 | 0.6440 | 0.4936 | 0.5589 |
| start_120_180 | 0-60 | parent | 91602.0 | 2.0323 | 5948.0 | 0.6399 | 0.4887 | 0.5542 |
| start_120_180 | 0-60 | persistence | 91602.0 | 2.5296 | 5948.0 | – | 0.0000 | – |
| start_120_180 | 60-120 | candidate | 94003.0 | 1.9541 | 6368.0 | 0.6480 | 0.5030 | 0.5664 |
| start_120_180 | 60-120 | parent | 0.0000 | – | 0.0000 | – | – | – |
| start_120_180 | 60-120 | persistence | 94003.0 | 2.5114 | 6368.0 | – | 0.0000 | – |
| start_120_180 | 120-180 | candidate | 98939.0 | 1.9063 | 7239.0 | 0.6931 | 0.5292 | 0.6002 |
| start_120_180 | 120-180 | parent | 0.0000 | – | 0.0000 | – | – | – |
| start_120_180 | 120-180 | persistence | 98939.0 | 2.6225 | 7239.0 | – | 0.0000 | – |
| start_120_180 | 180-240 | candidate | 0.0000 | – | 0.0000 | – | – | – |
| start_120_180 | 180-240 | parent | 0.0000 | – | 0.0000 | – | – | – |
| start_120_180 | 180-240 | persistence | 0.0000 | – | 0.0000 | – | – | – |
| start_120_180 | 240-300 | candidate | 0.0000 | – | 0.0000 | – | – | – |
| start_120_180 | 240-300 | parent | 0.0000 | – | 0.0000 | – | – | – |
| start_120_180 | 240-300 | persistence | 0.0000 | – | 0.0000 | – | – | – |
| start_60_120 | 0-60 | candidate | 96652.0 | 1.9486 | 5944.0 | 0.6274 | 0.4876 | 0.5487 |
| start_60_120 | 0-60 | parent | 96652.0 | 1.9543 | 5944.0 | 0.6283 | 0.4817 | 0.5453 |
| start_60_120 | 0-60 | persistence | 96652.0 | 2.4590 | 5944.0 | – | 0.0000 | – |
| start_60_120 | 60-120 | candidate | 101570.0 | 1.8405 | 6835.0 | 0.6740 | 0.5191 | 0.5865 |
| start_60_120 | 60-120 | parent | 0.0000 | – | 0.0000 | – | – | – |
| start_60_120 | 60-120 | persistence | 101570.0 | 2.4959 | 6835.0 | – | 0.0000 | – |
| start_60_120 | 120-180 | candidate | 107952.0 | 2.1245 | 8156.0 | 0.7440 | 0.5369 | 0.6237 |
| start_60_120 | 120-180 | parent | 0.0000 | – | 0.0000 | – | – | – |
| start_60_120 | 120-180 | persistence | 107952.0 | 3.0195 | 8156.0 | – | 0.0000 | – |
| start_60_120 | 180-240 | candidate | 0.0000 | – | 0.0000 | – | – | – |
| start_60_120 | 180-240 | parent | 0.0000 | – | 0.0000 | – | – | – |
| start_60_120 | 180-240 | persistence | 0.0000 | – | 0.0000 | – | – | – |
| start_60_120 | 240-300 | candidate | 0.0000 | – | 0.0000 | – | – | – |
| start_60_120 | 240-300 | parent | 0.0000 | – | 0.0000 | – | – | – |
| start_60_120 | 240-300 | persistence | 0.0000 | – | 0.0000 | – | – | – |

## Portola held-out test (reused)

First-hour guardrail vs the parent (same windows, its own 6 horizons): `{"first_hour_citywide_rel": -0.0015301227301520973, "first_hour_control_rel": -0.002538796250172442, "first_hour_severe_rel": -0.0016019059072851813, "first_hour_safe": true}`

First hour (horizons 10-60 min):

| stratum | system | labels | tt_mae_s | tt_wape | speed_mae_mph | cong_mae | positives | precision | recall | f1 |
|---|---|---|---|---|---|---|---|---|---|---|
| all | candidate | 28158376.0 | 2.1415 | 0.1333 | 1.6036 | 0.0631 | 6018169.0 | 0.8642 | 0.7940 | 0.8276 |
| all | parent | 28158376.0 | 2.1448 | 0.1335 | 1.6043 | 0.0631 | 6018169.0 | 0.8648 | 0.7925 | 0.8271 |
| all | persistence | 28158376.0 | 3.2167 | 0.2002 | 2.5828 | 0.1015 | 6018169.0 | 0.7731 | 0.7331 | 0.7526 |
| antic | candidate | 123580.0 | 3.9159 | 0.2055 | 1.6634 | 0.0611 | 3667.0 | 0.6716 | 0.1974 | 0.3052 |
| antic | parent | 123580.0 | 3.9154 | 0.2055 | 1.6670 | 0.0613 | 3667.0 | 0.6793 | 0.2010 | 0.3102 |
| antic | persistence | 123580.0 | 4.3345 | 0.2275 | 2.2809 | 0.0832 | 3667.0 | – | 0.0000 | – |
| antic_pre_start | candidate | 123580.0 | 3.9159 | 0.2055 | 1.6634 | 0.0611 | 3667.0 | 0.6716 | 0.1974 | 0.3052 |
| antic_pre_start | parent | 123580.0 | 3.9154 | 0.2055 | 1.6670 | 0.0613 | 3667.0 | 0.6793 | 0.2010 | 0.3102 |
| antic_pre_start | persistence | 123580.0 | 4.3345 | 0.2275 | 2.2809 | 0.0832 | 3667.0 | – | 0.0000 | – |
| antic_strict | candidate | 95730.0 | 3.3697 | 0.1852 | 1.5360 | 0.0556 | 1885.0 | 0.6495 | 0.0737 | 0.1324 |
| antic_strict | parent | 95730.0 | 3.3700 | 0.1852 | 1.5389 | 0.0558 | 1885.0 | 0.6585 | 0.0716 | 0.1292 |
| antic_strict | persistence | 95730.0 | 3.6671 | 0.2015 | 1.9642 | 0.0702 | 1885.0 | – | 0.0000 | – |
| control_runs | candidate | 13907998.0 | 2.0524 | 0.1288 | 1.6145 | 0.0635 | 2960209.0 | 0.8630 | 0.7937 | 0.8269 |
| control_runs | parent | 13907998.0 | 2.0576 | 0.1291 | 1.6151 | 0.0635 | 2960209.0 | 0.8637 | 0.7920 | 0.8263 |
| control_runs | persistence | 13907998.0 | 3.1183 | 0.1956 | 2.6077 | 0.1024 | 2960209.0 | 0.7712 | 0.7316 | 0.7509 |
| event_far | candidate | 11336576.0 | 2.1173 | 0.1311 | 1.5935 | 0.0629 | 2355512.0 | 0.8626 | 0.7913 | 0.8255 |
| event_far | parent | 11336576.0 | 2.1242 | 0.1315 | 1.5953 | 0.0630 | 2355512.0 | 0.8639 | 0.7889 | 0.8247 |
| event_far | persistence | 11336576.0 | 3.2136 | 0.1989 | 2.5714 | 0.1014 | 2355512.0 | 0.7698 | 0.7293 | 0.7490 |
| event_near | candidate | 371736.0 | 7.7033 | 0.3598 | 1.8526 | 0.0699 | 61414.0 | 0.8503 | 0.6679 | 0.7481 |
| event_near | parent | 371736.0 | 7.5150 | 0.3510 | 1.8224 | 0.0688 | 61414.0 | 0.8332 | 0.6953 | 0.7581 |
| event_near | persistence | 371736.0 | 9.0571 | 0.4230 | 2.6061 | 0.0986 | 61414.0 | 0.7362 | 0.6627 | 0.6975 |
| event_runs | candidate | 14250378.0 | 2.2284 | 0.1376 | 1.5930 | 0.0627 | 3057960.0 | 0.8653 | 0.7944 | 0.8283 |
| event_runs | parent | 14250378.0 | 2.2298 | 0.1377 | 1.5938 | 0.0627 | 3057960.0 | 0.8658 | 0.7931 | 0.8279 |
| event_runs | persistence | 14250378.0 | 3.3127 | 0.2045 | 2.5585 | 0.1006 | 3057960.0 | 0.7751 | 0.7345 | 0.7542 |
| near_missing_history | candidate | 61985.0 | 2.8066 | 0.1629 | 1.8939 | 0.0737 | 8620.0 | 0.8224 | 0.6878 | 0.7491 |
| near_missing_history | parent | 61985.0 | 2.7935 | 0.1621 | 1.8903 | 0.0736 | 8620.0 | 0.8008 | 0.7075 | 0.7513 |
| near_missing_history | persistence | 61985.0 | 4.2980 | 0.2494 | 4.1295 | 0.1610 | 8620.0 | 0.6845 | 0.4992 | 0.5774 |
| severe | candidate | 6018169.0 | 4.9322 | 0.2725 | 1.5766 | 0.0630 | 6018169.0 | 1.0000 | 0.7940 | 0.8852 |
| severe | parent | 6018169.0 | 4.9401 | 0.2730 | 1.5873 | 0.0635 | 6018169.0 | 1.0000 | 0.7925 | 0.8843 |
| severe | persistence | 6018169.0 | 6.3978 | 0.3535 | 3.0565 | 0.1220 | 6018169.0 | 1.0000 | 0.7331 | 0.8460 |

Hours 2-3 (horizons 70-180 min; the parent has no forecast here):

| stratum | system | labels | tt_mae_s | tt_wape | speed_mae_mph | cong_mae | positives | precision | recall | f1 |
|---|---|---|---|---|---|---|---|---|---|---|
| all | candidate | 57314483.0 | 2.1580 | 0.1338 | 1.5890 | 0.0625 | 12276007.0 | 0.8653 | 0.7965 | 0.8294 |
| all | persistence | 57314483.0 | 3.2817 | 0.2036 | 2.5979 | 0.1021 | 12276007.0 | 0.7744 | 0.7303 | 0.7517 |
| antic | candidate | 258939.0 | 10.3 | 0.4007 | 2.0843 | 0.0768 | 14644.0 | 0.7747 | 0.1303 | 0.2231 |
| antic | persistence | 258939.0 | 10.8 | 0.4206 | 2.8480 | 0.1043 | 14644.0 | – | 0.0000 | – |
| antic_pre_start | candidate | 258939.0 | 10.3 | 0.4007 | 2.0843 | 0.0768 | 14644.0 | 0.7747 | 0.1303 | 0.2231 |
| antic_pre_start | persistence | 258939.0 | 10.8 | 0.4206 | 2.8480 | 0.1043 | 14644.0 | – | 0.0000 | – |
| antic_strict | candidate | 195935.0 | 10.6 | 0.4151 | 2.0530 | 0.0746 | 9475.0 | 0.7366 | 0.0393 | 0.0745 |
| antic_strict | persistence | 195935.0 | 11.0 | 0.4288 | 2.5757 | 0.0927 | 9475.0 | – | 0.0000 | – |
| control_runs | candidate | 28227351.0 | 2.0404 | 0.1279 | 1.5998 | 0.0630 | 6008418.0 | 0.8636 | 0.7970 | 0.8290 |
| control_runs | persistence | 28227351.0 | 3.1221 | 0.1957 | 2.6112 | 0.1026 | 6008418.0 | 0.7720 | 0.7310 | 0.7510 |
| event_far | candidate | 23079645.0 | 2.0980 | 0.1297 | 1.5747 | 0.0622 | 4809172.0 | 0.8649 | 0.7931 | 0.8275 |
| event_far | persistence | 23079645.0 | 3.2243 | 0.1993 | 2.5826 | 0.1019 | 4809172.0 | 0.7720 | 0.7269 | 0.7488 |
| event_near | candidate | 791810.0 | 9.9556 | 0.4187 | 2.0403 | 0.0769 | 141502.0 | 0.8262 | 0.6372 | 0.7195 |
| event_near | persistence | 791810.0 | 13.1 | 0.5490 | 3.0930 | 0.1171 | 141502.0 | 0.7063 | 0.5696 | 0.6306 |
| event_runs | candidate | 29087132.0 | 2.2721 | 0.1395 | 1.5786 | 0.0621 | 6267589.0 | 0.8669 | 0.7960 | 0.8299 |
| event_runs | persistence | 29087132.0 | 3.4366 | 0.2110 | 2.5851 | 0.1017 | 6267589.0 | 0.7766 | 0.7297 | 0.7524 |
| near_missing_history | candidate | 156004.0 | 5.5381 | 0.2724 | 1.9496 | 0.0763 | 24433.0 | 0.8248 | 0.6544 | 0.7298 |
| near_missing_history | persistence | 156004.0 | 7.1845 | 0.3533 | 4.5533 | 0.1781 | 24433.0 | 0.6933 | 0.4200 | 0.5231 |
| severe | candidate | 12276007.0 | 5.0473 | 0.2774 | 1.5798 | 0.0631 | 12276007.0 | 1.0000 | 0.7965 | 0.8867 |
| severe | persistence | 12276007.0 | 6.6100 | 0.3632 | 3.1098 | 0.1240 | 12276007.0 | 1.0000 | 0.7303 | 0.8441 |

By target horizon (selected):

| stratum | horizon_min | system | labels | tt_mae_s | precision | recall | f1 |
|---|---|---|---|---|---|---|---|
| all | 10 | candidate | 4649585.0 | 2.1298 | 0.8626 | 0.7942 | 0.8270 |
| all | 10 | parent | 4649585.0 | 2.1313 | 0.8639 | 0.7920 | 0.8264 |
| all | 10 | persistence | 4649585.0 | 3.1576 | 0.7727 | 0.7340 | 0.7529 |
| all | 30 | candidate | 4685652.0 | 2.1400 | 0.8642 | 0.7942 | 0.8277 |
| all | 30 | parent | 4685652.0 | 2.1430 | 0.8642 | 0.7934 | 0.8273 |
| all | 30 | persistence | 4685652.0 | 3.2079 | 0.7736 | 0.7337 | 0.7531 |
| all | 60 | candidate | 4734829.0 | 2.1548 | 0.8646 | 0.7952 | 0.8285 |
| all | 60 | parent | 4734829.0 | 2.1590 | 0.8658 | 0.7929 | 0.8277 |
| all | 60 | persistence | 4734829.0 | 3.2439 | 0.7737 | 0.7319 | 0.7522 |
| all | 120 | candidate | 4781410.0 | 2.1563 | 0.8655 | 0.7968 | 0.8298 |
| all | 120 | persistence | 4781410.0 | 3.2743 | 0.7749 | 0.7303 | 0.7520 |
| all | 180 | candidate | 4778646.0 | 2.1623 | 0.8653 | 0.7969 | 0.8297 |
| all | 180 | persistence | 4778646.0 | 3.2924 | 0.7743 | 0.7300 | 0.7515 |
| antic | 10 | candidate | 20110.0 | 1.7251 | 0.6230 | 0.2585 | 0.3654 |
| antic | 10 | parent | 20110.0 | 1.7273 | 0.6203 | 0.2630 | 0.3694 |
| antic | 10 | persistence | 20110.0 | 2.1025 | – | 0.0000 | – |
| antic | 30 | candidate | 20548.0 | 3.7581 | 0.6593 | 0.2102 | 0.3187 |
| antic | 30 | parent | 20548.0 | 3.7571 | 0.6776 | 0.2172 | 0.3289 |
| antic | 30 | persistence | 20548.0 | 4.1693 | – | 0.0000 | – |
| antic | 60 | candidate | 21073.0 | 6.0053 | 0.7016 | 0.1634 | 0.2651 |
| antic | 60 | parent | 21073.0 | 6.0063 | 0.7021 | 0.1610 | 0.2619 |
| antic | 60 | persistence | 21073.0 | 6.4737 | – | 0.0000 | – |
| antic | 120 | candidate | 21701.0 | 10.8 | 0.7772 | 0.1251 | 0.2155 |
| antic | 120 | persistence | 21701.0 | 11.3 | – | 0.0000 | – |
| antic | 180 | candidate | 21497.0 | 11.6 | 0.7964 | 0.1341 | 0.2296 |
| antic | 180 | persistence | 21497.0 | 12.1 | – | 0.0000 | – |
| event_near | 10 | candidate | 59736.0 | 6.5397 | 0.8557 | 0.6878 | 0.7627 |
| event_near | 10 | parent | 59736.0 | 6.2914 | 0.8345 | 0.7238 | 0.7752 |
| event_near | 10 | persistence | 59736.0 | 6.1352 | 0.7504 | 0.7083 | 0.7288 |
| event_near | 30 | candidate | 61632.0 | 7.5354 | 0.8498 | 0.6690 | 0.7486 |
| event_near | 30 | parent | 61632.0 | 7.3348 | 0.8323 | 0.7014 | 0.7612 |
| event_near | 30 | persistence | 61632.0 | 8.9562 | 0.7371 | 0.6676 | 0.7006 |
| event_near | 60 | candidate | 63988.0 | 8.7926 | 0.8453 | 0.6542 | 0.7376 |
| event_near | 60 | parent | 63988.0 | 8.6474 | 0.8330 | 0.6709 | 0.7432 |
| event_near | 60 | persistence | 63988.0 | 11.0 | 0.7286 | 0.6277 | 0.6744 |
| event_near | 120 | candidate | 66377.0 | 10.1 | 0.8269 | 0.6314 | 0.7161 |
| event_near | 120 | persistence | 66377.0 | 13.2 | 0.7063 | 0.5642 | 0.6273 |
| event_near | 180 | candidate | 65714.0 | 10.2 | 0.8031 | 0.6436 | 0.7146 |
| event_near | 180 | persistence | 65714.0 | 13.8 | 0.6859 | 0.5493 | 0.6100 |
| severe | 10 | candidate | 992346.0 | 4.8463 | 1.0000 | 0.7942 | 0.8853 |
| severe | 10 | parent | 992346.0 | 4.8483 | 1.0000 | 0.7920 | 0.8839 |
| severe | 10 | persistence | 992346.0 | 6.2187 | 1.0000 | 0.7340 | 0.8466 |
| severe | 30 | candidate | 1001369.0 | 4.9235 | 1.0000 | 0.7942 | 0.8853 |
| severe | 30 | parent | 1001369.0 | 4.9295 | 1.0000 | 0.7934 | 0.8848 |
| severe | 30 | persistence | 1001369.0 | 6.3771 | 1.0000 | 0.7337 | 0.8464 |
| severe | 60 | candidate | 1013106.0 | 5.0118 | 1.0000 | 0.7952 | 0.8859 |
| severe | 60 | parent | 1013106.0 | 5.0269 | 1.0000 | 0.7929 | 0.8845 |
| severe | 60 | persistence | 1013106.0 | 6.4825 | 1.0000 | 0.7319 | 0.8452 |
| severe | 120 | candidate | 1024724.0 | 5.0427 | 1.0000 | 0.7968 | 0.8869 |
| severe | 120 | persistence | 1024724.0 | 6.6055 | 1.0000 | 0.7303 | 0.8442 |
| severe | 180 | candidate | 1023481.0 | 5.0701 | 1.0000 | 0.7969 | 0.8870 |
| severe | 180 | persistence | 1023481.0 | 6.6293 | 1.0000 | 0.7300 | 0.8439 |

Anticipation (clear near roads, issued up to 3 h before start/end) by event lead at issue x target horizon; a +180 min target issued 10 min before opening is not a 3-hour warning:

| lead_cat | hgroup | system | labels | tt_mae_s | positives | precision | recall | f1 |
|---|---|---|---|---|---|---|---|---|
| start_0_60 | 0-60 | candidate | 45921.0 | 6.4456 | 1743.0 | 0.7123 | 0.1193 | 0.2044 |
| start_0_60 | 0-60 | parent | 45921.0 | 6.4394 | 1743.0 | 0.7199 | 0.1268 | 0.2156 |
| start_0_60 | 0-60 | persistence | 45921.0 | 6.8252 | 1743.0 | – | 0.0000 | – |
| start_0_60 | 60-120 | candidate | 46661.0 | 9.4935 | 2382.0 | 0.7373 | 0.1037 | 0.1818 |
| start_0_60 | 60-120 | parent | 0.0000 | – | 0.0000 | – | – | – |
| start_0_60 | 60-120 | persistence | 46661.0 | 9.9201 | 2382.0 | – | 0.0000 | – |
| start_0_60 | 120-180 | candidate | 45116.0 | 7.7771 | 2094.0 | 0.8101 | 0.1304 | 0.2246 |
| start_0_60 | 120-180 | parent | 0.0000 | – | 0.0000 | – | – | – |
| start_0_60 | 120-180 | persistence | 45116.0 | 8.1904 | 2094.0 | – | 0.0000 | – |
| start_0_60 | 180-240 | candidate | 0.0000 | – | 0.0000 | – | – | – |
| start_0_60 | 180-240 | parent | 0.0000 | – | 0.0000 | – | – | – |
| start_0_60 | 180-240 | persistence | 0.0000 | – | 0.0000 | – | – | – |
| start_0_60 | 240-300 | candidate | 0.0000 | – | 0.0000 | – | – | – |
| start_0_60 | 240-300 | parent | 0.0000 | – | 0.0000 | – | – | – |
| start_0_60 | 240-300 | persistence | 0.0000 | – | 0.0000 | – | – | – |
| start_120_180 | 0-60 | candidate | 34914.0 | 1.6049 | 681.0 | 0.6032 | 0.3906 | 0.4742 |
| start_120_180 | 0-60 | parent | 34914.0 | 1.6085 | 681.0 | 0.6197 | 0.3877 | 0.4770 |
| start_120_180 | 0-60 | persistence | 34914.0 | 2.0465 | 681.0 | – | 0.0000 | – |
| start_120_180 | 60-120 | candidate | 37526.0 | 4.7551 | 1518.0 | 0.7075 | 0.2246 | 0.3410 |
| start_120_180 | 60-120 | parent | 0.0000 | – | 0.0000 | – | – | – |
| start_120_180 | 60-120 | persistence | 37526.0 | 5.2866 | 1518.0 | – | 0.0000 | – |
| start_120_180 | 120-180 | candidate | 39275.0 | 14.5 | 2932.0 | 0.7710 | 0.1344 | 0.2289 |
| start_120_180 | 120-180 | parent | 0.0000 | – | 0.0000 | – | – | – |
| start_120_180 | 120-180 | persistence | 39275.0 | 15.1 | 2932.0 | – | 0.0000 | – |
| start_120_180 | 180-240 | candidate | 0.0000 | – | 0.0000 | – | – | – |
| start_120_180 | 180-240 | parent | 0.0000 | – | 0.0000 | – | – | – |
| start_120_180 | 180-240 | persistence | 0.0000 | – | 0.0000 | – | – | – |
| start_120_180 | 240-300 | candidate | 0.0000 | – | 0.0000 | – | – | – |
| start_120_180 | 240-300 | parent | 0.0000 | – | 0.0000 | – | – | – |
| start_120_180 | 240-300 | persistence | 0.0000 | – | 0.0000 | – | – | – |
| start_60_120 | 0-60 | candidate | 42745.0 | 3.0857 | 1243.0 | 0.7246 | 0.2011 | 0.3149 |
| start_60_120 | 0-60 | parent | 42745.0 | 3.0880 | 1243.0 | 0.7159 | 0.2027 | 0.3160 |
| start_60_120 | 0-60 | persistence | 42745.0 | 3.5277 | 1243.0 | – | 0.0000 | – |
| start_60_120 | 60-120 | candidate | 44896.0 | 12.0 | 2715.0 | 0.8027 | 0.1094 | 0.1925 |
| start_60_120 | 60-120 | parent | 0.0000 | – | 0.0000 | – | – | – |
| start_60_120 | 60-120 | persistence | 44896.0 | 12.5 | 2715.0 | – | 0.0000 | – |
| start_60_120 | 120-180 | candidate | 45465.0 | 13.0 | 3003.0 | 0.8318 | 0.1185 | 0.2075 |
| start_60_120 | 120-180 | parent | 0.0000 | – | 0.0000 | – | – | – |
| start_60_120 | 120-180 | persistence | 45465.0 | 13.5 | 3003.0 | – | 0.0000 | – |
| start_60_120 | 180-240 | candidate | 0.0000 | – | 0.0000 | – | – | – |
| start_60_120 | 180-240 | parent | 0.0000 | – | 0.0000 | – | – | – |
| start_60_120 | 180-240 | persistence | 0.0000 | – | 0.0000 | – | – | – |
| start_60_120 | 240-300 | candidate | 0.0000 | – | 0.0000 | – | – | – |
| start_60_120 | 240-300 | parent | 0.0000 | – | 0.0000 | – | – | – |
| start_60_120 | 240-300 | persistence | 0.0000 | – | 0.0000 | – | – | – |

## Limitations

- No matched no-event model was trained (user decision), so the event branch's own contribution at long horizons is not isolated; comparisons are vs persistence and the 60-min parent's first hour.
- One validation (Bearrison) and one reused test group (Portola, before-start side only).
- Hidden demand factors (realised attendance, arrival curves) are not model inputs; long-horizon error has an irreducible floor from them.
- Paired event-minus-control impact metrics were not computed in this pass.

## Reproduce

```
python -m eventsim.citywide_batch plan --batch b4_long_event --families-per-event 8 --seeds 2 --seed 41 --events folsom portola sunday_streets_excelsior bearrison halloween_cortland chinatown_night_market potrero_hill_festival --windows arrival departure --horizon-min 180
python -m forecast audit --config configs/event_patch_v4_h18.yaml
python -m forecast prepare --config configs/event_patch_v4_h18.yaml --workers 24
python -m forecast retrain --config configs/event_patch_v4_h18.yaml --parent /opt/tp/transpeaktation/ml/data/forecast/experiments/event_patch_v2_main/best.pt
python -m forecast evaluate-retrain --checkpoint event_patch_v4_h18_full/best.pt --partition test
```
