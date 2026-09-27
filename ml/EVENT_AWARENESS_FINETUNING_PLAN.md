# Event-awareness fine-tuning: implementation handoff

Prepared from the repository on 2026-09-26. This document is an implementation plan for Claude. No training, checkpoint changes, or source-code implementation was performed while writing it. Commands marked **proposed** require implementation before they will work.

## 1. Objective and scope

Starting from `data/forecast/experiments/event_patch_v2_main/best.pt`, produce a separate checkpoint that better anticipates event-related congestion while nearby roads are still clear, without materially degrading ordinary traffic forecasts.

First fine-tune only the existing event-conditioning branch. If validation shows that this is insufficient, also fine-tune a narrowly defined part of the forecast decoder at a lower learning rate. Preserve the trained spatial/temporal backbone, normalization, road order, output contract, and original checkpoint.

Work in `ml/`. Follow the repository ownership rules. Do not change API/web behavior, shared contracts, routing policies, RL training, deployment defaults, or cloud infrastructure as part of this experiment. Do not automatically promote the candidate to the serving checkpoint. Use a task branch such as `ml/event-awareness-finetune`, preserving existing uncommitted work and other running jobs.

The first experiment intentionally retains the existing input features and 60-minute forecast horizon. Richer event categories, venue anchoring and longer horizons are separate follow-ups described below; they must not be silently mixed into the initial comparison.

## 2. What is actually implemented today

| Component | Code and current behavior |
|---|---|
| Configuration | `forecast/config.py`: strict dataclasses, unknown keys rejected. `load()` resolves only one inheritance layer. |
| Dataset | `forecast/data.py`: six completed 10-minute history buckets, six future buckets; causal history fill for at most two buckets; unfilled observed/non-closed targets. |
| Normalization | `fit_norm()` fits history statistics on training windows; checkpoint stores those statistics. |
| Event inputs | `forecast/events.py`: schedule, published attendance estimate/missing flag, closure footprints, proximity and graph connectivity. No explicit concert/festival category or realized future demand. |
| Event timing | Schedule context is present throughout a scenario. Time-to-start/end features are clipped at six hours, which is not a six-hour forecast horizon. Announcement/publication availability is not modeled. |
| Event branch | `model.EventBranch`: pair encoder, aggregation, graph propagation, block FiLM/gates and decoder conditioning. Parameters are under `events.*`. |
| Backbone | `model.EventPatchForecaster`: temporal attention, spatial patches, global patch summaries, legal-road message passing. |
| Training | `train.train()` optimizes all parameters. `epoch_plan()` balances families, but does not specifically balance pre-surge windows. There is no event-only fine-tuning mode. |
| Objective | `losses.masked_huber()` on log travel-time ratio; optional congestion loss is disabled in the existing run. |
| Selection | `train.val_loss()` and early stopping use citywide Huber loss, not advance-warning performance. |
| Evaluation | `evaluate.py` reports citywide, event-near, severe, buildup, and context-removal results. Its buildup metric includes missing issue-time traffic. |
| Serving | `predict.Predictor` strictly loads the model state and checkpoint config. `coordination/rl/forecast_bridge.py` uses this predictor. Preserve compatibility. |

### Current artifacts and data availability

Paths below are relative to `ml/`:

- Parent: `data/forecast/experiments/event_patch_v2_main/best.pt`.
- No-event comparison: `data/forecast/experiments/event_patch_v2_main_noevent/best.pt`.
- Frozen dataset: `data/forecast/datasets/b3_main_v3net_ep2/`.
- Source exports and scenario metadata: `data/sf_citywide/batches/b3_main/`.
- Current report: `reports/forecast_event_patch_v2_main.md`.
- Existing tests: `tests/test_forecast.py`.

At inspection, frozen metadata, graph, normalization, and window index existed locally, but the dataset's `runs/` cache was absent. Source exports existed. Verify this again before implementing recovery; another process may have restored them. The local Python environment can access an RTX 4070 Laptop GPU. The original v2 training summary records an RTX PRO 6000 Blackwell server; do not extrapolate its throughput to the laptop.

Frozen split:

