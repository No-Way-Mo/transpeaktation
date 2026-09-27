# Event-awareness fine-tuning (v3)

> **Synthetic.** SUMO scenarios on real SF roads/permits; demand and attendance are assumptions. Nothing here is validated on measured event traffic. Road/bucket labels overlap and are not independent trials.

## Identity

- Parent: `data/forecast/experiments/event_patch_v2_main/best.pt` (sha256 `45e075b4befa7d5e…`, best epoch 23); no-event reference: `data/forecast/experiments/event_patch_v2_main_noevent/best.pt`
- Dataset `b3_main_v3net_ep2` (manifest `101c3f1a8ec5…`, split `3697c9dc449c…`), 26408 roads, network `net_v3-eb5d68e9cb9b`; the parent's normalisation is used throughout.
- Fine-tuning spec digest `862d9817b0d5ff33`: `configs/event_patch_v3_awareness.yaml`

## Recommendation

**Keep the parent.** No candidate passed the predeclared validation rule; the best guardrail-safe candidate `event_patch_v3_awareness` is kept for experiments only and shown on Portola for information.

## Stage A: event branch only (`event_patch_v3_awareness`)

- Stage `event`, initialised from `/opt/tp/transpeaktation/ml/data/forecast/experiments/event_patch_v2_main/best.pt`; trainable parameters 84,672 of 372,097; loss weights `{"global": 1.0, "event_near": 1.0, "anticipation": 2.0, "preserve": 0.5, "pair": 0.0}`.
- Frozen-tensor check after training: 127 frozen tensors, changed: none; trainable tensors changed: 30/30.
- Epochs 5 (early stop), 1162 s on NVIDIA L40S, peak GPU 6219.0 MB; selected epoch 2; **promote: False**.

Validation (Bearrison) per epoch (travel-time MAE s; anticipation = directly observed clear near roads in the hour before public start/end):

| epoch | train_total | train_global | train_event_near | train_anticipation | train_preserve | val_citywide_tt_mae | val_control_tt_mae | val_severe_tt_mae | val_event_near_tt_mae | val_antic_tt_mae | val_antic_precision | val_antic_recall | guard_safe | guard_promote | seconds |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.0556 | 0.0283 | 0.0141 | 0.0066 | 0.0000 | 2.5348 | 2.5263 | 5.5532 | 3.7258 | 1.6794 | 0.6648 | 0.4663 | yes | no | 248.0 |
| 2 | 0.0551 | 0.0282 | 0.0139 | 0.0065 | 0.0000 | 2.5347 | 2.5266 | 5.5724 | 3.7179 | 1.6672 | 0.6692 | 0.4570 | yes | no | 242.9 |
| 3 | 0.0553 | 0.0282 | 0.0139 | 0.0066 | 0.0000 | 2.5342 | 2.5258 | 5.5729 | 3.7213 | 1.6726 | 0.6671 | 0.4577 | yes | no | 226.4 |
| 4 | 0.0554 | 0.0283 | 0.0140 | 0.0066 | 0.0000 | 2.5342 | 2.5258 | 5.5718 | 3.7205 | 1.6713 | 0.6694 | 0.4557 | yes | no | 221.3 |
| 5 | 0.0553 | 0.0282 | 0.0139 | 0.0066 | 0.0000 | 2.5345 | 2.5262 | 5.5765 | 3.7184 | 1.6686 | 0.6707 | 0.4562 | yes | no | 223.3 |

Parent on the same validation masks: `{"citywide_tt_mae": 2.5382020485201053, "control_tt_mae": 2.52997880913829, "severe_tt_mae": 5.590856162422249, "event_near_tt_mae": 3.718421531711203, "antic_tt_mae": 1.6629360928565031, "antic_precision": 0.6767265321236808, "antic_recall": 0.44236006051437216, "antic_f1": 0.5350020126614703, "antic_labels": 342686, "antic_positives": 16525}`

### Training / validation support (event runs)

| partition | phase | families | seeds | windows | windows_with_clear_near | clear_near_roads | anticipation_labels | anticipation_positives | anticipation_labels_strict |
|---|---|---|---|---|---|---|---|---|---|
| test | other | 6 | 12 | 348 | 348 | 75232 | 387052 | 9943 | 306954 |
| test | pre_start | 6 | 12 | 54 | 54 | 11578 | 60628 | 1607 | 46871 |
| train | other | 56 | 112 | 1542 | 1542 | 572272 | 2816450 | 110019 | 2088443 |
| train | pre_end | 37 | 74 | 330 | 330 | 119861 | 627758 | 32120 | 450593 |
| train | pre_start | 37 | 74 | 336 | 336 | 115313 | 581428 | 31818 | 411242 |
| val | other | 12 | 24 | 384 | 384 | 167846 | 884168 | 37284 | 698339 |
| val | pre_end | 8 | 16 | 72 | 72 | 31619 | 176754 | 9163 | 136967 |
| val | pre_start | 8 | 16 | 72 | 72 | 30956 | 165932 | 7362 | 126672 |

Pairs: `{"windows": 6276, "event_windows": 3138, "event_windows_with_control": 3138, "event_windows_without_control": 0, "control_windows_without_event": 0}`

## Paired-impact ablation (Stage A + 0.5 L_pair) (`event_patch_v3_awareness_paired`)

- Stage `event`, initialised from `/opt/tp/transpeaktation/ml/data/forecast/experiments/event_patch_v2_main/best.pt`; trainable parameters 84,672 of 372,097; loss weights `{"global": 1.0, "event_near": 1.0, "anticipation": 2.0, "preserve": 0.5, "pair": 0.5}`.
- Frozen-tensor check after training: 127 frozen tensors, changed: none; trainable tensors changed: 30/30.
- Epochs 5 (early stop), 1327 s on NVIDIA L40S, peak GPU 10459.4 MB; selected epoch 2; **promote: False**.

