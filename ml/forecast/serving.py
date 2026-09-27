"""Serving pointer: which forecaster checkpoint the service uses, and why (one command to change it).

    python -m forecast promote --checkpoint data/forecast/experiments/event_patch_v2_main/best.pt --reason "..."
    python -m forecast promote --checkpoint <candidate>/best_candidate.pt --force --reason "experiment"
    python -m forecast serving-status

`data/forecast/serving/current.json` records the checkpoint (copied next to it, content-addressed), its digest and
model version, who promoted it and when, whether it passed its predeclared validation rule
(`promotion_decision.json` next to a fine-tuned checkpoint; ordinary trained checkpoints have none), and the
previous pointer. A candidate that did not pass its rule needs `--force`; the override is recorded, never hidden.
Every change is appended to `history.jsonl`.
"""
from __future__ import annotations

import getpass
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .config import ML_DIR, read_json, save_json, sha256_file

SERVING_DIR = ML_DIR / "data" / "forecast" / "serving"


def _abs(p) -> Path:
    q = Path(p)
    return q if q.is_absolute() else ML_DIR / q


def current(serving_dir: Path = SERVING_DIR) -> dict | None:
    p = serving_dir / "current.json"
    return read_json(p) if p.exists() else None


def promote(checkpoint: str, reason: str, force: bool = False, serving_dir: Path = SERVING_DIR) -> dict:
    from .train import load_checkpoint
    src = _abs(checkpoint)
    if not src.exists():
        raise SystemExit(f"no checkpoint at {src}")
    ck = load_checkpoint(src)
    dec_path = src.parent / "promotion_decision.json"
    dec = read_json(dec_path) if dec_path.exists() else None
    passed = None if dec is None else bool(dec.get("promote"))
    if passed is False and not force:
        raise SystemExit(f"{src.parent.name} did not pass its validation rule ({dec_path}); "
                         "pass --force to serve it anyway (the override is recorded)")
    sha = sha256_file(src)
    serving_dir.mkdir(parents=True, exist_ok=True)
    dst = serving_dir / f"{ck['model_version']}-{sha[:12]}.pt"
    if not dst.exists():
        shutil.copy2(src, dst)
    prev = current(serving_dir)
    rec = {"checkpoint": dst.name, "source": str(src.relative_to(ML_DIR)) if src.is_relative_to(ML_DIR) else str(src),
           "sha256": sha, "model_version": ck["model_version"], "network_version": ck["network_version"],
           "dataset_id": ck["dataset_id"], "promoted_at": datetime.now(timezone.utc).isoformat(),
           "promoted_by": getpass.getuser(), "reason": reason,
           "validation_rule": ("none (ordinary trained checkpoint)" if dec is None else
                               ("passed" if passed else "NOT passed (forced)")),
           "forced": bool(force and passed is False),
           "validation": (dec or {}).get("validation"), "parent_validation": (dec or {}).get("parent_validation"),
           "previous": None if prev is None else {k: prev.get(k) for k in ("checkpoint", "model_version", "promoted_at")}}
    save_json(serving_dir / "current.json", rec)
    with open(serving_dir / "history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    return rec


def resolve(checkpoint: str | None = None, serving_dir: Path = SERVING_DIR) -> tuple[Path, dict]:
    """Explicit checkpoint, else the promoted one."""
    if checkpoint:
        return _abs(checkpoint), {"checkpoint": str(checkpoint), "note": "explicit --checkpoint (not the pointer)"}
    rec = current(serving_dir)
    if rec is None:
        raise SystemExit("nothing promoted yet: python -m forecast promote --checkpoint <ckpt> --reason ...")
    p = serving_dir / rec["checkpoint"]
    if sha256_file(p) != rec["sha256"]:
        raise SystemExit(f"{p} does not match the promoted digest")
    return p, rec
