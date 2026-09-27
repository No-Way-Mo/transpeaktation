"""Inference from an input snapshot and the fleet-facing forecast export.

Snapshot (directory):
    history.parquet  time (UTC bucket start), road_segment_id, speed_mph, observed, closed
                     = the 6 completed 10-min buckets before issued_at, every canonical road
    context.json     issued_at, network_version, cases (events / permits with scheduled hours and restrictions),
                     provenance of the inputs; optional event_cases = case_nums the event context is limited to
                     (every case still contributes its closures)

Output (parquet, one row per canonical road x horizon; see CONTRACT_PROPOSAL.md):
    road_segment_id, issued_at, valid_from, valid_to, horizon_min, predicted_travel_time_sec, predicted_speed_mph,
    predicted_congestion_ratio, availability, restriction_reason, prediction_source, represented_by, model_version,
    network_version, dataset_id, training_source, input_source, synthetic_training
plus `<output>.closures.parquet` with every known closure interval at its actual timestamps, and
`<output>.meta.json`. No confidence/uncertainty column: no uncertainty method has been implemented or evaluated.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import torch

from . import config as cfg_mod
from . import events as ev_mod
from . import graph as graph_mod
from .config import read_json, save_json
from .data import (Window, history_features, normalize_hist, persistence_z, time_features, z_from_speed)
from .evaluate import derive
from .model import build_model
from .train import forward, load_checkpoint, pick_device, to_batch


def _utc(s) -> pd.Timestamp:
    t = pd.Timestamp(s)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def snapshot(cfg, run_id: str, issued_at: str, output: str) -> dict:
    """Cut an input snapshot from an exported synthetic run: only buckets that finished by issued_at."""
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    t_issue = _utc(issued_at)
    B = cfg.data.bucket_min * 60
    Th = cfg.data.history_steps
    lo = t_issue - pd.Timedelta(seconds=B * Th)
    src = cfg.batch_dir / "export" / f"sim_{run_id}.parquet"
    t = pq.read_table(src, columns=["time", "road_segment_id", "speed_mph", "observed", "closed"],
                      filters=[("time", ">=", lo), ("time", "<", t_issue)]).to_pandas()
    if t.time.max() + pd.Timedelta(seconds=B) > t_issue:
        raise SystemExit("snapshot would include an unfinished bucket")
    if t.time.nunique() != Th:
        raise SystemExit(f"need {Th} completed buckets before {t_issue}, found {t.time.nunique()}")
    t.to_parquet(out / "history.parquet", index=False)
    sc = read_json(cfg.batch_dir / "scenarios.json")
    run = next(r for r in sc["runs"] if r["run_id"] == run_id)
    man = read_json(cfg.dataset_dir / "manifest.json")
    ctx = ev_mod.run_context(sc, run)
    ctx.update({"issued_at": t_issue.isoformat(), "network_version": man["network"]["version"],
                "provenance": {"source": "sumo_synthetic", "synthetic": True, "batch": cfg.data.batch, "run_id": run_id,
                               "status": man["provenance"]["export_status"]}})
    save_json(out / "context.json", ctx)
    return {"snapshot": str(out), "buckets": sorted(t.time.astype(str).unique()), "cases": len(ctx["cases"])}


def closure_table(ctx: dict) -> pd.DataFrame:
    rows = [{"road_segment_id": s, "case_num": c["case_num"], "kind": c["kind"], "restriction": r["restriction"],
             "closure_begin": _utc(r["begin"]), "closure_end": _utc(r["end"])}
            for c in ctx["cases"] for r in c["restrictions"] for s in r["segment_ids"]]
    return pd.DataFrame(rows, columns=["road_segment_id", "case_num", "kind", "restriction", "closure_begin",
                                       "closure_end"])


def closure_cover(closures: pd.DataFrame, roads: pd.Index, starts: np.ndarray, B: int) -> np.ndarray:
    """[H, R] share of each bucket covered by a full closure, from the exact closure timestamps."""
    out = np.zeros((len(starts), len(roads)), np.float32)
    full = closures[closures.restriction == "full"]
    for r in full.itertuples():
        j = roads.get_indexer([r.road_segment_id])[0]
        if j < 0:
            continue
        b, e = r.closure_begin.timestamp(), r.closure_end.timestamp()
        cov = np.clip((np.minimum(starts + B, e) - np.maximum(starts, b)) / B, 0, 1)
        out[:, j] = np.maximum(out[:, j], cov)
    return out


class Predictor:
    """A checkpoint loaded once (model, graph, manifest) for repeated inference, e.g. every 10 simulated minutes
    inside a routing episode. `frame` takes the snapshot as in-memory objects instead of files."""

    def __init__(self, checkpoint: str, device: str | None = None):
        ck = load_checkpoint(checkpoint)
        self.ck = ck
        self.cfg = cfg_mod.from_dict(ck["config"])
        self.dev = torch.device(device) if device else pick_device(self.cfg)
        self.g = graph_mod.load(self.cfg.dataset_dir / "graph")
        if list(map(str, self.g.model_ids)) != ck["model_ids"]:
            raise SystemExit("graph road order differs from the checkpoint")
        self.model = build_model(self.cfg, self.g, ck["norm"], len(ev_mod.EVENT_PAIR_FEATURES)).to(self.dev)
        self.model.load_state_dict(ck["model"])
        self.model.eval()
        self.manifest = read_json(self.cfg.dataset_dir / "manifest.json")
        self.model_version, self.network_version = ck["model_version"], ck["network_version"]

    @torch.no_grad()
    def frame(self, hist: pd.DataFrame, ctx: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
        """history rows (time, road_segment_id, speed_mph, observed, closed) + context -> (forecast, closures)."""
        ck, cfg, dev, g = self.ck, self.cfg, self.dev, self.g
        if ctx.get("network_version") and ctx["network_version"] != ck["network_version"]:
            raise SystemExit(f"snapshot network {ctx['network_version']} != model network {ck['network_version']}")
        B, Th, H = cfg.data.bucket_min * 60, cfg.data.history_steps, cfg.data.horizon_steps
        t_issue = _utc(ctx["issued_at"])
        issue_s = int(t_issue.timestamp())
        hist = hist.copy()
        return self._run(hist, ctx, ck, cfg, dev, g, B, Th, H, t_issue, issue_s)

    def _run(self, hist, ctx, ck, cfg, dev, g, B, Th, H, t_issue, issue_s):
        hist["t"] = hist.time.values.astype("datetime64[s]").astype(np.int64)
        want = issue_s - B * np.arange(Th, 0, -1)
        if hist.t.max() + B > issue_s:
            raise SystemExit("history contains a bucket that ends after issued_at")
        pos = {s: i for i, s in enumerate(g.model_ids)}
        N = g.n
        spd = np.full((Th, N), np.nan, np.float32)
        obs = np.zeros((Th, N), bool)
        closed = np.zeros((Th, N), bool)
        hist = hist[hist.road_segment_id.isin(pos.keys()) & hist.t.isin(want)]
        ti = np.searchsorted(want, hist.t.to_numpy())
        ri = hist.road_segment_id.map(pos).to_numpy()
        spd[ti, ri] = hist.speed_mph.to_numpy()
        obs[ti, ri] = hist.observed.to_numpy().astype(bool)
        closed[ti, ri] = hist.closed.to_numpy().astype(bool)
        z = np.where(obs, z_from_speed(spd, g.length_m[None], g.free_flow_mph[None]), np.nan).astype(np.float32)
        f, zf = history_features(z, obs, closed, cfg.data.max_ffill)
        starts = issue_s + B * np.arange(H)
        closures = closure_table(ctx)
        cover_model = closure_cover(closures, pd.Index(g.model_ids), starts.astype(float), B)
        w = Window(run_id="snapshot", origin=Th, issued_at=issue_s, hist=normalize_hist(f, ck["norm"]), zf_last=zf[-1],
                   time_hist=time_features(want), time_fut=time_features(starts), fut_base=cover_model[..., None],
                   fut_start=starts, target_z=np.full((H, N), np.nan, np.float32), target_mask=np.zeros((H, N), bool),
                   tt=None, speed=None, cong=None)
        model = self.model
        ev_ctx = ctx                          # optional ctx["event_cases"] (case_nums): the event context uses only
        if ctx.get("event_cases") is not None:   # those; closures/availability still use every case
            keep = set(ctx["event_cases"])
            ev_ctx = {**ctx, "cases": [c for c in ctx["cases"] if c["case_num"] in keep]}
        ev = ev_mod.build_tensors(ev_ctx, g, cfg, (float(np.log(20_000.0)), 1.5)).to_torch(dev) if cfg.model.use_events else None
        zp = forward(model, to_batch(w, dev, ev, cfg), cfg.train.amp)[0].cpu().numpy()
        pred = derive(zp, g)

        roads = g.roads
        R = len(roads)
        all_ids = roads.road_segment_id.to_numpy()
        cover_all = closure_cover(closures, pd.Index(all_ids), starts.astype(float), B)
        midx = roads.model_idx.to_numpy()
        rep = roads.represented_by.to_numpy() if "represented_by" in roads else np.full(R, None)
        src_idx = midx.copy()                               # model row supplying the prediction (-1 = none)
        source = np.where(midx >= 0, "model", "none").astype(object)
        reason = np.full(R, "none", object)
        avail_static = roads.availability_static.to_numpy().astype(object)
        reason[(avail_static == "restricted")] = "no_passenger_access"
        gap = roads.gap.to_numpy()
        reason[(avail_static == "unavailable")] = [f"not_modelled:{x}" for x in gap[avail_static == "unavailable"]]
        rid_pos = {s: i for i, s in enumerate(all_ids)}
        for i in np.flatnonzero((midx < 0) & (gap == "merged_parallel")):
            j = rid_pos.get(rep[i])
            if j is not None and midx[j] >= 0:
                src_idx[i] = midx[j]
                source[i] = "representative_road"
                avail_static[i] = "open"
                reason[i] = "merged_parallel"
        rows = []
        valid_from = [t_issue + pd.Timedelta(seconds=B * k) for k in range(H)]
        for k in range(H):
            avail = avail_static.copy()
            rsn = reason.copy()
            full = cover_all[k] >= 1.0
            part = (cover_all[k] > 0) & ~full
            avail[full & (avail != "unavailable")] = "closed"
            rsn[full & (avail == "closed")] = "scheduled_closure"
            m_part = part & (avail == "open")
            avail[m_part] = "restricted"
            rsn[m_part] = "partial_closure_see_closures_table"
            has = (src_idx >= 0) & np.isin(avail, ["open", "restricted"]) & (rsn != "no_passenger_access")
            tt = np.full(R, np.nan); sp = np.full(R, np.nan); cg = np.full(R, np.nan)
            tt[has] = pred["tt"][k][src_idx[has]]
            sp[has] = pred["speed"][k][src_idx[has]]
            cg[has] = pred["cong"][k][src_idx[has]]
            rows.append(pd.DataFrame({
                "road_segment_id": all_ids, "issued_at": t_issue, "valid_from": valid_from[k],
                "valid_to": valid_from[k] + pd.Timedelta(seconds=B), "horizon_min": (k + 1) * cfg.data.bucket_min,
                "predicted_travel_time_sec": tt, "predicted_speed_mph": sp, "predicted_congestion_ratio": cg,
                "availability": avail, "restriction_reason": rsn,
                "prediction_source": np.where(has, source, "none"),
                "represented_by": np.where(source == "representative_road", rep, None)}))
        df = pd.concat(rows, ignore_index=True)
        prov = ctx.get("provenance", {})
        man = self.manifest
        df["model_version"] = ck["model_version"]
        df["network_version"] = ck["network_version"]
        df["dataset_id"] = ck["dataset_id"]
        df["training_source"] = f"sumo_synthetic:{man['batch']}"
        df["input_source"] = prov.get("source", "unknown")
        df["synthetic_training"] = True
        return df, closures


def predict(checkpoint: str, input_dir: str, output: str) -> dict:
    p = Predictor(checkpoint)
    inp = Path(input_dir)
    ctx = read_json(inp / "context.json")
    df, closures = p.frame(pd.read_parquet(inp / "history.parquet"), ctx)
    ck, cfg = p.ck, p.cfg
    t_issue = _utc(ctx["issued_at"])
    prov = ctx.get("provenance", {})
    man = p.manifest
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    closures.to_parquet(out.with_suffix(".closures.parquet"), index=False)
    meta = {"issued_at": t_issue.isoformat(), "model_version": ck["model_version"],
            "network_version": ck["network_version"], "dataset_id": ck["dataset_id"],
            "input_provenance": prov, "training_provenance": man["provenance"],
            "uncertainty": "not available (no uncertainty method implemented or evaluated)",
            "units": {"predicted_travel_time_sec": "s", "predicted_speed_mph": "mph",
                      "predicted_congestion_ratio": "1 - speed/free_flow, clipped [0, 1]"},
            "timing": "horizon_min = 10k covers [issued_at + 10(k-1) min, issued_at + 10k min)",
            "rows": len(df), "availability_counts": df.availability.value_counts().to_dict(),
            "prediction_source_counts": df.prediction_source.value_counts().to_dict(),
            "persistence_fallback": "not used"}
    save_json(out.with_suffix(".meta.json"), meta)
    return {"output": str(out), **{k: meta[k] for k in ("rows", "availability_counts", "prediction_source_counts")}}
