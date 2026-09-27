# Event-jam anticipation: improvements that need no new outside data

Handoff for whoever picks this up next (written 2026-09-27). Everything here uses data and code already in `ml/`:
the saved simulations (`s3://transpeaktation-sim-692859931626-usw2/results/{b3_main,b4_long_event,b5_long_event}/`),
the road network and the event tables. No new web research, APIs or measured traffic are needed.

## 1. Where we are

The 3-hour model `event_patch_v4_h18_full` (`reports/long_horizon_retraining_h18.md`) was trained from the 60-min
v2 checkpoint on batch `b4_long_event` (7 events, issue times up to 3 h before public start/end).

| Portola test, hours 2-3 | v4 point forecast | persistence |
|---|---|---|
| Citywide travel-time MAE (s / segment / bucket) | 2.16 | 3.28 |
| Event-near MAE | 9.96 | 13.05 |
| Clear-road build-ups ("antic"): MAE | 10.30 | 10.81 |
| Clear-road build-ups: recall / precision | **0.13 / 0.77** | 0 / – |

On Bearrison (validation, a street fair like the training events) build-up recall is 0.50. The first hour is
0.2-0.3% better than v2, so general forecasting is fine. **The gap is anticipating event jams on roads that are
still clear at issue time, especially at a new venue.**

Jam-probability wrapper (`forecast/jam_wrapper.py`, `reports/jam_wrapper_h18.md`): isotonic P(jam | predicted
congestion) per group x horizon group, fitted on Bearrison. At the F1-best threshold, build-up recall goes
0.50 -> 0.68 on Bearrison (precision 0.69 -> 0.59), but only 0.13 -> 0.17 on Portola (precision 0.80 -> 0.51).
It cannot find jams the point forecast calls clear. **That is the baseline every item below must beat.**

## 2. Why the model misses them (read before changing anything)

