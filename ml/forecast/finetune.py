"""Event-awareness fine-tuning of a trained parent checkpoint (EVENT_AWARENESS_FINETUNING_PLAN.md §3, §5-§9).

    python -m forecast finetune-preflight --spec configs/event_patch_v3_awareness.yaml
    python -m forecast event-audit        --spec configs/event_patch_v3_awareness.yaml
    python -m forecast finetune           --spec configs/event_patch_v3_awareness.yaml --stage event [--resume]
    python -m forecast finetune           --spec configs/event_patch_v3_awareness.yaml --stage decoder [--init <ckpt>]
    python -m forecast evaluate-events    --spec configs/event_patch_v3_awareness.yaml --partition test

Stage `event` trains only `events.*`; stage `decoder` also trains `head.*` and `dec_ln.*` at a lower learning rate.
Everything else (embeddings, blocks, summary, horizon/future embeddings) is frozen and verified bitwise unchanged.
Forwards are deterministic (model.eval(): dropout off) with autograd enabled, so gradients reach the event
parameters through the frozen blocks that event FiLM modulates. The parent is an immutable teacher (no gradients).

Objective per window (each term its own masked mean with equal horizon weights; empty strata are a
differentiable zero):  L = w_g L_global + w_n L_event_near + w_a L_anticipation + w_p L_preserve [+ w_pair L_pair]
Selection uses Bearrison validation only, with predeclared guardrails; the parent's config hash is never reused.
"""
from __future__ import annotations

import csv
import dataclasses
import hashlib
import json
import platform
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import yaml

from . import config as cfg_mod
from . import event_windows as ew
from . import evaluate_events as ee
from . import events as ev_mod
from .config import ML_DIR, read_json, save_json, sha256_file
from .data import FUTURE_BASE_FEATURES, HIST_FEATURES, TIME_FEATURES
from .losses import masked_huber, paired_delta_huber
from .model import build_model
from .train import (Data, checkpoint_payload, forward, load_checkpoint, pick_device, rng_state, seed_all,
                    set_rng_state, to_batch)

STAGES = {"event": {"events.": "lr_event"},
          "decoder": {"events.": "stage_b_lr_event", "head.": "stage_b_lr_decoder", "dec_ln.": "stage_b_lr_decoder"}}


@dataclass
class Spec:
    parent: str = "data/forecast/experiments/event_patch_v2_main/best.pt"
    noevent_reference: str = "data/forecast/experiments/event_patch_v2_main_noevent/best.pt"
    output: str = "event_patch_v3_awareness"
    lr_event: float = 1e-4
    stage_b_lr_event: float = 5e-5
    stage_b_lr_decoder: float = 1e-5
    weight_decay: float = 1e-4
    grad_clip: float = 1.0
    max_epochs: int = 8
    patience: int = 3
    stage_b_max_epochs: int = 4
    stage_b_patience: int = 2
    per_family: int = 8
    seed: int = 0
    device: str = "auto"
    weights: dict = field(default_factory=lambda: {"global": 1.0, "event_near": 1.0, "anticipation": 2.0,
                                                   "preserve": 0.5, "pair": 0.0})
    phase_targets: dict = field(default_factory=lambda: {"pre_start": 0.5, "pre_end": 0.25, "other": 0.25})
    val_stride: int = 1
    guardrails: dict = field(default_factory=lambda: {"citywide_max_rel": 0.02, "control_max_rel": 0.02,
                                                      "severe_max_rel": 0.02, "antic_min_gain": 0.05,
                                                      "precision_max_drop": 0.02})
    source_path: str = ""

    def digest(self) -> str:
        d = dataclasses.asdict(self)
        d.pop("source_path")
        return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]

    def path(self, p: str) -> Path:
        q = Path(p)
        return q if q.is_absolute() else ML_DIR / q


def load_spec(path) -> Spec:
    p = Path(path)
    if not p.is_absolute() and not p.exists():
        p = ML_DIR / p
    raw = yaml.safe_load(p.read_text()) or {}
    bad = set(raw) - set(Spec.__dataclass_fields__)
    if bad:
        raise ValueError(f"unknown fine-tuning keys: {sorted(bad)}")
    s = Spec(**raw)
    for k in ("weights", "phase_targets", "guardrails"):
        base = getattr(Spec(), k)
        if set(getattr(s, k)) - set(base):
            raise ValueError(f"unknown {k}: {sorted(set(getattr(s, k)) - set(base))}")
        setattr(s, k, {**base, **getattr(s, k)})
    s.source_path = str(p)
    return s


