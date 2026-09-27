# Jam-probability wrapper (3-hour model)

> **Synthetic** SUMO data. Calibration and thresholds fitted on Bearrison (validation) only; Portola (test) uses them unchanged. Cells in `near`/`other` are subsampled (30% / 1%); `antic` is complete.

A jam = target congestion >= 0.5. `base` = the point forecast's own rule (predicted congestion >= threshold); `f1thr` = calibrated probability >= the F1-best validation threshold; `rec70thr` = the highest validation threshold that caught >= 70% of validation jams. `antic` = near roads observed clear at issue, forecast issued up to 3 h before public start/end.

## Bearrison (validation, fitted here)

| group | hgroup | labels | positives | base_precision | base_recall | base_f1 | f1thr_precision | f1thr_recall | f1thr_f1 | rec70thr_precision | rec70thr_recall | brier_base | brier_calibrated |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| antic | 0-60 | 643255 | 37906 | 0.6545 | 0.4882 | 0.5593 | 0.5669 | 0.6535 | 0.6071 | 0.5019 | 0.7248 | 0.0453 | 0.0332 |
| antic | 120-180 | 652375 | 40902 | 0.6938 | 0.4968 | 0.5790 | 0.5884 | 0.6792 | 0.6305 | 0.5608 | 0.7094 | 0.0453 | 0.0334 |
| antic | 60-120 | 652793 | 40501 | 0.6751 | 0.4964 | 0.5721 | 0.5790 | 0.6742 | 0.6230 | 0.5420 | 0.7152 | 0.0461 | 0.0337 |
| near | 0-60 | 389732 | 153430 | 0.8488 | 0.8325 | 0.8405 | 0.8266 | 0.8657 | 0.8457 | 0.8973 | 0.7111 | 0.1243 | 0.0926 |
| near | 120-180 | 394008 | 153147 | 0.8488 | 0.8284 | 0.8384 | 0.8163 | 0.8730 | 0.8437 | 0.8978 | 0.7027 | 0.1241 | 0.0926 |
| near | 60-120 | 396502 | 154766 | 0.8465 | 0.8315 | 0.8389 | 0.8234 | 0.8643 | 0.8434 | 0.8969 | 0.7066 | 0.1246 | 0.0929 |
| other | 0-60 | 634177 | 148373 | 0.8477 | 0.7927 | 0.8193 | 0.8180 | 0.8327 | 0.8253 | 0.8775 | 0.7172 | 0.0818 | 0.0636 |
| other | 120-180 | 628199 | 146805 | 0.8451 | 0.7913 | 0.8173 | 0.8198 | 0.8267 | 0.8232 | 0.8797 | 0.7012 | 0.0827 | 0.0642 |
| other | 60-120 | 635348 | 149079 | 0.8483 | 0.7920 | 0.8192 | 0.8112 | 0.8386 | 0.8247 | 0.8795 | 0.7119 | 0.0820 | 0.0639 |

## Portola (held-out test)

| group | hgroup | labels | positives | base_precision | base_recall | base_f1 | f1thr_precision | f1thr_recall | f1thr_f1 | rec70thr_precision | rec70thr_recall | brier_base | brier_calibrated |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| antic | 0-60 | 123580 | 3667 | 0.6725 | 0.1977 | 0.3056 | 0.4838 | 0.2520 | 0.3314 | 0.3438 | 0.2923 | 0.0267 | 0.0248 |
| antic | 120-180 | 129856 | 8029 | 0.8016 | 0.1273 | 0.2197 | 0.5096 | 0.1683 | 0.2530 | 0.4483 | 0.1787 | 0.0559 | 0.0534 |
| antic | 60-120 | 129083 | 6615 | 0.7452 | 0.1339 | 0.2271 | 0.5137 | 0.1791 | 0.2656 | 0.4168 | 0.1932 | 0.0467 | 0.0442 |
| near | 0-60 | 74641 | 17522 | 0.8562 | 0.7001 | 0.7703 | 0.8175 | 0.7375 | 0.7754 | 0.9217 | 0.5933 | 0.0980 | 0.0795 |
| near | 120-180 | 79604 | 18853 | 0.8143 | 0.7002 | 0.7529 | 0.7597 | 0.7579 | 0.7588 | 0.8973 | 0.5874 | 0.1088 | 0.0854 |
| near | 60-120 | 79676 | 19043 | 0.8390 | 0.6925 | 0.7588 | 0.8007 | 0.7289 | 0.7631 | 0.9146 | 0.5857 | 0.1053 | 0.0842 |
| other | 0-60 | 277491 | 59462 | 0.8636 | 0.7944 | 0.8276 | 0.8288 | 0.8357 | 0.8322 | 0.8994 | 0.7163 | 0.0709 | 0.0555 |
| other | 120-180 | 282791 | 60551 | 0.8672 | 0.8007 | 0.8326 | 0.8372 | 0.8354 | 0.8363 | 0.9072 | 0.7072 | 0.0689 | 0.0543 |
| other | 60-120 | 282036 | 60714 | 0.8667 | 0.7989 | 0.8314 | 0.8223 | 0.8470 | 0.8345 | 0.9039 | 0.7161 | 0.0697 | 0.0549 |

## Reading this

- The wrapper re-reads the point forecast. It can trade false alarms for caught jams, but a jam the model predicts as fully clear stays invisible; that needs retraining (see EVENT_ANTICIPATION_IMPROVEMENTS_PLAN.md).
- Calibration file: `C:\Users\haryd\transpeaktation\ml\data\forecast\experiments\event_patch_v4_h18_full\jam_wrapper\calibration.json` (isotonic knots per group x horizon group).
