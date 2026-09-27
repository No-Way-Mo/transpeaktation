# Load-balancing backtest and congestion demonstration plan

Codebase inspection: 2026-09-26. Planning document only: no benchmark, training, or implementation was run for this handoff. Paths are relative to `ml/` unless stated otherwise.

## 1. Answer: the policy layer is modular

The implemented flow is:

```text
SUMO measurements -> frozen congestion forecaster -> time-dependent road costs
 -> shared candidate-route generator -> selectable allocation policy
 -> coordinator validation + reservation ledger -> actual SUMO routes
 -> new measurements -> next forecast and decisions
```

`coordination/selectors/base.py` defines `Selector.select(SelectionContext) -> SelectionResult`. A selector proposes candidate indexes; the coordinator owns validation, persistence, reservations and lifecycle. Replacing a selector should not require replacing the forecaster, graph, candidates, ledger or simulator.

| Method | Current implementation | Interpretation |
|---|---|---|
| `forecast_only` | `selectors/forecast_only.py` | Each request chooses its fastest forecast-based candidate without a load penalty. This is our primary independent-routing baseline, not a reproduction of Google Maps. |
| `heuristic` | `selectors/heuristic.py`, shared sequential scorer | Adds a reservation-concentration penalty and updates the temporary load after each choice. |
| `batch` | `selectors/batch.py` | OR-Tools CP-SAT chooses routes jointly for an arrived batch. It optimizes the candidate/penalty objective, not the simulator directly. |
| `rl` | `selectors/rl.py` | Loads a MaskablePPO or masked Double DQN checkpoint and selects from the same candidate slots. |
| `rl_ppo`, `rl_ddqn` | `benchmark/runner.py` policy aliases | Benchmark names mapped to the RL selector with separate checkpoints. They are not additional names in the service selector registry. |

All policies share K=5 candidate slots, masks, forecast version, reservation ledger, legal-road constraints and detour bounds. Existing candidate detour allowance is **the smaller of 180 seconds and 15% of the fastest forecast ETA**. This limits predicted detour, not realized trip delay.

Important limits to “swap it in”:

- A new algorithm still needs an adapter to this interface and registration in `selectors/__init__.py` or benchmark policy construction.
- RL needs a real compatible checkpoint. Locally inspected pilot directories contained manifests/logs, not verified trained policies; resolve available checkpoints before including them.
- A different policy must get a fresh isolated ledger and simulator episode in comparisons. Do not carry one policy's reservations into another policy's run.
- Changing forecaster or candidate semantics can shift RL inputs. The RL metadata records forecaster identity, but `rl/checkpoint.py:problems()` does not currently enforce its hash or every candidate setting. Benchmark preflight should check them and label deliberate transfer experiments explicitly.
- Batch policy changes decision timing as well as route allocation. Its current simulation batch window is 60 seconds, while service configuration mentions milliseconds. These are separate settings and must be reported.

## 2. The question the experiments must answer

Primary question: **With the same scheduled trips, event, road network and background traffic, does coordinated route selection reduce total travel burden versus independent forecast-based routing?**

Supporting questions:

1. Does it reduce time spent in congested traffic, rather than only spread reservations across more roads?
2. Are improvements shared with background traffic, or paid for by making nonparticipants worse off?
3. How much adoption and route compliance are needed?
4. Is a simple heuristic as effective as joint optimization or RL?
5. Does a better event-aware forecast make routing outcomes better?

Use closed-loop SUMO replay. Historical/static replay can test decisions and latency, but cannot establish how a different route changes congestion. In a dynamic experiment, each policy must receive forecasts based on its own evolving measurements. Use the same forecaster weights and refresh schedule, not identical future forecast values once traffic diverges.

Do not call lower allocation penalty, more unique routes, lower predicted ETA or larger RL reward alone proof of congestion reduction. Report measured simulation outcomes.

## 3. Existing infrastructure to reuse

The benchmark is implemented; do not rebuild it from scratch:

- `coordination/benchmark/runner.py`: `static`, `profile`, `screening`, `heldout` suites, process workers, shared warm starts, policy adapters, SUMO trip outcomes.
- `coordination/benchmark/report.py`: paired differences versus `forecast_only` and Markdown/CSV output.
- `coordination/rl/sumo_env.py`: applies selected routes, reads routes back, advances SUMO and refreshes predictions.
- `coordination/rl/rewards.py`: in-scope vehicle-seconds, including running vehicles and insertion queues, plus unfinished counts.
- `coordination/rl/scenario.py`: approved scenarios, exact exported demand, deterministic participants/compliance and splits.
- `configs/coordinated_routing_rl_main.yaml`: main batch and v2 forecaster; use as the starting configuration.
- Tests: `tests/test_coordination.py`, `test_coordination_env.py`, `test_coordination_benchmark.py`, `test_coordination_rl.py`.

