"""Full-model transfer of a trusted parent checkpoint to a longer horizon (LONG_HORIZON_RETRAINING_PLAN.md §6-§9).

    python -m forecast retrain          --config configs/event_patch_v4_h18.yaml --parent <v2 best.pt> [--resume]
    python -m forecast evaluate-retrain --checkpoint <exp>/best.pt --partition val|test

Initialisation: every parent tensor whose shape matches is copied (graph buffers must be identical); the horizon
embedding keeps the parent's rows exactly and new rows start from the parent's last row + small seeded noise.
Every parameter trains (backbone/decoder at lr_backbone, events.* and hor.* at lr_event) with a fresh AdamW. The
parent's normalisation is used for inputs (the new dataset's fitted norm.json is not read).

Objective per window: w_g L_global + w_n L_event_near + w_a L_anticipation, each a masked Huber on z whose horizons
are grouped (default: first hour 50%, hours 2-3 50%; equal weight inside a group; empty groups drop out).
Anticipation = event run issued within the longest lead band before public start/end, directly observed clear
near roads (future congested and clear targets both kept). Selection: lowest validation objective (Bearrison).
"""
from __future__ import annotations

import csv
import dataclasses
import json
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F

from . import config as cfg_mod
from . import event_windows as ew
from . import evaluate_events as ee
from . import events as ev_mod
from .config import read_json, save_json, sha256_file
from .data import FUTURE_BASE_FEATURES, HIST_FEATURES, TIME_FEATURES, persistence_z
from .evaluate import derive
from .finetune import Objective, _git
from .model import build_model
from .train import (Data, checkpoint_payload, forward, load_checkpoint, pick_device, seed_all, set_rng_state,
                    to_batch)

FAST = ("events.", "hor.", "jam_head.", "q_head.")   # parameter prefixes trained at lr_event
NEW_HEADS = ("jam_head.", "q_head.", "events.attn.")
EVENT_IN = "events.pair.0.weight"
GROW_COLS = (EVENT_IN, "events.agg.0.weight")   # inputs extended at the end (event features / attention pooling)


@dataclass
class RetrainCfg:
    lr_backbone: float = 1e-4
    lr_event: float = 3e-4
    weight_decay: float = 1e-4
    grad_clip: float = 1.0
    max_epochs: int = 30
    patience: int = 5
    per_family: int = 24
    seed: int = 0
    new_row_noise: float = 0.01
    weights: dict = field(default_factory=lambda: {"global": 1.0, "event_near": 1.0, "anticipation": 2.0})
    horizon_groups: list = field(default_factory=lambda: [[0, 6, 0.5], [6, 18, 0.5]])
    lead_bands_min: list = field(default_factory=lambda: [0, 60, 120, 180])
    other_share: float = 0.25
    val_stride: int = 2
    prefetch: int = 6
    guardrails: dict = field(default_factory=lambda: {"first_hour_citywide_max_rel": 0.02,
                                                      "first_hour_control_max_rel": 0.02,
                                                      "first_hour_severe_max_rel": 0.02})
    # improvement-plan options (defaults = the v4/v5 objective)
    jam_weight: float = 0.0          # BCE on the jam head (model.jam_head), per stratum like the z loss
    jam_pos_weight: float = 1.0      # positive-class weight of that BCE
    jam_tolerance: int = 0           # label = jam anywhere within +-k target buckets (timing-tolerant)
    quantile_weight: float = 0.0     # pinball loss on the quantile heads (model.quantiles)
    attendance_weight: bool = False  # event-run windows weighted by exp(0.5 (log att - mean log att)), clipped 0.5-2
    lr_schedule: str = "constant"    # constant | cosine (per step, linear warm-up)
    warmup_epochs: float = 0.5
    init: str = "parent"             # parent (migrate the parent's weights) | scratch (random init; parent = norm only)
    select_on: str = "total"         # total | anticipation (validation Huber + jam BCE on the anticipation stratum)

    def digest(self) -> str:
        import hashlib
        return hashlib.sha256(json.dumps(dataclasses.asdict(self), sort_keys=True).encode()).hexdigest()[:16]


def retrain_cfg(cfg) -> RetrainCfg:
    raw = getattr(cfg, "retrain", None) or {}
    bad = set(raw) - set(RetrainCfg.__dataclass_fields__)
    if bad:
        raise ValueError(f"unknown retrain keys: {sorted(bad)}")
    rc = RetrainCfg(**raw)
    H = cfg.data.horizon_steps
    if rc.horizon_groups[-1][1] != H or rc.horizon_groups[0][0] != 0:
        raise ValueError(f"horizon_groups must cover buckets 0..{H}")
    return rc


# ---------------------------------------------------------------- migration