1. **Hidden per-run randomness.** `eventsim/citywide_batch.py:sample_family` draws, per family: arrival peak offset
   -45..+120 min around public start, arrival spread 20-90 min, drive share 0.10-0.35, occupancy 1.3-2.2, parking
   radius 500-1500 m, origin decay 2-8 km, ride-hail share, departure surge. None are model inputs (correctly: they
   aren't known at prediction time). The same schedule therefore produces jams at different times and places.
2. **Point forecast + averaging loss.** Huber on z optimises a typical outcome. If a road jams in one of three
   plausible futures, the loss-optimal answer is "mostly clear". Build-ups are ~6% of anticipation cells.
3. **Few, similar training events.** v4 trained on 5 street-fair groups; Portola is a music festival at a different
   location. b5 adds Castro plus 12 permit events (still mostly neighbourhood-scale).
4. **Training barely moved.** Validation objective 0.0663 -> 0.0660 over 11 epochs; most of the result is the
   migrated v2 weights. The optimisation settings (lr 1e-4 backbone, patience 5) were never tuned for this task.

## 2b. Diagnosis after the overnight run (2026-09-27): background vs event-caused build-ups

Every build-up cell was split using the matched no-event control run (identical background trips): a jam that also
happens in the control is **background**; one that happens only with the event is **event-caused**. v4 point
forecast, jams 1-3 h ahead on near roads observed clear at issue, windows issued up to 3 h before start/end:

| | Bearrison (val) | Portola (test) |
|---|---|---|
| Share of build-ups that are background | 56% | 13% |
| Recall on background build-ups | 65% | 70% |
| **Recall on event-caused build-ups** | **32%** | **5%** |
| False alarms on roads clear in both runs | 1.0% | 0.1% |

The model forecasts background congestion well and anticipates almost no event-caused jams at an unseen venue. The
headline "antic" metric mixes both, so it overstated event awareness (Bearrison) and every overnight variant was
selected on it. None of the overnight changes (b5's 20 events, jam / quantile heads, onset / route features, loss
weighting, attention pooling, even the diagnostic model given the hidden per-run parameters) moved the pooled
numbers on identical windows beyond ~+0.01-0.06 F1. Script: split `jam_event` / `jam_both` per window with
`forecast.event_windows` + the `pair` column of the event index.

**Revised priorities (supersede the order in section 3):**

1. **Measure and select on event-caused build-ups.** Add the background / event-caused split to
   `evaluate-retrain` and `jam-wrapper`, and use event-caused recall at fixed precision as the selection metric.
2. **Learn the event effect directly.** Train with a paired target: a head predicting z(event) - z(control) (or
   "event-caused jam") on matched windows, next to the normal forecast. `losses.paired_delta_huber` exists; the
   earlier v3 paired-loss test only trained the event branch with a frozen backbone.
3. **Leave-one-venue-out validation** across training event groups, so selection rewards generalisation to new
   venues rather than similarity to Folsom (Bearrison is next to Folsom in SoMa).
4. **Venue-independent geometry inputs:** direction and distance to closures, number of access routes into the
   footprint, parking capacity inside the parking ring (from the network), so what is learned at one venue transfers.
5. Then sections 3.1-3.9 (most are now implemented: jam head, quantiles, onset / route features, attention
   pooling, multi-dataset training, ensembles; configs `event_patch_v6_*`, `v7_*`, `x_*`, `s_*`).

## 3. Improvements, in priority order

Each item lists: what, where in the code, rough effort, and how to evaluate. Keep Bearrison = validation and
Portola = test (`data.fixed_split`), select on validation only, and compare on identical windows with
`python -m forecast evaluate-retrain` plus the jam-wrapper metrics.

### 3.1 Jam-probability head (highest value)

Predict P(jam) directly next to z instead of reading it off a point forecast.

- **Model** (`forecast/model.py`): a second head on the decoder state `q` (`EventPatchForecaster.forward`, after
  `dec_ln` + event FiLM): `self.jam_head = nn.Sequential(nn.Linear(d, d), nn.GELU(), nn.Linear(d, 1))` -> logit
  `[B, H, N]`. Initialise the last bias to logit(base jam rate, ~0.25 citywide) so the untrained head is calibrated
  on average. Return `(z, logit)` behind a flag so old checkpoints and callers are unchanged.
- **Labels:** jam = target congestion >= `eval.buildup_congestion` (0.5) on valid labels (`target_mask`); never on
  missing / closed cells.
- **Loss** (`forecast/retrain.py:objective`): add `w_jam * BCE(logit, jam)` per stratum with the same horizon-group
  weighting as `hgroup_huber`. Start with `pos_weight` = 3 in the anticipation stratum, or a focal loss (gamma 2).
  Keep the z loss, since routing needs travel times.
- **Migration:** `retrain.migrate` currently errors on unknown keys; allow keys that are new in the child model
  (`jam_head.*`) to be initialised and log them. Start from `event_patch_v4_h18_full/best.pt` via a new
  `forecast finetune-jam` command, or relax the "horizon must be longer" preflight rule for same-H transfer.
- **Evaluation:** Brier score, reliability table (10 bins), PR-AUC, and recall at fixed precision (0.5 / 0.7) per
  group (antic / near / other) x horizon group x lead band. Compare with the wrapper at the same precision.
- **Serving:** add `jam_probability` to `forecast/predict.py` output. That is a **`contracts/` change**: propose it
  in its own PR and tell the team first (AGENTS.md rule). Until then keep it `ml/`-internal.
- Effort: ~1.5 h code + tests, ~40 min training on the saved data.

### 3.2 Timing-tolerant targets

Because the surge timing is hidden (section 2.1), exact-bucket labels punish a correct warning that is 20 min off.

- Add a label "jam anywhere in [t - 20 min, t + 20 min]" (max over neighbouring target buckets) and train the jam
  head on it; report both exact and tolerant metrics.
- Alternatively predict "jam at any time within the next 60 / 120 / 180 min" per road (three logits): the
  question an early warning answers.
- Effort: ~1 h on top of 3.1. Evaluation must say which label definition is used.

### 3.3 Distribution heads for travel time

Quantile heads for z (q10 / q50 / q90, pinball loss) so routing can use a pessimistic travel time near events.
Report interval coverage per stratum (target: ~80% of labels inside q10-q90). Same code paths as 3.1. ~1 h.

### 3.4 Static "route-to-venue" features (network only)

Arriving traffic concentrates on the shortest paths from the city to the footprint. Compute per (case, road) from
the network alone: the share of shortest paths from a sample of origin nodes (weighted by distance decay, as the
demand generator does) to the footprint that use that road, and the same for footprint -> city (departures). Add
them as `PAIR_STATIC` columns in `forecast/events.py:build_tensors`.

- This changes the event feature schema: migrate the event-pair input layer (`events.pair.0.weight`) by feature
  name, zero-initialising the new columns (plan section 6 rule). Never change the global default silently.
- It uses no hidden per-run values, so it is legitimate at inference.
- Effort: ~2 h (cache per footprint; the graph has ~26k roads).

### 3.5 Explicit recent-onset features near the footprint

The history already contains early arrivals, but patch attention can dilute a small local signal. Add per case:
mean / max z over footprint-near roads in the last 1-3 history buckets and their slope, broadcast to the case's
pairs (`CASE_TIME`-like columns computed from history, causal only). This mainly helps short leads (the surge has
begun), which also lifts the 0-60 min band. ~1 h + migration as in 3.4.

### 3.6 Loss / sampling tuning (cheap, do alongside)

- Up-weight jam cells in the anticipation stratum (x3-x5) and/or scale event-run weight by log(attendance)
  normalised to mean 1 (`attendance_for` in `eventsim/citywide_demand.py`; loss weight only, never an input).
- Larger `weights.anticipation` (2 -> 5), `per_family` 24 -> 48, cosine LR schedule with warm-up, backbone LR
  1e-4 -> 3e-4. The current run plateaued in 4 epochs.
- Expect a recall-vs-false-alarm trade-off, not a free gain: always report precision next to recall.
- Effort: config-only for most; ~30 min per run on one L40S / RTX PRO 6000.

### 3.7 Use all simulations already paid for

`b3_main` (312 runs, 60-min windows, includes full event days), `b4_long_event` (224) and `b5_long_event` (480)
share the network and road order. Train one model on all three with a per-window horizon mask (b3 windows have
labels only for horizons 1-6; mask the rest with the existing `target_mask` logic).

- `forecast/data.py` / `train.Data` assume one batch per dataset. Add a multi-batch dataset (list of
  `(batch, dataset_id)`) whose window index carries `batch`. The split must still come from `data.fixed_split`, and
  event groups must not cross partitions across batches.
- This also restores mid-event issue times (b3 full-day runs) that b4 / b5 lack.
- Effort: ~2-3 h.

### 3.8 Stronger event conditioning (architecture)

Only after 3.1-3.6. Options: cross-attention from each road's decoder query to per-case event tokens (instead of
only FiLM from mean/max pair aggregates), per-horizon event context into every block (now only issue-time context
modulates the blocks), and a larger event branch (hidden 64 -> 128 in the branch only). Compare against a matched
no-event model trained on the same data, otherwise the event branch's contribution is not measured (v4 skipped it).