The main config points to `b3_main` and `event_patch_v2_main/best.pt`; the old `coordinated_routing_v2.yaml` serves a fixture snapshot. Benchmark with `env.forecast_mode: model`. Freeze the current forecaster for the first comparison rather than waiting for event fine-tuning.

## 4. Correctness work before believing a leaderboard

### A. Immutable experiment identity and matched population

Create a separate benchmark YAML and experiment output directory. Save full resolved config, code identity, SUMO version, scenario/network/demand/closure/split digests, forecast/checkpoint digests, participant IDs, compliance draws and simulation seed in a frozen manifest.

Current per-policy files are named by scenario and seed under a suite, so rerunning can overwrite them. Introduce an experiment ID/config digest into output paths, including reports. Resume only missing jobs whose complete identities match; do not mix results from different configurations.

Hash and compare exact scheduled trip IDs, origins/destinations/departures, participant IDs and in-scope population across policies. Equal vehicle counts alone are insufficient. Failed route selection must preserve demand through a common fallback, while being marked as a failure for pure-policy ranking.

`choose_scenarios()` accepts explicit IDs without enforcing the suite split. Preflight must reject test scenarios in screening, train scenarios in held-out evaluation and incompatible split/checkpoint provenance. Validate the whole manifest before launching workers.

### B. Warm starts and repeatability

The current cache key includes scenario, participants and history length; load verification checks time and running vehicle IDs. Strengthen cache identity to include source demand, network, closures, SUMO version/options, seed, step size and history measurement settings. A matching vehicle set is not proof of an unchanged initial state.

Test that warm-start replay and a full replay produce equivalent starting measurements and subsequent outcomes for a fixed policy. Verify simulator RNG state restoration, including rerouting behavior. Reject/rebuild stale caches rather than silently using them. Change participation/window settings only under a new compatible cache identity.

Run two independent repeats of the same baseline/seed. If outcomes differ beyond numerical tolerance, diagnose before interpreting small policy differences. Fixed exogenous seeds align experiments, but routing divergence can still change the simulator's random-number consumption; paired seeds do not make all later random events identical.

### C. Prevent incomplete/failed runs from winning

Current dynamic tasks may return `status=ok` even when summaries contain route failures, unchosen fallbacks or unfinished trips. The report's eligibility checks currently cover only successful task status, invalid routes and selector failures. Extend them.

For the primary complete-trip comparison require:

- matched intended demand and initial state;
- zero dropped trips, invalid routes and route-readback mismatches;
- zero unexpected selector/forecast failures and unchosen-policy fallbacks;
- exact closure legality and detour-mask compliance;
- completed common in-scope population, or an explicitly separate censored-outcome analysis;
- no unexplained disappearance of vehicles and a documented teleport policy.

Do not silently exclude a losing/failing policy episode and compare it on an easier subset. Report failures across the full intended matrix; use the same complete scenario/seed blocks for the primary policy ranking.

The current 30-minute drain cap can truncate trips. If any policy is incomplete, extend the drain for every policy in that matched block under a fixed maximum chosen before final evaluation. If completion remains impossible, report common-horizon accumulated vehicle-hours plus backlog and label full-trip performance inconclusive. Completed-trip-only averages can favor policies that leave the slowest vehicles unfinished.

SUMO currently permits teleporting after 300 seconds. Count and explain teleports; they can relieve simulated gridlock. For final evidence use zero-teleport comparisons where feasible, or repeat shortlisted policies with a shared stricter/disabled-teleport setting and bounded runtime. Keep gridlocked runs visible; do not remove them to improve a score.

### D. Timing and batching fairness

Batch policy waits for arrived requests; that time must count from each vehicle's original scheduled departure. The runner already adds batching waits and trip outcomes use scheduled departure. Test that this is counted exactly once, including waits crossing decision-window boundaries and unsuccessful selections.

Record selector latency, candidate-generation latency, forecast latency and total recommendation latency separately. Verify the benchmark enforces the intended deadline/validation rules; do not assume service fallback behavior applies to every direct benchmark call. Solver timeouts with valid incumbents, heuristic incumbents and actual policy failures need distinct labels.

In addition to operational immediate policies versus delayed batch, add an equal-timing comparison: feed heuristic and batch the same arrived request groups at the same release time. Without that comparison, any difference combines batching delay, available information and optimization quality.

### E. Participation and decision opportunity