- Train: Sunday Streets Excelsior, Folsom, Halloween Cortland, Chinatown Night Market, Potrero Hill Festival.
- Validation: Bearrison.
- Test: Portola.

Existing arrival windows first issue forecasts 60 minutes before public opening; full-event windows first issue forecasts 30 minutes before opening. These can already contain attendee traffic. Audit actual clear-road coverage rather than equating “before opening” with “before congestion.”

### Baseline to preserve

Held-out Portola results, rounded from the existing report:

| Metric | Existing event model | Model without event branch |
|---|---:|---:|
| Citywide travel-time MAE | 2.330 s | 2.331 s |
| Event-run, event-near travel-time MAE | 5.695 s | 5.879 s |
| Severe-road travel-time MAE | 5.075 s | 5.070 s |
| Reported buildup recall | approximately 53–54% | approximately 53–54% |

Removing event context from the same event model increases event-near MAE from 5.695 to 5.790 seconds. This shows context sensitivity and modest benefit, not demonstrated advance warning. The report's large label counts include overlapping forecasts; they are not independent trials.

## 3. Preflight and reproducibility

Implement a preflight before any optimizer step:

1. Load the trusted parent checkpoint; verify `use_events=True`, dataset/split hashes, feature schema, network version, and exact ordered road IDs.
2. Record parent SHA-256, code revision where available, dirty-file status, seed, device, dependency versions, and the complete fine-tuning specification.
3. Verify graph arrays and normalization agree with the checkpoint. Use the parent's normalization for both training and evaluation. Existing `Data` reads disk normalization while `Predictor` uses checkpoint normalization: reject an unexplained discrepancy.
4. Verify every selected source export against its frozen manifest hash before reconstructing missing arrays. Reuse `data.prepare()` extraction semantics, `run_context()`, and scheduled-closure logic.
5. Add a cache-only recovery path if needed. It may rebuild missing `runs/<run_id>/` arrays and context, but must not rewrite the frozen split, manifest, road graph, normalization or window index. Write completion markers only after successful construction; incomplete caches must be detectable.
6. Check disk space, GPU availability and existing jobs. Profile one full-city forward/backward step before the main run. Do not start cloud resources or terminate unrelated processes.
7. Refuse to overwrite an existing output experiment unless explicitly resuming that same experiment with matching provenance.

Do not run a fresh audit that silently changes the selected dataset. Do not include previously excluded scenarios simply because their exports exist.

## 4. Add an explicit event-window index

New suggested module: `forecast/event_windows.py`.

Build an index from the existing frozen windows and scenario metadata, with:

- run ID, family ID, actual simulator seed, partition, event/control flag;
- issue timestamp and origin index;
- focal case/event ID, public start/end, minutes to each boundary;
- arrival/departure/full scenario designation;
- valid nearby-road counts, directly observed clear-road counts and future buildup-label counts;
- matched control run/window when one exists.

Match event/control windows by **family ID + actual seed + issue timestamp**. Validate road order, bucket times and partition. Never pair using family ID alone: a family can contain multiple seeds. Read seed fields from `scenarios.json`, rather than inferring them from a filename. Reject ambiguous matches, and report missing matches.

For phase-balanced sampling, classify a window from known schedules:

- pre-start: issue time in `[public_start - 60 min, public_start)`;
- pre-end: issue time in `[public_end - 60 min, public_end)`;
- other: the remaining existing windows.

Keep start and end membership separately for reporting; define a deterministic priority if the sampling categories overlap. Public schedule boundaries are proxies for traffic phases, not observed surge onset.

### Define clear-road anticipation precisely

For each road at issue time, require:

- a real observation in the last completed bucket (`a.obs[o-1]`), finite congestion and no closure;
- issue-time congestion `< 0.3`;
- a valid observed, non-closed future target from `target_mask()`;
- road within the existing 1 km focal-event neighborhood for the event-near stratum.

The primary anticipation stratum is event-run, pre-start or pre-end, event-near, directly observed clear roads. Include both future congested and future uncongested targets. Otherwise false alarms disappear from the evaluation and training rewards predicting congestion everywhere.

