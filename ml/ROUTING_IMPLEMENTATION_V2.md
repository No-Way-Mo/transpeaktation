# Implementation handoff: coordinated navigation after the congestion model

## 0. Objective and working rules

Deliver a navigation system that recommends individual routes while accounting for other participating users directed onto the same roads at similar times. Implement three interchangeable route selectors and compare them against forecast-only routing. Select the deployed default from measured results; do not assume RL or a solver must beat a heuristic.

Keep the current congestion forecaster frozen during routing development and RL training. This plan starts at its output. No rider/vehicle assignment, autonomous-fleet dispatch, idle positioning, passenger-demand forecasting, second learned traffic-response model, or large new traffic-training dataset is required.

Architecture:

    Forecast snapshot + exact restrictions + versioned road network
      -> endpoint snapping and legal candidate routes
      -> forecast travel times and road-entry schedules
      -> shared routing context and allocation ledger
      -> selector: forecast_only | heuristic | batch | rl
      -> validated recommendation and atomic reservation
      -> acceptance/progress/cancellation/completion
      -> updated allocation ledger

SUMO is the RL training and dynamic evaluation environment, not a dependency of live recommendation serving. Simulation observations are not presented as real telemetry. This plan supersedes COORDINATED_ROUTING_PLAN.md.

Read current repository instructions and preserve other contributors' uncommitted changes/processes. Core work belongs under ml/. Shared contracts require their own small PR and team notice; API and web owners implement their integration work. Access sibling components through contracts and HTTP/DB, never imports of their internals. No cloud provisioning or unbounded experiment spending is authorized by this document.

## 1. Freeze the input contract and one usable fixture

Inspect ml/forecast/predict.py, CONTRACT_PROPOSAL.md, graph.py, adapter.py and current actual exports. Confirm whether a trained checkpoint and successful forecast export exist; code alone does not establish readiness. Record hashes, model/network versions, issue time, training provenance and coverage. A labeled fixture may unblock development if needed, but final trained-forecast integration remains outstanding until a real model export works.

Consume the existing road forecast without adding heads:

- road_segment_id; issued_at; valid_from; valid_to; horizon_min.
- predicted_travel_time_sec; predicted_speed_mph; predicted_congestion_ratio.
- availability; restriction_reason; prediction_source; represented_by.
- network_version, model_version and provenance fields.
- Companion exact closure intervals and metadata.

Use predicted travel time as the routing cost; congestion ratio is supplementary context. Horizons 10,20,...,60 represent consecutive ten-minute intervals; horizon 10 covers [issue, issue+10 minutes). Use UTC internally.

Require unique road/interval keys, positive finite usable costs, consistent versions, contiguous intervals and valid availability semantics. Build an immutable validated snapshot, retain the last good snapshot if the replacement is malformed, and publish versions atomically. Missing forecasts do not mean free flow. Use matching network metadata for lengths, lanes, class, geometry and legal turns.

Initial service policy: maximum issue age 20 minutes; coordinate only trips whose departure and evaluated path fit the available forecast window. Return explicit unsupported/degraded outcomes for stale, missing or beyond-horizon requests. Provider fallback can remain available through the API but must be labeled uncoordinated. Do not silently keep extending the last forecast bucket. These thresholds are configurable starting settings.

## 2. Build the legal navigation graph

Construct sparse directed connectivity from the same versioned network artifacts as the forecasts. Never infer a turn merely from spatial proximity, and never redownload an unrelated OSM graph and assume IDs or topology match.

Handle merged_parallel aliases explicitly. Forecast lookup and shared allocation resources must not give duplicate capacity to aliases of one modeled resource. Preserve correct direction and physical geometry; equal forecast values are not evidence of a legal link. Handle SUMO absorbed junctions with verified connector geometry/crosswalks. Unsupported connections/endpoints must be reported rather than invented.

Snap coordinates to a legal directed road and fraction along it, with bounded snap distance. Correctly price remaining origin distance, destination partial distance, and same-road trips. Preserve legal turn restrictions and passenger-road access.