Current defaults are 5% requested participation, capped at 150 drivers, with 100% compliance. `participants()` applies both the share and cap. Raising share without raising the cap may leave the intervention effectively unchanged.

Report eligible trips, selected participants, compliant participants, effective participation fraction, actual nontrivial decisions, single-candidate trips, unsupported trips and changed routes. Freeze deterministic nested participant cohorts across adoption levels. Keep the same cohort across policies. Report participants as a share of eligible departures and of all departures; these denominators differ.

A small citywide effect is unsurprising when only a small fraction can change route. Select representative development scenarios with genuine congestion and multiple legal route choices, and also include uncongested/no-event controls. Do not select final scenarios after seeing which policies win.

## 5. Metrics and interpretation

| Metric | Purpose / implementation requirement |
|---|---|
| Total in-scope vehicle-hours | Primary network efficiency outcome. Existing accountant includes participants and background vehicles from the common scoring start; vehicles already present contribute remaining time. It is not automatically excess delay. |
| Completed-trip delay/time loss | Complement total time. Report participant and background groups, common completion coverage and batching/insertion waits separately. SUMO time loss depends on the traveled route; it is not a universal fixed-OD baseline. |
| Time spent at congestion ratio >= 0.5 | Direct congestion outcome: vehicle-seconds at speed <= 0.5 of the road's consistent free-flow reference. Add observed measurement accumulation and document intersections/internal-edge treatment. |
| Queue and backlog | Time-integrated stopped/slow vehicle count, pending insertion, unfinished population; separate road queues from off-network waits. |
| Throughput/completion | Arrivals by a common time and completed in-scope trips. Prevent “improvements” obtained by serving fewer trips. |
| Participant trip time | Median, mean, p95 and individual changes on matched completed IDs. Quantifies driver tradeoff. |
| Background trip time | Mean and p95 with completion checks. Detects harm shifted onto nonparticipants. |
| Road/corridor impact | Congested vehicle-minutes near the event and elsewhere, plus spillover onto residential roads; do not just display the most improved corridor. |
| Route distance | Additional distance/vehicle-km, to expose long detours. |
| Routing diagnostics | Non-fastest share, route overlap, ledger concentration, invalid/fallback decisions and latency. Useful mechanism evidence, not congestion outcomes. |

Do not treat unobserved/empty road buckets as measured free flow. For map comparison show observation coverage; for vehicle-seconds count observed traffic, with insertion queues separately accounted for. Use fixed roads/corridors and time intervals across policies.

A fair headline is “X% lower total vehicle time and Y% less time in congested traffic in these matched SUMO scenarios.” If only allocation concentration improves, say that rather than claiming less congestion.

## 6. Experiment sequence

### Phase 0: contract and smoke checks

Run existing relevant tests plus new identity, completeness, accounting and strict-ranking tests. Use `static` to check common candidate masks and policy choices. Use `env-check` to verify different routes affect actual traffic with identical demand. Neither is a performance result.

Run one development scenario x one simulation seed x the three available non-RL policies = **3 dynamic profile episodes**. Measure time/memory and actual route-choice opportunities. Profile before choosing concurrency: main training config was written for a 192-core node; do not use its 48 environments or CPU-count default blindly on the laptop. Start benchmark `workers=1`, then try 2 only if resources allow. Each process can load its own forecaster.

### Phase 1: inexpensive policy screening

Freeze 3 development scenarios, covering arrival, departure and sustained/full-event traffic, with 2 simulation seeds. Use Bearrison validation groups for tuning; audit actual selected windows overlap the desired traffic phase.

Compare:

1. independent forecast routing;
2. reservation-aware heuristic;
3. CP-SAT batch;
4. PPO only if its trained checkpoint is available and compatible;
5. DDQN only if its trained checkpoint is available and compatible.

Cost: **18 episodes** for three policies, or **30** for five. Start at 5% actual participation with an adequate cap, and 100% compliance to isolate algorithm behavior. This is a controlled experimental setting, not a deployment assumption.

Tune only a small development grid. For the heuristic try concentration weights such as 15, 60, 120 with the original detour bound fixed; use zero as the independent-routing sanity check. For batch test a modest window such as 5 or 15 seconds against the existing 60-second window, including equal-timing controls. Run one axis at a time; do not multiply every setting into an exhaustive grid.

No trained RL checkpoint is a reason to mark RL unavailable, not to postpone the three-policy benchmark or let heuristic fallback be labeled RL. Do not launch RL training as part of this planning task.

### Phase 2: establish how much adoption is needed

