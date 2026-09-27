# Coordinated routing implementation handoff

**Superseded by [ROUTING_IMPLEMENTATION_V2.md](ROUTING_IMPLEMENTATION_V2.md).** The updated plan implements and benchmarks heuristic, batch-optimization, and RL selectors behind one shared routing interface. The document below records the earlier heuristic-only scope.

## Decision and scope

Build forecast-aware navigation with shared, time-indexed route allocation. Users supply their own origins, destinations, and departure times. There is no rider/vehicle matching, pickup staging, passenger-demand model, learned routing policy, or second traffic-response model in this version.

This is the chosen architecture for the prototype, not a claim of globally optimal traffic assignment. Keep the existing trained congestion forecaster. Use Dijkstra to generate candidate routes and an explicit allocation heuristic to discourage excessive shared bottlenecks. Validate actual benefits independently of the heuristic score.

Implement the core under `ml/coordination/`. Preserve existing work and generation/training processes. Read the current repository instructions before editing. Changes to contracts require their own small PR and team notice; API and web changes belong to those folder owners. Complete the ML service and integration examples before handing those owners their work. Do not import another folder's internals.

## 1. Establish the actual inputs and freeze one integration fixture

Audit current forecast artifacts and checkpoint availability; code presence does not prove inference or training succeeded. Select one actual forecast snapshot, matching road network, and exact closures table. Record hashes, issue time, network version, model version, and coverage. If a trained export is unavailable, use an explicitly labeled fixture only for development and keep trained-model integration outstanding.

Read these existing files:

- `ml/forecast/predict.py`: exported forecast and companion files.
- `ml/forecast/CONTRACT_PROPOSAL.md`: timestamp, availability, provenance semantics.
- `ml/forecast/adapter.py`: reference router, not a ready production router.
- `ml/forecast/graph.py`: legal connections and model-to-road mappings.
- `api/app/main.py`, `api/app/providers.py`, `api/app/segments.py`: present routing, caching, and approximate geometry matching.
- `web/lib/route.ts`, `web/lib/use-route-planner.ts`: route display and selection.

Require one row per canonical road and valid interval, finite positive usable travel times, unique keys, UTC timestamps, contiguous forecast intervals, and a matching network version. Validate before publishing an immutable forecast snapshot. Reject malformed snapshots without replacing the last good one.

Consume: road_segment_id, issued_at, valid_from, valid_to, predicted_travel_time_sec, predicted_congestion_ratio, availability, restriction_reason, prediction_source, represented_by, model_version, network_version. Preserve provenance. Horizon 10 describes [issue, issue+10 min), not a point observation at issue+10.

Do not require new forecast heads. Obtain road lengths, directions, geometry, lane metadata, and legal turns from the versioned network artifacts. No confidence scores are available; do not invent them.

## 2. Build a routing graph and correct endpoint semantics

Create a versioned directed road graph with legal successor connections and geometry suitable for rendering. Keep forecast road IDs as the join keys. Do not invent turns from coordinate proximity or independently redownload an OSM graph and assume compatibility.

Resolve merged_parallel aliases explicitly for forecast lookup and allocation accounting. Aliases sharing one modeled road resource must not receive duplicate independent capacity budgets. Preserve their actual navigation geometry and direction; matching a prediction is not proof of a legal physical connection.

SUMO may connect roads across absorbed junction segments. Preserve those connections and obtain verified connector geometry from the same network/crosswalk for display. Do not draw a straight navigable link through a gap without validating it. Report routing coverage and unsupported endpoints instead of inventing predictions or geometry.

Snap endpoints to legal directed roads with an along-road fraction and maximum snap distance. Support remaining origin distance, destination partial distance, and same-road trips correctly. A trip beginning partway along a road must not traverse that entire road again. Reject implausible or directionally invalid snaps.

Apply access prohibitions and exact closure timestamps as hard rules. Document whether each closure forbids entry or also requires clearing the segment; do not assume all vehicles already on a newly closed road disappear. Full-bucket flags are summaries; partial closures require the exact companion intervals.

## 3. Generate alternatives with Dijkstra, then evaluate their timing

Start with static, nonnegative snapshot weights for candidate generation. Generate up to five unique loop-free candidates, with an explicit search budget. Use Dijkstra plus a proper alternative-path procedure, or bounded repeated searches with overlap penalties. Always retain the shortest candidate from the unpenalized snapshot. Repeated penalized searches are heuristic alternatives, not an exact k-shortest guarantee.

