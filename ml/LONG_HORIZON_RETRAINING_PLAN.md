# Full-model retraining for 3-hour and optional 5-hour event forecasts

Codebase-specific handoff for Claude, inspected 2026-09-26. This is a plan only: no code, dataset, checkpoint or running job was changed and no training was started to produce this document.

## 1. Decision

Build a **3-hour model first**, predicting 18 future 10-minute buckets from the existing 6 completed history buckets. Train all model parameters, starting from the successful v2 checkpoint where shapes are compatible. This is full-model adaptation, not another frozen-backbone event-only experiment.

Make 5 hours an explicitly supported second configuration: 30 future buckets. Start it after the 3-hour data/shape/optimization pilot passes. Preserve independent artifacts for both horizons. Do not repeatedly feed the 60-minute prediction back as history and call that a validated 3/5-hour model.

Longer forecasts answer a new question: what will traffic look like several hours ahead? They do not automatically solve weak event conditioning. Include genuinely earlier event examples, context coverage checks and event-versus-no-event comparisons so the run measures the requested capability.

Scope: model, synthetic-data preparation, evaluation, and necessary internal routing compatibility in `ml/`. No cloud provisioning, deployment, API/web contract changes or RL retraining is implied. Preserve other contributors' work. Use a dedicated task branch and new dataset/experiment IDs.

## 2. How long: evidence and planning estimates

Measured reference from `data/forecast/experiments/event_patch_v2_main/train_summary.json`:

- 60-minute v2 model: 31 epochs, selected epoch 23, **6,751 seconds = 1 h 52 min** training.
- Hardware: **RTX PRO 6000 Blackwell Server Edition**, approximately 6.7 GB reported peak GPU allocation.
- These are not RTX 4070 Laptop training timings.
- Main simulation batch: 384 runs, two AWS c8a.48xlarge nodes with 384 runs in parallel; pipeline manifest records approximately **69 minutes** elapsed and a longest simulation of 4,110 seconds. That large machine pool is why the batch completed quickly; availability of that pool is not assumed.

Unbenchmarked planning allowances, assuming a comparable GPU, roughly the existing number of training steps, and no large memory bottleneck:

| Work | 3-hour target | 5-hour target |
|---|---|---|
| Train one all-parameter candidate | approximately 3–6 hours | approximately 4–10 hours |
| Train matching no-event baseline | additional run of comparable order | additional run of comparable order |
| Data regeneration | separate, potentially dominant | separate, usually more expensive |
| Preparation and final evaluations | profile and budget separately | profile and budget separately |

These are broad scheduling allowances, not measured forecasts or promises. A larger horizon does not triple/quintuple the entire compute cost: history backbone length is unchanged, while the decoder, future event features, targets and output grow. GPU memory may nevertheless be the limiting factor. More scenarios or optimizer steps increase runtime independently of horizon.

For an implementation + new-data + trained/evaluated result, reserve **a working day or more on a suitable GPU with a substantial CPU simulation pool**. A small CPU pool or laptop can stretch data generation to days. There is no defensible fixed end-to-end ETA until the longer scenario pilot runs. Do not describe this as a 25–30-minute evaluation job.

Before the full run, replace these allowances with measurements:

1. Simulate representative long arrival, departure and full scenarios, including a high-load case; measure CPU time, RAM, output size and quality flags.
2. Run 50 training steps after warm-up and at least 20 validation windows on the intended GPU for H=18; separately profile H=30 if requested.
3. Estimate `steps_per_epoch * seconds_per_step * expected_epochs + validation_time`, with a 30% contingency and a stated early-stopping assumption.
4. Estimate simulation wall time from measured total CPU demand, effective worker count and the longest jobs, not just ideal parallel division. Include export/preparation.
5. Report the estimate and configured budgets before expensive execution; use only compute already authorized by the user.

## 3. Existing data cannot just be relabeled

`forecast.data.window_origins()` requires all history and future buckets to be in the allowed demand phase. For a contiguous run with D demand buckets, Th=6 and H targets, usable origins are `max(0, D - Th - H + 1)`.

Inspection of `b3_main_v3net_ep2/window_coverage.csv` found:

