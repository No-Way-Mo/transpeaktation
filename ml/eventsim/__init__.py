"""Event-aware traffic adjustment model trained on SUMO scenarios grounded in real SF events.

Stages (one command each, see ml/README.md):
    prepare  -> join a permitted event to canonical OSM segments + real traffic context
    network  -> SUMO network for the patch + crosswalk to OSM segment ids
    scenarios-> sampled scenario configurations (families of seeds + no-event controls)
    simulate -> SUMO runs -> per-segment 10-min measurements + trip outcomes
    dataset  -> model-visible observations, baselines and residual targets
    train    -> pooled gradient-boosted residual model
    evaluate -> held-out comparison against persistence and the event rule
    replay   -> closed-loop routing replay per policy (re-simulated)
"""

import os as _os

# joblib probes physical cores with a subprocess on Windows and warns when it can't; the logical count is fine.
_os.environ.setdefault("LOKY_MAX_CPU_COUNT", str(_os.cpu_count() or 1))