Candidate search can use several representative forecast snapshots and a current allocation-penalized snapshot to expose useful alternatives. Treat each search's weights as fixed for that search. Cache candidate generation by network, snapped endpoints, forecast snapshot/departure bucket, and any search policy version. Do not cache the final personalized allocation as a shared answer.

For every candidate, propagate actual forecast arrival times road by road. Look up the interval containing each entry time, apply partial-edge costs, and check restrictions at the resulting times. Return per-road entry/exit times and forecast-only ETA. Reject candidates that become infeasible. If necessary, broaden candidate search within a bounded budget. A lack of feasible candidates is an explicit outcome.

The existing adapter calls itself FIFO Dijkstra but switches directly between bucket values; FIFO is not established. Do not copy that correctness claim. The proposed candidate-and-evaluate approach is approximate and does not require pretending this is an exact time-dependent shortest-path solver. An exact time-dependent solver is a later improvement requiring verified FIFO travel-time functions or a suitable expanded state algorithm.

Do not advance arrival times using a balancing penalty: that penalty is a decision preference, not physical travel time.

Initial freshness policy: forecasts older than 20 minutes at decision time are stale. Initially support coordinated requests whose departure and route evaluation fit the forecast horizon. Out-of-horizon/stale cases return an explicit unsupported/degraded result for the API's independently labeled provider fallback. No silent extension of the 60-minute forecast. Expose thresholds in configuration and validate against actual deployment cadence.

## 4. Maintain one shared allocation ledger

Use five-minute allocation bins as an initial setting; retain ten-minute forecast bins. Five-minute allocation bins express planned entry timing, not improved forecast resolution.

Record every trip's planned ordered road entries, expected entry times, assignment version, forecast version, lifecycle status, and expiry. Aggregate expected participating entries per modeled road resource and allocation bin. Use modest normalized timing spread around uncertain bin boundaries to avoid artificial jumps; contribution weights for one road entry must sum to the chosen trip participation weight.

Suggested lifecycle: provisional -> accepted -> active -> completed, with cancelled and expired terminal states. Route previews do not reserve every displayed alternative. A requested recommendation may reserve exactly one provisional route with a short TTL, e.g. 60 seconds. Acceptance confirms it; expiry/cancellation removes it. For the demo, explicitly assume accepted assignments are followed, and test lower compliance in evaluation rather than claiming a calibrated acceptance probability.

Progress updates remove passed entries and rebuild the remaining schedule. Replacement removes the previous remaining schedule and inserts the new one atomically. Cancellation and duplicate progress messages are idempotent. Timeout abandoned active plans; allow telemetry or a documented demo clock to advance trips. Do not retain ghost traffic forever.

Publish each new forecast as an immutable version. Re-evaluate remaining plans against it and rebuild their ledger contributions once, using current positions when available. This changes anticipated timing, not automatically the route promised to every driver. Preserve explicit closure invalidations and unsupported-plan status.

This ledger represents allocation pressure among our participants. It is not an estimate of total observed road flow. Do not add it blindly to traffic counts already embedded in the congestion forecast. On a reroute remove the old contribution; never append another full vehicle journey.

## 5. Implement a transparent allocation score

For each candidate calculate forecast-only travel time T and marginal increase in a convex concentration penalty:

    score(route) = T(route) + lambda * [Phi(ledger + route) - Phi(ledger)]

For a first implementation:

    Phi(L) = sum over road/time bins of w[e,b] * (L[e,b] / B[e,b])^2

L is expected participating entries, B is a positive configured allocation budget per bin, and w weights road exposure/bottleneck sensitivity. Define units so lambda * delta_Phi is a seconds-equivalent preference score. It is not added to the returned physical ETA. Base road weighting on length/travel exposure to limit sensitivity to arbitrary segment splitting; test this property.

B is an allocation budget, not measured spare road capacity. Initialize from documented road-class/lane assumptions, make assumptions visible, and tune on development scenarios. Congestion ratios do not identify spare capacity; do not compute capacity as 1 minus congestion. Missing lane counts need explicit conservative defaults. Known congested roads may receive stronger configured penalties, without claiming a calibrated traffic-response equation.

Apply a hard detour constraint before scoring. Initial policy: forecast ETA <= fastest feasible candidate ETA + min(180 seconds, 15% of that ETA). These are tunable product defaults. Call the reference the fastest candidate found, not the globally fastest route. If no acceptable alternative exists, keep the baseline candidate or return no route if that candidate is illegal.

