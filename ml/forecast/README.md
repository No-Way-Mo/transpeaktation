# `forecast/`: event-conditioned spatial-patch traffic forecasting

```
traffic history + road attributes + structured event context
  → shared spatial-patch forecasting model
  → future road travel times and congestion (10-min buckets, next 60 min, every modelled road)
  → time-dependent routing graph for fleet optimization (adapter.py)
```

The design takes PatchSTG's local/global spatial patching and ConFormer-style event conditioning and adapts them.
It is **not** a reproduction of either paper (see "Simplifications"). It is a separate package from the Castro-only
`eventsim` trainer. It does not use `eventsim.features.Static`, which builds dense N×N matrices around one event
footprint, or `ObsModel`, which adds synthetic noise and missingness. The exported traffic grid is used as is.

> **Synthetic.** Every model here is trained and evaluated on SUMO scenarios (`sumo_synthetic`). They are grounded
> in real SF roads, verified permit closures and sourced event hours. Demand, attendance and driver behaviour are
> scenario assumptions. Outputs carry that provenance and must not be presented as measured traffic.

## Install and run (from `ml/`)

```sh
pip install -e .[forecast]           # torch, scipy, pyarrow, pyyaml; the SUMO generator does not need them
python -m forecast audit    --config configs/event_patch_v1.yaml   # eligibility, integrity, frozen split + manifest
python -m forecast prepare  --config configs/event_patch_v1.yaml   # per-run .npy cache, graph, patches, windows, norm
python -m forecast sanity   --config configs/event_patch_v1.yaml   # tiny overfit, gradients, schedule influence, profile
python -m forecast train    --config configs/event_patch_v1.yaml            # [--resume] [--seed S --name N]
python -m forecast train    --config configs/event_patch_v1_noevent.yaml    # ablation: same backbone, no event branch
python -m forecast evaluate --checkpoint data/forecast/experiments/event_patch_v1/best.pt --partition val
python -m forecast evaluate --checkpoint data/forecast/experiments/event_patch_v1/best.pt --partition test
python -m forecast report   --experiments event_patch_v1 event_patch_v1_noevent
python -m forecast snapshot --config configs/event_patch_v1.yaml --run <run_id> --issued-at <ISO UTC> --output <dir>
python -m forecast predict  --checkpoint <ckpt> --input <dir> --output <forecast.parquet>
python -m unittest tests.test_forecast
```

The machine used here has the conda env `strats`, which already has the stack installed.

## Stages and files

| Module | Role |
|---|---|
| `config.py` | dataclass config loaded from YAML (`inherit:` for ablations); config hash stored in checkpoints |
| `audit.py` | batch inventory; per-run export checks (row count, road order, consecutive 10-min UTC buckets, masks, provenance, closure mask vs scheduled restrictions); pair eligibility; deterministic event-group split; immutable `manifest.json` + `splits.json` |
| `graph.py` | modelled roads, legal arcs from the selected network, static road features, balanced patches, sparse BFS |
| `data.py` | one-pass Parquet → memory-mapped per-run `.npy`; causal windows; history features; train-only normalisation |
| `events.py` | scenario metadata → portable context JSON → sparse (case, road) pair features |
| `model.py` | patch backbone + event branch |
| `losses.py` | masked Huber on z (equal horizon weights); optional congestion L1 (off) |
| `train.py` | AdamW training, balanced family sampling, early stopping, resumable checkpoints, `sanity` |
| `evaluate.py` | persistence baseline, metrics by horizon / run type / event-near / severity / event group, build-up detection, counterfactual context check, markdown report |
| `predict.py` | snapshot cutter, inference, fleet-facing export + closures table |
| `adapter.py` | time-dependent routing costs over legal connections; vehicle→pickup and trip ETAs |
| `CONTRACT_PROPOSAL.md` | proposed shared contract (not applied) |

Outputs go to `data/forecast/` (gitignored): `datasets/<dataset_id>/` and `experiments/<name>/`. Reports go to
`reports/forecast_*.md`.

## Data definition

* **Dataset.** `b3_verify` on `net_v3`: 8 event families, each with an event run and a paired control run, all 16
  runs `ok`, and the v3 quality gate passed. `b2_bench` (v2 network) and `calib_v3` are not mixed in. The manifest
  records every selected and excluded run with reasons, input SHA-256s, the network version hash, road-order hashes
  and the feature schema.
