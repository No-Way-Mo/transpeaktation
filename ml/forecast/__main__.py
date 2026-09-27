"""Stage commands (run from ml/):

    python -m forecast audit    --config configs/event_patch_v1.yaml
    python -m forecast prepare  --config configs/event_patch_v1.yaml
    python -m forecast retrain  --config configs/event_patch_v4_h18.yaml --parent data/forecast/experiments/event_patch_v2_main/best.pt [--resume]
    python -m forecast evaluate-retrain --checkpoint data/forecast/experiments/event_patch_v4_h18_full/best.pt --partition test
    python -m forecast jam-wrapper --checkpoint data/forecast/experiments/event_patch_v4_h18_full/best.pt
    python -m forecast rebuild-cache --config configs/event_patch_v2_main.yaml [--workers 8]   # frozen dataset: runs/ only
    python -m forecast sanity   --config configs/event_patch_v1.yaml     # overfit a tiny batch + profile one city batch
    python -m forecast train    --config configs/event_patch_v1.yaml [--resume]
    python -m forecast evaluate --checkpoint data/forecast/experiments/event_patch_v1/best.pt [--partition test]
    python -m forecast report   --experiments event_patch_v1 event_patch_v1_noevent
    python -m forecast snapshot --config configs/event_patch_v1.yaml --run <run_id> --issued-at <ISO UTC> --output <dir>
    python -m forecast predict  --checkpoint <ckpt> --input <snapshot dir> --output <forecast.parquet>
    python -m forecast finetune-preflight --spec configs/event_patch_v3_awareness.yaml [--stage event|decoder]
    python -m forecast event-audit        --spec configs/event_patch_v3_awareness.yaml
    python -m forecast finetune           --spec configs/event_patch_v3_awareness.yaml --stage event [--resume] [--init <ckpt>]
    python -m forecast evaluate-events    --spec configs/event_patch_v3_awareness.yaml --partition test --candidates name=<ckpt> ...
    python -m forecast promote  --checkpoint <ckpt> --reason "..." [--force]      # what the service serves
    python -m forecast serving-status
    python -m forecast serve    [--checkpoint <ckpt>] [--host 127.0.0.1] [--port 8200]   # FORECAST_API_TOKEN for non-local
"""
from __future__ import annotations

import argparse
import json