def out_dir(spec: Spec, cfg, stage: str) -> Path:
    return cfg.path(cfg.data.out_root) / "experiments" / (spec.output if stage == "event" else f"{spec.output}_decoder")


# ---------------------------------------------------------------- parent + data

def load_parent(spec: Spec):
    p = spec.path(spec.parent)
    ck = load_checkpoint(p)
    cfg = cfg_mod.from_dict(ck["config"])
    return ck, cfg, sha256_file(p)


def build_from(ck, cfg, data, dev) -> torch.nn.Module:
    m = build_model(cfg, data.graph, ck["norm"], len(ev_mod.EVENT_PAIR_FEATURES)).to(dev)
    m.load_state_dict(ck["model"])
    return m


def trainable_names(model, stage: str) -> dict:
    """param name -> spec lr field, for the stage's groups (everything else frozen)."""
    out = {}
    for n, _ in model.named_parameters():
        for pre, lr in STAGES[stage].items():
            if n.startswith(pre):
                out[n] = lr
    return out


def freeze(model, stage: str, spec: Spec) -> list[dict]:
    names = trainable_names(model, stage)
    groups: dict = {}
    for n, p in model.named_parameters():
        p.requires_grad_(n in names)
        if n in names:
            groups.setdefault(names[n], []).append(p)
    return [{"params": ps, "lr": getattr(spec, lr), "name": lr} for lr, ps in groups.items()]


def frozen_unchanged(model, ref_state: dict, stage: str) -> dict:
    names = set(trainable_names(model, stage))
    sd = model.state_dict()
    changed_frozen = [k for k, v in sd.items() if k not in names and not torch.equal(v.cpu(), ref_state[k].cpu())]
    changed_train = [k for k in names if not torch.equal(sd[k].cpu(), ref_state[k].cpu())]
    return {"frozen_tensors": len(sd) - len(names), "frozen_changed": changed_frozen,
            "trainable_tensors": len(names), "trainable_changed": len(changed_train)}


# ---------------------------------------------------------------- preflight

def _git() -> dict:
    try:
        rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ML_DIR, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "ml/forecast", "ml/configs"], cwd=ML_DIR.parent,
                               capture_output=True, text=True).stdout.splitlines()
        return {"revision": rev or None, "dirty_files": dirty[:50]}
    except Exception as e:
        return {"revision": None, "error": str(e)}