def migrate(model: torch.nn.Module, parent_sd: dict, noise: float, seed: int) -> dict:
    """Copy the parent into `model` in place. Returns a log of what was copied / initialised. Any tensor that is
    neither identical in shape nor the horizon embedding is an error (no strict=False shortcuts)."""
    sd = model.state_dict()
    copied, grown = [], {}
    new_heads = [k for k in sd if k not in parent_sd and k.startswith(NEW_HEADS)]
    missing = [k for k in sd if k not in parent_sd and k not in new_heads]
    unexpected = [k for k in parent_sd if k not in sd]
    if missing or unexpected:
        raise SystemExit(f"parent/new model key mismatch: missing {missing[:5]}, unexpected {unexpected[:5]}")
    gen = torch.Generator().manual_seed(seed)
    new = {}
    for k, v in sd.items():
        if k in new_heads:              # absent in the parent: keep this model's (deliberate) initialisation
            new[k] = v.clone()
            grown[k] = {"init": "new head (model init)"}
            continue
        p = parent_sd[k].to(device=v.device, dtype=v.dtype)
        if p.shape == v.shape:
            new[k] = p.clone()
            copied.append(k)
        elif k == "hor.weight" and p.shape[1] == v.shape[1] and p.shape[0] < v.shape[0]:
            h0 = p.shape[0]
            extra = p[-1:].expand(v.shape[0] - h0, -1) + noise * torch.randn(v.shape[0] - h0, v.shape[1], generator=gen).to(v.device)
            new[k] = torch.cat([p, extra.to(v.dtype)], 0)
            grown[k] = {"parent_rows": h0, "new_rows": v.shape[0] - h0, "init": f"parent last row + N(0, {noise}) seed {seed}"}
        elif k in GROW_COLS and p.shape[0] == v.shape[0] and p.shape[1] < v.shape[1]:
            # extra event features are appended after the parent's (by name, verified in preflight): zero columns
            new[k] = torch.cat([p, torch.zeros(v.shape[0], v.shape[1] - p.shape[1], device=v.device, dtype=v.dtype)], 1)
            grown[k] = {"parent_cols": p.shape[1], "new_cols": v.shape[1] - p.shape[1], "init": "zero"}
        else:
            raise SystemExit(f"cannot migrate {k}: parent {tuple(p.shape)} -> new {tuple(v.shape)}")
    for k in sd:   # graph buffers (patches, arcs, static) must be the parent's exactly
        if k.startswith("g.") and not torch.equal(new[k].cpu(), sd[k].cpu().to(new[k].dtype)):
            raise SystemExit(f"graph buffer {k} differs from the parent's: different road graph")
    model.load_state_dict(new)
    return {"copied": len(copied), "grown": grown}


def param_groups(model, rc: RetrainCfg) -> list[dict]:
    fast, slow = [], []
    for n, p in model.named_parameters():
        p.requires_grad_(True)
        (fast if n.startswith(FAST) else slow).append(p)
    return [{"params": slow, "lr": rc.lr_backbone, "name": "backbone"}, {"params": fast, "lr": rc.lr_event, "name": "event_horizon"}]


# ---------------------------------------------------------------- objective

def hgroup_huber(pred, target, mask, groups, delta: float = 1.0) -> torch.Tensor:
    """Masked Huber [B,H,N]: mean over valid roads per horizon, equal horizons inside a group, groups weighted;
    groups without labels drop out (weights renormalised). Empty = differentiable zero."""
    pred = pred.float()
    tgt = torch.where(mask, target, torch.zeros_like(target)).float()
    l = F.huber_loss(pred, tgt, reduction="none", delta=delta) * mask
    n = mask.sum(dim=(0, 2)).float()
    per_h = l.sum(dim=(0, 2)) / n.clamp(min=1)
    tot, wsum = pred.sum() * 0.0, 0.0
    for a, b, w in groups:
        has = n[a:b] > 0
        if has.any():
            tot = tot + w * per_h[a:b][has].mean()
            wsum += w
    return tot / wsum if wsum else tot


def hgroup_mean(l: torch.Tensor, mask: torch.Tensor, groups) -> torch.Tensor:
    """Per-cell loss l [B,H,N] -> masked mean per horizon, equal horizons inside a group, weighted groups."""
    l = l.float() * mask
    n = mask.sum(dim=(0, 2)).float()
    per_h = l.sum(dim=(0, 2)) / n.clamp(min=1)
    tot, wsum = l.sum() * 0.0, 0.0
    for a, b_, w in groups:
        has = n[a:b_] > 0
        if has.any():
            tot = tot + w * per_h[a:b_][has].mean()
            wsum += w
    return tot / wsum if wsum else tot


def jam_labels(b: dict, thr: float, tol: int) -> torch.Tensor:
    """[B,H,N] float jam label from the target z (congestion = 1 - exp(-z) >= thr) on valid cells; with tol > 0,
    a jam anywhere within +-tol valid target buckets."""
    y = ((b["target"] >= float(np.log(1.0 / (1.0 - thr)))) & b["mask"]).float()
    if tol > 0:
        y = F.max_pool1d(y.permute(0, 2, 1).reshape(-1, 1, y.shape[1]), 2 * tol + 1, 1, tol) \
            .reshape(y.shape[0], y.shape[2], y.shape[1]).permute(0, 2, 1)
    return y


def objective(pred, b, mk, rc: RetrainCfg, delta: float, thr: float = 0.5, w_window: float = 1.0
              ) -> tuple[torch.Tensor, dict]:
    """pred: z [B,H,N] or the model's aux dict. Per stratum k: w_k (Huber_z + jam_weight BCE + quantile_weight
    pinball); all horizon-grouped; multiplied by the window weight (attendance)."""
    out = pred if isinstance(pred, dict) else {"z": pred}
    z = out["z"]
    comps = {k: hgroup_huber(z, b["target"], mk[k], rc.horizon_groups, delta) for k in rc.weights}
    info = {k: float(v) for k, v in comps.items()}
    total = sum(rc.weights[k] * v for k, v in comps.items())
    if rc.jam_weight and "jam_logit" in out:
        y = jam_labels(b, thr, rc.jam_tolerance)
        pw = torch.tensor(rc.jam_pos_weight, device=z.device)
        bce = F.binary_cross_entropy_with_logits(out["jam_logit"].float(), y, pos_weight=pw, reduction="none")
        for k in rc.weights:
            v = hgroup_mean(bce, mk[k], rc.horizon_groups)
            info[f"jam_{k}"] = float(v)
            total = total + rc.weights[k] * rc.jam_weight * v
    if rc.quantile_weight and "z_q" in out:
        qs = torch.tensor(rc_quantiles(out), device=z.device)
        e = b["target"][..., None] - out["z_q"].float()                       # [B,H,N,Q]
        pin = torch.maximum(qs * e, (qs - 1) * e).mean(-1)
        for k in rc.weights:
            v = hgroup_mean(pin, mk[k], rc.horizon_groups)
            info[f"q_{k}"] = float(v)
            total = total + rc.weights[k] * rc.quantile_weight * v
    return total * w_window, info


