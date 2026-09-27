| model | what | warning source | VAL F1 | VAL P / R | VAL 1h vs v2 | VAL 2-3h antic MAE s | TEST F1 | TEST P / R | TEST 1h vs v2 | TEST 2-3h city MAE s | TEST 2-3h antic MAE s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| v4 | 3-hour model on 7 events | point forecast | – | – | -0.3% | 2.02 | – | – | -0.1% | 2.93 | 4.28 |
| v5_h18_full | v5: 20 events, no new heads | calibrated | 0.642 | 0.62 / 0.67 | -0.2% | 2.02 | 0.414 | 0.53 / 0.34 | -0.1% | 2.93 | 4.30 |
| v6_tuned | tuned loss / LR | calibrated | 0.644 | 0.62 / 0.67 | -0.3% | 2.01 | 0.428 | 0.61 / 0.33 | -0.1% | 2.92 | 4.27 |
| v6_heads | + jam & quantile heads, onset feats | jam head | 0.651 | 0.59 / 0.73 | +1.4% | 2.07 | 0.412 | 0.70 / 0.29 | – | – | – |
| v6_route | + route-to-venue feats | jam head | 0.651 | 0.58 / 0.74 | +1.6% | 2.08 | 0.419 | 0.68 / 0.30 | – | – | – |
| v6_route_att | + attendance-weighted loss | jam head | 0.650 | 0.58 / 0.75 | +1.6% | 2.08 | 0.415 | 0.68 / 0.30 | – | – | – |
| v7_attn | + attention pooling | jam head | 0.651 | 0.59 / 0.73 | +1.5% | 2.08 | 0.413 | 0.69 / 0.30 | +1.3% | 2.97 | 4.30 |
| v7_multi | route, trained on b3+b5 | jam head | 0.649 | 0.59 / 0.73 | +1.2% | 2.06 | 0.406 | 0.68 / 0.29 | – | – | – |
| x_all | route, trained on b3+b4+b5 | jam head | 0.652 | 0.58 / 0.75 | +1.4% | 2.06 | 0.428 | 0.67 / 0.31 | +1.2% | 2.97 | 4.31 |
| x_scratch_big | bigger model from scratch | jam head | 0.633 | 0.54 / 0.76 | +3.8% | 2.12 | 0.431 | 0.62 / 0.33 | +3.7% | 3.05 | 4.35 |
| s_jam10 | route, heavy jam weights | jam head | 0.651 | 0.59 / 0.73 | +2.0% | 2.10 | 0.417 | 0.68 / 0.30 | +1.5% | 2.98 | 4.31 |
| s_lr | route, higher LR | jam head | 0.643 | 0.58 / 0.72 | +2.3% | 2.10 | 0.418 | 0.69 / 0.30 | +1.8% | 2.99 | 4.31 |
| x_oracle | ORACLE diagnostic (not deployable) | jam head | 0.648 | 0.59 / 0.72 | +1.5% | 2.07 | 0.403 | 0.70 / 0.28 | +1.2% | 2.97 | 4.30 |
| **ens3 (chosen)** | average of x_all + s_jam10 + v6_route | jam head | 0.653 | 0.58 / 0.75 | +1.4% | 2.07 | 0.423 | 0.69 / 0.31 | +1.2% | 2.97 | 4.30 |