Validation (Bearrison) per epoch (travel-time MAE s; anticipation = directly observed clear near roads in the hour before public start/end):

| epoch | train_total | train_global | train_event_near | train_anticipation | train_preserve | train_pair | val_citywide_tt_mae | val_control_tt_mae | val_severe_tt_mae | val_event_near_tt_mae | val_antic_tt_mae | val_antic_precision | val_antic_recall | guard_safe | guard_promote | seconds |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.0796 | 0.0283 | 0.0141 | 0.0066 | 0.0000 | 0.0385 | 2.5345 | 2.5261 | 5.5539 | 3.7243 | 1.6778 | 0.6646 | 0.4634 | yes | no | 303.3 |
| 2 | 0.0791 | 0.0282 | 0.0139 | 0.0065 | 0.0000 | 0.0381 | 2.5342 | 2.5260 | 5.5706 | 3.7174 | 1.6672 | 0.6691 | 0.4566 | yes | no | 293.2 |
| 3 | 0.0791 | 0.0282 | 0.0139 | 0.0066 | 0.0000 | 0.0379 | 2.5338 | 2.5254 | 5.5707 | 3.7203 | 1.6719 | 0.6677 | 0.4568 | yes | no | 273.8 |
| 4 | 0.0792 | 0.0283 | 0.0140 | 0.0066 | 0.0000 | 0.0376 | 2.5340 | 2.5257 | 5.5723 | 3.7187 | 1.6701 | 0.6697 | 0.4545 | yes | no | 275.6 |
| 5 | 0.0791 | 0.0282 | 0.0139 | 0.0066 | 0.0000 | 0.0376 | 2.5343 | 2.5260 | 5.5752 | 3.7172 | 1.6681 | 0.6707 | 0.4543 | yes | no | 180.5 |

Parent on the same validation masks: `{"citywide_tt_mae": 2.5382040803372545, "control_tt_mae": 2.529984120045907, "severe_tt_mae": 5.5908713375698715, "event_near_tt_mae": 3.718377198634721, "antic_tt_mae": 1.662938788065286, "antic_precision": 0.6767620635361674, "antic_recall": 0.442178517397882, "antic_f1": 0.5348803162286803, "antic_labels": 342686, "antic_positives": 16525}`

## Stage B: event branch + decoder output (`event_patch_v3_awareness_decoder`)

- Stage `decoder`, initialised from `/opt/tp/transpeaktation/ml/data/forecast/experiments/event_patch_v3_awareness/best_candidate.pt`; trainable parameters 89,025 of 372,097; loss weights `{"global": 1.0, "event_near": 1.0, "anticipation": 2.0, "preserve": 0.5, "pair": 0.0}`.
- Frozen-tensor check after training: 121 frozen tensors, changed: none; trainable tensors changed: 36/36.
- Epochs 4 (early stop), 598 s on NVIDIA L40S, peak GPU 6219.0 MB; selected epoch 2; **promote: False**.

Validation (Bearrison) per epoch (travel-time MAE s; anticipation = directly observed clear near roads in the hour before public start/end):

| epoch | train_total | train_global | train_event_near | train_anticipation | train_preserve | val_citywide_tt_mae | val_control_tt_mae | val_severe_tt_mae | val_event_near_tt_mae | val_antic_tt_mae | val_antic_precision | val_antic_recall | guard_safe | guard_promote | seconds |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.0555 | 0.0282 | 0.0141 | 0.0066 | 0.0000 | 2.5341 | 2.5257 | 5.5577 | 3.7212 | 1.6745 | 0.6646 | 0.4654 | yes | no | 168.7 |
| 2 | 0.0550 | 0.0282 | 0.0139 | 0.0064 | 0.0000 | 2.5347 | 2.5265 | 5.5723 | 3.7189 | 1.6683 | 0.6675 | 0.4598 | yes | no | 144.1 |
| 3 | 0.0552 | 0.0282 | 0.0138 | 0.0066 | 0.0000 | 2.5345 | 2.5261 | 5.5759 | 3.7202 | 1.6696 | 0.6681 | 0.4572 | yes | no | 142.7 |
| 4 | 0.0554 | 0.0283 | 0.0140 | 0.0066 | 0.0000 | 2.5340 | 2.5257 | 5.5724 | 3.7191 | 1.6692 | 0.6703 | 0.4558 | yes | no | 142.8 |

Parent on the same validation masks: `{"citywide_tt_mae": 2.5382021932315944, "control_tt_mae": 2.5299778861744, "severe_tt_mae": 5.590854877971425, "event_near_tt_mae": 3.718431285305678, "antic_tt_mae": 1.662966547207115, "antic_precision": 0.6765768268963601, "antic_recall": 0.4420574886535552, "antic_f1": 0.5347339140619282, "antic_labels": 342686, "antic_positives": 16525}`

## VAL (Bearrison)

