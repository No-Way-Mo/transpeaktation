"""CLI: python -m eventsim <stage> --event castro [options]. See ml/README.md."""
from __future__ import annotations

import argparse
import json
import time

from .config import get_event


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="eventsim")
    sub = p.add_subparsers(dest="stage", required=True)

    def add(name, help_):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--event", default="castro")
        return sp

    add("prepare", "join event closures + real traffic context to the OSM patch; write join report")
    add("network", "build the SUMO network + crosswalk for the patch")
    sp = add("scenarios", "sample scenario configurations")
    sp.add_argument("--families", type=int, default=12)
    sp.add_argument("--seeds", type=int, default=2, help="seed variants per family (each also gets a no-event control)")
    sp.add_argument("--seed", type=int, default=7)
    sp = add("simulate", "run SUMO for every scenario that has no output yet")
    sp.add_argument("--workers", type=int, default=4)
    sp.add_argument("--only", nargs="*", help="run ids")
    sp.add_argument("--force", action="store_true")
    add("check", "simulation dynamics checks (queues, closures, detours, lost vehicles)")
    sp = add("dataset", "build model-visible observations, baselines and residual targets")
    sp.add_argument("--row-frac", type=float, default=0.35, help="share of (origin, segment) rows kept per run")
    add("train", "fit the pooled residual model (family-level split, tuned on validation)")
    add("evaluate", "held-out comparison against persistence and the event rule")
    sp = add("replay", "closed-loop routing replay per policy on held-out scenarios")
    sp.add_argument("--runs", type=int, default=3)
    sp.add_argument("--probe-share", type=float, default=0.3)
    sp.add_argument("--workers", type=int, default=4)
    sp = add("export", "write run-tagged simulation_metrics / prediction_metrics shaped CSVs")
    sp.add_argument("--runs", nargs="*")
    a = p.parse_args(argv)
    ev = get_event(a.event)
    t0 = time.time()
    if a.stage == "prepare":
        from . import prepare
        out = prepare.run(ev)
    elif a.stage == "network":
        from . import sumonet
        out = sumonet.run(ev)
    elif a.stage == "scenarios":
        from . import scenarios
        out = scenarios.run(ev, a.families, a.seeds, a.seed)
    elif a.stage == "simulate":
        from . import simulate
        out = simulate.run(ev, a.workers, a.only, a.force)
    elif a.stage == "check":
        from . import checks
        out = checks.run(ev)
    elif a.stage == "dataset":
        from . import dataset
        out = dataset.run(ev, a.row_frac)
    elif a.stage == "train":
        from . import train
        out = train.run(ev)
    elif a.stage == "evaluate":
        from . import evaluate
        out = evaluate.run(ev)
    elif a.stage == "replay":
        from . import replay
        out = replay.run(ev, a.runs, a.probe_share, a.workers)
    elif a.stage == "export":
        from . import export
        out = export.run(ev, a.runs)
    print(json.dumps({"stage": a.stage, "event": ev.key, "seconds": round(time.time() - t0, 1), **(out or {})},
                     indent=1, default=str))


if __name__ == "__main__":
    main()