### 3.9 Ensembles

Average 3-5 seeds (and optionally MC dropout) to get cheaper uncertainty for the jam head; report the spread.
~40 min training per seed, so run them in parallel on one GPU (each run peaks at ~9 GB).

## 4. Rules that still apply

- Synthetic data only; no claim about real events. Declared attendance is an input only where a published figure
  exists. Realised attendance, arrival curves and parking radius never are.
- Select on Bearrison, report Portola once. Do not tune thresholds on Portola.
- First-hour guardrail: citywide / control / severe travel-time MAE within +2% of v2 on identical windows.
- Keep v2 (60 min) as the serving default until a candidate is explicitly adopted. `contracts/` changes go in their
  own PR, announced to the team.

## 5. How to run things

```
cd ml
python -m forecast retrain --config configs/event_patch_v5_h18.yaml --parent data/forecast/experiments/event_patch_v2_main/best.pt
python -m forecast evaluate-retrain --checkpoint data/forecast/experiments/<exp>/best.pt --partition val|test
python -m forecast jam-wrapper --checkpoint data/forecast/experiments/<exp>/best.pt
python -m unittest tests.test_long_horizon tests.test_forecast tests.test_event_finetune
```

AWS: simulations and training ran on S3-driven EC2 nodes (scripts are not in the repo; see the b4 / b5 stage scripts
in the bucket under `b4/` and `b5/`). Watch the vCPU quotas: other jobs often hold them.
