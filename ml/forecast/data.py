"""Per-run cached arrays and causal forecast windows.

Timing. Buckets are 10-min UTC intervals [t, t + 10 min). A window with origin index o is issued at
`issued_at = time[o]`, the end of the last completed history bucket o-1. History = buckets o-6 .. o-1 (all finished
by issued_at). Targets = buckets o .. o+5; horizon k (1..6) covers [issued_at + (k-1)*10 min, issued_at + k*10 min),
reported as horizon_min = 10*k. No bucket aggregate at or after o is ever read into the inputs.

Windows never cross a run boundary and every bucket of a window lies in the demand phase (warmup and the no-departure
drain are excluded). Nothing is filled in the targets; history is forward-filled at most `max_ffill` buckets inside
the window, with the original mask, the fill flag and the age kept as features. Volume/throughput are not inputs.

Per-run arrays are written once as .npy and memory-mapped afterwards.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from . import graph as graph_mod
from .config import Config, MPH_PER_MPS, SF_TZ, SPEED_FLOOR_MPS, read_json, save_json, sha256_file
from .graph import STATIC_FEATURES, RoadGraph

HIST_FEATURES = ["z_filled", "speed_ratio_filled", "congestion_filled", "observed", "ffilled", "missing_after_fill",
                 "age_frac", "closed"]
TIME_FEATURES = ["tod_sin", "tod_cos", "dow_sin", "dow_cos"]   # SF local time at bucket start
FUTURE_BASE_FEATURES = ["scheduled_closed_share"]              # own-road scheduled closure share of the bucket
PHASES = {"warmup": 0, "demand": 1, "drain": 2}
NORMALIZED_HIST = [0, 1, 2]                                      # continuous history features standardised


def time_features(epoch_s: np.ndarray) -> np.ndarray:
    out = np.zeros((len(epoch_s), 4), np.float32)
    for i, t in enumerate(epoch_s):
        lt = datetime.fromtimestamp(int(t), timezone.utc).astimezone(SF_TZ)
        tod = (lt.hour * 3600 + lt.minute * 60 + lt.second) / 86400.0
        dow = (lt.weekday() + tod) / 7.0
        out[i] = [math.sin(2 * math.pi * tod), math.cos(2 * math.pi * tod),
                  math.sin(2 * math.pi * dow), math.cos(2 * math.pi * dow)]
    return out


def z_from_speed(speed_mph: np.ndarray, length_m: np.ndarray, ff_mph: np.ndarray) -> np.ndarray:
    """log(travel time / free-flow travel time) with the export's 0.1 m/s floor (NaN stays NaN)."""
    tt = length_m / np.maximum(speed_mph / MPH_PER_MPS, SPEED_FLOOR_MPS)
    return np.log(tt / (length_m / (ff_mph / MPH_PER_MPS)))


def history_features(z: np.ndarray, obs: np.ndarray, closed: np.ndarray, max_ffill: int) -> tuple[np.ndarray, np.ndarray]:
    """z/obs/closed [T, N] of completed history buckets -> ([T, N, F] unnormalised features, z_filled [T, N]).

    Causal forward fill inside the window only, at most `max_ffill` buckets. Missing-after-fill cells carry z_filled
    = NaN here; `normalize_hist` turns them into the neutral value 0 plus the missing flag."""
    T, N = z.shape
    zf = np.full((T, N), np.nan, np.float32)
    ffilled = np.zeros((T, N), bool)
    age = np.full((T, N), T, np.float32)          # buckets since last observation (T = never in window)
    last = np.full(N, np.nan, np.float32)
    since = np.full(N, np.inf)
    for t in range(T):
        o = obs[t] & np.isfinite(z[t])
        last = np.where(o, z[t], last)
        since = np.where(o, 0, since + 1)
        ok = np.isfinite(last) & (since <= max_ffill)
        zf[t] = np.where(ok, last, np.nan)
        ffilled[t] = ok & ~o
        age[t] = np.minimum(since, T)
    miss = ~np.isfinite(zf)
    with np.errstate(invalid="ignore", over="ignore"):
        ratio = np.exp(-zf)
    cong = np.clip(1 - ratio, 0, 1)
    feats = np.stack([zf, ratio, cong, obs.astype(np.float32), ffilled.astype(np.float32), miss.astype(np.float32),
                      age / T, closed.astype(np.float32)], -1)
    return feats.astype(np.float32), zf