For the strongest simple policy versus independent routing, use the same 3 development scenarios x 2 seeds, at 5%, 15%, 30% participation and 100% compliance. Total **36 episodes**, before reusing exact-matching earlier runs. Add 50% only if the smaller levels reveal no detectable effect and cost permits; do not promise this is realistic adoption.

Remove or raise the participant cap consistently with the intended share, subject to profiling. Verify realized selected share rather than assuming it. This produces an adoption-versus-benefit curve and identifies an interpretable demo setting.

At the chosen development adoption level, compare compliance 100%, 75%, 50% for baseline and shortlisted policy: **36 episodes** over the same six blocks before reuse. Verify noncompliant participants' fallback route logic is identical between policy arms. Do not train/tune on held-out outcomes.

### Phase 3: frozen held-out comparison

Freeze policies, checkpoints, parameters, participation, compliance, decision windows, drain criteria, metrics and scenario selection before this phase.

Choose 6 held-out scenario families with balanced arrival/departure/full coverage where available, then 3 simulation seed offsets. Compare independent routing, the best simple coordinated policy and the strongest available challenger: **54 episodes**. If retaining all five policies, **90 episodes**.

The current held-out event group is Portola. Six scenarios from one event are not six independent event types. Verify distinct family IDs rather than selecting six filename variants of the same family. Additional simulation offsets and source demand seeds are separate replication dimensions; record both.

Use additional untouched event groups later for wider claims. No new model training or split manipulation is required to start this evaluation. Preserve exclusions and quality gates, and report the resulting coverage limitations.

### Phase 4: explain why it works

After a policy is chosen on development data, run focused ablations:

- **No coordination:** independent fastest route with the same forecast/candidate generator.
- **No ledger penalty:** heuristic with lambda=0 should reproduce independent selection under the same tie/ordering rules. This is a sanity check rather than a novel competitor.
- **Timing control:** heuristic and batch at identical release times and batch groups.
- **Forecast quality:** the original event model versus the no-event model, then the event-fine-tuned candidate if one is actually trained and validated. First use heuristic to avoid RL distribution changes confounding the comparison.
- **Forecast/coordination interaction:** a 2x2 experiment (parent vs improved forecast; independent vs coordinated routing). Six blocks x four arms = **24 episodes**. This separates improved prediction from coordination and measures their interaction.
- **Event/control traffic:** rerun the same routing comparison on matched no-event scenarios. Compare policy benefits within each scenario, then the difference in benefits. Event scenarios may have different intended demand; do not require event and no-event populations to be identical, only populations between policies within each scenario.

An old RL checkpoint used with a new forecaster is a transfer test; record it as such or fine-tune it separately. Do not silently replace its forecaster and attribute the outcome solely to the routing algorithm.

## 7. Statistical and practical decision rules

For each matched scenario/seed block calculate:

```text
vehicle_time_reduction_pct = 100 * (baseline_hours - policy_hours) / baseline_hours
```

Also calculate absolute hours saved, congestion-exposure reduction, participant/background changes and completion metrics. Report individual pairs, median and mean paired effects, win/loss counts and worst regressions. Keep population-weighted aggregate results separate from equal-scenario averages.

Resample scenario families, keeping their seeds and paired policies together, for uncertainty estimates when enough families exist. Do not use each vehicle/road bucket as an independent experiment. With only a few families and one held-out event, call uncertainty broad; “better in every pair” alone is not a statistical significance test.

Suggested development success target, chosen before final runs:

- at least 5% average reduction in total vehicle-hours;
- lower observed congested vehicle-time, with matched completion;
- no increase in unfinished/dropped/invalid trips;
- background mean trip time no more than 2% worse;
- participant p95 no more than 5% worse, with predicted detour constraints obeyed;
- practical end-to-end decision latency within the declared service budget.

These are engineering targets, not guaranteed outcomes. If improvements are smaller, report them exactly. If effects are inconsistent, present the conditions where they help and hurt. A prototype can demonstrate coordinated decisions without claiming demonstrated citywide congestion reduction.

Choose the simplest policy that meets the outcome/latency requirements. A neural policy is not automatically preferable; compare its benefit with training cost and robustness. Use multiple RL training seeds before claiming one RL algorithm is superior, separately from simulator seed repetitions.

## 8. Demo experiment and visuals

Choose a representative development scenario before final held-out ranking, using congestion and candidate-diversity criteria, not maximum observed policy improvement. Show a held-out summary beside the illustrative replay.

Create synchronized baseline/coordinated SUMO replays with:

- same demand, network, initial state, event and clock;
- identical map extent and congestion color scale;
- selected drivers taking alternate routes, and those routes' extra distance/time;
- counters for all-traffic vehicle-hours, arrivals, current backlog and congested vehicle-minutes;
- participant and background trip-time summaries;
- an event/closure timeline and participation/compliance setting.

Current environments use headless SUMO. Add an optional replay/GUI path or export route traces and traffic summaries for visualization; do not put a GUI into every benchmark worker. If the chosen run does not show a benefit, show that outcome or another predeclared illustrative scenario, not an undisclosed best-of-many seed.

Recommended final figures:

1. Paired total-time and congestion-exposure improvement by policy, with each scenario visible.
2. Congestion/queue evolution around the event for baseline and winner.
3. Adoption-versus-benefit curve.
4. Participant versus background tradeoff, with p95 and completion counts.
5. Map of improved and worsened corridors using the same observation mask/coverage display.

Simulation results support a claim about the tested scenarios, not observed real-world SF outcomes.

## 9. Implementation checklist for Claude

1. Add a dedicated benchmark config derived from the main-batch config, with conservative worker count, explicit forecaster identity and unique output paths. The coordination YAML loader does not support inheritance: write a full config or implement/test inheritance separately.
2. Extend `benchmark/runner.py` preflight to freeze the full matrix and verify scenario splits, model availability, checkpoint compatibility, exact demand/cohort identity and warm-state identity.
3. Extend warm cache validation and repeatability tests in `rl/sumo_env.py` without changing policy logic.
4. Add congestion exposure/queue counters and export time series; preserve original accountant semantics and label scoring scope.
5. Add strict quality flags for readback, dropped/unfinished trips, teleports, unchosen fallbacks, forecast failures and paired population mismatch.
6. Extend `benchmark/report.py` to rank on common valid blocks, display all failures/censoring, protect against incomplete-run wins and use run-specific output names.
7. Add per-policy batch-window configuration for equal-timing comparisons, recording all delays; the current runner applies a window only to the literal `batch` policy.
8. Add matrix generation for adoption/compliance/forecaster variants with immutable experiment IDs and resumable jobs. Preserve nested participant cohorts and distinguish scenario seeds from simulator offsets and RL training seeds.
9. Run accounting/identity/selection tests, then profile, screen and freeze choices. Run held-out results only after selection.
10. Produce a Markdown outcome report, machine-readable manifest/CSV/time series, and a reproducible illustrative replay. Do not change serving defaults automatically.

## 10. Existing commands to start from

Run from `ml/` after resolving dependencies and creating the dedicated config described above. These benchmark commands already exist; the additional integrity/metric behavior in this plan still needs implementation.

```powershell
python -m unittest tests.test_coordination tests.test_coordination_env tests.test_coordination_benchmark tests.test_coordination_rl

python -m coordination benchmark --config configs/coordinated_routing_backtest.yaml --suite static --policies forecast_only,heuristic,batch --workers 1

python -m coordination benchmark --config configs/coordinated_routing_backtest.yaml --suite profile --policies forecast_only,heuristic,batch --seeds 0 --workers 1

python -m coordination benchmark --config configs/coordinated_routing_backtest.yaml --suite screening --policies forecast_only,heuristic,batch --seeds 0,1 --workers 1

# Only after selection and protocol freeze:
python -m coordination benchmark --config configs/coordinated_routing_backtest.yaml --suite heldout --policies forecast_only,heuristic,batch --seeds 0,1,2 --workers 1
```

`configs/coordinated_routing_backtest.yaml` is a proposed new file, not created by this plan. For explicit scenarios use the existing `--scenarios` argument, after adding split validation. Available RL policies can be specified as `rl_ppo=<checkpoint-directory>` or `rl_ddqn=<checkpoint-directory>` in the comma-separated policy list.

The dynamic runner already prewarms the selected scenario/seed combinations. Avoid prewarming every available scenario unnecessarily. Estimate total cost from measured episode/worker throughput, allowing for initialization and slow/congested cases; a policy selector can be cheap while the surrounding SUMO replay is expensive.

## 11. Required final report

Write `reports/load_balancing_backtest_<experiment_id>.md` with the exact experiment identity, supported policies, resource use, intended/completed matrix, all exclusions/failures, paired outcomes, congestion exposure, driver/background tradeoffs, adoption sensitivity, ablations and limitations. Link the saved manifest and representative replay.

Conclude with one evidence-based recommendation: retain independent routing, deploy the simple coordinator for the prototype, or prefer a stronger policy with a quantified benefit. If no policy reduces congestion, preserve the negative result and identify whether the limiting factor is insufficient controllable traffic, lack of alternative routes, forecast error, allocation logic or measurement coverage.