def rc_quantiles(out: dict) -> list[float]:
    return out.get("_quantiles", [0.1, 0.9])


def forward_aux(model, b: dict, amp: bool) -> dict:
    dev = b["hist"].device.type
    with torch.autocast(device_type=dev, dtype=torch.bfloat16, enabled=amp and dev == "cuda"):
        out = model(b["hist"], b["time_hist"], b["time_fut"], b["fut_base"], b.get("event_feats"),
                    b.get("pair_road"), aux=True)
    out = {k: v.float() for k, v in out.items()}
    out["_quantiles"] = model.quantiles
    return out


def attendance_weights(cfg, index: pd.DataFrame) -> np.ndarray:
    """Per window: event runs exp(0.5 (log att - mean log att over event families)) clipped to [0.5, 2]; controls
    1. Attendance = the family's event attendance from scenarios.json (loss weight only, never a model input)."""
    sc = read_json(cfg.batch_dir / "scenarios.json")
    att = {f["family_id"]: float(f["event"].get("attendance") or f["event"].get("attendance_assumed") or np.nan)
           for f in sc["families"]}
    la = np.log(np.array([att.get(f, np.nan) for f in index.family_id]))
    ev = index.with_event.to_numpy()
    mu = np.nanmean(la[ev])
    w = np.where(ev, np.clip(np.exp(0.5 * (la - mu)), 0.5, 2.0), 1.0)
    return np.nan_to_num(w, nan=1.0)


def sampling_targets(rc: RetrainCfg) -> tuple:
    bands = [f"{s}_{lo}_{hi}" for s in ("start", "end") for lo, hi in zip(rc.lead_bands_min[:-1], rc.lead_bands_min[1:])]
    return tuple((c, (1 - rc.other_share) / len(bands)) for c in bands) + (("other", rc.other_share),)


# ---------------------------------------------------------------- data

def _index(cfg, data, rc: RetrainCfg, counts: bool) -> tuple[pd.DataFrame, dict]:
    index, audit = ew.build_index(cfg, data, counts=counts, pre_s=max(rc.lead_bands_min) * 60,
                                  lead_bands_min=rc.lead_bands_min)
    index["sample_cat"] = index.lead_cat
    return index, audit


class Prefetch:
    """Builds upcoming windows (numpy, memory-mapped reads) on worker threads while the GPU runs."""

    def __init__(self, data, rows: pd.DataFrame, order: list[int], k: int):
        self.data, self.rows, self.order = data, rows, order
        self.ex = ThreadPoolExecutor(max(1, k))
        self.q: deque = deque()
        self.it = iter(order)
        for _ in range(max(1, k) * 2):
            self._push()

    def _push(self):
        i = next(self.it, None)
        if i is not None:
            r = self.rows.loc[i]
            self.q.append((r, self.ex.submit(self.data.window, r)))

    def __iter__(self):
        while self.q:
            r, f = self.q.popleft()
            self._push()
            yield r, f.result()
        self.ex.shutdown()


@torch.no_grad()
def validate(cfg, data, index, model, obj: Objective, rc: RetrainCfg) -> dict:
    model.eval()
    rows = index[(index.partition == "val") & (index.get("ds", 0) == 0)]
    if rc.val_stride > 1:
        rows = rows.groupby("run_id", group_keys=False).apply(lambda g: g.sort_values("origin").iloc[::rc.val_stride])
    sums: dict = {}
    for r, w in Prefetch(data, rows, list(rows.index), rc.prefetch):
        b = to_batch(w, data.device, data.event_tensors(r.run_id), cfg)
        mk = obj.masks(r, b)
        out = forward_aux(model, b, cfg.train.amp)
        p = out["z"]
        tot, info = objective(out, b, mk, rc, cfg.train.huber_delta, cfg.eval.buildup_congestion)
        info["total"] = float(tot)
        m = b["mask"][:, :6]
        info["first_hour_z_mae"] = float(((p[:, :6] - b["target"][:, :6]).abs() * m).sum() / m.sum().clamp(min=1))
        m = b["mask"]
        info["all_z_mae"] = float(((p - b["target"]).abs() * m).sum() / m.sum().clamp(min=1))
        for k, v in info.items():
            s = sums.setdefault(k, [0.0, 0])
            s[0] += v
            s[1] += 1
    return {k: s[0] / max(s[1], 1) for k, s in sums.items()} | {"windows": len(rows)}


# ---------------------------------------------------------------- training