def normalize_hist(feats: np.ndarray, norm: dict) -> np.ndarray:
    out = feats.copy()
    for j in NORMALIZED_HIST:
        name = HIST_FEATURES[j]
        v = (out[..., j] - norm["hist_mean"][name]) / norm["hist_std"][name]
        out[..., j] = np.where(np.isfinite(v), v, 0.0)
    return out


def persistence_z(zf_last: np.ndarray) -> np.ndarray:
    """Persistence baseline on the same causal inputs: last filled value (<= max_ffill old), else free flow."""
    return np.where(np.isfinite(zf_last), zf_last, 0.0).astype(np.float32)


# ---------------------------------------------------------------- prepare

def window_origins(phase: np.ndarray, Th: int, H: int, allowed: list[int]) -> np.ndarray:
    """Origins o of one run such that history o-Th..o-1 and targets o..o+H-1 all exist in this run and lie in an
    allowed phase. Windows never reach before the run's first bucket or past its last one."""
    ok = np.isin(phase, allowed)
    return np.array([o for o in range(Th, len(phase) - H + 1) if ok[o - Th:o + H].all()], np.int64)


def prepare(cfg: Config, workers: int = 1) -> dict:
    from . import events as ev_mod
    from .audit import local_to_utc, scheduled_closed
    ddir = cfg.dataset_dir
    man = read_json(ddir / "manifest.json")
    splits = read_json(ddir / "splits.json")
    g = graph_mod.build(cfg)
    got = hashlib.sha256("\n".join(g.model_ids).encode()).hexdigest()
    if got != man["roads"]["model_sha256"]:
        raise SystemExit("model road order differs from the frozen manifest")
    graph_mod.save(g, ddir / "graph")
    sc = read_json(cfg.batch_dir / "scenarios.json")
    runs = {r["run_id"]: r for r in sc["runs"]}
    fams = {f["family_id"]: f for f in sc["families"]}
    seg = pd.read_parquet(cfg.batch_dir / "export" / "segments.parquet")
    mcols = seg.index[seg.road_segment_id.isin(set(g.model_ids))].to_numpy()
    assert (seg.road_segment_id.to_numpy()[mcols] == g.model_ids).all()
    Th, H = cfg.data.history_steps, cfg.data.horizon_steps
    if workers > 1:   # per-run caches in parallel (graph saved above; each worker reads it)
        from concurrent.futures import ProcessPoolExecutor
        todo = [s["run_id"] for s in man["selected_runs"] if not (ddir / "runs" / s["run_id"] / "done.json").exists()]
        with ProcessPoolExecutor(workers) as ex:
            list(ex.map(_cache_one, [cfg] * len(todo), todo))
    win_rows, cov_rows = [], []
    for sel in man["selected_runs"]:
        rid = sel["run_id"]
        rdir = ddir / "runs" / rid
        cache_run(cfg, man, sc, runs, fams, seg, mcols, g, rid)
        phase = np.load(rdir / "phase.npy")
        times = np.load(rdir / "time.npy")
        ok = np.isin(phase, [PHASES[p] for p in cfg.data.phases])
        T = len(phase)
        origins = window_origins(phase, Th, H, [PHASES[p] for p in cfg.data.phases])
        n_win = len(origins)
        win_rows += [{"run_id": rid, "family_id": sel["family_id"], "family_group": sel["family_group"],
                      "partition": sel["partition"], "with_event": sel["with_event"], "origin": int(o),
                      "issued_at": int(times[o])} for o in origins]
        fam = fams[sel["family_id"]]
        ph = [local_to_utc(fam["date"], s).timestamp() for s in fam["public_hours_s"]]
        dem = times[phase == PHASES["demand"]]
        cov_rows.append({"run_id": rid, "window": fam["window"], "buckets": T, "demand_buckets": int(ok.sum()),
                         "windows": n_win, "demand_start_utc": _iso(dem.min()), "demand_end_utc": _iso(dem.max() + 600),
                         "public_start_utc": _iso(ph[0]), "public_end_utc": _iso(ph[1]),
                         "covers_public_start": bool(dem.min() <= ph[0] < dem.max() + 600),
                         "covers_public_end": bool(dem.min() <= ph[1] < dem.max() + 600),
                         "excluded_warmup_buckets": int((phase == 0).sum()), "excluded_drain_buckets": int((phase == 2).sum())})
    win = pd.DataFrame(win_rows)
    win.to_parquet(ddir / "windows.parquet", index=False)
    pd.DataFrame(cov_rows).to_csv(ddir / "window_coverage.csv", index=False)
    for p in ("train", "val", "test"):   # windows must respect the frozen split
        assert set(win[win.partition == p].run_id) <= set(splits["runs"][p])
    norm = fit_norm(cfg, g, win)
    save_json(ddir / "norm.json", norm)
    return {"windows": {f"{p}/{fg}": int(n) for (p, fg), n in win.groupby(["partition", "family_group"]).size().items()},
            "graph": g.stats,
            "coverage": cov_rows}