def preflight(spec: Spec, stage: str = "event", resume: bool = False, profile: bool = True) -> dict:
    ck, cfg, sha = load_parent(spec)
    problems, checks = [], {}
    if not cfg.model.use_events:
        problems.append("parent has use_events=False")
    dev = pick_device(cfg) if spec.device == "auto" else torch.device(spec.device)
    data = Data(cfg, dev)
    if ck["dataset_manifest_sha256"] != data.manifest_sha:
        problems.append("dataset manifest differs from the parent's")
    if ck["splits_sha256"] != data.splits_sha:
        problems.append("split differs from the parent's")
    schema = {"history": HIST_FEATURES, "time": TIME_FEATURES, "future_base": FUTURE_BASE_FEATURES,
              "event_pair": ev_mod.EVENT_PAIR_FEATURES}
    for k, v in schema.items():
        if ck["feature_schema"].get(k) != v:
            problems.append(f"feature schema '{k}' differs from the parent")
    man = read_json(cfg.dataset_dir / "manifest.json")
    if ck["network_version"] != man["network"]["version"]:
        problems.append("network version differs")
    if list(map(str, data.graph.model_ids)) != ck["model_ids"]:
        problems.append("ordered road ids differ from the parent")
    if json.dumps(data.norm, sort_keys=True) != json.dumps(ck["norm"], sort_keys=True):
        problems.append("normalisation on disk differs from the parent checkpoint's")
    missing, stale = [], []
    for r in man["selected_runs"]:
        d = cfg.dataset_dir / "runs" / r["run_id"] / "done.json"
        if not d.exists():
            missing.append(r["run_id"])
        elif read_json(d)["source_sha256"] != man["input_sha256"][f"export/sim_{r['run_id']}.parquet"]:
            stale.append(r["run_id"])
    if missing:
        problems.append(f"{len(missing)} run caches missing: python -m forecast rebuild-cache")
    if stale:
        problems.append(f"{len(stale)} run caches built from a different export")
    od = out_dir(spec, cfg, stage)
    if (od / "last.pt").exists() and not resume:
        problems.append(f"{od} already has a run (use --resume with the same parent/spec)")
    checks.update({"parent": str(spec.path(spec.parent)), "parent_sha256": sha, "parent_best_epoch": ck["state"]["best_epoch"],
                   "dataset_id": cfg.data.dataset_id, "manifest_sha256": data.manifest_sha, "splits_sha256": data.splits_sha,
                   "network_version": ck["network_version"], "roads": len(ck["model_ids"]), "spec_digest": spec.digest(),
                   "spec": dataclasses.asdict(spec), "stage": stage, "device": str(dev),
                   "gpu": torch.cuda.get_device_name(0) if dev.type == "cuda" else None,
                   "versions": {"python": platform.python_version(), "torch": torch.__version__, "numpy": np.__version__,
                                "pandas": pd.__version__},
                   "git": _git(), "disk_free_gb": round(shutil.disk_usage(cfg.dataset_dir).free / 2**30, 1),
                   "run_caches": {"selected": len(man["selected_runs"]), "missing": len(missing), "stale": len(stale)}})
    if profile and not problems:
        model = build_from(ck, cfg, data, dev)
        model.eval()
        groups = freeze(model, stage, spec)
        tr = data.partition("train")
        r = tr[tr.with_event].iloc[0]
        b = to_batch(data.window(r), dev, data.event_tensors(r.run_id), cfg)
        if dev.type == "cuda":
            torch.cuda.synchronize(); torch.cuda.reset_peak_memory_stats()
        t0 = time.time()
        loss = masked_huber(forward(model, b, cfg.train.amp), b["target"], b["mask"])
        loss.backward()
        if dev.type == "cuda":
            torch.cuda.synchronize()
        gn = {n: float(p.grad.norm()) for n, p in model.named_parameters() if p.grad is not None}
        checks["profile_step"] = {"seconds": round(time.time() - t0, 3),
                                  "peak_gpu_mb": round(torch.cuda.max_memory_allocated() / 2**20) if dev.type == "cuda" else None,
                                  "trainable_params": sum(p.numel() for g_ in groups for p in g_["params"]),
                                  "frozen_params": sum(p.numel() for p in model.parameters() if not p.requires_grad),
                                  "grad_reaches_event_encoder": any(n.startswith("events.pair") and v > 0 for n, v in gn.items()),
                                  "frozen_have_no_grad": all(n in trainable_names(model, stage) for n in gn)}
    return {"ok": not problems, "problems": problems, "checks": checks}


# ---------------------------------------------------------------- objective

class Objective:
    """Per-window loss components. Masks come from the frozen index + the event run's neighbourhood."""

    def __init__(self, cfg, spec: Spec, data, index: pd.DataFrame):
        self.cfg, self.spec, self.data, self.index = cfg, spec, data, index
        self.nb: dict = {}
        self.delta = cfg.train.huber_delta

    def masks(self, row, b) -> dict:
        dev = b["mask"].device
        m = b["mask"]
        if row.event_run not in self.nb:
            self.nb[row.event_run] = ew.neighbourhoods(self.data.run(row.event_run).context, self.data.graph, self.cfg)
        nb = self.nb[row.event_run]
        t = lambda a: torch.as_tensor(a, device=dev)[None, None]
        zero = torch.zeros_like(m)
        if not row.with_event:
            return {"global": m, "event_near": zero, "anticipation": zero, "preserve": m, "near": t(nb.near)}
        pre = bool(row.pre_start) or bool(row.pre_end)
        clear = ew.clear_roads(self.data.run(row.run_id), int(row.origin)) & nb.near
        return {"global": m, "event_near": m & t(nb.near), "anticipation": (m & t(clear)) if pre else zero,
                "preserve": m & t(nb.far), "near": t(nb.near)}

    def window(self, pred, tpred, b, mk) -> tuple[torch.Tensor, dict]:
        comps = {"global": masked_huber(pred, b["target"], mk["global"], self.delta),
                 "event_near": masked_huber(pred, b["target"], mk["event_near"], self.delta),
                 "anticipation": masked_huber(pred, b["target"], mk["anticipation"], self.delta),
                 "preserve": masked_huber(pred, tpred, mk["preserve"], self.delta)}
        w = self.spec.weights
        total = sum(w[k] * v for k, v in comps.items())
        info = {k: float(v) for k, v in comps.items()}
        info.update({f"n_{k}": int(mk[k].sum()) for k in comps})
        return total, info