| Run category | Runs | Demand buckets | Windows at H=6 | Windows at H=18 | Windows at H=30 |
|---|---:|---|---:|---:|---:|
| Arrival | 104 | 21 | 1,040 | 0 | 0 |
| Departure | 108 | 8, 20 or 21 | 904 | 0 | 0 |
| Full event | 100 | 42–68 | 4,332 | 3,132 | 1,932 |
| Total | 312 | | 6,276 | 3,132 | 1,932 |

These are arithmetic counts from the coverage CSV, assuming its demand intervals are contiguous; verify against actual cached arrays and break down by partition. Sixteen short departure runs already have no current windows.

Keeping only full-event runs would change the training mixture and eliminate all short arrival/departure examples. Their earliest issue time is still only 30 minutes before public opening. A longer target sequence would not create predictions issued 3–5 hours before the event.

Use existing long runs for a shape/runtime smoke test only. For the intended advance-warning result, generate additional earlier and longer scenarios in a new versioned batch.

## 4. Data generation changes

Relevant code: `eventsim/citywide_batch.py`, especially `window_for()`, scenario planning/time fields, event/background demand generation, restrictions and export; orchestration is in `eventsim/citywide_pipeline.py`.

### Declare issue times, then derive simulation coverage

For each event boundary B (start or end), choose desired forecast issue times in `[B - H_minutes, B + 30 min]`, sampled every 10 minutes. A fully supported run must contain:

```text
demand_start <= earliest_issue - 60 minutes
demand_end   >= latest_issue + forecast_horizon
simulation_start <= demand_start - warmup
simulation_end   >= demand_end + drain
```

This example needs 7.5 hours of demand coverage for H=3 hours, or 11.5 hours for H=5 hours, per boundary before overlap consolidation. Adjust desired issue-time ranges explicitly if that is too expensive; do not silently shorten the lead-time claim. Combine overlapping arrival/departure windows into a full-event run where this reduces redundant simulation.

The current `window_for()` clamps to the event calendar day. Supporting very early starts or late departure forecasts may require crossing midnight. Implement date-aware absolute times/day offsets consistently for schedules, background demand profiles, restrictions, exports and local-to-UTC conversion. Do not clip away the requested lead time. If cross-day support is deferred, flag/exclude affected cases and report the resulting event coverage.

### Keep the data physically and causally consistent

- Keep the existing reviewed road network and canonical segment order.
- Keep one unit system and 10-minute UTC buckets; observed values only, no filled targets.
- Preserve paired event/control family and actual seed identity and intended exogenous settings.
- Ensure background departures continue through every forecast target interval. Existing drain is a no-new-departure phase and cannot be relabeled as normal demand.
- Generate actual additional history/future traffic; never pad, repeat or interpolate old forecasts into labels.
- Regenerate or correctly extend demand/restriction files for the longer interval; simply changing SUMO end time is insufficient.
- Re-evaluate closure overlaps and concurrent permits for the expanded interval. Do not carry only the old narrower restriction list.
- Record clipping/truncation of sampled arrivals and departures; extending a window must not silently change total event demand in an undocumented way.
- Retain scenario quality gates for unfinished traffic, closure violations, route errors and teleports. Report exclusions by event group.

Run a small pilot across train and validation groups before launching the full matrix. A proposed starting matrix is 7 retained event groups x 3 window types x 4 families x 2 seeds x event/control = 336 runs before exclusions or merged windows. This is an initial budget, not a claim that 336 runs are required or sufficient. Profile first, then freeze the chosen manifest.

Where 5 hours is likely to be required, generating a reusable 5-hour-capable batch can avoid repeating simulation for the later model. That costs more upfront. Otherwise start with the 3-hour batch. Give the two derived horizon datasets distinct IDs even if they share verified immutable source exports.

## 5. Audit what the event model can actually know

Before retraining, report per event group:

- scheduled public hours and source;
- published attendance estimate and missingness;
- number of qualifying footprint roads and nearby roads receiving event features;
- event/control target differences versus lead time;
- scenario variation visible to the model versus hidden sampled demand/arrival variation.

Do not assume a missing venue anchor explains the previous results without this audit. Existing event features derive direct road pairs from modeled full-closure footprints. If any included event has no such anchor, add a sourced venue/event-geometry fallback in a versioned preprocessing path; proximity anchoring must not create a fictitious closure. Train and inference must share the same implementation.