| stratum | system | labels | tt_mae_s | tt_wape | speed_mae_mph | cong_mae | positives | precision | recall | f1 |
|---|---|---|---|---|---|---|---|---|---|---|
| all | persistence | 104453729.0 | 3.8307 | 0.2303 | 2.8406 | 0.1115 | 25211518.0 | 0.7563 | 0.7159 | 0.7356 |
| all | noevent | 104453729.0 | 2.5322 | 0.1522 | 1.7480 | 0.0687 | 25211518.0 | 0.8529 | 0.7792 | 0.8144 |
| all | parent | 104453729.0 | 2.5382 | 0.1526 | 1.7541 | 0.0689 | 25211518.0 | 0.8549 | 0.7742 | 0.8126 |
| all | event_patch_v3_awareness | 104453729.0 | 2.5347 | 0.1524 | 1.7513 | 0.0688 | 25211518.0 | 0.8518 | 0.7796 | 0.8141 |
| all | event_patch_v3_awareness_decoder | 104453729.0 | 2.5347 | 0.1524 | 1.7514 | 0.0688 | 25211518.0 | 0.8517 | 0.7795 | 0.8140 |
| all | event_patch_v3_awareness_paired | 104453729.0 | 2.5342 | 0.1524 | 1.7508 | 0.0688 | 25211518.0 | 0.8517 | 0.7799 | 0.8142 |
| antic | persistence | 342686.0 | 2.2389 | 0.1720 | 2.3984 | 0.0937 | 16525.0 | – | 0.0000 | – |
| antic | noevent | 342686.0 | 1.6705 | 0.1283 | 1.5597 | 0.0616 | 16525.0 | 0.7273 | 0.3500 | 0.4726 |
| antic | parent | 342686.0 | 1.6630 | 0.1277 | 1.5666 | 0.0617 | 16525.0 | 0.6769 | 0.4422 | 0.5350 |
| antic | event_patch_v3_awareness | 342686.0 | 1.6673 | 0.1281 | 1.5766 | 0.0621 | 16525.0 | 0.6692 | 0.4571 | 0.5432 |
| antic | event_patch_v3_awareness_decoder | 342686.0 | 1.6683 | 0.1281 | 1.5783 | 0.0622 | 16525.0 | 0.6673 | 0.4597 | 0.5444 |
| antic | event_patch_v3_awareness_paired | 342686.0 | 1.6672 | 0.1281 | 1.5764 | 0.0621 | 16525.0 | 0.6691 | 0.4563 | 0.5426 |
| antic_pre_end | persistence | 176754.0 | 2.3187 | 0.1748 | 2.3339 | 0.0925 | 9163.0 | – | 0.0000 | – |
| antic_pre_end | noevent | 176754.0 | 1.7262 | 0.1301 | 1.5183 | 0.0605 | 9163.0 | 0.7571 | 0.3391 | 0.4684 |
| antic_pre_end | parent | 176754.0 | 1.7068 | 0.1286 | 1.5134 | 0.0601 | 9163.0 | 0.6921 | 0.4620 | 0.5541 |
| antic_pre_end | event_patch_v3_awareness | 176754.0 | 1.7144 | 0.1292 | 1.5301 | 0.0608 | 9163.0 | 0.6775 | 0.4843 | 0.5648 |
| antic_pre_end | event_patch_v3_awareness_decoder | 176754.0 | 1.7158 | 0.1293 | 1.5326 | 0.0609 | 9163.0 | 0.6746 | 0.4883 | 0.5665 |
| antic_pre_end | event_patch_v3_awareness_paired | 176754.0 | 1.7143 | 0.1292 | 1.5299 | 0.0608 | 9163.0 | 0.6780 | 0.4818 | 0.5633 |
| antic_pre_start | persistence | 165932.0 | 2.1539 | 0.1689 | 2.4670 | 0.0949 | 7362.0 | – | 0.0000 | – |
| antic_pre_start | noevent | 165932.0 | 1.6111 | 0.1263 | 1.6037 | 0.0627 | 7362.0 | 0.6955 | 0.3636 | 0.4776 |
| antic_pre_start | parent | 165932.0 | 1.6163 | 0.1267 | 1.6234 | 0.0634 | 7362.0 | 0.6571 | 0.4177 | 0.5107 |
| antic_pre_start | event_patch_v3_awareness | 165932.0 | 1.6170 | 0.1268 | 1.6260 | 0.0635 | 7362.0 | 0.6578 | 0.4233 | 0.5151 |
| antic_pre_start | event_patch_v3_awareness_decoder | 165932.0 | 1.6178 | 0.1268 | 1.6270 | 0.0636 | 7362.0 | 0.6572 | 0.4242 | 0.5156 |
| antic_pre_start | event_patch_v3_awareness_paired | 165932.0 | 1.6170 | 0.1268 | 1.6259 | 0.0635 | 7362.0 | 0.6569 | 0.4246 | 0.5158 |
| antic_strict | persistence | 263639.0 | 1.3302 | 0.1167 | 1.8281 | 0.0700 | 5041.0 | – | 0.0000 | – |
| antic_strict | noevent | 263639.0 | 1.0589 | 0.0929 | 1.3328 | 0.0517 | 5041.0 | 0.6511 | 0.1658 | 0.2643 |
| antic_strict | parent | 263639.0 | 1.0632 | 0.0933 | 1.3491 | 0.0522 | 5041.0 | 0.5978 | 0.2474 | 0.3499 |
| antic_strict | event_patch_v3_awareness | 263639.0 | 1.0696 | 0.0939 | 1.3612 | 0.0527 | 5041.0 | 0.5900 | 0.2563 | 0.3574 |
| antic_strict | event_patch_v3_awareness_decoder | 263639.0 | 1.0706 | 0.0939 | 1.3630 | 0.0528 | 5041.0 | 0.5875 | 0.2597 | 0.3602 |
| antic_strict | event_patch_v3_awareness_paired | 263639.0 | 1.0696 | 0.0939 | 1.3611 | 0.0527 | 5041.0 | 0.5890 | 0.2567 | 0.3576 |
| control_runs | persistence | 51485999.0 | 3.8314 | 0.2311 | 2.8829 | 0.1131 | 12409189.0 | 0.7540 | 0.7122 | 0.7325 |
| control_runs | noevent | 51485999.0 | 2.5224 | 0.1522 | 1.7683 | 0.0694 | 12409189.0 | 0.8515 | 0.7772 | 0.8127 |
| control_runs | parent | 51485999.0 | 2.5300 | 0.1526 | 1.7748 | 0.0697 | 12409189.0 | 0.8537 | 0.7717 | 0.8106 |
| control_runs | event_patch_v3_awareness | 51485999.0 | 2.5266 | 0.1524 | 1.7720 | 0.0696 | 12409189.0 | 0.8512 | 0.7762 | 0.8120 |
| control_runs | event_patch_v3_awareness_decoder | 51485999.0 | 2.5265 | 0.1524 | 1.7720 | 0.0696 | 12409189.0 | 0.8512 | 0.7761 | 0.8120 |
| control_runs | event_patch_v3_awareness_paired | 51485999.0 | 2.5260 | 0.1524 | 1.7715 | 0.0696 | 12409189.0 | 0.8510 | 0.7767 | 0.8122 |
| event_far | persistence | 35760484.0 | 3.3100 | 0.2052 | 2.7707 | 0.1076 | 8400039.0 | 0.7708 | 0.7212 | 0.7452 |
| event_far | noevent | 35760484.0 | 2.1341 | 0.1323 | 1.6295 | 0.0631 | 8400039.0 | 0.8656 | 0.7937 | 0.8281 |
| event_far | parent | 35760484.0 | 2.1419 | 0.1328 | 1.6370 | 0.0634 | 8400039.0 | 0.8702 | 0.7855 | 0.8257 |
| event_far | event_patch_v3_awareness | 35760484.0 | 2.1382 | 0.1325 | 1.6337 | 0.0632 | 8400039.0 | 0.8673 | 0.7904 | 0.8270 |
| event_far | event_patch_v3_awareness_decoder | 35760484.0 | 2.1382 | 0.1325 | 1.6337 | 0.0632 | 8400039.0 | 0.8673 | 0.7902 | 0.8270 |
| event_far | event_patch_v3_awareness_paired | 35760484.0 | 2.1377 | 0.1325 | 1.6331 | 0.0632 | 8400039.0 | 0.8671 | 0.7908 | 0.8272 |
| event_near | persistence | 3091575.0 | 5.2858 | 0.2991 | 2.5709 | 0.1030 | 857890.0 | 0.7774 | 0.7646 | 0.7709 |
| event_near | noevent | 3091575.0 | 3.7447 | 0.2119 | 1.8015 | 0.0723 | 857890.0 | 0.8597 | 0.7866 | 0.8215 |
| event_near | parent | 3091575.0 | 3.7184 | 0.2104 | 1.7940 | 0.0720 | 857890.0 | 0.8467 | 0.8094 | 0.8276 |
| event_near | event_patch_v3_awareness | 3091575.0 | 3.7179 | 0.2104 | 1.7965 | 0.0721 | 857890.0 | 0.8397 | 0.8202 | 0.8298 |
| event_near | event_patch_v3_awareness_decoder | 3091575.0 | 3.7189 | 0.2104 | 1.7969 | 0.0722 | 857890.0 | 0.8392 | 0.8209 | 0.8300 |
| event_near | event_patch_v3_awareness_paired | 3091575.0 | 3.7174 | 0.2104 | 1.7959 | 0.0721 | 857890.0 | 0.8400 | 0.8199 | 0.8298 |
| event_runs | persistence | 52967730.0 | 3.8299 | 0.2295 | 2.7995 | 0.1100 | 12802329.0 | 0.7585 | 0.7196 | 0.7385 |
| event_runs | noevent | 52967730.0 | 2.5417 | 0.1523 | 1.7282 | 0.0679 | 12802329.0 | 0.8542 | 0.7812 | 0.8160 |
| event_runs | parent | 52967730.0 | 2.5462 | 0.1526 | 1.7340 | 0.0682 | 12802329.0 | 0.8560 | 0.7767 | 0.8144 |
| event_runs | event_patch_v3_awareness | 52967730.0 | 2.5426 | 0.1524 | 1.7313 | 0.0681 | 12802329.0 | 0.8524 | 0.7828 | 0.8161 |
| event_runs | event_patch_v3_awareness_decoder | 52967730.0 | 2.5427 | 0.1524 | 1.7314 | 0.0681 | 12802329.0 | 0.8522 | 0.7828 | 0.8161 |
| event_runs | event_patch_v3_awareness_paired | 52967730.0 | 2.5421 | 0.1524 | 1.7308 | 0.0680 | 12802329.0 | 0.8523 | 0.7830 | 0.8162 |
| near_missing_history | persistence | 342409.0 | 5.0950 | 0.3094 | 4.1617 | 0.1704 | 73224.0 | 0.6896 | 0.5323 | 0.6008 |
| near_missing_history | noevent | 342409.0 | 3.0646 | 0.1861 | 2.0628 | 0.0854 | 73224.0 | 0.8274 | 0.6689 | 0.7398 |
| near_missing_history | parent | 342409.0 | 3.0659 | 0.1862 | 2.0678 | 0.0856 | 73224.0 | 0.8136 | 0.6944 | 0.7493 |
| near_missing_history | event_patch_v3_awareness | 342409.0 | 3.0649 | 0.1861 | 2.0674 | 0.0856 | 73224.0 | 0.8052 | 0.7140 | 0.7569 |
| near_missing_history | event_patch_v3_awareness_decoder | 342409.0 | 3.0659 | 0.1862 | 2.0686 | 0.0857 | 73224.0 | 0.8041 | 0.7154 | 0.7571 |
| near_missing_history | event_patch_v3_awareness_paired | 342409.0 | 3.0645 | 0.1861 | 2.0671 | 0.0856 | 73224.0 | 0.8058 | 0.7129 | 0.7565 |
| severe | persistence | 25211518.0 | 7.4043 | 0.3729 | 3.3009 | 0.1318 | 25211518.0 | 1.0000 | 0.7159 | 0.8345 |
| severe | noevent | 25211518.0 | 5.5806 | 0.2811 | 1.6769 | 0.0672 | 25211518.0 | 1.0000 | 0.7792 | 0.8759 |
| severe | parent | 25211518.0 | 5.5908 | 0.2816 | 1.6970 | 0.0679 | 25211518.0 | 1.0000 | 0.7742 | 0.8727 |
| severe | event_patch_v3_awareness | 25211518.0 | 5.5724 | 0.2807 | 1.6766 | 0.0671 | 25211518.0 | 1.0000 | 0.7796 | 0.8761 |
| severe | event_patch_v3_awareness_decoder | 25211518.0 | 5.5723 | 0.2807 | 1.6764 | 0.0671 | 25211518.0 | 1.0000 | 0.7795 | 0.8761 |
| severe | event_patch_v3_awareness_paired | 25211518.0 | 5.5706 | 0.2806 | 1.6750 | 0.0671 | 25211518.0 | 1.0000 | 0.7799 | 0.8764 |

