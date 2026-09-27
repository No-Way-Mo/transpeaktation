# RL route selection: research decision and implementation handoff

Scope: synthetic demand/SUMO -> frozen congestion forecast -> existing candidate router -> load-balancing selector. Implement the missing RL environment, trainer, selector and comparison runner. No API, web, live ingestion, fleet dispatch or second traffic-response model work is included.

## Decision

Implement MaskablePPO first behind the existing `Selector.select(SelectionContext)` interface. It chooses among the existing K<=5 candidate routes. Keep forecast_only, heuristic and batch as the mandatory baselines. Masked Double DQN is the next experiment if measured simulation cost/sample efficiency warrants it; it is not a prerequisite for delivering the first working RL implementation.

This is an engineering recommendation for our small discrete action space and current code, not a claim that PPO is the strongest routing algorithm. No research located establishes a best algorithm for our particular graph, forecaster, candidate generator and event scenarios.

## Research and alternatives

1. **Sequential route recommendation with MSA-guided DQN (Wang et al., 2025):** closely matches one central agent selecting a route for each arriving OD request. However, it uses static assignment, analytic BPR link costs and full compliance; the larger reported example has 13 nodes and 48 links. Candidate-set quality materially affected results. Borrow the bounded route action space and system-wide objective; do not transfer its optimality gap or convergence claims to dynamic SF traffic. [Paper](https://arxiv.org/html/2505.20889v1)

2. **MaskablePPO:** directly supports discrete actions with invalid-action masks and parallel environments. Its implementation has mask-aware evaluation utilities and does not support recurrent policies. That reduces implementation work for padded/illegal route slots. PPO still requires fresh interactive experience; a small policy does not imply cheap simulation. [Official documentation](https://sb3-contrib.readthedocs.io/en/master/modules/ppo_mask.html)

3. **Masked Double DQN:** a credible alternative because experience replay permits repeated learning from collected transitions. Double Q-learning separates action selection and evaluation to address overestimation. We must implement masks in exploration, greedy selection and bootstrap targets; masking only inference is wrong. SB3's documented DQN is vanilla DQN, not Double DQN. [Original Double DQN paper](https://arxiv.org/abs/1509.06461), [SB3 documentation](https://stable-baselines3.readthedocs.io/en/master/modules/dqn.html)

4. **Recurrent PPO:** potentially useful if limited observations hide important history, but the current ledger and compact observation histories provide an explicit starting representation. Recurrent PPO and MaskablePPO are separate implementations; combining them is extra engineering. Revisit only if observation ablations establish a need. [Official documentation](https://sb3-contrib.readthedocs.io/en/master/modules/ppo_recurrent.html)

5. **SAC/TD3:** standard continuous-action implementations are an awkward fit for choosing one route slot. Discrete SAC variants exist, but introduce another implementation without a demonstrated advantage here. Consider continuous control only if the task changes to regional routing proportions. [SB3 SAC action-space documentation](https://stable-baselines3.readthedocs.io/en/master/modules/sac.html)

6. **AlphaRoute / model-assisted RL:** AlphaRoute combines regional agents, graph attention and tree search; TransRL combines traffic physics with RL under uncertainty. They show that richer traffic structure can help, but are larger changes than replacing our selector. Keep as later references, not dependencies. [AlphaRoute, AAAI 2023](https://ojs.aaai.org/index.php/AAAI/article/view/26422), [TransRL](https://arxiv.org/abs/2407.07364)

A contextual bandit would model each recommendation's immediate outcome and is not the first choice when subsequent congestion depends on earlier allocations. We also do not need an independent RL agent for every driver: the present application has one coordinating decision maker.

## Current code to retain

The candidate generator, legality/detour checks, forecast store, ledger, storage, heuristic and batch selectors already exist. Avoid rebuilding them.

Observed extension points:

- `coordination/selectors/rl.py` is a stub raising SelectorUnavailable.
- `coordination/selectors/__init__.py` constructs RL without checkpoint/configuration.
- `Coordinator._selector()` creates a selector repeatedly; cache loaded policy instances rather than loading a checkpoint per request.
- `SelectionContext` has candidate items and load/coefficient accessors, but no explicit global/event observation bundle. Add a versioned, optional, read-only policy context if needed.
- `Candidate.features` currently contains ETA, distance, extra travel, overlap and class exposure; add only causal forecast summaries needed by the policy.
- `coordination/__main__.py` explicitly refuses `train-rl` and `benchmark`.
- `coordination/config.py` rejects unknown config sections; adding YAML alone is insufficient. Add typed RL, environment and benchmark config sections.
- `eventsim/replay.py` already demonstrates TraCI lifecycle, subscriptions and rerouting. Reuse ideas/helpers, but do not import its obsolete single-event Static/ObsModel assumptions or noise augmentation into the new pipeline.
- `eventsim/citywide_batch.py::request_trips` can write requests.parquet in newer batches. Audit availability per run rather than assuming older runs have it.

Read current AGENTS instructions before edits, preserve other contributors' work, and keep changes under ml/. This is a plan; no experiments have been run by this handoff.

## 1. Audit the scenario and forecast prerequisites

Select a completed quality-approved network-compatible batch. Freeze run IDs, requests, demand, restrictions, network hash, forecaster checkpoint, observation schema and experiment splits in a manifest. Do not combine partially completed batches silently.

Use requests.parquet where present. For older runs, reconstruct a fixed request stream from saved trip routes and departure metadata, with explicit edge/fraction mapping and provenance. Do not resample different demand per policy. Verify date/local simulation time/UTC conversions. Planned request metadata may be read by the simulator, but reveal only arrived requests to the agent.

For initial controlled routing, select ordinary point-to-point passenger trips without mandatory intermediate stops. Keep vehicles with parking/ride-hail dwell or special constraints in unchanged background traffic and in outcome accounting. Never lose those stops by replacing their route. Freeze participation independently of route feasibility or policy; unsupported participant requests follow the documented common fallback and remain in metrics.

Produce and validate an actual trained-model forecast and compare its road/network IDs with the coordinator. Reject the current fixture forecast in main training/evaluation mode. Permit it only in explicit debug mode, clearly labeled.

Group train, validation and test by event/location, keeping variants/seeds together. Reuse compatible forecaster splits. If a held-out routing scenario was used to train the forecaster, report the distinction; do not call the combined pipeline fully held out.

## 2. Define the route-choice observation and action

Action space is Discrete(K), initially K=5. Candidate order remains deterministic: forecast ETA then path hash. Pad absent slots and provide a Boolean action mask. Do not change K without versioning the checkpoint/schema. No feasible route is handled outside policy selection; never sample from an all-false mask. One candidate can use a direct deterministic choice while remaining part of reward/state evolution.

Use one shared feature builder for training and serving. Begin with a compact fixed vector consisting of:

- Per candidate: ETA, distance, extra time/ratio, weighted forecast congestion and missingness, expected entries/load summaries on that path, normalized allocation pressure, marginal heuristic penalty, overlap with other candidates, road-class exposure, departure/arrival offsets.
- Shared context: time-of-day encoding, forecast age, current arrived-request count, aggregate participating load over future bins, origin/destination coordinates normalized to the supported area, and known closure/event indicators when genuinely available.
- Valid-slot indicators and feature missingness. No future realized travel times, hidden demand, SUMO internal queue truth absent from deployment, or test-scenario labels.

Compute candidate-specific load features using the existing ledger plus earlier selections in the current batch. Add safe read-only budget/global summaries rather than using simulator-only features. Known-event features need an actual common input path; otherwise omit or mask them.

Normalize with fixed physical scales or training-only statistics and persist all scales/schema/order. Treat the observation as a partial summary, not a mathematically sufficient full traffic state. Start without a GNN/LSTM; add complexity only after a measured representation limitation.

## 3. Build an interactive Gymnasium environment

Implement `rl/sumo_env.py` using a labeled TraCI connection per environment, a dedicated output directory and an injected simulation clock. No wall-clock TTL behavior inside simulated episodes. Close only owned SUMO processes/connections on reset or error, including Windows spawn-safe subprocess handling.

Reuse the approved SF network and event restrictions. Run enough warmup to collect six completed ten-minute history buckets. A 30-minute SUMO warmup alone is insufficient for the forecaster; either extend the predecision history or use a verified compatible initial state with its matching history. Warmup/demand is matched across policies.

Implement the decision cycle:

1. Advance to the next arrived eligible request or forecast refresh boundary.
2. Aggregate traffic measurements causally and update the forecast when appropriate.
3. Prepare existing legal route candidates and an observation/mask.
4. Accept an action, validate it, and commit through the same coordinator lifecycle.
5. Apply the chosen SUMO route at supported departure/current-edge semantics.
6. Advance traffic to the next decision, accrue reward, and update progress/completion in the ledger.

Refactor a small shared prepare/commit seam if necessary. The environment must not implement a second reservation system or use public/private paths that re-run a selector and override the policy action. Snapshot/candidate versions must remain valid at commit.

Requests at the same timestamp are processed in deterministic order; ledger state changes between them, while physical time need not advance. Requests arriving later are not revealed early. Subsequent traffic motion, including background vehicles, occurs according to simulation time.

Verify each canonical path maps to a continuous legal SUMO route. For active vehicles preserve the current edge and current lane constraints; internal junction edges require a supported rerouting boundary. For predeparture vehicles register the route before vehicle insertion. Read back actual route/trajectory samples to prove actions are applied. [TraCI vehicle-state documentation](https://sumo.dlr.de/docs/TraCI/Change_Vehicle_State.html)

Disable or explicitly account for background automatic rerouting that could overwrite participating assignments. Seed driver compliance independently of policy-dependent random-call order. First debug with full compliance, then evaluate reduced compliance.

Use actual ten-minute road measurement aggregation compatible with forecaster training: unit conversion, sampling/observed masks and weighting must match. Keep unobserved roads missing; no extra observation-noise stage. Refresh the frozen forecaster from each policy's own completed history. Do not reuse another policy run's future traffic observations.

First gate: run the same initial state with two deliberately different feasible routing actions; confirm different actual routes and corresponding outcome measurement. Do this before neural training.

## 4. Reward and episode accounting

Use a finite horizon with a fixed exogenous request population and negative realized vehicle-time:

    reward = -(vehicle-seconds accumulated since the previous decision) / reward_scale

Count all in-scope vehicles, including background vehicles, waiting time after their scheduled departure, and uninserted departure queues. Vehicles contribute until arrival; completion-only averages are insufficient. Vehicles already present at scoring start contribute their remaining time consistently across paired runs.

The immediate interval reward is not labeled the causal marginal effect of the latest driver. RL learns the delayed sequence outcome. The value function supplies a baseline for variance reduction; do not run a second counterfactual simulation for every action.

Use fixed demand introduction/decision windows, then drain to completion where feasible. Include post-last-decision traffic cost in the terminal transition. If a fixed maximum drain is reached, log unfinished vehicles and a separately identified terminal cost estimate; report actual observed time and unfinished counts independently. Do not turn resource/time-limit truncation into a successful terminal outcome or claim measured total travel time for censored trips.

Keep detour/closure rules as hard constraints. Start without rewarding low hand-written allocation penalty; that would mostly teach the heuristic objective. Optional later potential-based shaping must telescope with the chosen discount/terminal handling and be evaluated separately.

Use gamma=1 initially for finite request-indexed episodes; otherwise the effective discount depends on request density rather than physical time. Start GAE lambda=1 to preserve long delayed credit, recognizing the higher variance. Treat this as a testable design choice. If time-discounted returns are introduced later, implement duration-aware discounting explicitly.

Begin with a modest number of decision-making participants over a realistic background so action effects and credit are observable. Log participant count, number of nontrivial choices, decisions per simulated minute, and reward timing. Avoid claiming useful learning from episodes where nearly every request has only one valid candidate.

## 5. Implement MaskablePPO training

Add an optional RL dependency group for compatible tested versions of gymnasium, stable-baselines3, sb3-contrib and Torch. Preserve the existing forecasting/SUMO/solver environment. Resolve version compatibility before installing; do not casually upgrade the shared numpy/protobuf stack.

Initial settings, to validate rather than treat as established optima:

| Setting | Initial choice |
|---|---|
| Policy | MaskablePPO MlpPolicy |
| Actor/critic hidden layers | 128, 128 |
| Learning rate | 3e-4 |
| Rollout steps per environment | 1024 |
| Batch size | 128 |
| PPO epochs | 5 |
| Clip range | 0.2 |
| Entropy coefficient | 0.01 |
| Gamma / GAE lambda | 1.0 / 1.0 for finite request episodes |
| Environments | 1 to debug, then 2-4 if profiling permits |
| First pilot | 50,000 decisions or 2-hour wall cap, configurable |

Long trajectories can still exceed the rollout horizon; inspect reward delay/value learning and adjust episode participant count or rollout size on validation runs. No model quality is guaranteed by the pilot budget.

Implement action_masks inside the environment, including worker processes. Use the mask-aware evaluation callback/evaluation function. Shared feature normalization must freeze for validation and test. No invalid route should be applied to SUMO even if generic environment checkers sample it; fail cleanly without changing demand.

Profile the small policy on CPU first to avoid contention with GPU forecast inference. Measure whole-pipeline throughput; GPU policy inference is optional if it helps. Forecaster inference should reuse a loaded checkpoint instead of loading it every refresh, with per-process/batched scheduling based on memory. Do not overcommit four independent large GPU forecasters by default.

Save best-validation and latest checkpoints with optimizer state, normalization, feature/action schema, graph hash, forecaster hash, scenario split, seed and training counters. Resume at an episode boundary unless complete simulator and rollout state is saved; do not describe a fresh environment restart as bit-for-bit continuation. Wall-time stops must preserve a usable checkpoint and report partial progress accurately.

## 6. Replace the RL selector stub

Implement `RL.select(ctx)` with lazy optional imports, a cached loaded policy, schema/network compatibility checks and deterministic masked evaluation. For a batch, process requests in recorded order and accumulate a temporary extra-load overlay after each choice, as the heuristic already does. Do not mutate the real ledger inside the selector.

Extend selector factory/configuration to pass checkpoint and inference settings. Cache the policy at coordinator/runtime level keyed by checkpoint identity; current per-request selector construction must not reload weights. Checkpoint replacement is explicit and validated.

Return existing SelectionResult shapes with `policy=rl`, checkpoint identity and per-request choice/reason diagnostics. Shared coordinator validation commits only valid proposals. Preserve fallback for missing/incompatible checkpoints in normal operation; in RL benchmarks, treat any fallback as an explicit failed/unavailable RL decision, not silently as evidence of RL quality.

Do not claim that a chosen route reduced congestion based solely on the policy's logits/value estimate. Continue to display forecast ETA separately from selection diagnostics.

## 7. Implement the comparison runner

Replace the benchmark CLI placeholder. Implement `static`, `profile`, `screening` and `heldout` suites. Static tests compare timing, latency, masks and allocations only. Dynamic tests use the shared SUMO adapter, identical exogenous demand and matched initial conditions, but each policy's own evolving traffic.

Mandatory policies: forecast_only, heuristic, batch and rl_ppo. Use the same search procedure, route validity rules, detour bounds and observable information. Batch lookahead is limited to requests that have already arrived; include real batching delay in reported response latency. Candidate sets naturally change when policies induce different traffic states; this is not a fairness violation if the generator is identical.

First dynamic screen: 4 policies x 3 development scenarios x 2 simulation seeds = 24 runs, with one validation-selected RL checkpoint. Freeze tuning before held-out evaluation. If making a serious RL comparison, repeat training with three seeds; extra simulation seeds do not substitute for training-seed variability.

Report realized total vehicle-hours/delay, participant/nonparticipant outcomes, completed/uninserted/unfinished counts, median/p95 trip times, detours, road-class diversion, invalid routes, teleports, route changes, serving latency, simulation/inference/training time and memory. Use paired episode-level differences; do not use thousands of correlated road samples to inflate confidence.

Freeze the participation cohort and compliance draws per scenario/seed. Include low/high load and departure surges; test multiple compliance/participation rates after the first screen. Report baseline variability and inconclusive results honestly. Select the default subject to legality, detour and latency constraints, not reward alone.

## 8. Optional masked Double DQN follow-up

Only add after the shared environment and PPO comparison work, or if profiling demonstrates that fresh experience is prohibitively expensive. Keep the same observation/action/reward and compare both interaction count and total compute.

Implement online and target Q networks with replay storing observation, action, reward, next observation, terminal/truncation semantics and next action mask. Sample epsilon-greedy exploration only from valid candidates. For nonterminal targets, select the masked argmax with the online network and evaluate that chosen action using the target network. Terminals have no bootstrap; do not take an argmax over all-invalid next slots. Handle truncation separately.

Dynamic route slot identities are encoded by per-slot route features in every replay observation. Preserve deterministic ordering and masks. Freeze forecaster/feature versions during a run and clear or segregate replay if they change. Reuse is not safe if old feature/action semantics silently change.

Start with uniform replay, two 128-unit layers and a target network; do not add dueling/prioritized replay/MSA all at once. Compare Double DQN to PPO under the same collected-transition budget and also the same wall-time budget. Improved sample efficiency here remains a hypothesis until measured.

## 9. Files, commands and tests

Create:

- `coordination/rl/features.py`: shared versioned observation encoder.
- `coordination/rl/sumo_env.py`: action-responsive simulator and Gymnasium environment.
- `coordination/rl/forecast_bridge.py`: causal history accumulation and reusable frozen inference.
- `coordination/rl/rewards.py`: vehicle-time and terminal accounting.
- `coordination/rl/train.py`, `evaluate.py`, `checkpoint.py`: training, validation and metadata.
- `coordination/benchmark/{runner,metrics,report}.py`: matched evaluation and reports.
- `configs/coordinated_routing_rl.yaml`: actual paths and bounded experiment defaults.
- `tests/test_coordination_rl.py`, `test_coordination_env.py`: tests.

Modify only the necessary existing extension points: selectors/rl.py, selectors/__init__.py, coordinator.py, schemas.py, config.py, __main__.py, pyproject.toml and documentation. Preserve the existing heuristic/batch behavior and tests.

Implement commands equivalent to:

    python -m coordination benchmark --suite profile --config configs/coordinated_routing_rl.yaml
    python -m coordination train-rl --config configs/coordinated_routing_rl.yaml --seed 0
    python -m coordination train-rl --config configs/coordinated_routing_rl.yaml --seed 0 --resume
    python -m coordination benchmark --suite screening --config configs/coordinated_routing_rl.yaml
    python -m coordination benchmark --suite heldout --config configs/coordinated_routing_rl.yaml
    python -m coordination route --selector rl --config configs/coordinated_routing_rl.yaml

These are proposed extensions, not claims that the current placeholders work. Keep long runs opt-in and locally budgeted; do not provision cloud instances from a benchmark command.

Tests must cover identical train/serve features, padding/masks, one/no candidate, cached checkpoint loading, temporal leakage, timestamp conversions, legal route application, same-time requests, demand preservation, actual action impact, reward/drain accounting, expiry on simulation time, forecast refresh from own history, and no silent RL fallback. Verify a checkpoint roundtrip selects the same action and that a trained policy actually changes parameters; decreasing loss alone is not a success criterion.

Gate delivery in this order:

1. Action-responsive environment and honest cost accounting, validated without neural training.
2. Working MaskablePPO trainer and checkpoint with a bounded pilot.
3. Real RL inference through the existing selector and shared coordinator.
4. Four-policy matched comparison, followed by frozen held-out results.
5. Reproducible commands, measured costs, limitations and the default-selector decision.

Do not stop at scaffolding or leave CLI commands saying not implemented. Do not call PPO better unless evaluated. If it fails to outperform the existing selectors, retain the functioning pipeline and report the experiment; RL success is not a prerequisite for the navigation product to work.