Report a stricter secondary stratum requiring two consecutive observed clear history buckets. Report missing-history and forward-filled-history roads separately; do not include them in the headline advance-warning result.

Future congestion may define training/evaluation labels and diagnostic counts. It must never enter model inputs or serving-time selection logic. Select validation/test windows by the fixed schedule/observation rules, never only by successful predicted outcomes.

Report how many families, seeds, windows, roads, labels and positive buildup cases qualify. If coverage is insufficient, mark that finding and retain the same definition; do not loosen it silently.

## 5. Fine-tuning interface and checkpoint compatibility

Add `forecast/finetune.py` and an explicit CLI command rather than overloading ordinary resume behavior. Ordinary `train --resume` continues the original all-parameter optimizer; it is not transfer learning.

Use a separate fine-tuning specification, for example `configs/event_patch_v3_awareness.yaml`, parsed separately from `Config`. Its fields include parent path, output name, stage, sampler, loss weights, selection thresholds and training limits. Start model/data config from the parent checkpoint and change only allowed training/output settings.

Avoid nested `inherit: event_patch_v2_main.yaml` under the current one-level YAML loader: that can lose inherited dataset/model settings. Either fix recursive inheritance with cycle tests or avoid inheritance in this new interface.

Preserve the checkpoint keys used by existing loaders: `config`, `config_hash`, `model`, `norm`, `feature_schema`, `model_ids`, dataset/split hashes, network/model versions and `state.best_epoch`. Add a separate `finetune` metadata block containing parent digest, stage, specification digest and selection results. Never claim new metadata uses the parent's original config hash if the config has changed.

Resume must restore the candidate optimizer, scheduler if used, sampler RNG, Torch RNG and early-stopping state, and verify its parent and fine-tuning specification. Do not load the parent's all-parameter optimizer into a smaller parameter group.

## 6. Stage A: event branch only

Trainable: every parameter whose name starts with `events.`. Freeze everything else, including `head`, `summary`, history/static/calendar embeddings, horizon embedding and all `blocks`.

Important: do **not** wrap the backbone forward pass in `torch.no_grad()`. Event FiLM changes activations inside frozen blocks; gradients must pass through those blocks to reach the event parameters. Frozen weights reduce optimizer state but do not eliminate activation-memory costs.

For this small adaptation, use deterministic forwards with dropout disabled (`model.eval()` with autograd enabled is valid). The current stochastic regularization is not needed to compare frozen-teacher and candidate outputs on identical windows. Document this policy consistently for both stages.

Starting settings, fixed before inspecting new test results:

| Setting | Stage A |
|---|---|
| Event learning rate | `1e-4` |
| Optimizer | AdamW, weight decay `1e-4` |
| Gradient clipping | norm `1.0` |
| Precision | existing bf16 autocast on supported CUDA |
| Batch | one full-city window; accumulate sequential windows if needed |
| Maximum epochs | 8 |
| Patience | 3 full validation evaluations |
| Sample budget | initially 8 windows per training family per epoch |
| Seed | 0 for the first experiment |

Use family-balanced sampling, split approximately equally between event/control runs. Within each group target 50% pre-start, 25% pre-end and 25% other windows. Reallocate unavailable categories transparently and log actual proportions. Keep control cases' real context; do not inject the focal event into control model inputs. The matched event's neighborhood and schedule can define control loss/evaluation masks only.

### Loss: ordinary accuracy plus explicit anticipation

Compute each component with its own valid-label denominator and equal horizon weighting, using NaN-safe targets. Empty strata contribute differentiable zero and are reported as empty.

Initial objective:

```text
L = L_global
  + 1.0 * L_event_near
  + 2.0 * L_anticipation
  + 0.5 * L_preserve
```

- `L_global`: existing masked Huber on z over all valid targets, event and control runs.
- `L_event_near`: the same loss on event-run roads within 1 km, across all phases.
- `L_anticipation`: same loss on the primary anticipation stratum. Include congested and uncongested outcomes.
- `L_preserve`: Huber between candidate and frozen parent z on valid control-run targets and event-run roads outside 3 km. The teacher sees exactly the same causal history and context. It is always evaluated without gradients.