def preflight(cfg, pck: dict, data, scratch: bool = False) -> list[str]:
    problems = []
    pcfg = cfg_mod.from_dict(pck["config"])
    if not pcfg.model.use_events or not cfg.model.use_events:
        problems.append("parent and new model must both use events")
    base = lambda m: {k: v for k, v in dataclasses.asdict(m).items() if k not in cfg_mod.MODEL_EXTENSIONS}
    if base(pcfg.model) != base(cfg.model) and not scratch:
        problems.append("model section differs from the parent's")
    for k in ("history_steps", "bucket_min", "max_ffill", "network", "split_salt"):
        if getattr(pcfg.data, k) != getattr(cfg.data, k):
            problems.append(f"data.{k} differs from the parent's")
    if cfg.data.horizon_steps <= pcfg.data.horizon_steps:
        problems.append("new horizon must be longer than the parent's")
    schema = {"history": HIST_FEATURES, "time": TIME_FEATURES, "future_base": FUTURE_BASE_FEATURES}
    for k, v in schema.items():
        if pck["feature_schema"].get(k) != v:
            problems.append(f"feature schema '{k}' differs from the parent")
    pe, ne = pck["feature_schema"].get("event_pair"), ev_mod.event_feature_names(cfg)
    if pe != ne[:len(pe or [])] and not scratch:
        problems.append("parent event features are not a prefix of the new model's (migration copies by position)")
    g = data.graph
    if list(map(str, g.model_ids)) != pck["model_ids"]:
        problems.append("ordered road ids differ from the parent")
    elif not (np.array_equal(g.patch_idx, pck["patch_idx"]) and np.array_equal(g.road_patch, pck["road_patch"])
              and np.array_equal(np.stack([g.src, g.dst]), pck["arcs"])):
        problems.append("patches / connections differ from the parent")
    man = read_json(cfg.dataset_dir / "manifest.json")
    if man["network"]["version"] != pck["network_version"]:
        problems.append("network version differs from the parent")
    sp = read_json(cfg.dataset_dir / "splits.json")
    psp = cfg.path(cfg.data.out_root) / "datasets" / pcfg.data.dataset_id / "splits.json"
    if psp.exists():
        old = read_json(psp)
        for part in ("val", "test"):
            if sorted(sp[part]) != sorted(old[part]):
                problems.append(f"{part} event groups {sp[part]} differ from the parent's {old[part]}")
    else:
        problems.append(f"parent splits not found at {psp}: cannot verify the event-group split")
    return problems