# ---------------------------------------------------------------- validation / selection

def validate(cfg, data, index, model, spec: Spec, log=None) -> tuple[dict, pd.DataFrame]:
    res = ee.run(cfg, data, index, "val", {"candidate": (model, True)}, stride=spec.val_stride, persistence=False,
                 log=log)
    return ee.headline(res["cells"], "candidate"), res["cells"]


def guard(cand: dict, parent: dict, g: dict) -> dict:
    """Predeclared validation rules (engineering criteria, not statistical guarantees)."""
    rel = lambda k: (cand[k] - parent[k]) / parent[k] if cand.get(k) is not None and parent.get(k) else None
    out = {"citywide_rel": rel("citywide_tt_mae"), "control_rel": rel("control_tt_mae"),
           "severe_rel": rel("severe_tt_mae"), "antic_rel": rel("antic_tt_mae")}
    safe = all(v is not None for v in (out["citywide_rel"], out["control_rel"], out["severe_rel"])) \
        and out["citywide_rel"] <= g["citywide_max_rel"] and out["control_rel"] <= g["control_max_rel"] \
        and out["severe_rel"] <= g["severe_max_rel"]
    cls_ok = (cand.get("antic_recall") is not None and parent.get("antic_recall") is not None
              and cand["antic_recall"] >= parent["antic_recall"] - 1e-12
              and (cand.get("antic_precision") or 0) >= (parent.get("antic_precision") or 0) - g["precision_max_drop"])
    supported = (cand.get("antic_labels") or 0) > 0
    improved = supported and out["antic_rel"] is not None and out["antic_rel"] <= -g["antic_min_gain"]
    out.update(safe=bool(safe), classification_ok=bool(cls_ok), anticipation_supported=bool(supported),
               meaningful_improvement=bool(improved), promote=bool(safe and cls_ok and improved))
    return out


# ---------------------------------------------------------------- training