def cache_run(cfg: Config, man: dict, sc: dict, runs: dict, fams: dict, seg: pd.DataFrame, mcols: np.ndarray,
              g: RoadGraph, rid: str) -> bool:
    """Per-run arrays + context from the run's source export (verified against the frozen manifest hash).
    `done.json` is written last, so an interrupted cache is detectable and rebuilt. Returns True if built."""
    from . import events as ev_mod
    from .audit import represented_map, scheduled_closed
    rdir = cfg.dataset_dir / "runs" / rid
    src = cfg.batch_dir / "export" / f"sim_{rid}.parquet"
    if sha256_file(src) != man["input_sha256"][f"export/sim_{rid}.parquet"]:
        raise SystemExit(f"{src.name} changed since the manifest was frozen")
    if (rdir / "done.json").exists():
        return False
    print(f"caching {rid}", flush=True)
    t = pq.read_table(src, columns=["time", "speed_mph", "congestion_ratio", "travel_time_s", "observed",
                                    "closed", "phase"]).to_pandas()
    R = len(seg)
    T = len(t) // R
    sl = lambda c: t[c].to_numpy().reshape(T, R)[:, mcols]
    times = t.time.values.astype("datetime64[s]").astype(np.int64).reshape(T, R)[:, 0]
    obs = sl("observed").astype(bool)
    tt = sl("travel_time_s").astype(np.float32)
    speed = sl("speed_mph").astype(np.float32)
    z = np.where(obs, np.log(tt / g.ref_tt_s[None, :]), np.nan).astype(np.float32)
    rdir.mkdir(parents=True, exist_ok=True)
    np.save(rdir / "time.npy", times)
    np.save(rdir / "phase.npy", np.array([PHASES[p] for p in t.phase.to_numpy().reshape(T, R)[:, 0]], np.int8))
    np.save(rdir / "z.npy", z)
    np.save(rdir / "observed.npy", obs)
    np.save(rdir / "closed.npy", sl("closed").astype(bool))
    np.save(rdir / "travel_time_s.npy", tt)
    np.save(rdir / "speed_mph.npy", speed)
    np.save(rdir / "congestion_ratio.npy", sl("congestion_ratio").astype(np.float32))
    ctx = ev_mod.run_context(sc, runs[rid])
    save_json(rdir / "context.json", ctx)
    sched = scheduled_closed(runs[rid], fams[runs[rid]["family_id"]], pd.to_datetime(times, unit="s", utc=True),
                             pd.Index(g.model_ids), cfg.data.bucket_min * 60, represented_map(sc))
    np.save(rdir / "scheduled_closed.npy", sched.astype(np.float16))
    save_json(rdir / "done.json", {"source_sha256": man["input_sha256"][f"export/sim_{rid}.parquet"],
                                   "buckets": int(T), "roads": int(len(mcols))})
    del t
    return True