Anticipation stratum by horizon:

| horizon_min | system | labels | tt_mae_s | positives | precision | recall | f1 |
|---|---|---|---|---|---|---|---|
| 10 | persistence | 56067.0 | 2.1056 | 2513.0 | – | 0.0000 | – |
| 10 | noevent | 56067.0 | 1.6080 | 2513.0 | 0.7005 | 0.3685 | 0.4829 |
| 10 | parent | 56067.0 | 1.6278 | 2513.0 | 0.6462 | 0.4485 | 0.5295 |
| 10 | event_patch_v3_awareness | 56067.0 | 1.6372 | 2513.0 | 0.6417 | 0.4604 | 0.5361 |
| 10 | event_patch_v3_awareness_decoder | 56067.0 | 1.6382 | 2513.0 | 0.6416 | 0.4624 | 0.5375 |
| 10 | event_patch_v3_awareness_paired | 56067.0 | 1.6371 | 2513.0 | 0.6414 | 0.4604 | 0.5360 |
| 20 | persistence | 56588.0 | 2.0629 | 2596.0 | – | 0.0000 | – |
| 20 | noevent | 56588.0 | 1.5287 | 2596.0 | 0.6905 | 0.3490 | 0.4637 |
| 20 | parent | 56588.0 | 1.5370 | 2596.0 | 0.6444 | 0.4418 | 0.5242 |
| 20 | event_patch_v3_awareness | 56588.0 | 1.5457 | 2596.0 | 0.6352 | 0.4542 | 0.5296 |
| 20 | event_patch_v3_awareness_decoder | 56588.0 | 1.5475 | 2596.0 | 0.6344 | 0.4599 | 0.5333 |
| 20 | event_patch_v3_awareness_paired | 56588.0 | 1.5457 | 2596.0 | 0.6348 | 0.4534 | 0.5290 |
| 30 | persistence | 57190.0 | 2.2167 | 2748.0 | – | 0.0000 | – |
| 30 | noevent | 57190.0 | 1.6453 | 2748.0 | 0.7275 | 0.3508 | 0.4734 |
| 30 | parent | 57190.0 | 1.6235 | 2748.0 | 0.6736 | 0.4461 | 0.5368 |
| 30 | event_patch_v3_awareness | 57190.0 | 1.6301 | 2748.0 | 0.6653 | 0.4592 | 0.5434 |
| 30 | event_patch_v3_awareness_decoder | 57190.0 | 1.6314 | 2748.0 | 0.6651 | 0.4640 | 0.5466 |
| 30 | event_patch_v3_awareness_paired | 57190.0 | 1.6303 | 2748.0 | 0.6668 | 0.4603 | 0.5447 |
| 40 | persistence | 57595.0 | 2.2553 | 2882.0 | – | 0.0000 | – |
| 40 | noevent | 57595.0 | 1.6546 | 2882.0 | 0.7427 | 0.3446 | 0.4707 |
| 40 | parent | 57595.0 | 1.6421 | 2882.0 | 0.7004 | 0.4445 | 0.5438 |
| 40 | event_patch_v3_awareness | 57595.0 | 1.6405 | 2882.0 | 0.6927 | 0.4608 | 0.5534 |
| 40 | event_patch_v3_awareness_decoder | 57595.0 | 1.6414 | 2882.0 | 0.6901 | 0.4629 | 0.5541 |
| 40 | event_patch_v3_awareness_paired | 57595.0 | 1.6404 | 2882.0 | 0.6917 | 0.4594 | 0.5521 |
| 50 | persistence | 57693.0 | 2.3629 | 2927.0 | – | 0.0000 | – |
| 50 | noevent | 57693.0 | 1.7497 | 2927.0 | 0.7572 | 0.3420 | 0.4712 |
| 50 | parent | 57693.0 | 1.7306 | 2927.0 | 0.7048 | 0.4373 | 0.5397 |
| 50 | event_patch_v3_awareness | 57693.0 | 1.7310 | 2927.0 | 0.6981 | 0.4558 | 0.5515 |
| 50 | event_patch_v3_awareness_decoder | 57693.0 | 1.7317 | 2927.0 | 0.6954 | 0.4571 | 0.5516 |
| 50 | event_patch_v3_awareness_paired | 57693.0 | 1.7308 | 2927.0 | 0.6986 | 0.4537 | 0.5501 |
| 60 | persistence | 57553.0 | 2.4232 | 2859.0 | – | 0.0000 | – |
| 60 | noevent | 57553.0 | 1.8324 | 2859.0 | 0.7446 | 0.3477 | 0.4740 |
| 60 | parent | 57553.0 | 1.8135 | 2859.0 | 0.6901 | 0.4362 | 0.5345 |
| 60 | event_patch_v3_awareness | 57553.0 | 1.8160 | 2859.0 | 0.6796 | 0.4526 | 0.5434 |
| 60 | event_patch_v3_awareness_decoder | 57553.0 | 1.8165 | 2859.0 | 0.6750 | 0.4526 | 0.5419 |
| 60 | event_patch_v3_awareness_paired | 57553.0 | 1.8159 | 2859.0 | 0.6786 | 0.4512 | 0.5420 |