Log each raw component, weighted contribution and cell count separately. Independent normalization ensures the few nearby roads are not drowned out by citywide cell counts. Do not tune weights using Portola test results.

Keep the parent as an immutable teacher. Teacher predictions can be cached by parent digest, source/dataset digest, run ID and issue time. Never reuse a cache after those inputs change.

## 7. Paired event/control impact: separate ablation

First measure Stage A with the objective above. Then run an explicitly named variant adding a paired-impact loss, from the same parent, with the same training budget and validation selection. This distinguishes the benefit of event-focused adaptation from the benefit of pairing.

For aligned event/control targets on their common valid, nearby roads:

```text
predicted_delta_z = predicted_z_event - predicted_z_control
observed_delta_z  = observed_z_event  - observed_z_control
L_pair = masked_huber(predicted_delta_z, observed_delta_z, common_mask)
L_total = L + 0.5 * L_pair
```

This trains a log travel-time-ratio difference. Also evaluate paired travel-time differences in seconds; do not label z differences as seconds of delay. Do not force event effects to be positive: closures and diversion may reduce traffic on some roads.

Each forecast receives only its own history and context. The paired future is a training label, never an inference feature. Matching seeds does not prove histories or background paths are identical after the event changes traffic; this is a paired-scenario prediction target, not proof of causal identification.

Keep event/control pairs in the same partition. Profile memory before retaining two full autograd graphs. If needed, use gradient checkpointing or exact sequential recomputation with detached counterpart predictions and verified gradients under deterministic forwards. Do not silently replace the paired objective with a different teacher-target objective to avoid memory use.

## 8. Stage B only if Stage A is insufficient

If Stage A fails the validation promotion criteria, allow a bounded decoder adaptation. Initialize from the best safe Stage A candidate, or from the parent if none meets the ordinary-accuracy guardrails. Record which was used.

Trainable:

- `events.*`, learning rate `5e-5`;
- `head.*` and `dec_ln.*`, learning rate `1e-5`.

Keep `summary`, `hor`, `time_fut`, `fut_base`, input embeddings and `blocks` frozen. This deliberately limits the second stage to the final decoder output and normalization. Max 4 epochs, patience 2, with the same loss, sampler, teacher and validation definitions.

Verify frozen tensors are unchanged after training. For Stage A this includes the decoder; for Stage B it excludes only the explicitly unfrozen parameters. Parameter freezing alone does not guarantee unchanged outputs, because event conditioning modifies the computation.

## 9. Validation, selection and final evaluation

Add `forecast/evaluate_events.py`, reusing `derive()`, `target_mask()` and the frozen window index. Keep the old evaluation output intact for comparison.

Evaluate the parent and every candidate with identical masks and horizons. Report pooled metrics and family-level summaries for:

1. All valid roads and all control runs.
2. Event-near roads during event runs.
3. Pre-start and pre-end anticipation strata separately, plus their combined result.
4. Severe future targets separately.
5. Far roads and missing-history roads separately.
6. Matched event/control impact error in z and seconds.

Within anticipation strata, report travel-time MAE, speed/congestion MAE, positive support, precision, recall and F1 at the existing fixed congestion threshold `0.5`, for all six horizons and highlighted 10/30/60-minute horizons. A regressed congestion score threshold is not a calibrated probability.

Do not use persistence's inevitable failure to invent a new jam from a clear current state as the sole proof of success. The primary comparison is the frozen parent; retain the no-event model as a second reference.

### Predeclared candidate selection

Use Bearrison validation only. Suggested engineering criteria, not statistical guarantees:

- Citywide travel-time MAE and control-run travel-time MAE each no more than 2% worse than the parent.
- Severe-road travel-time MAE no more than 2% worse.
- Primary anticipation travel-time MAE at least 5% lower than the parent for a meaningful improvement claim.
- Anticipation recall no lower, and precision no more than 2 percentage points lower, at the fixed threshold.