Use exact closure intervals when evaluating road entry. Define whether a restriction is entry-only or requires road clearance; retain supported semantics and mark unknown cases conservatively. Already being on a road and entering a closed road are different cases. Do not smooth closure prohibitions into congestion penalties.

Produce route geometry and ordered canonical road IDs suitable for the web renderer. Report supported road/endpoint coverage. No path may pass through an unresolved geometry/turn mapping just to make the demo appear complete.

## 3. Generate and time the same candidates for every selector

Initial K=5 maximum candidate routes. Use fixed nonnegative snapshot weights per Dijkstra search, with a bounded alternative-path procedure. Retain an unpenalized shortest-snapshot candidate. Generate alternatives from representative forecast intervals and bounded overlap-penalized searches; deduplicate and exclude loops. Document that this is an approximate candidate set, not a proof of the five globally best time-dependent routes.

For comparison experiments, candidate generation is selector-independent: use the same deterministic procedure, search budget and diversity rules for all policies. A frozen-input screening test supplies exactly the same candidates. Interactive policy runs will naturally develop different states and hence may produce different candidates through that identical procedure. Log search timeouts and candidate coverage.

Evaluate each candidate by advancing its forecast clock over successive roads. Use each expected entry time to choose the forecast interval and check legal availability. Return per-road entry/exit times, forecast-only ETA, distance, overlap features, road-class exposure and degradation flags. If candidates become illegal, expand search within the budget; otherwise return an explicit no-feasible-route outcome.

The existing adapter's piecewise bucket lookups do not establish FIFO despite its description. Do not rely on its exact-shortest-path claim. Fixed-weight candidate search followed by temporal evaluation avoids claiming an exact time-dependent Dijkstra solution. Keep a full time-dependent solver outside initial scope unless correctness conditions are implemented and tested.

A balancing preference never advances the physical travel-time clock. All selectors report forecast ETA separately from their selection scores.

Initial detour constraint: ETA <= fastest feasible candidate ETA + min(180 seconds, 0.15 * fastest candidate ETA). The comparison is against the fastest candidate found, not an asserted global optimum. Filter candidates for closures, legality and detour bounds before any selector sees them. Prefer suitable road classes for through traffic while preserving local access to endpoints.

## 4. Implement the shared allocation ledger first

Keep one authoritative state for all users. Start with five-minute allocation bins and ten-minute forecasts. Finer allocation bins express planned arrival timing, not finer forecast accuracy.

Store assignment ID/version, request/idempotency ID, origin/destination, departure, selected route, ordered road-entry schedule, forecast/network versions, status and expiry. Aggregate expected participating road entries per road resource and time bin. Optional timing spread across adjacent bins must conserve each entry's total weight and be identical across selectors.

Lifecycle: provisional -> accepted -> active -> completed, with cancellation and expiry. Plain route previews allocate nothing. A deliberate recommendation may reserve one provisional route for 60 seconds; displaying five alternatives does not reserve five trips. Confirm/revalidate the selected alternative on acceptance. Document the initial accepted-route compliance assumption; test lower compliance separately.

Progress removes passed entries and updates the remaining schedule. A replacement subtracts the old remaining route and adds the new one atomically. Expired/cancelled trips release entries. Duplicate events do not duplicate vehicles. A newly published forecast updates schedules from current positions and rebuilds contributions once; it does not automatically switch everyone's routes.

The ledger is allocation pressure among participants, not observed total road volume. Do not add it to background vehicle counts already represented in the forecast. Current predictions include traffic patterns under their training/observed conditions; the concentration penalty is not a calibrated causal correction to them.

Use one coordinator process, an in-memory ledger, and SQLite persistence initially. Generate candidates outside the transaction; recheck snapshot/ledger versions when scoring and atomically committing. Rebuild live state after restart. Failed persistence must not return a successful commitment. Do not scale by starting independent workers with separate ledgers.