Anticipation travel-time MAE per family (families are the less-correlated unit):

| family_id | persistence | noevent | parent | event_patch_v3_awareness | event_patch_v3_awareness_decoder | event_patch_v3_awareness_paired |
|---|---|---|---|---|---|---|
| b3_main_bearrison_arrival_f048 | 2.6746 | 1.9815 | 2.0003 | 2.0026 | 2.0033 | 2.0032 |
| b3_main_bearrison_arrival_f051 | 1.8605 | 1.4408 | 1.4478 | 1.4499 | 1.4521 | 1.4501 |
| b3_main_bearrison_arrival_f054 | 2.1801 | 1.5013 | 1.5074 | 1.5086 | 1.5090 | 1.5084 |
| b3_main_bearrison_arrival_f057 | 1.9005 | 1.4106 | 1.4133 | 1.4106 | 1.4112 | 1.4104 |
| b3_main_bearrison_departure_f050 | 3.4040 | 2.5018 | 2.3894 | 2.3704 | 2.3701 | 2.3709 |
| b3_main_bearrison_departure_f053 | 2.2583 | 1.6573 | 1.6243 | 1.6344 | 1.6347 | 1.6341 |
| b3_main_bearrison_departure_f056 | 1.3782 | 1.1053 | 1.1043 | 1.1240 | 1.1253 | 1.1235 |
| b3_main_bearrison_departure_f059 | 2.5362 | 1.8867 | 1.8265 | 1.8363 | 1.8363 | 1.8378 |
| b3_main_bearrison_full_f049 | 3.0267 | 2.2372 | 2.2537 | 2.2690 | 2.2716 | 2.2683 |
| b3_main_bearrison_full_f052 | 1.8650 | 1.3806 | 1.3876 | 1.3976 | 1.3986 | 1.3974 |
| b3_main_bearrison_full_f055 | 1.7536 | 1.3326 | 1.3125 | 1.3051 | 1.3058 | 1.3048 |
| b3_main_bearrison_full_f058 | 2.5329 | 1.9222 | 1.9093 | 1.9177 | 1.9189 | 1.9177 |