def rebuild_cache(cfg: Config, workers: int = 8) -> dict:
    """Cache-only recovery of missing `runs/<run_id>/` arrays of a FROZEN dataset: reuses the frozen graph and road
    order and the prepare() extraction; never rewrites manifest, splits, graph, normalisation or window index."""
    from concurrent.futures import ProcessPoolExecutor
    ddir = cfg.dataset_dir
    man = read_json(ddir / "manifest.json")
    g = graph_mod.load(ddir / "graph")
    if hashlib.sha256("\n".join(map(str, g.model_ids)).encode()).hexdigest() != man["roads"]["model_sha256"]:
        raise SystemExit("frozen graph road order differs from the manifest")
    frozen = {f: sha256_file(ddir / f) for f in ("manifest.json", "splits.json", "norm.json", "windows.parquet")}
    todo = [s["run_id"] for s in man["selected_runs"] if not (ddir / "runs" / s["run_id"] / "done.json").exists()]
    with ProcessPoolExecutor(max(1, workers)) as ex:
        built = sum(ex.map(_cache_one, [cfg] * len(todo), todo))
    after = {f: sha256_file(ddir / f) for f in frozen}
    if after != frozen:
        raise SystemExit("frozen dataset metadata changed during cache rebuild")
    return {"selected_runs": len(man["selected_runs"]), "missing": len(todo), "built": int(built),
            "frozen_metadata_unchanged": True}


def _cache_one(cfg: Config, rid: str) -> bool:
    ddir = cfg.dataset_dir
    man = read_json(ddir / "manifest.json")
    g = graph_mod.load(ddir / "graph")
    sc = read_json(cfg.batch_dir / "scenarios.json")
    seg = pd.read_parquet(cfg.batch_dir / "export" / "segments.parquet")
    mcols = seg.index[seg.road_segment_id.isin(set(g.model_ids))].to_numpy()
    assert (seg.road_segment_id.to_numpy()[mcols] == g.model_ids).all()
    return cache_run(cfg, man, sc, {r["run_id"]: r for r in sc["runs"]},
                     {f["family_id"]: f for f in sc["families"]}, seg, mcols, g, rid)


def _iso(ts) -> str:
    return datetime.fromtimestamp(int(ts), timezone.utc).isoformat()


def fit_norm(cfg: Config, g: RoadGraph, win: pd.DataFrame) -> dict:
    """Standardisation statistics from TRAIN windows only (history cells after fill) and training targets."""
    sums = np.zeros(3); sq = np.zeros(3); n = 0
    zt_sum, zt_n = 0.0, 0
    Th, H = cfg.data.history_steps, cfg.data.horizon_steps
    tr = win[win.partition == "train"]
    for rid, grp in tr.groupby("run_id"):
        a = RunArrays(cfg.dataset_dir / "runs" / rid)
        for o in grp.origin.to_numpy()[::3]:
            f, _ = history_features(a.z[o - Th:o], a.obs[o - Th:o], a.closed[o - Th:o], cfg.data.max_ffill)
            v = f[..., :3].reshape(-1, 3)
            v = v[np.isfinite(v).all(1)]
            sums += v.sum(0); sq += (v ** 2).sum(0); n += len(v)
            zt = a.z[o:o + H][a.obs[o:o + H] & ~a.closed[o:o + H]]
            zt_sum += float(zt.sum()); zt_n += len(zt)
    mean = sums / n
    std = np.sqrt(np.maximum(sq / n - mean ** 2, 1e-6))
    st = g.static.astype(np.float64)
    smean, sstd = st.mean(0), st.std(0)
    sstd[sstd < 1e-6] = 1.0
    return {"hist_mean": dict(zip(HIST_FEATURES[:3], mean.tolist())), "hist_std": dict(zip(HIST_FEATURES[:3], std.tolist())),
            "static_mean": smean.tolist(), "static_std": sstd.tolist(), "static_features": STATIC_FEATURES,
            "target_z_mean_train": zt_sum / max(zt_n, 1), "fit_on": "train partition windows only (every 3rd origin)",
            "cells": int(n)}