## 5. Give every selector the same interface

Define a typed SelectionContext with available requests, candidates and their masks, fixed existing reservations, forecast version, ledger version, deadlines and reproducibility seed. A SelectionResult contains chosen candidate IDs, reason codes, score diagnostics, runtime and solver/policy version.

Only the coordinator mutates reservations. Selectors propose choices; shared validation and atomic commitment enforce legal paths, detour bounds, request uniqueness and current versions. An invalid, timed-out or unavailable selector falls back to the heuristic, with fallback explicitly recorded. An unavailable RL checkpoint is not a trained-RL result in a benchmark.

Support single requests and small batches. Initially batch up to 32 currently arrived requests or 250 ms, whichever comes first. No selector sees future arrivals from the replay file. Include batching wait in latency metrics. In controlled comparisons expose the same arrived-request batch to all selectors: sequential methods process it in the same recorded order, while the batch solver may choose jointly. Report this lookahead difference and test request-order sensitivity.

## 6. Policy A: forecast-only baseline and policy B: heuristic

forecast_only selects the feasible candidate with minimum forecast ETA and still records its route in the ledger for measurement. It does not use allocation pressure to choose.

heuristic selects the candidate minimizing:

    ETA(route) + lambda * [Phi(L + route) - Phi(L)]
    Phi(L) = sum[e,b] w[e,b] * (L[e,b] / B[e,b])^2

L is participating entries, B is a positive configured allocation budget per bin, and w weights road exposure/bottleneck sensitivity. Set units such that lambda times the penalty has seconds-equivalent selection units, but never label it predicted extra delay. Weight exposure consistently with road length/travel time to limit sensitivity to arbitrary graph segmentation.

B is a policy budget initialized from documented road-class/lane assumptions, not a measured residual physical capacity. Do not infer capacity as 1 minus congestion. Make missing-lane assumptions explicit. Tune budgets and lambda on development scenarios only. Seed near-tie breaking. Lambda zero must reproduce the forecast-only choice over identical candidates.

## 7. Policy C: bounded joint batch optimization

Use OR-Tools CP-SAT for the first implementation. One Boolean x[i,k] selects candidate k for request i; exactly one feasible route per request with candidates. Requests with no candidates are explicit failures outside the solver, not silently dropped vehicles.

Existing accepted reservations are fixed. Candidate contribution schedules are fixed for the solve; congestion-adjusted arrival times are not iteratively invented. Optimize the same heuristic objective over all requests together:

    sum[i,k] ETA[i,k] * x[i,k] + lambda * Phi(L_fixed + sum[i,k] contribution[i,k] * x[i,k])

Use bounded integer scaling for times and fractional contributions. Represent the convex quadratic concentration cost through a documented piecewise-linear approximation over the feasible load range, with integer linear constraints. Do not pass floating-point nonlinear expressions directly to CP-SAT. Build only touched road/time cells and check overflow bounds.

Supply the heuristic assignment as a feasible hint/incumbent. Initial solve budget: 250 ms, configurable. Distinguish feasible, proven optimal, timeout-without-solution and invalid status. Return a feasible incumbent; fall back to the heuristic if necessary. Evaluate the returned plan under the shared exact scoring function and retain the heuristic if the approximation produced a worse score. Record solver gap/bound when available; an optimum of this candidate/penalty formulation is not an optimum of real traffic.

## 8. Policy D: a small masked RL selector

Start with one centralized feed-forward MaskablePPO policy using stable-baselines3/sb3-contrib. It chooses one of K candidate slots for the current request; it does not generate road sequences. The explicit ledger supplies memory, so recurrent policies are unnecessary for this first experiment.

Observation: padded per-candidate ETA, distance, extra travel, forecast congestion summaries, upcoming allocation load/budget statistics, overlap with committed routes and with other candidates, road-class exposure, plus departure/event context and compact network allocation summaries. Include a small recent history summary if useful. All features must be available in deployment; no hidden SUMO future demand, exact future traffic, or test outcomes. Normalize with training-only statistics and save the feature schema.