Rank safe candidates by primary anticipation travel-time MAE; use F1 as a tie-breaker. If a primary stratum has no valid support, it cannot establish promotion. Keep `best_candidate.pt` even if no candidate passes, and write an explicit `promotion_decision.json`. Never label the unchanged parent as a newly trained checkpoint.

Early stopping should follow the event-focused validation objective with guardrails, not the current citywide-only `val_loss()`. Save last state for resumability and the best candidate with its actual selection epoch and metrics.

After selecting one candidate and freezing all choices, evaluate Portola once alongside the parent and no-event model. Portola's previous scores have already informed discussion, so describe it as a reused held-out test, not a pristine final validation of generalization. Additional untouched event groups would strengthen later claims; do not regenerate splits for this experiment.

Overlapping windows and roads are correlated. Do not compute confidence intervals as if every road/bucket were independent. If estimating uncertainty, resample scenario families with paired conditions and seeds kept together; make clear that one test event group still limits event-level generalization.

### Event sensitivity and onset diagnostics

For fixed causal history, compare normal event context with focal-event-removed context, and separately with a shifted public schedule. Preserve concurrent permits and keep scheduled road closures unchanged for a schedule-only sensitivity check. State exactly what changed; this is context sensitivity, not a simulated event-free world.

Do not score shifted hypothetical schedules against unchanged factual traffic as evidence of improved counterfactual accuracy. Look for a plausible response and local concentration, then use factual error/paired scenarios for accuracy.

Optionally report onset timing: the first observed future threshold crossing on an initially clear road, predicted crossing, misses, false alarms and 10-minute bucket resolution. Require continuous valid labels up to the crossing, and report beyond-horizon/no-onset cases separately. Do not give timing errors only for detected cases without also reporting misses.

## 10. Tests required before the real run

Extend the existing tiny fixture tests; add `tests/test_event_finetune.py`:

- Stage A changes event parameters while every frozen tensor remains bitwise unchanged after an optimizer step; Stage B changes only its allowed groups.
- Gradients reach early event encoder/FiLM parameters through frozen blocks.
- Event/control pairs match seed, family and timestamp; wrong/ambiguous/missing pairs are rejected or reported.
- Directly observed clear roads qualify; missing, filled-only, closed and congested current roads do not. Future negatives remain in the denominator.
- All loss components handle empty masks and NaN excluded labels without non-finite gradients.
- If using sequential paired gradients, compare them against a joint two-forward reference on the tiny model.
- Teacher receives no gradients; its parameters never change. Prediction caches are invalidated by provenance changes.
- Cache recovery reproduces source-derived arrays without changing frozen metadata or normalization.
- A deliberately strong event-specific fixture can improve its targeted loss while frozen weights remain unchanged; this is an implementation test, not a performance claim.
- Interrupted fine-tuning resumes with the same selection/sampler/RNG behavior on a deterministic CPU fixture.
- Test-set labels cannot enter training, sampling or candidate selection.
- Parent and candidate load through `Predictor`, preserve forecast columns and mutually consistent travel time/speed/congestion, and preserve exact closure restrictions.

Run existing `tests.test_forecast` and the new fine-tuning tests. Run coordination integration checks only where needed to verify checkpoint consumption; there is no need to retrain RL.

## 11. Suggested file changes and commands

| File | Required change |
|---|---|
| `forecast/finetune.py` | Parent loading, freeze groups, optimizer, objectives, teacher, stage logic, resume and checkpoints. |
| `forecast/event_windows.py` | Phase/observation index, matched pairs, balanced sampler, support audit. |
| `forecast/evaluate_events.py` | Anticipation, paired-impact, guardrails and sensitivity reports. |
| `forecast/losses.py` | Reusable NaN-safe stratum and paired losses, preserving old functions. |
| `forecast/data.py` | Cache-only reconstruction if required; do not change existing target semantics. |
| `forecast/__main__.py` | Explicit new commands, leaving current commands functional. |
| `configs/event_patch_v3_awareness.yaml` | Separate fine-tuning specification with predeclared settings. |
| `tests/test_event_finetune.py` | Meaningful invariance, leakage, loss, resume and compatibility tests. |
| `forecast/README.md` | New run commands and truthful supported behavior. |

