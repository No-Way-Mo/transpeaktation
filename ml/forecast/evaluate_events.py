"""Event-aware evaluation (EVENT_AWARENESS_FINETUNING_PLAN.md §9): every system on identical masks and horizons.

Strata (masks on valid labels, `target_mask`):
    all, control_runs, event_runs, event_near, event_far (> context radius), severe (target congestion >= 0.5),
    antic_pre_start / antic_pre_end / antic (primary: event run, pre-boundary window, directly observed clear near
    road at issue time), antic_strict (clear in the last TWO buckets), near_missing_history (near roads without a
    real observation at issue time; reported separately, never in the headline)
Classification at the fixed congestion threshold (eval.buildup_congestion) is reported for every stratum; in the
anticipation strata a positive is a clear road that becomes congested (a regressed score, not a probability).
Paired impact: for matched event/control windows, predicted vs observed (event - control) difference on their common
valid near roads, in z and in travel-time seconds.

Windows overlap and roads are correlated: pooled counts are not independent trials. Family-level summaries are
reported beside pooled numbers; the event group is the unit of generalisation.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import torch

from . import event_windows as ew
from .config import Config
from .data import persistence_z
from .evaluate import derive
from .train import forward, to_batch

STRATA = ("all", "control_runs", "event_runs", "event_near", "event_far", "severe", "antic_pre_start",
          "antic_pre_end", "antic", "antic_strict", "near_missing_history")


def window_strata(cfg: Config, data, row, nb: ew.Neighbourhoods, w) -> dict:
    """Label masks [H, N] of one window for every stratum (future labels only define masks)."""
    a = data.run(row.run_id)
    o = int(row.origin)
    m = w.target_mask
    H = m.shape[0]
    empty = np.zeros_like(m)
    ev = bool(row.with_event)
    sev = m & (np.nan_to_num(w.cong, nan=0.0) >= cfg.eval.buildup_congestion)
    out = {"all": m, "control_runs": m if not ev else empty, "event_runs": m if ev else empty, "severe": sev}
    if ev:
        near, far = nb.near[None], nb.far[None]
        pre = bool(row.pre_start) or bool(row.pre_end)
        c1 = (ew.clear_roads(a, o) & nb.near)[None]
        c2 = (ew.clear_roads(a, o, strict=True) & nb.near)[None]
        out.update(event_near=m & near, event_far=m & far,
                   antic_pre_start=m & c1 if row.pre_start else empty,
                   antic_pre_end=m & c1 if row.pre_end else empty,
                   antic=m & c1 if pre else empty, antic_strict=m & c2 if pre else empty,
                   near_missing_history=m & near & ew.missing_history(a, o)[None])
    else:
        out.update({k: empty for k in STRATA if k not in out})
    return out


class StratAcc:
    """Sums per (system, stratum, horizon, family): absolute errors and threshold confusion counts."""

    def __init__(self, thr: float):
        self.thr = thr
        self.rows: dict = {}

    def add(self, system: str, family: str, pred: dict, tgt: dict, strata: dict) -> None:
        pc = pred["cong"] >= self.thr
        tc = np.nan_to_num(tgt["cong"], nan=0.0) >= self.thr
        err = {k: np.abs(pred[k] - tgt[k]) for k in ("tt", "speed", "cong", "z")}
        H = pc.shape[0]
        for s, mk in strata.items():
            if not mk.any():
                continue
            for h in range(H):
                c = mk[h]
                n = int(c.sum())
                if not n:
                    continue
                key = (system, s, 10 * (h + 1), family)
                r = self.rows.setdefault(key, np.zeros(10))
                r += [n, err["tt"][h][c].sum(), err["speed"][h][c].sum(), err["cong"][h][c].sum(), err["z"][h][c].sum(),
                      tgt["tt"][h][c].sum(), (pc[h] & tc[h] & c).sum(), (pc[h] & ~tc[h] & c).sum(),
                      (~pc[h] & tc[h] & c).sum(), (~pc[h] & ~tc[h] & c).sum()]

    def frame(self) -> pd.DataFrame:
        cols = ["n", "tt_ae", "speed_ae", "cong_ae", "z_ae", "tt_true", "tp", "fp", "fn", "tn"]
        if not self.rows:
            return pd.DataFrame(columns=["system", "stratum", "horizon_min", "family_id"] + cols)
        idx = pd.MultiIndex.from_tuples(list(self.rows), names=["system", "stratum", "horizon_min", "family_id"])
        return pd.DataFrame(np.array(list(self.rows.values())), index=idx, columns=cols).reset_index()


def summarize(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    g = df.groupby(by, dropna=False)[["n", "tt_ae", "speed_ae", "cong_ae", "z_ae", "tt_true", "tp", "fp", "fn", "tn"]].sum()
    out = pd.DataFrame({"labels": g.n, "tt_mae_s": g.tt_ae / g.n, "speed_mae_mph": g.speed_ae / g.n,
                        "cong_mae": g.cong_ae / g.n, "z_mae": g.z_ae / g.n, "tt_wape": g.tt_ae / g.tt_true,
                        "positives": g.tp + g.fn})
    p = g.tp / (g.tp + g.fp).replace(0, np.nan)
    r = g.tp / (g.tp + g.fn).replace(0, np.nan)
    out["precision"], out["recall"], out["f1"] = p, r, 2 * p * r / (p + r)
    return out.reset_index()


def headline(df: pd.DataFrame, system: str) -> dict:
    """Selection metrics of one system (pooled over horizons and families)."""
    s = summarize(df[df.system == system], ["stratum"]).set_index("stratum")
    get = lambda st, k: float(s.loc[st, k]) if st in s.index and np.isfinite(s.loc[st, k]) else None
    return {"citywide_tt_mae": get("all", "tt_mae_s"), "control_tt_mae": get("control_runs", "tt_mae_s"),
            "severe_tt_mae": get("severe", "tt_mae_s"), "event_near_tt_mae": get("event_near", "tt_mae_s"),
            "antic_tt_mae": get("antic", "tt_mae_s"), "antic_precision": get("antic", "precision"),
            "antic_recall": get("antic", "recall"), "antic_f1": get("antic", "f1"),
            "antic_labels": int(s.loc["antic", "labels"]) if "antic" in s.index else 0,
            "antic_positives": int(s.loc["antic", "positives"]) if "antic" in s.index else 0}


def _predict(model, cfg: Config, data, row, w, use_events: bool):
    b = to_batch(w, data.device, data.event_tensors(row.run_id) if use_events else None, cfg)
    with torch.no_grad():
        return forward(model, b, cfg.train.amp)[0].float().cpu().numpy()


def run(cfg: Config, data, index: pd.DataFrame, partition: str, systems: dict, stride: int = 1,
        persistence: bool = True, log=None) -> dict:
    """systems: name -> (model, use_events). Returns {"cells": frame, "pairs": frame, "seconds": s}."""
    log = log or (lambda m: None)
    t0 = time.time()
    rows = index[index.partition == partition]
    if stride > 1:
        rows = rows.groupby("run_id", group_keys=False).apply(lambda g: g.sort_values("origin").iloc[::stride])
    acc = StratAcc(cfg.eval.buildup_congestion)
    nbs: dict = {}
    pair_sums: dict = {}
    done: set = set()
    g = data.graph
    order = list(rows[rows.with_event].index) + list(rows[~rows.with_event].index)
    for k, i in enumerate(order):
        if i in done:
            continue
        group = [i]
        j = int(index.at[i, "pair"])
        if index.at[i, "with_event"] and j >= 0 and j in rows.index:
            group.append(j)                       # evaluate the matched control together for the paired metric
        preds: dict = {}
        for ii in group:
            r = index.loc[ii]
            if r.event_run not in nbs:
                nbs[r.event_run] = ew.neighbourhoods(data.run(r.event_run).context, g, cfg)
            w = data.window(r)
            st = window_strata(cfg, data, r, nbs[r.event_run], w)
            tgt = {"tt": w.tt, "speed": w.speed, "cong": w.cong, "z": np.nan_to_num(w.target_z)}
            sysz = {name: _predict(m, cfg, data, r, w, ue) for name, (m, ue) in systems.items()}
            if persistence:
                sysz["persistence"] = np.broadcast_to(persistence_z(w.zf_last), w.target_mask.shape)
            for name, z in sysz.items():
                d = derive(z, g)
                acc.add(name, r.family_id, d, tgt, st)
                preds.setdefault(ii, {})[name] = (z, d)
            preds[ii]["_w"] = w
            done.add(ii)
        if len(group) == 2:
            e, c = group
            we, wc = preds[e]["_w"], preds[c]["_w"]
            near = nbs[index.at[e, "event_run"]].near[None]
            common = we.target_mask & wc.target_mask & near
            if common.any():
                obs_dz = (np.nan_to_num(we.target_z) - np.nan_to_num(wc.target_z))[common]
                obs_dtt = (we.tt - wc.tt)[common]
                for name in preds[e]:
                    if name == "_w":
                        continue
                    (ze, de), (zc, dc) = preds[e][name], preds[c][name]
                    s = pair_sums.setdefault(name, np.zeros(3))
                    s += [int(common.sum()), np.abs((ze - zc)[common] - obs_dz).sum(),
                          np.abs((de["tt"] - dc["tt"])[common] - obs_dtt).sum()]
        if k % 200 == 0:
            log(f"  eval {partition}: {len(done)}/{len(rows)} windows")
    pairs = pd.DataFrame([{"system": n, "pair_labels": int(v[0]), "pair_dz_mae": v[1] / max(v[0], 1),
                           "pair_dtt_mae_s": v[2] / max(v[0], 1)} for n, v in pair_sums.items()])
    return {"cells": acc.frame(), "pairs": pairs, "seconds": round(time.time() - t0, 1), "windows": len(rows)}