If adding event categories, use sourced or explicitly curated categories, with unknown handling; never use event IDs as memorization features. Category columns change feature schema and input-layer shapes, so handle them through explicit checkpoint migration rather than changing global defaults that break old models.

Neither model may see realized attendance, future generated vehicle counts, generator arrival curves or future traffic. At longer horizons these hidden factors may impose an irreducible error floor. State that limitation instead of promising precise five-hour jams from a schedule alone.

For the minimum controlled experiment, retain the existing feature schema unless the audit reveals missing context for an included event. Treat new event attributes as a named feature ablation rather than changing everything at once.

## 6. Model and checkpoint migration

The current `EventPatchForecaster` already accepts configurable H. Most weights are horizon-independent; `hor.weight` is an H-by-hidden learned embedding. Keep the six-history-step encoder and change future dimensions to 18 or 30.

Implement a dedicated full-model transfer entry point, e.g. `forecast/retrain.py`, rather than using ordinary `train --resume` or the event-only freeze groups in `finetune.py`.

Initialization:

1. Load trusted parent v2 metadata and weights; retain a read-only parent digest.
2. Build the new model/config/graph with H=18 or H=30.
3. Copy matching weights only after verifying graph/feature identity. Copy the first six horizon embedding rows exactly. Initialize additional rows from the parent's last row plus small seeded noise; log the initialization. An analytic horizon encoding would be a separate architecture change.
4. If event input schema expands, migrate old columns by feature name and initialize only genuinely new columns. Do not rely on `strict=False` to solve tensor shape mismatches; incompatible shapes must be explicitly handled.
5. Set every intended model parameter trainable, including `blocks.*`, embeddings, summary, decoder and event branch. Verify with a parameter count and gradient test.
6. Start a new optimizer and experiment; do not load the parent's optimizer state across resized parameters.
7. Keep the parent's normalization for the transfer experiment, after verifying input semantics. Record its provenance; do not accidentally let `Data` read newly fitted disk statistics while `Predictor` uses the old checkpoint statistics. A new normalization scheme requires explicit migration or a from-scratch comparison.

Save complete candidate provenance: parent hash, new batch/dataset/split hashes, feature/normalization version, H, source code identity, actual initialization and trainable groups. Preserve loading of original 6-step checkpoints and their exact behavior.

Train all layers, but do not discard the useful v2 weights by default. Random initialization is an optional ablation if needed, not required just because the entire model is being trained.

## 7. Training objective and sampling

Use the implemented `event_windows.py` and event-specific evaluation helpers as a starting point; they are now present in the codebase. The prior event-fine-tuning plan is not merely hypothetical anymore. Keep its directly observed clear-road semantics.

Replace hard-coded `PRE_S=3600` with versioned/configured lead bands:

- 0–60 minutes before start/end;
- 60–120;
- 120–180;
- 180–240 and 240–300 for the five-hour experiment.

Track start and end flags separately even when they overlap, and define one deterministic sampling category. Include ordinary event-active/recovery windows and no-event controls. Balance event families, seeds and lead bands instead of drawing mostly many overlapping long-run origins. Do not select validation/test cases based on whether the model succeeds.

Starting loss:

```text
L = L_global + 1.0 * L_event_near + 2.0 * L_clear_road_anticipation
```

Each term uses NaN-safe masked Huber on z, including future clear negatives as well as congested positives. Normalize each stratum and horizon group independently. Clear-road anticipation requires an actually observed, finite, non-closed last history bucket with congestion <0.3; missing/filled-only roads remain separate diagnostics.

Protect the first hour through explicit horizon-group weighting, rather than allowing 12 or 24 extra buckets to swamp it:

- H=18: first 6 buckets receive 50% of each term's weight, remaining 12 receive 50%.
- H=30: first hour 40%, hours 2–3 30%, hours 4–5 30%.

Within groups, weight valid horizons equally and report empty support. These are initial settings to evaluate on validation, not established optimal weights. Keep the previously unhelpful paired-loss variant out of the default expensive run; preserve paired-impact evaluation and add paired training later only as a bounded ablation.

Optional parent distillation applies only to the first six matching horizons and control/far-road strata, with separately reported weight. Never distill parent predictions into unsupported hours 2–5.

Initial all-layer optimization settings:

| Setting | Initial value |
|---|---|
| Inherited backbone/decoder LR | `1e-4` |
| Event branch and horizon embedding LR | `3e-4` |
| Optimizer | AdamW, weight decay `1e-4` |
| Gradient clipping | 1.0 |
| Precision | bf16 autocast on supported CUDA |
| Dropout | existing 0.1 for full-model training |
| Maximum epochs | 30, early stopping patience 5 |
| Windows per family per epoch | begin with existing 24, balanced across phases/event-control |
| Batch | one full-city window, optionally accumulate 2–4 steps |
| Seed | 0 for first candidate; more seeds after a promising result |

Do a short optimization pilot before the full budget. If memory is tight, checkpoint attention blocks or chunk horizon-conditioned decoder/event computations while verifying identical loss/gradients. Do not reduce road coverage or silently move parts of the run to CPU. Report achieved rather than nominal epoch/step budgets.

## 8. Data and evaluation versioning

Suggested new names:

```text
batch:       b4_long_event
datasets:    b4_long_h18_v1, b4_long_h30_v1
experiments: event_patch_v4_h18_full, event_patch_v4_h18_noevent
             event_patch_v4_h30_full, event_patch_v4_h30_noevent
```

Names are proposed, not created. Preserve the current train/validation/test event-group mapping explicitly. Do not rerun hash-based group selection after adding/removing groups and accidentally move Portola or Bearrison into training. Preserve family/seed event-control pairs in one partition.

Hash immutable source files and new window indexes. Existing arrays are shareable only where source road order, bucket semantics and context match exactly; window lists/manifests are horizon-specific. A warm-start parent legitimately has a different dataset/H, so use a migration compatibility check rather than disabling all hash checks or pretending the datasets are identical.

## 9. Evaluation that establishes longer advance warning

Evaluate two independent axes:

1. **Forecast horizon**: target bucket +10, +30, +60, +120, +180, and +240/+300 when applicable.
2. **Event lead time at issue**: how long before opening/closing the forecast was made.

A forecast for +180 minutes issued 10 minutes before opening is not evidence of a warning issued three hours before opening. Report the cross-tabulation and support counts.

Systems:

- persistence on the same available causal inputs, repeated to the relevant H;
- new full event model;
- matching new no-event model trained on the same long-horizon windows and budget;
- original v2 checkpoint **only for the first six horizons on common issue windows**. Do not extend it by copying its last prediction and call that the original model's three-hour accuracy.

The no-event model retains the same explicit closure inputs/routing restrictions as the existing ablation. Start it from the v2 no-event checkpoint, with the same horizon migration procedure and full-layer training; document its different parent as in the existing comparison.

Report citywide, control, event-near, severe and directly observed clear-road anticipation metrics: travel-time MAE/WAPE, speed/congestion error, fixed-threshold precision/recall/F1, positive counts and signed error. Report near-road positive and negative outcomes separately, without removing negatives from the headline confusion matrix. Add event/control incremental impact errors on common valid targets.

Select using Bearrison validation only. Suggested initial guardrails:

- first-hour citywide and control MAE no more than 2% worse than v2 on identical supported windows;
- first-hour severe MAE no more than 2% worse;
- long-horizon event-near/anticipation error better than persistence and the matched no-event model, with support and recall/precision tradeoffs displayed;
- require a practically meaningful advantage, e.g. 5% lower long-horizon anticipation MAE than no-event, before claiming strong event benefit.

These targets are predeclared engineering criteria. If the new model fails, save the candidate and honest results rather than changing the threshold after viewing Portola. Portola is a reused held-out event, already discussed in prior experiments; report that limitation. Bootstrap families, not individual correlated road/bucket rows, if estimating uncertainty.

Keep final evaluation affordable: parent first-hour, persistence and the two new H-matched systems are enough. Do not rerun all unsuccessful event-only candidates across the enlarged dataset unless a specific question requires it.

## 10. Internal compatibility changes that a YAML edit would miss