Prefer equivalent road classes for through traffic; penalize unnecessary residential shortcuts and preserve endpoint access. Distinct route names do not establish diversity: measure overlap on actual road resources and times. Use seeded tie-breaking for reproducible experiments; near-equal routes can differ without forcing a bad detour.

Lambda=0 must reproduce forecast-only selection over the same candidate set. This is a heuristic objective, not a proof of system-optimal routing or a learned marginal-delay estimate.

## 6. Make allocation atomic and persistent

For the prototype run one coordinator process with an in-memory ledger and a SQLite assignment/event store. One authoritative allocator serializes score-and-commit transactions. Do not deploy multiple independent workers with separate ledgers.

Generate candidates outside the critical section, then recheck forecast/ledger versions and score against the current ledger before atomically persisting the assignment and updating state. Bound retries when versions change. Treat forecast publication as a versioned transaction too. Rebuild memory from persisted current assignments on restart and expire obsolete state.

Use idempotency keys: repeating a request returns the same decision and does not reserve twice. Proposals and replacements use expected assignment versions to avoid overwriting newer progress or cancellations. If the service cannot persist a reservation, it must not report it as committed.

Never reroute everyone automatically on each forecast refresh. In the first release reroute only on explicit requests or route invalidation; optional periodic optimization can be added after validation. Rerouting starts from the current road position and excludes the driver's own old remaining reservation while evaluating replacements.

## 7. Package a runnable ML service and contract proposal

Suggested modules in ml/coordination:

- config.py, schemas.py: settings and validated local input/output shapes.
- forecast_store.py, network.py: snapshot validation, mappings, legal graph, snapping.
- candidates.py, timing.py: candidate search and temporal evaluation.
- ledger.py, storage.py: lifecycle, atomic allocations, persistence.
- scoring.py, service.py: allocation policy and coordinator HTTP endpoints.
- evaluate.py, __main__.py: reproducible benchmarks and CLI.

Add coordination package discovery and its optional dependencies to ml/pyproject.toml. Importing the routing service must not load PyTorch/checkpoints; it reads exported forecasts. Keep inference as a separate producer. Reuse suitable pure ML utilities rather than duplicating them, but do not import ingest or API internals.

Propose these HTTP operations, with final shapes in the separate shared-contract change:

- POST /recommendations: trip/request ID, idempotency key, origin/destination, departure time, detour preferences; returns one provisional recommended assignment and alternatives.
- POST /assignments/{id}/accept: confirm or revalidate the chosen alternative atomically; no client-supplied unverified path is trusted.
- POST /assignments/{id}/progress: timestamp, position, expected assignment version.
- POST /assignments/{id}/cancel and /complete: idempotent lifecycle operations.
- GET /health and /metrics: snapshot freshness, network coverage, active reservations, latency.

Return assignment ID/version, expiry/status, selected route ID, geometry, ordered road IDs, entry/exit schedule, forecast ETA, fastest-candidate ETA, extra travel seconds, allocation score components, reason codes, and forecast/network versions. Include provenance and degradation flags. Do not expose internal balancing scores as actual delay savings or model confidence.

Provide curl examples and JSON fixtures so API/web owners can integrate without waiting on each other. Proposed new CLI: python -m coordination audit, serve, and evaluate --config configs/coordinated_routing_v1.yaml. Document exact implemented flags rather than leaving pseudocommands.

## 8. API and web owner integration tasks

API owner: call the ML coordinator via HTTP and map the agreed shared contract into navigation responses. Retain place search and clearly labeled Mapbox/OSRM fallback. A fallback route is uncoordinated unless its full legal road schedule is validated and registered; never silently claim it participates.

The existing GET /routes cache can serve ordinary previews, not state-mutating recommendation/acceptance operations. Add POST operations with idempotency and necessary CORS handling. Do not rely on the API's current nearest-edge-per-polyline matching as an authoritative continuous legal route. Its separately loaded graph must not override the coordinator's versioned network identity.

Web owner: show 'Recommended' on the selected coordinated route and independently mark the fastest candidate. Existing routeTag assumes index zero is fastest; replace that assumption with explicit fields. Show ETA and extra travel plainly. A user choosing an alternative triggers acceptance/revalidation for that alternative. Tie reservation creation to deliberate route requests rather than every map render or place-search keystroke.

