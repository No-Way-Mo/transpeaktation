"""Training (AdamW, early stopping on validation), resumable checkpoints, and pre-training sanity checks.

Checkpoints hold: model + optimizer state, epoch/early-stopping state, python/numpy/torch RNG states, config and
its hash, dataset manifest + splits hashes, road ids and patch/connection mappings (as model buffers + explicit
arrays), normalisation statistics and the feature schema.
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from . import events as ev_mod
from . import graph as graph_mod
from .config import Config, read_json, save_json, sha256_file
from .data import FUTURE_BASE_FEATURES, HIST_FEATURES, TIME_FEATURES, RunArrays, Window, make_window
from .losses import masked_congestion_l1, masked_huber
from .model import build_model

CKPT_VERSION = 1


def pick_device(cfg: Config) -> torch.device:
    if cfg.train.device != "auto":
        return torch.device(cfg.train.device)
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


class Data:
    """Windows of a frozen dataset, served one full-city window at a time (memory-mapped run arrays)."""

    def __init__(self, cfg: Config, device: torch.device):
        self.cfg, self.device = cfg, device
        d = cfg.dataset_dir
        self.graph = graph_mod.load(d / "graph")
        self.norm = read_json(d / "norm.json")
        self.windows = pd.read_parquet(d / "windows.parquet")
        self.manifest_sha = sha256_file(d / "manifest.json")
        self.splits_sha = sha256_file(d / "splits.json")
        self._runs: dict[str, RunArrays] = {}
        self._ev: dict[str, ev_mod.EventTensors] = {}

    def run(self, rid: str) -> RunArrays:
        if rid not in self._runs:
            self._runs[rid] = RunArrays(self.cfg.dataset_dir / "runs" / rid)
        return self._runs[rid]

    def event_tensors(self, rid: str, context: dict | None = None) -> ev_mod.EventTensors:
        if context is not None:
            return ev_mod.build_tensors(context, self.graph, self.cfg, self.att_norm).to_torch(self.device)
        if rid not in self._ev:
            self._ev[rid] = ev_mod.build_tensors(self.run(rid).context, self.graph, self.cfg,
                                                 self.att_norm).to_torch(self.device)
        return self._ev[rid]

    @property
    def att_norm(self):
        return (float(np.log(20_000.0)), 1.5)   # fixed scale for log declared attendance (not fitted on labels)

    def partition(self, p: str) -> pd.DataFrame:
        return self.windows[self.windows.partition == p].reset_index(drop=True)

    def window(self, row) -> Window:
        return make_window(self.cfg, self.run(row.run_id), int(row.origin), self.norm)


def to_batch(w: Window, device, ev: ev_mod.EventTensors | None, cfg: Config) -> dict:
    t = lambda a, dt=torch.float32: torch.as_tensor(np.ascontiguousarray(a), dtype=dt, device=device)[None]
    b = {"hist": t(w.hist), "time_hist": t(w.time_hist), "time_fut": t(w.time_fut), "fut_base": t(w.fut_base),
         "target": t(np.nan_to_num(w.target_z)), "mask": t(w.target_mask, torch.bool)}
    if ev is not None:
        B = cfg.data.bucket_min * 60
        times = torch.as_tensor(np.concatenate([[w.issued_at - B], w.fut_start]), dtype=torch.float64, device=device)
        b["event_feats"] = ev_mod.pair_features(ev, times, B, cfg.events.clip_hours)[None]
        b["pair_road"] = ev.pair_road
    return b


def forward(model, b: dict, amp: bool) -> torch.Tensor:
    dev = b["hist"].device.type
    with torch.autocast(device_type=dev, dtype=torch.bfloat16, enabled=amp and dev == "cuda"):
        return model(b["hist"], b["time_hist"], b["time_fut"], b["fut_base"], b.get("event_feats"),
                     b.get("pair_road")).float()


def loss_fn(cfg: Config, pred, b) -> torch.Tensor:
    l = masked_huber(pred, b["target"], b["mask"], cfg.train.huber_delta)
    if cfg.train.congestion_loss_weight:
        l = l + cfg.train.congestion_loss_weight * masked_congestion_l1(pred, b["target"], b["mask"])
    return l


def epoch_plan(train: pd.DataFrame, per_family: int, rng: np.random.Generator) -> list[int]:
    """Balanced origins: the same number of windows from every training family per epoch (without replacement when
    the family has enough, else with), so long runs do not dominate by producing more windows."""
    idx = []
    for fam, grp in sorted(train.groupby("family_id"), key=lambda kv: kv[0]):
        rows = grp.index.to_numpy()
        idx += list(rng.choice(rows, size=per_family, replace=len(rows) < per_family))
    rng.shuffle(idx)
    return [int(i) for i in idx]


@torch.no_grad()
def val_loss(cfg, model, data: Data, rows: pd.DataFrame) -> dict:
    model.eval()
    ls, zmae = [], []
    for r in rows.itertuples():
        w = data.window(r)
        b = to_batch(w, data.device, data.event_tensors(r.run_id) if cfg.model.use_events else None, cfg)
        p = forward(model, b, cfg.train.amp)
        ls.append(float(masked_huber(p, b["target"], b["mask"], cfg.train.huber_delta)))
        m = b["mask"]
        zmae.append(float(((p - b["target"]).abs() * m).sum() / m.sum().clamp(min=1)))
    return {"loss": float(np.mean(ls)), "z_mae": float(np.mean(zmae))}


def rng_state(rng: np.random.Generator) -> dict:
    st = {"python": random.getstate(), "numpy_global": np.random.get_state(), "sampler": rng.bit_generator.state,
          "torch": torch.get_rng_state()}
    if torch.cuda.is_available():
        st["cuda"] = torch.cuda.get_rng_state_all()
    return st


def set_rng_state(st: dict, rng: np.random.Generator) -> None:
    random.setstate(st["python"])
    np.random.set_state(st["numpy_global"])
    rng.bit_generator.state = st["sampler"]
    torch.set_rng_state(st["torch"])
    if "cuda" in st and torch.cuda.is_available():
        torch.cuda.set_rng_state_all(st["cuda"])


def seed_all(seed: int) -> np.random.Generator:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    return np.random.default_rng(seed)


def checkpoint_payload(cfg, data: Data, model, opt, state: dict, rng) -> dict:
    g = data.graph
    return {"ckpt_version": CKPT_VERSION, "model": model.state_dict(), "optimizer": opt.state_dict(),
            "state": state, "rng": rng_state(rng), "config": cfg.to_dict(), "config_hash": cfg.hash(),
            "dataset_id": cfg.data.dataset_id, "dataset_manifest_sha256": data.manifest_sha,
            "splits_sha256": data.splits_sha, "network_version": read_json(cfg.dataset_dir / "manifest.json")["network"]["version"],
            "model_ids": list(map(str, g.model_ids)), "patch_idx": g.patch_idx, "road_patch": g.road_patch,
            "arcs": np.stack([g.src, g.dst]), "norm": data.norm,
            "feature_schema": {"history": HIST_FEATURES, "time": TIME_FEATURES, "future_base": FUTURE_BASE_FEATURES,
                               "event_pair": ev_mod.EVENT_PAIR_FEATURES, "static": graph_mod.STATIC_FEATURES},
            "model_version": f"{cfg.name}-{cfg.hash()}"}


def load_checkpoint(path) -> dict:
    return torch.load(path, map_location="cpu", weights_only=False)


def train(cfg: Config, resume: bool = False, log=None, stop_after_epochs: int | None = None) -> dict:
    log = log or (lambda m: print(m, flush=True))
    dev = pick_device(cfg)
    rng = seed_all(cfg.train.seed)
    data = Data(cfg, dev)
    model = build_model(cfg, data.graph, data.norm, len(ev_mod.EVENT_PAIR_FEATURES)).to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.train.lr, weight_decay=cfg.train.weight_decay)
    out = cfg.exp_dir
    out.mkdir(parents=True, exist_ok=True)
    state = {"epoch": 0, "best_val": float("inf"), "best_epoch": -1, "bad_epochs": 0, "curves": [],
             "train_seconds": 0.0, "done": False}
    if resume and (out / "last.pt").exists():
        ck = load_checkpoint(out / "last.pt")
        if ck["config_hash"] != cfg.hash() or ck["dataset_manifest_sha256"] != data.manifest_sha \
                or ck["splits_sha256"] != data.splits_sha:
            raise SystemExit("resume refused: config, dataset or split changed since the checkpoint")
        model.load_state_dict(ck["model"])
        opt.load_state_dict(ck["optimizer"])
        state = ck["state"]
        set_rng_state(ck["rng"], rng)
        log(f"resumed at epoch {state['epoch']}")
    elif (out / "last.pt").exists() and not resume:
        raise SystemExit(f"{out} already has a run; pass --resume or use a new experiment name")
    save_json(out / "config.json", {**cfg.to_dict(), "config_hash": cfg.hash(), "source": cfg.source_path})
    tr, va = data.partition("train"), data.partition("val")
    if dev.type == "cuda":
        torch.cuda.reset_peak_memory_stats()
    epochs_this_call = 0
    while state["epoch"] < cfg.train.max_epochs and not state["done"]:
        if stop_after_epochs is not None and epochs_this_call >= stop_after_epochs:
            break   # simulated interruption (tests); last.pt is resumable
        t0 = time.time()
        model.train()
        losses = []
        for i in epoch_plan(tr, cfg.train.origins_per_family, rng):
            r = tr.loc[i]
            b = to_batch(data.window(r), dev, data.event_tensors(r.run_id) if cfg.model.use_events else None, cfg)
            loss = loss_fn(cfg, forward(model, b, cfg.train.amp), b)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.train.grad_clip)
            opt.step()
            losses.append(float(loss))
        v = val_loss(cfg, model, data, va)
        state["epoch"] += 1
        epochs_this_call += 1
        dt = time.time() - t0
        state["train_seconds"] += dt
        peak = torch.cuda.max_memory_allocated() / 2**20 if dev.type == "cuda" else float("nan")
        row = {"epoch": state["epoch"], "train_loss": float(np.mean(losses)), "val_loss": v["loss"],
               "val_z_mae": v["z_mae"], "seconds": round(dt, 1), "peak_gpu_mb": round(peak, 1)}
        state["curves"].append(row)
        improved = v["loss"] < state["best_val"] - 1e-6
        if improved:
            state["best_val"], state["best_epoch"], state["bad_epochs"] = v["loss"], state["epoch"], 0
        else:
            state["bad_epochs"] += 1
        state["done"] = state["bad_epochs"] >= cfg.train.patience
        payload = checkpoint_payload(cfg, data, model, opt, state, rng)
        if improved:
            torch.save(payload, out / "best.pt")
        torch.save(payload, out / "last.pt")
        log(f"epoch {state['epoch']:>2} train {row['train_loss']:.4f} val {v['loss']:.4f} (z-MAE {v['z_mae']:.4f}) "
            f"{dt:.0f}s peak {peak:.0f}MB{' *' if improved else ''}")
    with open(out / "curves.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(state["curves"][0]))
        w.writeheader()
        w.writerows(state["curves"])
    summary = {"experiment": cfg.name, "best_epoch": state["best_epoch"], "best_val_loss": state["best_val"],
               "epochs_run": state["epoch"], "early_stopped": state["done"], "train_seconds": round(state["train_seconds"], 1),
               "device": str(dev), "gpu": torch.cuda.get_device_name(0) if dev.type == "cuda" else None,
               "peak_gpu_mb": max(r["peak_gpu_mb"] for r in state["curves"]),
               "parameters": sum(p.numel() for p in model.parameters())}
    save_json(out / "train_summary.json", summary)
    return summary


# ---------------------------------------------------------------- sanity checks before full training

def sanity(cfg: Config) -> dict:
    """(1) forward/backward on one full-city window, (2) deliberately overfit that single window, (3) the event branch
    gets gradients, (4) moving a future scheduled event start changes later-horizon predictions, (5) profile."""
    dev = pick_device(cfg)
    seed_all(cfg.train.seed)
    data = Data(cfg, dev)
    res = {"device": str(dev)}
    tr = data.partition("train")
    r = tr[tr.with_event].iloc[len(tr[tr.with_event]) // 2]
    ctx = data.run(r.run_id).context
    ev = data.event_tensors(r.run_id)
    res["window"] = {"run_id": r.run_id, "issued_at": pd.Timestamp(r.issued_at, unit="s", tz="UTC").isoformat(),
                     "event_pairs": ev.n_pairs, "cases": len(ctx["cases"])}
    cfg.model.dropout = 0.0
    model = build_model(cfg, data.graph, data.norm, len(ev_mod.EVENT_PAIR_FEATURES)).to(dev)
    w = data.window(r)
    b = to_batch(w, dev, ev, cfg)
    res["valid_targets"] = int(b["mask"].sum())
    # (1)+(5) profile one full-city training step and one inference pass
    for amp in (False, True) if dev.type == "cuda" else (False,):
        if dev.type == "cuda":
            torch.cuda.synchronize(); torch.cuda.reset_peak_memory_stats()
        t0 = time.time()
        loss = loss_fn(cfg, forward(model, b, amp), b)
        loss.backward()
        if dev.type == "cuda":
            torch.cuda.synchronize()
        res[f"train_step_{'bf16' if amp else 'fp32'}"] = {
            "seconds": round(time.time() - t0, 3), "loss": float(loss), "finite": bool(torch.isfinite(loss)),
            "peak_gpu_mb": round(torch.cuda.max_memory_allocated() / 2**20, 1) if dev.type == "cuda" else None}
        model.zero_grad(set_to_none=True)
    # (3) gradients reach the event branch (zero-init heads get gradient even though their output is 0 at init)
    loss = loss_fn(cfg, forward(model, b, False), b)
    loss.backward()
    gn = {n: float(p.grad.norm()) for n, p in model.named_parameters() if n.startswith("events.") and p.grad is not None}
    res["event_grad_norms"] = {k: round(v, 6) for k, v in gn.items() if k.endswith("weight")}
    res["event_branch_receives_gradients"] = bool(any(v > 0 for k, v in gn.items() if "film" in k or "dec_" in k))
    model.zero_grad(set_to_none=True)
    # (2) deliberately overfit a tiny batch: 512 labels of this window, no dropout, fp32
    g = torch.Generator(device="cpu").manual_seed(0)
    valid = torch.nonzero(b["mask"].flatten().cpu()).squeeze(1)
    keep = valid[torch.randperm(len(valid), generator=g)[:512]]
    tiny = dict(b, mask=torch.zeros_like(b["mask"]).flatten().index_fill_(0, keep.to(dev), True).view_as(b["mask"]))
    opt = torch.optim.AdamW(model.parameters(), lr=3e-3, weight_decay=0.0)
    curve = []
    model.train()
    for step in range(400):
        loss = masked_huber(forward(model, tiny, False), tiny["target"], tiny["mask"], cfg.train.huber_delta)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
        if step % 50 == 0 or step == 399:
            curve.append((step, round(float(loss), 6)))
    res["overfit_tiny_512_labels"] = curve
    res["overfit_ratio"] = round(curve[-1][1] / curve[0][1], 5)
    # (4) schedule sensitivity: a window whose focal event starts inside the forecast hour; move the start (and end)
    # 3 h later so it falls outside the horizon. Only scheduled context changes; traffic inputs are identical.
    cand = tr[tr.with_event].copy()
    starts = {rid: next(pd.Timestamp(c["public_start"]).timestamp() for c in data.run(rid).context["cases"]
                        if c["kind"] == "public_event") for rid in cand.run_id.unique()}
    lead = cand.run_id.map(starts) - cand.issued_at
    cand = cand[(lead > 0) & (lead <= 3600)]
    if len(cand):
        r2 = cand.iloc[0]
        w2 = data.window(r2)
        ctx2 = data.run(r2.run_id).context
        moved = json.loads(json.dumps(ctx2))
        for c in moved["cases"]:
            if c["kind"] == "public_event":
                for k in ("public_start", "public_end"):
                    c[k] = (pd.Timestamp(c[k]) + pd.Timedelta(hours=3)).isoformat()
        from .events import focal_footprint
        fp = focal_footprint(ctx2, data.graph)
        from scipy.spatial import cKDTree
        near = torch.as_tensor(cKDTree(data.graph.xy[fp]).query(data.graph.xy)[0] <= 1000, device=dev)
        model.eval()
        with torch.no_grad():
            p0 = forward(model, to_batch(w2, dev, data.event_tensors(r2.run_id), cfg), False)
            p1 = forward(model, to_batch(w2, dev, data.event_tensors(r2.run_id, context=moved), cfg), False)
            d = (p1 - p0).abs()[0]
        res["schedule_shift"] = {
            "run_id": r2.run_id, "issued_at": pd.Timestamp(r2.issued_at, unit="s", tz="UTC").isoformat(),
            "event_start_lead_min": float(lead.loc[r2.name] / 60), "shift": "+3 h (start moved beyond the horizon)",
            "mean_abs_dz_near_by_horizon": [round(float(x), 6) for x in d[:, near].mean(-1)],
            "mean_abs_dz_far_by_horizon": [round(float(x), 6) for x in d[:, ~near].mean(-1)],
            "note": "after the tiny overfit only; trained-model counterfactuals are in the evaluation report"}
    # inference latency
    with torch.no_grad():
        if dev.type == "cuda":
            torch.cuda.synchronize(); torch.cuda.reset_peak_memory_stats()
        t0 = time.time()
        for _ in range(5):
            forward(model, to_batch(w, dev, ev, cfg), cfg.train.amp)
        if dev.type == "cuda":
            torch.cuda.synchronize()
        res["inference_seconds_per_city_window"] = round((time.time() - t0) / 5, 4)
        res["inference_peak_gpu_mb"] = round(torch.cuda.max_memory_allocated() / 2**20, 1) if dev.type == "cuda" else None
    res["parameters"] = sum(p.numel() for p in model.parameters())
    save_json(cfg.path(cfg.data.out_root) / "sanity" / f"{cfg.name}.json", res)
    return res