Use fixed deterministic candidate ordering, e.g. forecast ETA then canonical path hash, with valid-action masks. Keep invalid/padded candidates masked in training and inference. If no candidate is valid, handle no-route outside the policy. Shared validation still enforces hard restrictions. Use mask-aware evaluation utilities; implement environment action_masks internally for subprocess environments. Do not combine this library's MaskablePPO with an unsupported recurrent policy.

Initial network: two hidden layers of 128 units. Suggested starting settings: learning rate 3e-4, n_steps 512 per environment, batch size 128, n_epochs 5, entropy coefficient 0.01. They are starting choices, not known optima. For finite episodes with irregular request steps, initially use gamma=1 so discounting does not depend on how many requests occur in a minute; document this choice and test training stability. Bound rollout storage and parallel environments by measured memory.

The simulator advances to the next actual decision time after each action. Multiple requests at one timestamp can be assigned sequentially with zero traffic-time advance; update the ledger immediately. Do not advance one full simulation step per arriving request as if request count were elapsed time.

Use negative realized vehicle-seconds accrued between decisions as the core reward, covering all vehicles, including background traffic and departure queues after scheduled departure. Optionally add a fixed, documented fairness/route-change penalty; keep hard detour bounds separate. Account for the final drain interval in the last transition. Avoid per-completed-trip rewards that hide unfinished vehicles or incentives to withhold departures.

Episode demand is fixed independently of agent choices. Invalid actions cannot delete demand. Count uninserted/unfinished vehicles and teleport interventions; mark problematic episodes and apply an explicit residual terminal accounting rule when a maximum drain time is reached. Do not let the agent improve reward by leaving trips outside the measured population. Reward scaling is fixed from training data, not recalculated from each test result.

Keep the forecaster frozen. Training uses a real action-responsive environment, described next. A policy trained only to minimize our handcrafted score is not evidence of reduced congestion. Save checkpoints, optimizer state where supported, RNGs, normalization, candidate/graph/forecast versions and run configuration.

## 9. Connect an interactive SUMO environment

Reuse the existing event scenario/network generator and SUMO infrastructure inside ml/. Build a TraCI adapter that can apply a selected legal route to a participating vehicle before departure or at a supported rerouting point. Verify canonical-road to SUMO-edge mapping before training. Preserve the already-traversed prefix and actual current edge on reroutes.

Treat simulation demand as the benchmark request stream: fixed origins/destinations/departures, with a deterministic subset of participating vehicles. Nonparticipants follow the documented background routing behavior. Model compliance with seeded draws keyed by vehicle/scenario, not by policy-dependent random-call order.

Maintain the forecaster's required 60 minutes of completed history before scored decisions. Recompute ten-minute forecasts causally from each policy run's own observations; sharing initial conditions is valid, borrowing future observations from another policy is not. Batch/cached inference can save work only for genuinely identical inputs. Benchmark inference overhead separately.

For early environment debugging a labeled frozen-forecast fixture is acceptable, but the final dynamic experiment must state whether forecasts are refreshed or frozen. Do not claim full closed-loop validation for a frozen-input test.

Start with bounded 30-60 minute decision windows after adequate warmup, and a drain period to account for trips already introduced. Reuse validated initial states only where timestamps, random state and scenario compatibility are verified. Do not crop network boundaries without a defensible boundary-demand treatment.

Run one complete baseline episode and one episode with deliberately different routes. Verify that decisions change actual vehicle paths and can change measured traffic. If they do not, the environment is unsuitable for RL regardless of whether training loss decreases.

## 10. Train and benchmark with bounded stages

First freeze scenario manifests and train/validation/test groups by event/location. Keep seeds and variants of the same event together. The forecaster must not have been trained on claimed held-out test scenarios; otherwise explicitly report that only the routing policy is held out. Never tune detour settings, heuristic lambda, solver settings or RL checkpoints on final tests.