Paired event-minus-control impact error on common valid near roads (z = log travel-time ratio; seconds from derived travel times):

| system | pair_labels | pair_dz_mae | pair_dtt_mae_s |
|---|---|---|---|
| parent | 2677665 | 0.1804 | 4.4439 |
| noevent | 2677665 | 0.1806 | 4.4431 |
| event_patch_v3_awareness | 2677665 | 0.1806 | 4.4452 |
| event_patch_v3_awareness_paired | 2677665 | 0.1805 | 4.4432 |
| event_patch_v3_awareness_decoder | 2677665 | 0.1807 | 4.4466 |
| persistence | 2677665 | 0.2664 | 6.8237 |

## TEST (Portola, reused held-out test)

| stratum | system | labels | tt_mae_s | tt_wape | speed_mae_mph | cong_mae | positives | precision | recall | f1 |
|---|---|---|---|---|---|---|---|---|---|---|
| all | persistence | 80477313.0 | 3.4808 | 0.2143 | 2.7783 | 0.1083 | 18247427.0 | 0.7598 | 0.7227 | 0.7408 |
| all | noevent | 80477313.0 | 2.3308 | 0.1435 | 1.7392 | 0.0678 | 18247427.0 | 0.8552 | 0.7840 | 0.8181 |
| all | parent | 80477313.0 | 2.3299 | 0.1434 | 1.7413 | 0.0679 | 18247427.0 | 0.8578 | 0.7798 | 0.8169 |
| all | event_patch_v3_awareness | 80477313.0 | 2.3283 | 0.1433 | 1.7398 | 0.0679 | 18247427.0 | 0.8548 | 0.7845 | 0.8182 |
| antic | persistence | 60628.0 | 2.9727 | 0.1675 | 2.4466 | 0.0874 | 1607.0 | – | 0.0000 | – |
| antic | noevent | 60628.0 | 2.4931 | 0.1405 | 1.7292 | 0.0626 | 1607.0 | 0.6874 | 0.1861 | 0.2929 |
| antic | parent | 60628.0 | 2.5017 | 0.1410 | 1.7444 | 0.0633 | 1607.0 | 0.6746 | 0.2116 | 0.3221 |
| antic | event_patch_v3_awareness | 60628.0 | 2.5024 | 0.1410 | 1.7439 | 0.0632 | 1607.0 | 0.6476 | 0.2116 | 0.3189 |
| antic_pre_start | persistence | 60628.0 | 2.9727 | 0.1675 | 2.4466 | 0.0874 | 1607.0 | – | 0.0000 | – |
| antic_pre_start | noevent | 60628.0 | 2.4931 | 0.1405 | 1.7292 | 0.0626 | 1607.0 | 0.6874 | 0.1861 | 0.2929 |
| antic_pre_start | parent | 60628.0 | 2.5017 | 0.1410 | 1.7444 | 0.0633 | 1607.0 | 0.6746 | 0.2116 | 0.3221 |
| antic_pre_start | event_patch_v3_awareness | 60628.0 | 2.5024 | 0.1410 | 1.7439 | 0.0632 | 1607.0 | 0.6476 | 0.2116 | 0.3189 |
| antic_strict | persistence | 46871.0 | 2.5404 | 0.1477 | 2.1492 | 0.0746 | 718.0 | – | 0.0000 | – |
| antic_strict | noevent | 46871.0 | 2.1797 | 0.1267 | 1.6181 | 0.0575 | 718.0 | 0.6727 | 0.0515 | 0.0957 |
| antic_strict | parent | 46871.0 | 2.1884 | 0.1272 | 1.6320 | 0.0581 | 718.0 | 0.6224 | 0.0850 | 0.1495 |
| antic_strict | event_patch_v3_awareness | 46871.0 | 2.1875 | 0.1272 | 1.6286 | 0.0580 | 718.0 | 0.5700 | 0.0794 | 0.1394 |
| control_runs | persistence | 39692658.0 | 3.4581 | 0.2138 | 2.8169 | 0.1097 | 8978409.0 | 0.7578 | 0.7196 | 0.7382 |
| control_runs | noevent | 39692658.0 | 2.2978 | 0.1421 | 1.7572 | 0.0685 | 8978409.0 | 0.8535 | 0.7832 | 0.8168 |
| control_runs | parent | 39692658.0 | 2.2994 | 0.1422 | 1.7596 | 0.0686 | 8978409.0 | 0.8569 | 0.7780 | 0.8156 |
| control_runs | event_patch_v3_awareness | 39692658.0 | 2.2974 | 0.1420 | 1.7581 | 0.0685 | 8978409.0 | 0.8541 | 0.7826 | 0.8168 |
| event_far | persistence | 32416076.0 | 3.4538 | 0.2117 | 2.7627 | 0.1080 | 7177511.0 | 0.7574 | 0.7207 | 0.7386 |
| event_far | noevent | 32416076.0 | 2.3018 | 0.1411 | 1.7287 | 0.0677 | 7177511.0 | 0.8539 | 0.7817 | 0.8162 |
| event_far | parent | 32416076.0 | 2.3041 | 0.1412 | 1.7312 | 0.0678 | 7177511.0 | 0.8561 | 0.7775 | 0.8149 |
| event_far | event_patch_v3_awareness | 32416076.0 | 2.3021 | 0.1411 | 1.7299 | 0.0678 | 7177511.0 | 0.8531 | 0.7822 | 0.8161 |
| event_near | persistence | 1092545.0 | 7.2969 | 0.3715 | 2.5916 | 0.0972 | 183200.0 | 0.7107 | 0.6761 | 0.6930 |
| event_near | noevent | 1092545.0 | 5.8795 | 0.2993 | 1.8191 | 0.0681 | 183200.0 | 0.8754 | 0.6497 | 0.7459 |
| event_near | parent | 1092545.0 | 5.6946 | 0.2899 | 1.8039 | 0.0676 | 183200.0 | 0.8399 | 0.6856 | 0.7550 |
| event_near | event_patch_v3_awareness | 1092545.0 | 5.7408 | 0.2923 | 1.8078 | 0.0677 | 183200.0 | 0.8302 | 0.6949 | 0.7565 |
| event_runs | persistence | 40784655.0 | 3.5028 | 0.2147 | 2.7408 | 0.1069 | 9269018.0 | 0.7617 | 0.7257 | 0.7433 |
| event_runs | noevent | 40784655.0 | 2.3628 | 0.1448 | 1.7217 | 0.0672 | 9269018.0 | 0.8569 | 0.7847 | 0.8192 |
| event_runs | parent | 40784655.0 | 2.3596 | 0.1446 | 1.7235 | 0.0673 | 9269018.0 | 0.8587 | 0.7814 | 0.8182 |
| event_runs | event_patch_v3_awareness | 40784655.0 | 2.3583 | 0.1445 | 1.7220 | 0.0672 | 9269018.0 | 0.8555 | 0.7865 | 0.8195 |
| near_missing_history | persistence | 170560.0 | 4.3848 | 0.2559 | 4.1525 | 0.1611 | 26737.0 | 0.6491 | 0.4839 | 0.5544 |
| near_missing_history | noevent | 170560.0 | 2.5819 | 0.1507 | 1.9459 | 0.0753 | 26737.0 | 0.8643 | 0.6300 | 0.7288 |
| near_missing_history | parent | 170560.0 | 2.5805 | 0.1506 | 1.9552 | 0.0757 | 26737.0 | 0.8371 | 0.6521 | 0.7331 |
| near_missing_history | event_patch_v3_awareness | 170560.0 | 2.5776 | 0.1505 | 1.9542 | 0.0756 | 26737.0 | 0.8206 | 0.6660 | 0.7352 |
| severe | persistence | 18247427.0 | 6.5805 | 0.3505 | 3.1200 | 0.1244 | 18247427.0 | 1.0000 | 0.7227 | 0.8390 |
| severe | noevent | 18247427.0 | 5.0697 | 0.2701 | 1.6279 | 0.0651 | 18247427.0 | 1.0000 | 0.7840 | 0.8789 |
| severe | parent | 18247427.0 | 5.0749 | 0.2703 | 1.6480 | 0.0659 | 18247427.0 | 1.0000 | 0.7798 | 0.8762 |
| severe | event_patch_v3_awareness | 18247427.0 | 5.0615 | 0.2696 | 1.6301 | 0.0652 | 18247427.0 | 1.0000 | 0.7845 | 0.8793 |