def retrain(cfg, parent: str, resume: bool = False, max_epochs: int | None = None, log=None,
            stop_after_epochs: int | None = None) -> dict:
    log = log or (lambda m: print(m, flush=True))
    rc = retrain_cfg(cfg)
    if max_epochs:
        rc.max_epochs = max_epochs
    dev = pick_device(cfg)
    rng = seed_all(rc.seed)
    ppath = cfg.path(parent)
    pck = load_checkpoint(ppath)
    psha = sha256_file(ppath)
    data = Data(cfg, dev)
    problems = preflight(cfg, pck, data, scratch=rc.init == "scratch")
    if problems:
        raise SystemExit("retrain preflight failed:\n- " + "\n- ".join(problems))
    data.norm = pck["norm"]                                   # parent normalisation (provenance recorded)
    model = build_model(cfg, data.graph, pck["norm"], len(ev_mod.EVENT_PAIR_FEATURES)).to(dev)
    mig = migrate(model, pck["model"], rc.new_row_noise, rc.seed) if rc.init == "parent" else \
        {"copied": 0, "grown": {}, "init": "scratch (random, seed %d); parent used for input normalisation only" % rc.seed}
    groups = param_groups(model, rc)
    opt = torch.optim.AdamW(groups, weight_decay=rc.weight_decay)
    index, audit = _index(cfg, data, rc, counts=True)
    index["w_window"] = attendance_weights(cfg, index) if rc.attendance_weight else 1.0
    n_train_fam = index[index.partition == "train"].family_id.nunique()
    steps_per_epoch = max(1, n_train_fam * rc.per_family)
    sched = None
    if rc.lr_schedule == "cosine":
        total, warm = rc.max_epochs * steps_per_epoch, max(1, int(rc.warmup_epochs * steps_per_epoch))
        sched = torch.optim.lr_scheduler.LambdaLR(
            opt, lambda t: min(1.0, (t + 1) / warm) * 0.5 * (1 + np.cos(np.pi * min(t, total) / total)))
    out = cfg.exp_dir
    out.mkdir(parents=True, exist_ok=True)
    index.to_parquet(out / "event_windows.parquet", index=False)
    save_json(out / "event_audit.json", audit)
    obj = Objective(cfg, None, data, index)
    meta = {"parent": str(ppath), "parent_sha256": psha, "parent_horizon": cfg_mod.from_dict(pck["config"]).data.horizon_steps,
            "horizon": cfg.data.horizon_steps, "retrain": dataclasses.asdict(rc), "retrain_digest": rc.digest(),
            "migration": mig, "normalisation": "parent checkpoint norm (dataset norm.json not used)",
            "dataset_manifest_sha256": data.manifest_sha, "splits_sha256": data.splits_sha,
            "windows_sha256": sha256_file(cfg.dataset_dir / "windows.parquet"), "git": _git(),
            "config_path": f"configs/{Path(cfg.source_path).name}" if getattr(cfg, "source_path", "") else None,
            "trainable_params": sum(p.numel() for g_ in groups for p in g_["params"]),
            "total_params": sum(p.numel() for p in model.parameters())}
    state = {"epoch": 0, "best_val": float("inf"), "best_epoch": -1, "bad_epochs": 0, "curves": [],
             "train_seconds": 0.0, "done": False}
    if resume and (out / "last.pt").exists():
        last = load_checkpoint(out / "last.pt")
        r = last["retrain"]
        if r["parent_sha256"] != psha or r["retrain_digest"] != rc.digest() or last["config_hash"] != cfg.hash():
            raise SystemExit("resume refused: parent, config or retrain settings changed")
        model.load_state_dict(last["model"])
        opt.load_state_dict(last["optimizer"])
        if sched is not None and last.get("scheduler"):
            sched.load_state_dict(last["scheduler"])
        state = last["state"]
        set_rng_state(last["rng"], rng)
        log(f"resumed at epoch {state['epoch']}")
    elif (out / "last.pt").exists():
        raise SystemExit(f"{out} already has a run; pass --resume or use a new experiment name")
    save_json(out / "retrain_meta.json", meta | {"config": cfg.to_dict(), "config_hash": cfg.hash()})
    log(f"retrain {cfg.name}: H {meta['parent_horizon']} -> {meta['horizon']}, {mig['copied']} tensors copied, "
        f"{meta['trainable_params']:,} trainable params, {len(index)} windows ({audit.get('event_windows')} event)")
    targets = sampling_targets(rc)
    if dev.type == "cuda":
        torch.cuda.reset_peak_memory_stats()
    calls = 0
    while state["epoch"] < rc.max_epochs and not state["done"]:
        if stop_after_epochs is not None and calls >= stop_after_epochs:
            break
        t0 = time.time()
        model.train()
        sw = index.assign(phase=index.sample_cat)
        plan, realized = ew.epoch_sample(sw, rc.per_family, rng, targets)
        sums: dict = {}
        for r, w in Prefetch(data, index, plan, rc.prefetch):
            b = to_batch(w, dev, data.event_tensors(r.run_id), cfg)
            mk = obj.masks(r, b)
            loss, info = objective(forward_aux(model, b, cfg.train.amp), b, mk, rc, cfg.train.huber_delta,
                                   cfg.eval.buildup_congestion, float(r.w_window))
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), rc.grad_clip)
            opt.step()
            if sched is not None:
                sched.step()
            info["total"] = float(loss)
            for k, v in info.items():
                s = sums.setdefault(k, [0.0, 0])
                s[0] += v
                s[1] += 1
        t_train = time.time() - t0
        v = validate(cfg, data, index, model, obj, rc)
        state["epoch"] += 1
        calls += 1
        dt = time.time() - t0
        state["train_seconds"] += dt
        peak = torch.cuda.max_memory_allocated() / 2**20 if dev.type == "cuda" else float("nan")
        score = v["total"] if rc.select_on == "total" else v["anticipation"] + v.get("jam_anticipation", 0.0)
        improved = score < state["best_val"] - 1e-6
        if improved:
            state.update(best_val=score, best_epoch=state["epoch"], bad_epochs=0)
        else:
            state["bad_epochs"] += 1
        state["done"] = state["bad_epochs"] >= rc.patience
        row = {"epoch": state["epoch"], "steps": len(plan), "train_s": round(t_train, 1), "seconds": round(dt, 1),
               "s_per_step": round(t_train / max(len(plan), 1), 4), "peak_gpu_mb": round(peak, 1),
               **{f"train_{k}": round(s[0] / max(s[1], 1), 6) for k, s in sums.items()},
               **{f"val_{k}": v[k] for k in v}, "sample": json.dumps(realized["phase_share"])}
        state["curves"].append(row)
        payload = checkpoint_payload(cfg, data, model, opt, state, rng)
        payload["retrain"] = meta | {"epoch": state["epoch"], "validation": v}
        if sched is not None:
            payload["scheduler"] = sched.state_dict()
        payload["model_version"] = f"{cfg.name}-{cfg.hash()}-rt{rc.digest()[:8]}"
        torch.save(payload, out / "last.pt")
        if improved:
            torch.save(payload, out / "best.pt")
        log(f"epoch {state['epoch']:>2} train {row['train_total']:.4f} val {v['total']:.4f} (first-hour z-MAE "
            f"{v['first_hour_z_mae']:.4f}, all {v['all_z_mae']:.4f}) {dt:.0f}s ({row['s_per_step']}s/step) "
            f"peak {peak:.0f}MB{' *' if improved else ''}")
        _write_curves(out, state["curves"])
    summary = {"experiment": cfg.name, "best_epoch": state["best_epoch"], "best_val_objective": state["best_val"],
               "epochs_run": state["epoch"], "early_stopped": state["done"], "train_seconds": round(state["train_seconds"], 1),
               "device": str(dev), "gpu": torch.cuda.get_device_name(0) if dev.type == "cuda" else None,
               "peak_gpu_mb": max((r["peak_gpu_mb"] for r in state["curves"]), default=None),
               "parameters": meta["total_params"], "trainable_parameters": meta["trainable_params"],
               "selection": "lowest validation objective (Bearrison), patience "
                            f"{rc.patience}, max {rc.max_epochs} epochs"}
    save_json(out / "train_summary.json", summary)
    return summary