Stage 1: unit tests and saved-input screening of forecast_only, heuristic and batch. Add RL after an actual checkpoint exists. Measure correctness, candidates, score, detours, p50/p95 latency, request-order effects, concurrency and memory. Target workloads: 100 then 1,000 active assignments. Static replay cannot establish congestion reduction.

Stage 2: profile the interactive environment. Record episode runtime, routing decisions/sec, inference overhead and peak memory with the coordinator included. Use these measurements to calculate experiment costs. Do not extrapolate pure SUMO costs as if routing and inference were free.

Stage 3: train a bounded RL pilot, initially up to 50,000 decisions with a configurable local wall-time cap (suggested 2 hours). Save resumably and evaluate on separate validation episodes. Reaching the cap does not imply convergence. If promising, train up to three independent seeds under a separately recorded budget. No broad hyperparameter sweep and no automatic cloud launch. Report actual decisions/episodes and aggregate worker-hours, not just wall time.

Stage 4: screening matrix: 4 policies x 3 development scenarios x 2 simulation seeds = 24 evaluations, using one validation-selected RL checkpoint. This is a screening comparison, not the final held-out test. Then freeze configurations and evaluate shortlisted policies on separate held-out event scenarios with more seeds. Evaluate RL training-seed variability for a serious performance claim; simulation seeds alone do not measure it.

Use identical exogenous demand, initial conditions, participation set, compliance draws, restrictions and warmup across paired policy runs. Evaluate additional participation/compliance conditions after the first screen. Full compliance is a useful first controlled setting, not a deployment assumption established by evidence.

Metrics: realized total vehicle-hours and delay for all demand; participant and nonparticipant results separately; completed/unfinished/uninserted counts; median and p95 trip time; detour distribution; road-class spillover; route changes; closure violations; teleports; request and end-to-end decision latency; memory; training and inference compute.

Compare episode-level paired differences across seeds/events. Do not treat thousands of correlated road samples as independent evidence, report only completed trips, or label a lower balancing score as actual congestion savings. Preserve raw outcomes and seeds, including failures.

Select the default on held-out traffic outcomes subject to correctness, detour and latency requirements. If methods are close within experimental variability, prefer the simpler/faster method. Keep heuristic and forecast-only fallbacks even if RL wins. Record a non-improvement honestly; do not change the test set until a desired winner appears.

## 11. Service, contracts and UI integration

Implement an ML HTTP service with typed local schemas and propose the shared shapes in its own contracts change. API talks to ML over HTTP; web talks to API. Suggested operations: request recommendation; accept chosen alternative; progress; cancel; complete; health. Use idempotency keys and expected assignment versions. A client selecting another displayed option must revalidate/reserve that option; it cannot submit an arbitrary path for commitment.

Response fields: assignment ID/version/status/expiry; route and candidate IDs; selector/version and fallback reason; route geometry and road IDs; forecast ETA; fastest-candidate ETA; extra travel seconds; recommendation reasons; forecast/network versions; data provenance and degradation flags. Keep allocation diagnostics distinct from user-facing ETA or unmeasured savings. Do not fabricate confidence.

API owner: retain geocoding and ordinary provider fallback, introduce state-changing POST operations and CORS handling, avoid shared caching of final allocation decisions. The current nearest-edge matching of provider polylines is not a guaranteed continuous legal route. Provider routes participate only after complete validation against the common graph and schedule; otherwise mark them uncoordinated.

Web owner: distinguish Recommended from Fastest candidate; current routeTag assumes index zero is fastest and needs changing. Show extra travel plainly. Create recommendations on deliberate user actions, not every render or search keystroke. Accept/cancel/complete the correct reservation. Render the selected route's actual geometry with explicit coordinate conventions. Do not reuse maneuver instructions from a different provider route. If turn-by-turn maneuvers are not implemented, deliver map-level route guidance and name that scope limit.