from . import config as cfg_mod


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m forecast")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("audit", "prepare", "sanity", "train"):
        p = sub.add_parser(name)
        p.add_argument("--config", required=True)
        if name == "train":
            p.add_argument("--resume", action="store_true")
            p.add_argument("--max-epochs", type=int)
            p.add_argument("--seed", type=int)
            p.add_argument("--name", help="override experiment name (e.g. for extra seeds)")
    sub.choices["prepare"].add_argument("--workers", type=int, default=1)
    p = sub.add_parser("retrain", help="full-model transfer of a trusted parent to a new horizon (retrain.py)")
    p.add_argument("--config", required=True)
    p.add_argument("--parent", required=True)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--max-epochs", type=int)
    p = sub.add_parser("evaluate-retrain", help="lead-time x horizon evaluation of a retrained checkpoint")
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--partition", default="val", choices=["val", "test"])
    p.add_argument("--config", help="score on this config's dataset instead of the checkpoint's own")
    p.add_argument("--tag", help="suffix for the output directory")
    p = sub.add_parser("jam-wrapper", help="calibrated jam probabilities over a trained point forecaster")
    p.add_argument("--checkpoint", required=True)
    p = sub.add_parser("rebuild-cache", help="rebuild missing per-run arrays of a frozen dataset (metadata untouched)")
    p.add_argument("--config", required=True)
    p.add_argument("--workers", type=int, default=8)
    p = sub.add_parser("evaluate")
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--partition", default="test", choices=["val", "test"])
    p = sub.add_parser("report")
    p.add_argument("--experiments", nargs="+", required=True)
    p.add_argument("--config", default="configs/event_patch_v1.yaml")
    p = sub.add_parser("snapshot")
    p.add_argument("--config", required=True)
    p.add_argument("--run", required=True)
    p.add_argument("--issued-at", required=True)
    p.add_argument("--output", required=True)
    p = sub.add_parser("predict")
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    for name in ("finetune-preflight", "event-audit", "finetune", "evaluate-events"):
        p = sub.add_parser(name)
        p.add_argument("--spec", required=True)
        if name in ("finetune-preflight", "finetune"):
            p.add_argument("--stage", default="event", choices=["event", "decoder"])
        if name == "finetune":
            p.add_argument("--resume", action="store_true")
            p.add_argument("--init", help="decoder stage: start from this candidate instead of the parent")
        if name == "evaluate-events":
            p.add_argument("--partition", default="test", choices=["val", "test"])
            p.add_argument("--candidates", nargs="*", default=[], help="name=<checkpoint> ...")
    p = sub.add_parser("promote", help="point serving at a checkpoint (recorded; --force for an unpromoted candidate)")
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--force", action="store_true")
    sub.add_parser("serving-status")
    p = sub.add_parser("serve")
    p.add_argument("--checkpoint")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8200)
    p.add_argument("--device")
    a = ap.parse_args(argv)
    if a.cmd in ("promote", "serving-status", "serve"):
        from . import serving
        if a.cmd == "promote":
            res = serving.promote(a.checkpoint, a.reason, a.force)
        elif a.cmd == "serving-status":
            res = serving.current() or {"serving": None}
        else:
            from .serve import serve
            return serve(a.checkpoint, a.host, a.port, a.device)
        print(json.dumps(res, indent=1, default=str))
        return
    if a.cmd in ("finetune-preflight", "event-audit", "finetune", "evaluate-events"):
        from . import finetune as ft
        spec = ft.load_spec(a.spec)
        if a.cmd == "finetune-preflight":
            res = ft.preflight(spec, a.stage)
        elif a.cmd == "event-audit":
            res = ft.event_audit(spec)
        elif a.cmd == "finetune":
            res = ft.finetune(spec, a.stage, a.resume, a.init)
        else:
            res = ft.evaluate_candidates(spec, a.partition, dict(c.split("=", 1) for c in a.candidates))
        print(json.dumps(res, indent=1, default=str)[:8000])
        return

    if a.cmd == "jam-wrapper":
        from .jam_wrapper import run
        res = run(a.checkpoint)
        print(json.dumps(res, indent=1, default=str)[:6000])
        return
    if a.cmd in ("retrain", "evaluate-retrain"):
        from . import retrain as rt
        if a.cmd == "retrain":
            res = rt.retrain(cfg_mod.load(a.config), a.parent, a.resume, a.max_epochs)
        else:
            res = rt.evaluate(a.checkpoint, a.partition, dataset_config=a.config, tag=a.tag)
        print(json.dumps(res, indent=1, default=str)[:8000])
        return
    if a.cmd == "audit":
        from .audit import run
        res = run(cfg_mod.load(a.config))
    elif a.cmd == "prepare":
        from .data import prepare
        res = prepare(cfg_mod.load(a.config), a.workers)
    elif a.cmd == "rebuild-cache":
        from .data import rebuild_cache
        res = rebuild_cache(cfg_mod.load(a.config), a.workers)
    elif a.cmd == "sanity":
        from .train import sanity
        res = sanity(cfg_mod.load(a.config))
    elif a.cmd == "train":
        from .train import train
        cfg = cfg_mod.load(a.config)
        if a.max_epochs:
            cfg.train.max_epochs = a.max_epochs
        if a.seed is not None:
            cfg.train.seed = a.seed
        if a.name:
            cfg.name = a.name
        res = train(cfg, resume=a.resume)
    elif a.cmd == "evaluate":
        from .evaluate import evaluate
        res = evaluate(a.checkpoint, a.partition)
    elif a.cmd == "report":
        from .evaluate import report
        res = report(cfg_mod.load(a.config), a.experiments)
    elif a.cmd == "snapshot":
        from .predict import snapshot
        res = snapshot(cfg_mod.load(a.config), a.run, a.issued_at, a.output)
    else:
        from .predict import predict
        res = predict(a.checkpoint, a.input, a.output)
    print(json.dumps(res, indent=1, default=str)[:6000])


if __name__ == "__main__":
    main()