Anticipation stratum by horizon:

| horizon_min | system | labels | tt_mae_s | positives | precision | recall | f1 |
|---|---|---|---|---|---|---|---|
| 10 | persistence | 9919.0 | 2.1993 | 231.0 | – | 0.0000 | – |
| 10 | noevent | 9919.0 | 1.7295 | 231.0 | 0.7162 | 0.2294 | 0.3475 |
| 10 | parent | 9919.0 | 1.7413 | 231.0 | 0.6625 | 0.2294 | 0.3408 |
| 10 | event_patch_v3_awareness | 9919.0 | 1.7452 | 231.0 | 0.6265 | 0.2251 | 0.3312 |
| 20 | persistence | 9879.0 | 2.7787 | 239.0 | – | 0.0000 | – |
| 20 | noevent | 9879.0 | 2.3087 | 239.0 | 0.6081 | 0.1883 | 0.2875 |
| 20 | parent | 9879.0 | 2.3224 | 239.0 | 0.5976 | 0.2050 | 0.3053 |
| 20 | event_patch_v3_awareness | 9879.0 | 2.3264 | 239.0 | 0.5930 | 0.2134 | 0.3138 |
| 30 | persistence | 9992.0 | 2.9690 | 267.0 | – | 0.0000 | – |
| 30 | noevent | 9992.0 | 2.4974 | 267.0 | 0.7083 | 0.1910 | 0.3009 |
| 30 | parent | 9992.0 | 2.5020 | 267.0 | 0.6905 | 0.2172 | 0.3305 |
| 30 | event_patch_v3_awareness | 9992.0 | 2.5048 | 267.0 | 0.6818 | 0.2247 | 0.3380 |
| 40 | persistence | 10151.0 | 2.9331 | 264.0 | – | 0.0000 | – |
| 40 | noevent | 10151.0 | 2.4797 | 264.0 | 0.7101 | 0.1856 | 0.2943 |
| 40 | parent | 10151.0 | 2.4905 | 264.0 | 0.7024 | 0.2235 | 0.3391 |
| 40 | event_patch_v3_awareness | 10151.0 | 2.4909 | 264.0 | 0.6477 | 0.2159 | 0.3239 |
| 50 | persistence | 10264.0 | 3.2942 | 282.0 | – | 0.0000 | – |
| 50 | noevent | 10264.0 | 2.7865 | 282.0 | 0.7286 | 0.1809 | 0.2898 |
| 50 | parent | 10264.0 | 2.7933 | 282.0 | 0.7229 | 0.2128 | 0.3288 |
| 50 | event_patch_v3_awareness | 10264.0 | 2.7918 | 282.0 | 0.6977 | 0.2128 | 0.3261 |
| 60 | persistence | 10423.0 | 3.6179 | 324.0 | – | 0.0000 | – |
| 60 | noevent | 10423.0 | 3.1146 | 324.0 | 0.6579 | 0.1543 | 0.2500 |
| 60 | parent | 10423.0 | 3.1189 | 324.0 | 0.6703 | 0.1883 | 0.2940 |
| 60 | event_patch_v3_awareness | 10423.0 | 3.1135 | 324.0 | 0.6383 | 0.1852 | 0.2871 |