Demo controls should switch selectors while resetting to the same initial scenario for comparisons. Show multiple users, their recommended paths and expected allocations, with forecast congestion separately labeled. Do not portray an allocation heatmap as observed congestion or use incomparable initial states in an A/B demonstration.

## 12. Suggested files and reproducible commands

Under ml/coordination/: config.py, schemas.py, forecast_store.py, network.py, candidates.py, timing.py, ledger.py, storage.py, coordinator.py, service.py, __main__.py; selectors/{base,forecast_only,heuristic,batch,rl}.py; rl/{env,features,train}.py; benchmark/{runner,metrics,report}.py. Create focused tests under ml/tests/.

Add coordination* to package discovery. Separate optional routing/service, solver and RL dependencies so heuristic serving need not load Torch or SUMO. Forecast inference remains a separate producer; simulation dependencies belong to training/evaluation. Pin compatible tested dependency versions in the implementation environment and document the install steps.

Implement and document commands equivalent to:

    python -m coordination audit --config configs/coordinated_routing_v2.yaml
    python -m coordination serve --config configs/coordinated_routing_v2.yaml --selector heuristic
    python -m coordination benchmark --suite static --config configs/coordinated_routing_v2.yaml
    python -m coordination benchmark --suite profile --config configs/coordinated_routing_v2.yaml
    python -m coordination train-rl --config configs/coordinated_routing_v2.yaml --seed 0
    python -m coordination benchmark --suite screening --config configs/coordinated_routing_v2.yaml
    python -m coordination benchmark --suite heldout --config configs/coordinated_routing_v2.yaml

These are proposed new commands, not existing functionality. Save suite manifests, configs, forecast/checkpoint hashes, raw metrics and a readable comparison report under versioned run directories. Supply small API fixtures and integration examples.

## 13. Tests and completion checklist

Test legal turns/closures, interval boundaries, partial-edge snapping, same-road trips, road aliases, unsupported coverage and stale forecasts. Test forecast validation and atomic version refresh. Test duplicates, simultaneous requests, lifecycle release, alternate acceptance, restart recovery and progress/replacement races.

Test shared bottlenecks across different routes, different-time usage, lambda-zero baseline behavior, hard detour bounds, no-alternative behavior and separation of ETA from scores. Cross-check batch solver results against exhaustive enumeration on tiny cases, including timeout fallback and integer scaling. Test RL action masks, no-route handling, observation causality, reward accounting, final drain and checkpoint compatibility. Test that routed actions actually affect the simulator.

Execution order and outputs:

1. Shared forecast/network/candidate pipeline and a real end-to-end route.
2. Ledger plus forecast-only and heuristic selectors; runnable persistent service.
3. Batch solver and static screening tests.
4. Interactive SUMO adapter and measured episode cost.
5. RL pilot/checkpoint and validation report, with actual training status.
6. Matched four-policy screening and frozen held-out comparison.
7. Shared contract plus API/web owner integration and multi-user demo.
8. Final README, reproducible commands, limitations, selected default and fallbacks.

API/web integration can proceed once the heuristic service and contract stabilize; it need not wait for RL training. Finish the working common product even if RL does not converge within its stated budget. A complete experimental comparison must identify any untrained/unavailable policy honestly rather than silently substituting a fallback and labeling it RL.

## Sources and interpretation

- [Sequential RL route recommendation (2025)](https://arxiv.org/abs/2505.20889) establishes a closely related static assignment formulation; it is not proof that the proposed dynamic SF policy will succeed.
- [MaskablePPO documentation](https://sb3-contrib.readthedocs.io/en/master/modules/ppo_mask.html) documents invalid-action masks, evaluation requirements and the lack of recurrent-policy support.
- [OR-Tools CP-SAT documentation](https://developers.google.com/optimization/cp/cp_solver) documents integer modeling and solver outcomes.

The concrete score, feature set, rewards, implementation modules and numerical defaults above are proposed project choices to test, not reproductions or proven best settings from these sources.