def finetune(spec: Spec, stage: str = "event", resume: bool = False, init: str | None = None, log=None,
             stop_after_epochs: int | None = None) -> dict:
    log = log or (lambda m: print(m, flush=True))
    pf = preflight(spec, stage, resume, profile=True)
    if not pf["ok"]:
        raise SystemExit("preflight failed:\n- " + "\n- ".join(pf["problems"]))
    ck, cfg, parent_sha = load_parent(spec)
    dev = torch.device(pf["checks"]["device"])
    rng = seed_all(spec.seed)
    data = Data(cfg, dev)
    data.norm = ck["norm"]                                  # the parent's normalisation, verified equal above
    index, audit = ew.build_index(cfg, data, counts=True)
    od = out_dir(spec, cfg, stage)
    od.mkdir(parents=True, exist_ok=True)
    index.to_parquet(od / "event_windows.parquet", index=False)
    save_json(od / "event_audit.json", audit)
    teacher = build_from(ck, cfg, data, dev)
    teacher.eval()
    for p in teacher.parameters():
        p.requires_grad_(False)
    start = ck
    init_path, init_sha = str(spec.path(spec.parent)), parent_sha
    if stage == "decoder" and init:
        start = load_checkpoint(spec.path(init))
        init_path, init_sha = str(spec.path(init)), sha256_file(spec.path(init))
    model = build_from(start, cfg, data, dev)
    ref_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
    model.eval()                                            # deterministic forwards (dropout off), autograd on
    groups = freeze(model, stage, spec)
    opt = torch.optim.AdamW(groups, weight_decay=spec.weight_decay)
    obj = Objective(cfg, spec, data, index)
    max_ep = spec.max_epochs if stage == "event" else spec.stage_b_max_epochs
    patience = spec.patience if stage == "event" else spec.stage_b_patience
    cand_cfg = cfg_mod.from_dict(ck["config"])
    cand_cfg.name = od.name
    state = {"epoch": 0, "best_score": None, "best_epoch": -1, "bad_epochs": 0, "curves": [], "done": False,
             "train_seconds": 0.0, "stage": stage}
    meta = {"parent": str(spec.path(spec.parent)), "parent_sha256": parent_sha, "init": init_path, "init_sha256": init_sha,
            "stage": stage, "spec_digest": spec.digest(), "spec": dataclasses.asdict(spec)}
    parent_val_path = od / "val_parent.json"
    if resume and (od / "last.pt").exists():
        last = load_checkpoint(od / "last.pt")
        f = last["finetune"]
        if f["parent_sha256"] != parent_sha or f["spec_digest"] != spec.digest() or f["stage"] != stage \
                or f["init_sha256"] != init_sha:
            raise SystemExit("resume refused: parent, init, stage or fine-tuning spec changed")
        model.load_state_dict(last["model"])
        opt.load_state_dict(last["optimizer"])
        state = last["state"]
        set_rng_state(last["rng"], rng)
        log(f"resumed at epoch {state['epoch']}")
    save_json(od / "finetune_spec.json", {**meta, "preflight": pf["checks"]})
    if parent_val_path.exists() and read_json(parent_val_path).get("key") == [parent_sha, spec.val_stride]:
        parent_val = read_json(parent_val_path)["headline"]
    else:
        log("validating parent (once)")
        parent_val, _ = validate(cfg, data, index, teacher, spec, log)
        save_json(parent_val_path, {"key": [parent_sha, spec.val_stride], "headline": parent_val})
    if dev.type == "cuda":
        torch.cuda.reset_peak_memory_stats()
    targets = tuple(spec.phase_targets.items())
    pair_w = spec.weights.get("pair", 0.0)
    calls = 0
    while state["epoch"] < max_ep and not state["done"]:
        if stop_after_epochs is not None and calls >= stop_after_epochs:
            break
        t0 = time.time()
        plan, realized = ew.epoch_sample(index, spec.per_family, rng, targets)
        comp_sums: dict = {}
        for i in plan:
            r = index.loc[i]
            b = to_batch(data.window(r), dev, data.event_tensors(r.run_id), cfg)
            mk = obj.masks(r, b)
            pred = forward(model, b, cfg.train.amp)
            with torch.no_grad():
                tpred = forward(teacher, b, cfg.train.amp)
            loss, info = obj.window(pred, tpred, b, mk)
            if pair_w and r.with_event and int(r.pair) >= 0:
                rc = index.loc[int(r.pair)]
                bc = to_batch(data.window(rc), dev, data.event_tensors(rc.run_id), cfg)
                mkc = obj.masks(rc, bc)
                predc = forward(model, bc, cfg.train.amp)
                with torch.no_grad():
                    tpredc = forward(teacher, bc, cfg.train.amp)
                lc, infoc = obj.window(predc, tpredc, bc, mkc)
                common = b["mask"] & bc["mask"] & mk["near"]
                lp = paired_delta_huber(pred, predc, b["target"], bc["target"], common, obj.delta)
                loss = loss + lc + pair_w * lp
                info["pair"], info["n_pair"] = float(lp), int(common.sum())
                info["control_total"] = float(lc)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_([p for g_ in groups for p in g_["params"]], spec.grad_clip)
            opt.step()
            info["total"] = float(loss)
            for k, v in info.items():
                s = comp_sums.setdefault(k, [0.0, 0])
                s[0] += v
                s[1] += 1
        v, _ = validate(cfg, data, index, model, spec)
        gd = guard(v, parent_val, spec.guardrails)
        state["epoch"] += 1
        calls += 1
        dt = time.time() - t0
        state["train_seconds"] += dt
        peak = torch.cuda.max_memory_allocated() / 2**20 if dev.type == "cuda" else float("nan")
        score = v["antic_tt_mae"] if v["antic_tt_mae"] is not None else v["event_near_tt_mae"]
        eligible = gd["safe"] and gd["classification_ok"]
        improved = eligible and (state["best_score"] is None or score < state["best_score"] - 1e-9 or (
            abs(score - state["best_score"]) <= 1e-9 and (v["antic_f1"] or 0) > state.get("best_f1", 0)))
        if improved:
            state.update(best_score=score, best_epoch=state["epoch"], best_f1=v["antic_f1"] or 0, bad_epochs=0,
                         best_val=v, best_guard=gd)
        else:
            state["bad_epochs"] += 1
        state["done"] = state["bad_epochs"] >= patience
        if state.get("fallback_score") is None or score < state["fallback_score"]:
            state["fallback_score"], state["fallback_epoch"] = score, state["epoch"]   # best regardless of guardrails
        row = {"epoch": state["epoch"], "seconds": round(dt, 1), "peak_gpu_mb": round(peak, 1),
               **{f"train_{k}": round(s[0] / max(s[1], 1), 6) for k, s in comp_sums.items() if not k.startswith("n_")},
               **{f"cells_{k[2:]}": int(s[0]) for k, s in comp_sums.items() if k.startswith("n_")},
               **{f"val_{k}": v[k] for k in v}, **{f"guard_{k}": gd[k] for k in gd},
               "sample": json.dumps(realized["phase_share"])}
        state["curves"].append(row)
        payload = checkpoint_payload(cand_cfg, data, model, opt, state, rng)
        payload["finetune"] = {**meta, "epoch": state["epoch"], "validation": v, "guard": gd,
                               "parent_validation": parent_val, "trainable": sorted(trainable_names(model, stage))}
        payload["model_version"] = f"{cand_cfg.name}-{cand_cfg.hash()}-ft{spec.digest()[:8]}"
        torch.save(payload, od / "last.pt")
        if improved:
            torch.save(payload, od / "best_candidate.pt")
            torch.save(payload, od / "best.pt")             # the same file under the name other tools expect
        elif state["fallback_epoch"] == state["epoch"] and not (od / "best_candidate.pt").exists():
            torch.save(payload, od / "best_unsafe.pt")
        log(f"[{stage}] epoch {state['epoch']} {dt:.0f}s antic_tt_mae {v['antic_tt_mae']} (parent "
            f"{parent_val['antic_tt_mae']}) city {v['citywide_tt_mae']:.4f}/{parent_val['citywide_tt_mae']:.4f} "
            f"safe={gd['safe']} cls_ok={gd['classification_ok']}{' *' if improved else ''}")
    check = frozen_unchanged(model, ref_state, stage)
    if check["frozen_changed"]:
        raise SystemExit(f"frozen tensors changed: {check['frozen_changed'][:5]}")
    best = state.get("best_guard")
    decision = {"stage": stage, "output": str(od), "selected_epoch": state["best_epoch"] if best else None,
                "promote": bool(best and best["promote"]), "validation": state.get("best_val"),
                "guard": best, "parent_validation": parent_val, "fallback_epoch": state.get("fallback_epoch"),
                "frozen_check": check,
                "rule": "safe (citywide/control/severe <= +2%) and recall >= parent and precision >= parent - 2 pp "
                        "and anticipation travel-time MAE >= 5% lower than the parent (Bearrison validation only)",
                "note": ("no candidate satisfied the guardrails: best_unsafe.pt is kept for inspection only"
                         if not best else "best_candidate.pt = best guardrail-safe epoch")}
    save_json(od / "promotion_decision.json", decision)
    curves = state["curves"]
    keys = sorted({k for r in curves for k in r})
    with open(od / "curves.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=keys)
        wr.writeheader()
        wr.writerows(curves)
    summary = {"experiment": od.name, "best_epoch": state["best_epoch"], "best_val_loss": state.get("best_score"),
               "epochs_run": state["epoch"], "early_stopped": state["done"], "train_seconds": round(state["train_seconds"], 1),
               "device": str(dev), "gpu": torch.cuda.get_device_name(0) if dev.type == "cuda" else None,
               "peak_gpu_mb": max((r["peak_gpu_mb"] for r in curves), default=None),
               "parameters": sum(p.numel() for p in model.parameters()),
               "trainable_parameters": sum(p.numel() for g_ in groups for p in g_["params"]),
               "selection_metric": "validation anticipation travel-time MAE (guardrail-safe epochs only)",
               "promote": decision["promote"]}
    save_json(od / "train_summary.json", summary)
    return {**summary, "decision": decision}


# ---------------------------------------------------------------- audit / evaluation commands

def event_audit(spec: Spec) -> dict:
    ck, cfg, _ = load_parent(spec)
    data = Data(cfg, torch.device("cpu"))
    index, audit = ew.build_index(cfg, data, counts=True)
    od = cfg.path(cfg.data.out_root) / "experiments" / spec.output
    od.mkdir(parents=True, exist_ok=True)
    index.to_parquet(od / "event_windows.parquet", index=False)
    save_json(od / "event_audit.json", audit)
    return audit


def evaluate_candidates(spec: Spec, partition: str, candidates: dict, log=None) -> dict:
    """Parent, no-event reference, persistence and the given candidates on identical masks."""
    log = log or (lambda m: print(m, flush=True))
    ck, cfg, _ = load_parent(spec)
    dev = pick_device(cfg) if spec.device == "auto" else torch.device(spec.device)
    data = Data(cfg, dev)
    data.norm = ck["norm"]
    index, _ = ew.build_index(cfg, data, counts=False)
    systems = {"parent": (build_from(ck, cfg, data, dev).eval(), True)}
    ne = spec.path(spec.noevent_reference)
    if ne.exists():
        nck = load_checkpoint(ne)
        ncfg = cfg_mod.from_dict(nck["config"])
        systems["noevent"] = (build_model(ncfg, data.graph, nck["norm"], len(ev_mod.EVENT_PAIR_FEATURES)).to(dev), False)
        systems["noevent"][0].load_state_dict(nck["model"])
        systems["noevent"][0].eval()
    for name, path in candidates.items():
        cck = load_checkpoint(spec.path(path))
        if cck["model_ids"] != ck["model_ids"] or cck["norm"] != ck["norm"]:
            raise SystemExit(f"{name}: road order or normalisation differs from the parent")
        systems[name] = (build_from(cck, cfg, data, dev).eval(), True)
    res = ee.run(cfg, data, index, partition, systems, persistence=True, log=log)
    od = cfg.path(cfg.data.out_root) / "experiments" / spec.output / f"eval_events_{partition}"
    od.mkdir(parents=True, exist_ok=True)
    res["cells"].to_parquet(od / "cells.parquet", index=False)
    res["pairs"].to_csv(od / "pairs.csv", index=False)
    out = {"partition": partition, "windows": res["windows"], "seconds": res["seconds"],
           "headline": {s: ee.headline(res["cells"], s) for s in res["cells"].system.unique()},
           "pairs": res["pairs"].to_dict("records")}
    save_json(od / "summary.json", out)
    return out


# ---------------------------------------------------------------- report

def _md(df: pd.DataFrame) -> str:
    def f(v):
        if isinstance(v, (bool, np.bool_)):
            return "yes" if v else "no"
        if isinstance(v, (float, np.floating)):
            return "–" if not np.isfinite(v) else (f"{v:.4f}" if abs(v) < 10 else f"{v:.1f}")
        return str(v)
    lines = ["| " + " | ".join(map(str, df.columns)) + " |", "|" + "---|" * len(df.columns)]
    return "\n".join(lines + ["| " + " | ".join(f(v) for v in row) + " |" for row in df.itertuples(index=False)])


def write_report(spec: Spec, stages: dict, evals: dict, path: Path, recommendation: str = "") -> Path:
    """stages: name -> experiment dir; evals: partition -> evaluate_candidates() output dir."""
    ck, cfg, sha = load_parent(spec)
    L = ["# Event-awareness fine-tuning (v3)", "",
         "> **Synthetic.** SUMO scenarios on real SF roads/permits; demand and attendance are assumptions. Nothing here is "
         "validated on measured event traffic. Road/bucket labels overlap and are not independent trials.", "",
         "## Identity", "",
         f"- Parent: `{spec.parent}` (sha256 `{sha[:16]}…`, best epoch {ck['state']['best_epoch']}); no-event reference: "
         f"`{spec.noevent_reference}`",
         f"- Dataset `{cfg.data.dataset_id}` (manifest `{ck['dataset_manifest_sha256'][:12]}…`, split "
         f"`{ck['splits_sha256'][:12]}…`), {len(ck['model_ids'])} roads, network `{ck['network_version']}`; the parent's "
         "normalisation is used throughout.",
         f"- Fine-tuning spec digest `{spec.digest()}`: `{spec.source_path}`", ""]
    if recommendation:
        L += ["## Recommendation", "", recommendation, ""]
    first = True
    for name, d in stages.items():
        d = Path(d)
        if not (d / "promotion_decision.json").exists():
            L += [f"## {name}: not run", ""]
            continue
        dec, summ = read_json(d / "promotion_decision.json"), read_json(d / "train_summary.json")
        fs = read_json(d / "finetune_spec.json")
        cur = pd.read_csv(d / "curves.csv")
        audit = read_json(d / "event_audit.json")
        fc = dec["frozen_check"]
        L += [f"## {name} (`{d.name}`)", "",
              f"- Stage `{fs['stage']}`, initialised from `{fs['init']}`; trainable parameters "
              f"{summ['trainable_parameters']:,} of {summ['parameters']:,}; loss weights `{json.dumps(fs['spec']['weights'])}`.",
              f"- Frozen-tensor check after training: {fc['frozen_tensors']} frozen tensors, changed: "
              f"{fc['frozen_changed'] or 'none'}; trainable tensors changed: {fc['trainable_changed']}/{fc['trainable_tensors']}.",
              f"- Epochs {summ['epochs_run']} ({'early stop' if summ['early_stopped'] else 'epoch cap'}), "
              f"{summ['train_seconds']:.0f} s on {summ['gpu']}, peak GPU {summ['peak_gpu_mb']} MB; selected epoch "
              f"{dec['selected_epoch']}; **promote: {dec['promote']}**.", "",
              "Validation (Bearrison) per epoch (travel-time MAE s; anticipation = directly observed clear near roads in "
              "the hour before public start/end):", ""]
        keep = [c for c in ["epoch", "train_total", "train_global", "train_event_near", "train_anticipation",
                            "train_preserve", "train_pair", "val_citywide_tt_mae", "val_control_tt_mae",
                            "val_severe_tt_mae", "val_event_near_tt_mae", "val_antic_tt_mae", "val_antic_precision",
                            "val_antic_recall", "guard_safe", "guard_promote", "seconds"] if c in cur.columns]
        L += [_md(cur[keep]), "", f"Parent on the same validation masks: `{json.dumps(dec['parent_validation'])}`", ""]
        if first:
            L += ["### Training / validation support (event runs)", "", _md(pd.DataFrame(audit.get("support", []))), "",
                  f"Pairs: `{json.dumps({k: v for k, v in audit.items() if k != 'support'})}`", ""]
            first = False
    for part, d in evals.items():
        d = Path(d)
        if not (d / "summary.json").exists():
            continue
        cells = pd.read_parquet(d / "cells.parquet")
        order = ["persistence", "noevent", "parent"] + sorted(s for s in cells.system.unique()
                                                              if s not in ("persistence", "noevent", "parent"))
        rank = {s: i for i, s in enumerate(order)}
        L += [f"## {part.upper()} ({'Bearrison' if part == 'val' else 'Portola, reused held-out test'})", ""]
        st = ee.summarize(cells, ["stratum", "system"])
        st["_o"] = st.system.map(rank)
        cols = ["stratum", "system", "labels", "tt_mae_s", "tt_wape", "speed_mae_mph", "cong_mae", "positives",
                "precision", "recall", "f1"]
        L += [_md(st.sort_values(["stratum", "_o"])[cols]), ""]
        hz = ee.summarize(cells[cells.stratum == "antic"], ["horizon_min", "system"])
        hz["_o"] = hz.system.map(rank)
        L += ["Anticipation stratum by horizon:", "",
              _md(hz.sort_values(["horizon_min", "_o"])[["horizon_min", "system", "labels", "tt_mae_s", "positives",
                                                         "precision", "recall", "f1"]]), ""]
        fam = ee.summarize(cells[cells.stratum == "antic"], ["family_id", "system"])
        if len(fam):
            fm = fam.pivot_table(index="family_id", columns="system", values="tt_mae_s")
            fm = fm[[c for c in order if c in fm.columns]]
            L += ["Anticipation travel-time MAE per family (families are the less-correlated unit):", "",
                  _md(fm.reset_index()), ""]
        pr = pd.read_csv(d / "pairs.csv")
        if len(pr):
            L += ["Paired event-minus-control impact error on common valid near roads (z = log travel-time ratio; "
                  "seconds from derived travel times):", "", _md(pr), ""]
    L += ["## Limitations", "",
          "- One validation event group (Bearrison) and one reused test group (Portola); pooled cell counts overlap.",
          "- Public schedule boundaries are proxies for traffic phases, not observed surge onset.",
          "- Schedule context is assumed known; announcement timing is not modelled. Horizon stays 60 min.",
          "- Onset-timing diagnostics and shifted-schedule sensitivity were not run in this pass; the standard "
          "`forecast evaluate` counterfactual (focal event removed) is in each candidate's eval directory.", "",
          "## Reproduce", "", "```", f"python -m forecast finetune-preflight --spec {spec.source_path}",
          f"python -m forecast finetune --spec {spec.source_path} --stage event",
          f"python -m forecast evaluate-events --spec {spec.source_path} --partition test --candidates <name>=<ckpt>",
          "```", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")
    return path