* **Split** (frozen before any window is built): event groups are ordered by `sha256("event_patch_v1:<group>")`.
  The first group is test, the next is val, and the other 6 are train. All seeds, windows and event/control variants
  of a group share a partition. Batch/family/seed/partition ids are never model inputs.
* **Timing.** Buckets are `[t, t+10 min)` in UTC. A window issued at `issued_at` sees buckets that ended by
  `issued_at` (6 buckets = 60 min). Horizon k covers `[issued_at + 10(k-1), issued_at + 10k)` min. Windows lie
  entirely in the demand phase of one run. Warmup and the no-departure drain are excluded (see the report for what
  this costs in arrival/departure/recovery coverage).
* **History features** (per road, per step): z (log travel-time ratio), speed/free-flow, congestion (all causally
  forward-filled for ≤ 2 buckets, then neutral 0 after standardisation), the original observed mask, the fill flag,
  a missing-after-fill flag, observation age, and closed status. Calendar sin/cos is in SF local time.
  Volume/throughput is excluded.
* **Static features.** Log length, log free-flow speed, lanes (+ assumed flag), one-way flag, signal at the
  downstream node, posted-limit flag, heading, local x/y, log in/out degree over legal arcs, link flag and road-class
  one-hots.
* **Targets.** `z = log(travel_time_s / (length / free_flow))` from the export's `travel_time_s = length /
  max(speed, 0.1 m/s)`. A label is used only if the road was measured, not closed in that bucket, has passenger
  access and has a SUMO edge. Labels are never filled.
* **Roads.** 26,408 modelled roads. 819 connectors absorbed into merged junctions and 27 omitted self-loops are
  `unavailable`. 127 merged parallel carriageways are `unavailable` to the model; in the export they get their
  representative's value with `prediction_source=representative_road`. 251 SUMO roads without passenger access are
  `restricted`.
* **Graph.** 60,347 legal arcs between modelled roads (SUMO connections of `net_v3/net_c90.net.xml`). None of the
  1,529 turn prohibitions appears as an arc. Arcs are never inferred from coordinates.
* **Patches.** Recursive coordinate bisection of road midpoints into 207 patches of 127–128 roads (88 padding
  slots). 10,398 arcs cross patch boundaries and are kept by the sparse exchange.

## Event context (allowed inputs only)

Cases are the focal public event (event runs only) and every concurrent permit applied to the run. Each case has:
kind; scheduled public start/end; scheduled restrictions (footprint roads and UTC begin/end); and the published
`attendance_claim` as a declared attendance with its source URL, or missing plus a flag when none was found (3 of 8
events). Concurrent permits are simulated as closures only, with no attendee demand, so they are encoded as permits,
not as public events.

Per (case, road) pair within 3 km of the case footprint, the features are: footprint membership, distance
proximities (300 m / 1 km / 3 km), hop proximity up- and downstream over legal arcs (≤ 8 hops), the case's static
features, and, for each bucket, hours to/from public start/end, public-active flag, hours to/from the restriction
window, restriction-active flag, and the share of the bucket for which this road is restricted by the case.

Never used: sampled attendance or vehicle counts, arrival curves, driver/routing/signal parameters, future traffic,
or the paired run's outputs.

## Model (`event_patch_v1`: starting settings, not tuned optima)

* Embedding: `Linear(history features) + MLP(static) + Linear(calendar)` → `[B, 6, N, 64]`.
* 3 × `PatchBlock`, each with pre-LayerNorm residual sub-layers:
  1. temporal self-attention over each road's 6 history steps;
  2. local self-attention inside each 128-road patch, with padding masked;
  3. global attention between mean-pooled patch summaries (207 tokens), broadcast back through a linear map;
  4. sparse exchange: mean of predecessor and successor states over legal arcs, via `index_add`;
  5. feed-forward.
* Event branch: pair MLP → per-road mean ‖ max ‖ log count (permutation-invariant over cases) → 2 steps of
  up/downstream propagation over legal arcs → per-block FiLM `(γ, β)` and residual gate `g`, applied as
  `h + (1+g)·f(LN(h)(1+γ)+β)`. All conditioning heads are zero-initialised, so the branch starts as an exact no-op
  (unit-tested).
* Decoder: per road, `Linear(flattened history states)` + horizon embedding + calendar of the target bucket +
  own-road scheduled closure share. With events on, it also gets that bucket's context (additive + FiLM). An event
  starting in 30 min can therefore change the 40–60 min horizons without appearing in the history.
* Output: `z` per road × horizon. Travel time is `ref · exp(z)`, with z clipped to `[−1, log(v_ff / 0.1 m/s)]`; the
  upper bound is the export's own speed floor, so severe congestion is kept. Speed and congestion are derived from
  travel time, so the three outputs cannot contradict each other.
* Loss: masked Huber (δ = 1) on z, mean per horizon, then equal horizon weights.
* Training: AdamW (lr 1e-3, wd 1e-4), gradient clip 1.0, ≤ 40 epochs, early stopping after 8 epochs without val
  improvement, bf16 autocast on CUDA, batch = one full-city window, 24 windows per training family per epoch
  (balanced sampling).
* The ablation `event_patch_v1_noevent` is the same config with `model.use_events: false`. Scheduled closures still
  enter through the history `closed` flag and the own-road future closure share, and hard closure rules apply to
  both at export and routing time.

### Simplifications vs the papers (deliberate)

* PatchSTG's patch-level interaction is replaced by attention over **mean-pooled patch summaries**.
* Patches come from balanced KD-style bisection of road midpoints. There is no learned or leaf-reordered patching.
* A sparse legal-connection exchange is added; the papers have nothing equivalent for turn-restricted road graphs.
* ConFormer-style conditioning is reduced to structured context → MLP → FiLM/gate. There is no text or LLM
  encoder and no generative component.

## Event-awareness fine-tuning (`finetune.py`, `event_windows.py`, `evaluate_events.py`)

Implements `ml/EVENT_AWARENESS_FINETUNING_PLAN.md` on top of a trained parent (default `event_patch_v2_main/best.pt`).
The specification (`configs/event_patch_v3_awareness.yaml`, paired ablation `..._paired.yaml`) is parsed separately
from the experiment `Config`; model/data settings come from the parent checkpoint.

```sh
python -m forecast rebuild-cache      --config configs/event_patch_v2_main.yaml   # only if data/.../runs/ is missing
python -m forecast finetune-preflight --spec configs/event_patch_v3_awareness.yaml
python -m forecast event-audit        --spec configs/event_patch_v3_awareness.yaml
python -m forecast finetune           --spec configs/event_patch_v3_awareness.yaml --stage event [--resume]
python -m forecast finetune           --spec configs/event_patch_v3_awareness.yaml --stage decoder [--init <best_candidate.pt>]
python -m forecast evaluate-events    --spec configs/event_patch_v3_awareness.yaml --partition val|test --candidates name=<ckpt>
python -m unittest tests.test_event_finetune
```

* `rebuild-cache` rebuilds missing per-run arrays from the verified source exports with the frozen graph; manifest,
  splits, normalisation and window index are checked unchanged. `done.json` is written last.
* Stage `event` trains only `events.*`; stage `decoder` adds `head.*` / `dec_ln.*` at a lower learning rate. Frozen
  tensors are verified bitwise unchanged; forwards are deterministic (dropout off) with gradients flowing through the
  frozen blocks. The parent is a no-gradient teacher for the preserve term.
* Objective: global + event-near + clear-road anticipation (hour before public start/end, directly observed clear
  near roads, future congested and uncongested targets) + preserve (parent output on controls and roads > 3 km),
  optional paired event-minus-control difference. Family-, event/control- and phase-balanced sampling (train only).
* Selection on validation only: guardrails (citywide/control/severe travel-time MAE <= +2%, anticipation recall not
  lower, precision within 2 pp) and anticipation travel-time MAE >= 5% lower to promote. Every run writes
  `promotion_decision.json`; `best_candidate.pt` is the best guardrail-safe epoch. Nothing is promoted to serving
  automatically. Report: `reports/event_awareness_finetuning_v3.md`.

## Not done / next

* Uncertainty is not implemented, so the export has no confidence column.
* Arrival, departure and recovery coverage is limited by the demand-phase-only windows (see report).
* One held-out test event group. Conclusions about event conditioning are weak until the v3 main batch
  (12 families × 2 seeds per event) exists.
* The live snapshot path (`traffic_metrics` → history) is proposed in `CONTRACT_PROPOSAL.md`, not wired.