| Location | Required audit/change |
|---|---|
| `forecast/config.py` / YAML | Explicit 18/30 horizons, headline horizons and lead-band settings. Loader currently resolves one inheritance layer only; use a full config or fix/test recursive loading. |
| `forecast/data.py` | New horizon-specific origins/masks, causal history, explicit normalization source, cache provenance. |
| `forecast/model.py` | Resized horizon embedding, migration and memory profiling; output remains z `[B,H,N]`. |
| `forecast/event_windows.py` | Replace the one-hour pre-boundary constant with lead bands used by sampling and evaluation. |
| `forecast/evaluate_events.py` | Stratify by event lead and future horizon; keep valid-mask and clear-road semantics. |
| `forecast/train.py:sanity` | Currently shifts event schedule +3 hours and calls it beyond the horizon. For H=18/30, calculate a shift genuinely outside the new forecast window. |
| `forecast/predict.py` / adapter | Generic H mostly exists. Verify 18/30 exports, per-road time intervals, normalization and old checkpoints. |
| `coordination/config.py:ForecastCfg` | Default horizons=6; dedicated long-horizon routing config must specify/derive 18 or 30. |
| `coordination/rl/forecast_bridge.py:refresh` | Currently passes literal `6` to `validate()`. Derive H/bucket/history from the loaded checkpoint and verify measurement compatibility. |
| `coordination/coordinator.py:_context` | Current future-load summary covers fixed 3600 seconds. Decide explicitly whether this remains a one-hour feature or becomes horizon-aware; do not silently change RL feature semantics. |
| `coordination/forecast_store.py` | Verify snapshot validation/allocation and index math for H=18/30. |
| Serving/defaults | Existing one-hour model stays active until explicit adoption. Do not change API/web assumptions or shared contracts automatically. |

The forecast output columns need not change just because there are more horizon rows. Check all consumers and any contract enum/max-horizon restriction before claiming end-to-end compatibility. A longer prediction window does not mean users must plan five-hour trips or wait for five hours of history.

RL checkpoints were trained under an observation/forecast setup. Changing H or the future-load summary is a transfer/compatibility issue; tag it and retain original behavior until separately tested. No RL retraining is needed to train/evaluate the forecaster itself.

## 11. Required tests and run order

Tests:

- H=18/H=30 window counts and exact target bounds on fixtures; short runs correctly yield zero origins.
- No warmup/drain/future labels enter history, and no artificial tail labels appear.
- Cross-midnight timestamps, restriction intervals and background-demand profiles where supported.
- Parent's first six horizon rows and other copied weights are exact after migration; new rows are finite and seeded.
- All model groups receive gradients and change after a full-training step; no unintended freeze survives from fine-tuning.
- Feature-schema/normalization mismatches fail loudly; inference and training use the same transforms.
- Old 6-step checkpoints still load; new predictions have 18/30 rows per supported road and consistent time/speed/congestion.
- Long-horizon closures and legal routing checks remain correct through the last target bucket.
- Lead-time metrics distinguish issue time from target time; no-event pairing and split isolation remain valid.
- Resume restores candidate optimizer/RNG and horizon provenance.

Order of work:

1. Data/event-feature audit and long-window planner.
2. Implement parameterized H, new lead metrics, migration and tests.
3. Long-scenario and training/memory pilot; publish measured cost estimate.
4. Generate/quality-check the frozen 3-hour-capable dataset, prepare new windows.
5. Full-model H=18 training and matched no-event training.
6. Validation selection, then one fixed held-out comparison and inference smoke test.
7. Only then execute H=30 using adequate coverage and a separate measured budget.

Existing `forecast audit`, `prepare`, `evaluate`, `predict` and `snapshot` commands remain reusable where their semantics fit. Add a clearly named transfer-training command such as `forecast retrain --config ... --parent ...`; that command is **proposed, not currently implemented**. Do not use `train --resume` as a substitute for migration.

## 12. Final deliverables

Write `reports/long_horizon_retraining_h18.md` and, if run, `reports/long_horizon_retraining_h30.md`, including:

- new scenario coverage and exclusions, original versus new issue lead times;
- actual hardware, source/parent/checkpoint identity and initialization;
- actual preparation/simulation/training/evaluation durations and resource use;
- event-feature coverage and known uncertainty in future demand;
- per-horizon and event-lead comparisons, including first-hour retention;
- clear-road positive/negative breakdown and paired incremental impact;
- selected checkpoint, test results and explicit promote/retain-parent decision;
- output/routing compatibility checks and reproduction commands.

The goal is an honestly evaluated model with a longer useful planning window. Training for three or five hours ahead is feasible architecturally; useful event anticipation must still be established by the new data and comparisons.