Render the chosen route's own geometry. Do not attach Mapbox turn instructions from another route. If maneuver generation is not implemented, show route overview and ETA and explicitly keep turn-by-turn navigation outside the completed scope. Translate coordinate order at the contract boundary: existing web coords use [lat, lon], while GeoJSON uses [lon, lat].

For the demo show multiple participating trips with distinct origins/destinations, shared-road allocation over time, an event closure, and a cancellation releasing load. Any replay/test controls must be labeled; do not claim a reservation heatmap is measured congestion.

## 9. Verification and evaluation

Write meaningful tests for:

- Legal turns, one-way roads, exact closure boundaries, same-road endpoints, partial segments, and unavailable-road handling.
- Forecast schema/order validation, network mismatch, timestamp interpretation, stale/beyond-horizon behavior.
- Simultaneous assignments observing prior committed load; duplicate calls reserving only once.
- Acceptance, alternative selection, cancellation, progress, replacement, TTL, restart, and forecast refresh preserving correct counts.
- Shared bottlenecks across differently named routes; different times not treated as simultaneous traffic; alias roads not creating duplicate capacity.
- Zero-load and lambda=0 baseline behavior; detour limits; no artificial ETA increase from penalties.
- Case with no useful alternative does not manufacture route diversity; high-load alternate selection works on a controlled fixture.

Run current relevant forecast/router tests as well as coordination tests. Benchmark with an actual SF graph at 100 and 1,000 active plans; report p50/p95 request latency, candidate-generation cost, throughput under concurrent requests, and memory. A provisional demo target is p95 under two seconds for a new recommendation on a documented machine; measure rather than promise it.

Compare matched routing policies:

1. Current-observation routing baseline.
2. Forecast-only route selection.
3. Same forecast and candidate set plus allocation balancing.

Keep origins, destinations, departures, background demand, closures, participating drivers, and seeds matched. Tune lambda, allocation budgets, and detour defaults on development events only; freeze before held-out evaluation. Test low/high participation, multiple compliance levels, request ordering, low demand, event buildup, and departure surges.

Static replay of fixed road travel times can validate timing and decisions but cannot prove congestion reduction caused by rerouting. For that claim run a small controlled evaluation with the existing SUMO setup so chosen routes affect resulting traffic. This is a routing-policy benchmark, not another large synthetic training-data project. The live product does not depend on running SUMO. If dynamic evaluation is unavailable, deliver the functional allocator and report congestion benefits as unverified.

Measure realized total travel time and delay for all vehicles and separately participants/nonparticipants, completion/unfinished counts, p95 trip times, detour distribution, road-class spillover, route changes, and closure violations. Do not score only completed trips, ignore SUMO teleport interventions, use future observations as forecast inputs, or use reduced allocation penalty as proof of reduced traffic delay.

In dynamic policy comparisons, recompute forecasts causally from each policy's own available history; sharing the same initial state is appropriate, but silently reusing future observations from another policy is not. If inference cadence cannot be integrated, document the frozen-forecast experiment and its limitation.

## 10. Finish criteria and execution order

Milestone A: valid real forecast fixture, versioned navigation graph, correct endpoints, feasible alternatives and timing. Deliver one end-to-end route without balancing.

Milestone B: persistent ledger, allocation score, detour limits, atomic lifecycle, and demonstrably different allocations on a congestion-sensitive fixture. Deliver a working ML HTTP service and reproducible commands.

Milestone C: shared contract agreed through its own change; API/web owners integrate selected-route labels, acceptance/cancellation, geometry, and degraded behavior. Deliver a usable multi-user map demonstration.

Milestone D: frozen comparison results, latency report, assumptions, coverage, limitations, and README. If balancing does not improve measured outcomes, report that and retain a configuration switch for forecast-only routing rather than manufacturing success.

Finish the runnable service, integration, and evaluation artifacts; do not stop at scaffolding or a notebook. No additional trained model or retraining is required by this plan. Do not provision cloud resources or launch the large data-generation batch as a substitute for implementing routing.

## Research context

The design borrows the objective of protecting users while improving network performance from [Jahn et al., System-Optimal Routing of Traffic Flows with User Constraints (2005)](https://pubsonline.informs.org/doi/10.1287/opre.1040.0197). Its discussion of dynamic routing correctness is informed by [Wei and Yang, Bi-level route guidance method for large-scale urban road networks (2019)](https://link.springer.com/article/10.1186/s13638-019-1451-z). The concrete score, defaults, modules, and lifecycle above are our prototype design choices, not claimed reproductions of either paper.