All commands run from `ml/` in an environment with the existing forecast dependencies. The following CLI is **proposed**, not currently implemented:

```powershell
python -m unittest tests.test_forecast tests.test_event_finetune
python -m forecast finetune-preflight --spec configs/event_patch_v3_awareness.yaml
python -m forecast event-audit --spec configs/event_patch_v3_awareness.yaml
python -m forecast finetune --spec configs/event_patch_v3_awareness.yaml --stage event
python -m forecast finetune --spec configs/event_patch_v3_awareness.yaml --stage event --resume
# Run decoder stage only if the documented validation rule requires it.
python -m forecast finetune --spec configs/event_patch_v3_awareness.yaml --stage decoder
python -m forecast evaluate-events --spec configs/event_patch_v3_awareness.yaml --partition test
```

The ordinary `forecast evaluate --checkpoint ... --partition val|test` already exists and should work on the new checkpoint. For a comparison report, pass the correct v2 dataset config explicitly; the existing `report` CLI defaults to the older v1 config.

Do not promise a training duration before profiling. Record cache preparation, teacher inference, optimization and validation time separately. Freezing the backbone still requires backpropagation through its activations, so it is not equivalent to training a tiny standalone head.

## 12. Deliverables and completion criteria

Write `reports/event_awareness_finetuning_v3.md` after execution, containing:

1. Parent/candidate paths and digests; dataset, split, feature and normalization identity.
2. Exactly which components trained and which remained frozen; proof from parameter comparisons.
3. Training/validation support before slowdowns, including unavailable strata.
4. Actual settings, loss contributions, epoch curves, selected epoch, runtime and peak memory.
5. Parent vs candidate vs no-event results, separating ordinary traffic, nearby event traffic and genuine anticipation.
6. Paired-objective ablation and sensitivity diagnostics, clearly distinguished from causal evidence.
7. Validation guardrail decisions, then final test results and limitations.
8. Predictor/closure compatibility checks and exact reproduction commands.
9. A clear recommendation: promote candidate, retain it for experiments, or keep the parent because adaptation did not help.

Save configuration, window/pair index, sampling audit, metrics and promotion decision alongside the new checkpoints under `data/forecast/experiments/`. Large artifacts remain gitignored; the implementation and human-readable report should be reviewable.

Completion means a reproducible, evaluated candidate and an honest report. Improvement is an experimental outcome, not a condition to manufacture. If it fails the gates, retain the original model and report which bottleneck remains.

## 13. Follow-ups if event-only adaptation remains weak

These are explicitly separate experiments, not prerequisites for the initial fine-tune:

**Venue/geometry anchoring.** `events.build_tensors()` skips road pairs when a case has no modeled full-closure footprint. Add versioned venue/event geometry fallback so a concert without closures can still condition nearby roads. Distinguish proximity anchors from actual closure membership; venue roads must not become closed merely because they anchor an event. Apply identical preprocessing in training and `Predictor`; preserve old checkpoint behavior through versioning. The current metadata does not guarantee venue coordinates for every event, so audit coverage before promising this fix.

**Richer known event information.** Add sourced event categories, entrances/access points and other available advance information. Do not infer features from event IDs in a way that memorizes the held-out event. New feature columns require explicit schema versioning and first-layer migration; do not change `EVENT_PAIR_FEATURES` globally and break old checkpoints. Never use sampled attendance, realized vehicle counts, generator arrival curves or future traffic as known inputs.

**Longer anticipation coverage.** If existing windows already show event-related slowing, generate a separately versioned dataset with longer pre-arrival and pre-departure coverage. Keep an entire completed history before the desired issue time. A 2–3 hour forecast needs new horizon targets and decoder handling, not merely a larger time-to-event feature range.

**Expected arrival/departure profiles.** If introducing these, estimate them only from training events and available event attributes, with uncertainty/missingness; never expose the simulator's realized future arrivals. Establish benefit on held-out event groups before relying on them.

**Announcement availability.** Current scenarios assume schedules are known. For claims about forecasts days in advance, add published/known-at timestamps and enforce issue-time filtering; do not retroactively assume every final event attribute was known earlier.