def _write_curves(out: Path, curves: list[dict]) -> None:
    keys = sorted({k for r in curves for k in r})
    with open(out / "curves.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=keys)
        wr.writeheader()
        wr.writerows(curves)


# ---------------------------------------------------------------- evaluation

HORIZON_GROUPS_MIN = ((0, 60, "0-60"), (60, 120, "60-120"), (120, 180, "120-180"), (180, 240, "180-240"),
                      (240, 300, "240-300"))


def evaluate(checkpoint: str, partition: str = "val", log=None, dataset_config: str | None = None,
             tag: str | None = None) -> dict:
    """Candidate vs persistence (repeated to H) vs the parent on its own first-hour horizons, identical windows and
    masks. Cells are keyed by (system, stratum, horizon_min, family|lead category); the report cross-tabulates
    event lead at issue time and target horizon."""
    log = log or (lambda m: print(m, flush=True))
    paths = [cfg_mod.ML_DIR / c if not Path(c).is_absolute() else Path(c) for c in str(checkpoint).split(",")]
    ck = load_checkpoint(paths[0])
    cfg = cfg_mod.from_dict(ck["config"])
    if dataset_config:   # score this checkpoint on another dataset's windows (same network / horizon / model)
        other = cfg_mod.load(dataset_config)
        if other.data.horizon_steps != cfg.data.horizon_steps or other.data.network != cfg.data.network:
            raise SystemExit("dataset config differs in horizon or network")
        cfg.data, cfg.name = other.data, other.name
    rc = RetrainCfg(**ck["retrain"]["retrain"])
    dev = pick_device(cfg)
    data = Data(cfg, dev)
    if list(map(str, data.graph.model_ids)) != ck["model_ids"]:
        raise SystemExit("dataset road order differs from the checkpoint")
    data.norm = ck["norm"]
    data.windows = data.windows[(data.windows.ds == 0) & (data.windows.partition == partition)].reset_index(drop=True)
    index, _ = _index(cfg, data, rc, counts=False)
    model = load_models(paths, data.graph, dev)
    pck = load_checkpoint(ck["retrain"]["parent"])
    pcfg = cfg_mod.from_dict(pck["config"])
    parent = build_model(pcfg, data.graph, pck["norm"], len(ev_mod.EVENT_PAIR_FEATURES)).to(dev)
    parent.load_state_dict(pck["model"])
    parent.eval()
    Hp = pcfg.data.horizon_steps
    acc = ee.StratAcc(cfg.eval.buildup_congestion)
    rows = index[(index.partition == partition) & (index.get("ds", 0) == 0)]   # main dataset windows only
    nbs: dict = {}
    t0 = time.time()
    g = data.graph
    for k, (r, w) in enumerate(Prefetch(data, rows, list(rows.index), rc.prefetch)):
        if r.event_run not in nbs:
            nbs[r.event_run] = ew.neighbourhoods(data.run(r.event_run).context, g, cfg)
        st = ee.window_strata(cfg, data, r, nbs[r.event_run], w)
        tgt = {"tt": w.tt, "speed": w.speed, "cong": w.cong, "z": np.nan_to_num(w.target_z)}
        key = f"{r.family_id}|{r.lead_cat}"
        b = to_batch(w, dev, data.event_tensors(r.run_id), cfg)
        with torch.no_grad():
            zc = forward(model, b, cfg.train.amp)[0].float().cpu().numpy()
            bp = dict(b, time_fut=b["time_fut"][:, :Hp], fut_base=b["fut_base"][:, :Hp],   # parent: its base features
                      event_feats=b["event_feats"][:, :1 + Hp, :, :len(ev_mod.event_feature_names(pcfg))])
            zp = forward(parent, bp, cfg.train.amp)[0].float().cpu().numpy()
        zpers = np.broadcast_to(persistence_z(w.zf_last), w.target_mask.shape)
        acc.add("candidate", key, derive(zc, g), tgt, st)
        acc.add("persistence", key, derive(zpers, g), tgt, st)
        acc.add("parent", key, derive(zp, g), {k_: v[:Hp] for k_, v in tgt.items()}, {s: m[:Hp] for s, m in st.items()})
        if k % 200 == 0:
            log(f"  eval {partition}: {k}/{len(rows)} windows")
    cells = acc.frame()
    cells[["family_id", "lead_cat"]] = cells.family_id.str.split("|", n=1, expand=True)
    od = cfg.exp_dir / (f"eval_retrain_{partition}" + (f"_{tag}" if tag else ""))
    od.mkdir(parents=True, exist_ok=True)
    cells.to_parquet(od / "cells.parquet", index=False)
    fh = cells[cells.horizon_min <= 60]
    head = {s: ee.headline(fh, s) for s in ("candidate", "parent", "persistence")}
    rel = lambda k: ((head["candidate"][k] - head["parent"][k]) / head["parent"][k]
                     if head["candidate"].get(k) and head["parent"].get(k) else None)
    gr = rc.guardrails
    guard = {"first_hour_citywide_rel": rel("citywide_tt_mae"), "first_hour_control_rel": rel("control_tt_mae"),
             "first_hour_severe_rel": rel("severe_tt_mae")}
    guard["first_hour_safe"] = all(v is not None for v in guard.values()) and \
        guard["first_hour_citywide_rel"] <= gr["first_hour_citywide_max_rel"] and \
        guard["first_hour_control_rel"] <= gr["first_hour_control_max_rel"] and \
        guard["first_hour_severe_rel"] <= gr["first_hour_severe_max_rel"]
    long = cells[cells.horizon_min > 60]
    head_long = {s: ee.headline(long, s) for s in ("candidate", "persistence")}
    beats = {k: (head_long["candidate"].get(k) is not None and head_long["persistence"].get(k) is not None
                 and head_long["candidate"][k] < head_long["persistence"][k])
             for k in ("citywide_tt_mae", "event_near_tt_mae", "antic_tt_mae")}
    res = {"partition": partition, "windows": len(rows), "seconds": round(time.time() - t0, 1),
           "first_hour": head, "guard": guard, "hours_2_3": head_long, "beats_persistence_hours_2_3": beats,
           "note": "parent = original 60-min checkpoint on its own 6 horizons of the same windows (never extended)"}
    save_json(od / "summary.json", res)
    return res


def tables(cells: pd.DataFrame) -> dict:
    """Report tables: stratum x system; horizon group x system; lead category x horizon group (antic, event_near)."""
    c = cells.copy()
    c["hgroup"] = pd.cut(c.horizon_min, [0, 60, 120, 180, 240, 300], labels=["0-60", "60-120", "120-180", "180-240", "240-300"])
    out = {"strata_first_hour": ee.summarize(c[c.horizon_min <= 60], ["stratum", "system"]),
           "strata_hours_2_3": ee.summarize(c[c.horizon_min > 60], ["stratum", "system"]),
           "by_horizon": ee.summarize(c[c.stratum.isin(["all", "event_near", "antic", "severe"])],
                                      ["stratum", "horizon_min", "system"])}
    for s in ("antic", "event_near"):
        out[f"lead_x_horizon_{s}"] = ee.summarize(c[c.stratum == s], ["lead_cat", "hgroup", "system"])
    return out


def write_report(exp_dir, path, timings: dict | None = None) -> Path:
    """reports/long_horizon_retraining_h18.md from a finished retrain + evaluate-retrain (val, test)."""
    from .finetune import _md
    exp_dir, path = Path(exp_dir), Path(path)
    meta = read_json(exp_dir / "retrain_meta.json")
    summ = read_json(exp_dir / "train_summary.json")
    cfg = cfg_mod.from_dict(meta["config"])
    cur = pd.read_csv(exp_dir / "curves.csv")
    audit = read_json(exp_dir / "event_audit.json")
    idx = pd.read_parquet(exp_dir / "event_windows.parquet")
    man = read_json(cfg.dataset_dir / "manifest.json")
    H = meta["horizon"]
    cp = meta.get("config_path") or "configs/event_patch_v4_h18.yaml"
    L = [f"# Long-horizon retraining: {H * cfg.data.bucket_min} min ({H} buckets)", "",
         "> **Synthetic.** SUMO scenarios on real SF roads/permits; demand and attendance are assumptions. Road/bucket "
         "labels overlap and are not independent trials.", "",
         "## Identity", "",
         f"- Experiment `{cfg.name}`; parent `{meta['parent']}` (sha256 `{meta['parent_sha256'][:16]}…`, H="
         f"{meta['parent_horizon']}); migration: {meta['migration']['copied']} tensors copied exactly, grown "
         f"`{json.dumps(meta['migration']['grown'])}`; all {meta['trainable_params']:,} parameters trained.",
         f"- Dataset `{cfg.data.dataset_id}` from batch `{cfg.data.batch}` (manifest `{meta['dataset_manifest_sha256'][:12]}…`, "
         f"windows `{meta['windows_sha256'][:12]}…`); split {json.dumps({p: man['split'][p] for p in ('train', 'val', 'test')})}; "
         f"{len(man['selected_runs'])} runs selected, {len(man['excluded_runs'])} excluded.",
         f"- Normalisation: {meta['normalisation']}. Retrain settings digest `{meta['retrain_digest']}`: "
         f"`{json.dumps(meta['retrain'])}`", f"- Code: `{json.dumps(meta['git'])[:300]}`", ""]
    if man["excluded_runs"]:
        ex = pd.DataFrame(man["excluded_runs"])
        L += ["Excluded runs by event group: " + ", ".join(f"{g} {n}" for g, n in ex.family_group.value_counts().items()), ""]
    wc = idx.groupby(["partition", "lead_cat"]).size().unstack(0).fillna(0).astype(int).reset_index()
    L += ["## Window coverage (issue time relative to the focal event's public start/end)", "", _md(wc), "",
          "No run crosses midnight (user decision): boundaries late in the day have truncated or no long-lead windows "
          "(Portola's 23:00 end has none).", ""]
    L += ["## Training", "",
          f"- {summ['epochs_run']} epochs ({'early stop' if summ['early_stopped'] else 'epoch cap'}), selected epoch "
          f"{summ['best_epoch']}, {summ['train_seconds']:.0f} s on {summ['gpu']}, peak GPU {summ['peak_gpu_mb']} MB.",
          f"- Selection: {summ['selection']}.", ""]
    keep = [c for c in ["epoch", "steps", "s_per_step", "train_total", "train_global", "train_event_near",
                        "train_anticipation", "val_total", "val_first_hour_z_mae", "val_all_z_mae", "seconds"] if c in cur]
    L += [_md(cur[keep]), ""]
    if timings:
        L += ["Measured wall times: " + ", ".join(f"{k} {v}" for k, v in timings.items()), ""]
    for part, label in (("val", "Bearrison validation"), ("test", "Portola held-out test (reused)")):
        d = exp_dir / f"eval_retrain_{part}"
        if not (d / "summary.json").exists():
            continue
        s = read_json(d / "summary.json")
        t = tables(pd.read_parquet(d / "cells.parquet"))
        cols = ["labels", "tt_mae_s", "tt_wape", "speed_mae_mph", "cong_mae", "positives", "precision", "recall", "f1"]
        L += [f"## {label}", "", f"First-hour guardrail vs the parent (same windows, its own 6 horizons): "
              f"`{json.dumps(s['guard'])}`", "", "First hour (horizons 10-60 min):", "",
              _md(t["strata_first_hour"][["stratum", "system"] + cols]), "",
              "Hours 2-3 (horizons 70-180 min; the parent has no forecast here):", "",
              _md(t["strata_hours_2_3"][["stratum", "system"] + cols]), "",
              "By target horizon (selected):", "",
              _md(t["by_horizon"][t["by_horizon"].horizon_min.isin(cfg.eval.headline_horizons)]
                  [["stratum", "horizon_min", "system", "labels", "tt_mae_s", "precision", "recall", "f1"]]), "",
              "Anticipation (clear near roads, issued up to 3 h before start/end) by event lead at issue x target "
              "horizon; a +180 min target issued 10 min before opening is not a 3-hour warning:", "",
              _md(t["lead_x_horizon_antic"].dropna(subset=["labels"])[["lead_cat", "hgroup", "system", "labels",
                                                                        "tt_mae_s", "positives", "precision", "recall", "f1"]]), ""]
    L += ["## Limitations", "",
          "- No matched no-event model was trained (user decision), so the event branch's own contribution at long "
          "horizons is not isolated; comparisons are vs persistence and the 60-min parent's first hour.",
          "- One validation (Bearrison) and one reused test group (Portola, before-start side only).",
          "- Hidden demand factors (realised attendance, arrival curves) are not model inputs; long-horizon error has "
          "an irreducible floor from them.",
          "- Paired event-minus-control impact metrics were not computed in this pass.", "",
          "## Reproduce", "", "```",
          f"python -m eventsim.citywide_batch plan --batch {cfg.data.batch} ...   # exact arguments: the batch's scenarios.json",
          f"python -m forecast audit --config {cp}",
          f"python -m forecast prepare --config {cp} --workers 24",
          f"python -m forecast retrain --config {cp} --parent {meta['parent']}",
          f"python -m forecast evaluate-retrain --checkpoint {exp_dir.name}/best.pt --partition test", "```", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")
    return path


def compare_report(exp_dirs: dict, path, title: str, notes: list[str] | None = None) -> Path:
    """One table per partition across experiments scored on identical windows: first-hour guardrail vs v2, hours 2-3
    vs persistence, and (if present) jam-wrapper / jam-head build-up metrics. exp_dirs: label -> (experiment dir,
    eval suffix), e.g. {"v4": (v5_dir, "_v4"), "v5": (v5_dir, "")}."""
    from .finetune import _md
    L = [f"# {title}", "", "> **Synthetic** SUMO data. All systems scored on the same windows of the same dataset; "
         "thresholds for jam warnings are chosen on Bearrison (val) only.", ""] + (notes or [])
    for part, label in (("val", "Bearrison (validation)"), ("test", "Portola (held-out test, before-start side)")):
        rows, jam_rows = [], []
        for name, (d, suf) in exp_dirs.items():
            f = Path(d) / f"eval_retrain_{part}{suf}" / "summary.json"
            if not f.exists():
                continue
            s = read_json(f)
            c1, c2 = s["first_hour"]["candidate"], s["hours_2_3"]["candidate"]
            rows.append({"system": name, "1h_city_mae": c1["citywide_tt_mae"], "1h_vs_v2": s["guard"]["first_hour_citywide_rel"],
                         "guard_ok": s["guard"]["first_hour_safe"], "2-3h_city_mae": c2["citywide_tt_mae"],
                         "2-3h_near_mae": c2["event_near_tt_mae"], "2-3h_antic_mae": c2["antic_tt_mae"],
                         "2-3h_antic_recall": c2["antic_recall"], "2-3h_antic_precision": c2["antic_precision"],
                         "persist_2-3h_antic_mae": s["hours_2_3"]["persistence"]["antic_tt_mae"]})
            jf = Path(d) / "jam_wrapper" / f"scores_{part}.csv"
            if not suf and jf.exists():
                js = pd.read_csv(jf)
                a = js[(js.group == "antic") & js.hgroup.isin(["60-120", "120-180"])]
                if len(a):
                    wmean = lambda c: float(np.average(a[c], weights=a.positives)) if c in a and a[c].notna().all() else None
                    jam_rows.append({"system": name, "wrapper_recall": wmean("f1thr_recall"),
                                     "wrapper_precision": wmean("f1thr_precision"), "head_recall": wmean("head_recall"),
                                     "head_precision": wmean("head_precision"), "ap_point": wmean("ap_point"),
                                     "ap_head": wmean("ap_head"), "head_tol_recall": wmean("head_tol_recall"),
                                     "head_tol_precision": wmean("head_tol_precision"), "q10_q90_coverage": wmean("q_coverage")})
        if rows:
            L += [f"## {label}", "", "Travel time (MAE in s per segment per bucket; antic = directly observed clear near "
                  "roads, issued up to 3 h before start/end):", "", _md(pd.DataFrame(rows)), ""]
        if jam_rows:
            L += ["Build-up warnings, hours 2-3 (antic cells; `wrapper` = calibrated point forecast, `head` = jam "
                  "head; F1-best thresholds from validation; `tol` = jam within +-20 min):", "", _md(pd.DataFrame(jam_rows)), ""]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")
    return path


def load_models(paths: list, graph, dev):
    """One checkpoint -> its model; several -> an Ensemble (same roads, horizon, event features and norm)."""
    from .model import Ensemble
    models, ref = [], None
    for p in paths:
        ck = load_checkpoint(p)
        c = cfg_mod.from_dict(ck["config"])
        key = (ck["model_ids"] == list(map(str, graph.model_ids)), c.data.horizon_steps, tuple(ev_mod.event_feature_names(c)),
               json.dumps(ck["norm"], sort_keys=True))
        if ref is None:
            ref = key
        elif key != ref:
            raise SystemExit(f"{p}: ensemble members differ in roads / horizon / event features / normalisation")
        m = build_model(c, graph, ck["norm"]).to(dev)
        m.load_state_dict(ck["model"])
        models.append(m.eval())
    return models[0] if len(models) == 1 else Ensemble(models).eval()