Anticipation travel-time MAE per family (families are the less-correlated unit):

| family_id | persistence | noevent | parent | event_patch_v3_awareness |
|---|---|---|---|---|
| b3_main_portola_arrival_f024 | 4.5896 | 4.2182 | 4.2324 | 4.2305 |
| b3_main_portola_arrival_f030 | 2.8692 | 2.2378 | 2.2430 | 2.2447 |
| b3_main_portola_arrival_f033 | 1.8242 | 1.3147 | 1.3209 | 1.3283 |
| b3_main_portola_full_f025 | 2.0390 | 1.5971 | 1.5997 | 1.5956 |
| b3_main_portola_full_f028 | 1.7377 | 1.2512 | 1.2655 | 1.2718 |
| b3_main_portola_full_f031 | 2.8406 | 2.3799 | 2.3859 | 2.3823 |

Paired event-minus-control impact error on common valid near roads (z = log travel-time ratio; seconds from derived travel times):

| system | pair_labels | pair_dz_mae | pair_dtt_mae_s |
|---|---|---|---|
| parent | 813966 | 0.1774 | 6.0275 |
| noevent | 813966 | 0.1818 | 6.2096 |
| event_patch_v3_awareness | 813966 | 0.1784 | 6.0793 |
| persistence | 813966 | 0.2481 | 7.9720 |

## Limitations

- One validation event group (Bearrison) and one reused test group (Portola); pooled cell counts overlap.
- Public schedule boundaries are proxies for traffic phases, not observed surge onset.
- Schedule context is assumed known; announcement timing is not modelled. Horizon stays 60 min.
- Onset-timing diagnostics and shifted-schedule sensitivity were not run in this pass; the standard `forecast evaluate` counterfactual (focal event removed) is in each candidate's eval directory.

## Reproduce

```
python -m forecast finetune-preflight --spec configs/event_patch_v3_awareness.yaml
python -m forecast finetune --spec configs/event_patch_v3_awareness.yaml --stage event
python -m forecast evaluate-events --spec configs/event_patch_v3_awareness.yaml --partition test --candidates <name>=<ckpt>
```