class RunArrays:
    """Memory-mapped per-run arrays (model road order)."""

    def __init__(self, d):
        self.dir = d
        m = lambda k: np.load(d / f"{k}.npy", mmap_mode="r")
        self.time, self.phase = np.load(d / "time.npy"), np.load(d / "phase.npy")
        self.z, self.obs, self.closed = m("z"), m("observed"), m("closed")
        self.tt, self.speed, self.cong = m("travel_time_s"), m("speed_mph"), m("congestion_ratio")
        self.sched = m("scheduled_closed")
        self.context = read_json(d / "context.json")


@dataclass
class Window:
    run_id: str
    origin: int
    issued_at: int
    hist: np.ndarray          # [Th, N, F] normalised
    zf_last: np.ndarray       # [N] last filled history z (NaN = missing) -> persistence baseline
    time_hist: np.ndarray     # [Th, 4]
    time_fut: np.ndarray      # [H, 4]
    fut_base: np.ndarray      # [H, N, 1]
    fut_start: np.ndarray     # [H] epoch s of each target bucket start
    target_z: np.ndarray      # [H, N] NaN = no valid label
    target_mask: np.ndarray   # [H, N]
    tt: np.ndarray            # [H, N] label travel time s
    speed: np.ndarray
    cong: np.ndarray


def _fut(arr, o: int, H: int, fill) -> np.ndarray:
    """arr[o:o+H] padded with `fill` past the run's last bucket (only windows of a shorter-horizon dataset reach it)."""
    x = np.asarray(arr[o:o + H])
    if len(x) == H:
        return x
    pad = np.full((H - len(x),) + x.shape[1:], fill, dtype=x.dtype)
    return np.concatenate([x, pad], 0)


def target_mask(a: RunArrays, o: int, H: int) -> np.ndarray:
    """Valid label: measured, not closed in that bucket, modelled road (model roads have passenger access and a
    represented SUMO edge by construction), finite, and inside the run's demand phase (drain / past-the-end buckets of
    a shorter-horizon dataset are never labels)."""
    z = _fut(a.z, o, H, np.nan)
    ph = _fut(a.phase, o, H, -1)
    return _fut(a.obs, o, H, False) & ~_fut(a.closed, o, H, True) & np.isfinite(z) & (ph == PHASES["demand"])[:, None]


def make_window(cfg: Config, a: RunArrays, o: int, norm: dict) -> Window:
    Th, H, B = cfg.data.history_steps, cfg.data.horizon_steps, cfg.data.bucket_min * 60
    f, zf = history_features(np.asarray(a.z[o - Th:o]), np.asarray(a.obs[o - Th:o]), np.asarray(a.closed[o - Th:o]),
                             cfg.data.max_ffill)
    m = target_mask(a, o, H)
    fut = a.time[o] + B * np.arange(H)
    return Window(run_id=a.dir.name, origin=o, issued_at=int(a.time[o]), hist=normalize_hist(f, norm), zf_last=zf[-1],
                  time_hist=time_features(a.time[o - Th:o]), time_fut=time_features(fut),
                  fut_base=_fut(a.sched, o, H, 0).astype(np.float32)[..., None], fut_start=fut.astype(np.int64),
                  target_z=np.where(m, _fut(a.z, o, H, np.nan), np.nan).astype(np.float32), target_mask=m,
                  tt=_fut(a.tt, o, H, np.nan), speed=_fut(a.speed, o, H, np.nan), cong=_fut(a.cong, o, H, np.nan))


def static_normalized(g: RoadGraph, norm: dict) -> np.ndarray:
    return ((g.static - np.asarray(norm["static_mean"])) / np.asarray(norm["static_std"])).astype(np.float32)
