"""Event-window index, clear-road anticipation masks, matched event/control pairs and the phase-balanced sampler
(EVENT_AWARENESS_FINETUNING_PLAN.md §4).

Built from the FROZEN window index (`windows.parquet`), the frozen manifest (run seed / window / family) and each
run's scheduled context. Future labels only define label masks and diagnostic counts; they never enter inputs,
sampling or selection.

Phases (from the focal event's published schedule; proxies for traffic phases, not observed surge onset):
    pre_start  issued_at in [public_start - 60 min, public_start)
    pre_end    issued_at in [public_end   - 60 min, public_end)
    other      everything else
A control run has no focal event in its own context; its phase comes from the matched event run of the same
family and seed (used for sampling and reporting only; the control's model inputs keep its own real context).

Clear-road anticipation (primary stratum): at issue time the road was actually observed in the last completed
bucket (o-1), finite, not closed, congestion < 0.3; it is within `near_radius_m` of the focal footprint; the future
target is a valid label (`target_mask`). Future congested AND uncongested targets are both kept. The strict variant
also requires the same at bucket o-2. Forward-filled or missing history never qualifies.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import Config, read_json
from .data import RunArrays, target_mask

PRE_S = 3600          # the "pre" windows: the hour before a schedule boundary
CLEAR_MAX = 0.3       # issue-time congestion below this = clear (same value as eval.buildup_prior_max)
PHASES = ("pre_start", "pre_end", "other")


def _ts(s) -> float:
    return np.nan if s is None else pd.Timestamp(s).timestamp()


def focal_schedule(ctx: dict) -> tuple[float, float]:
    c = next((c for c in ctx["cases"] if c["kind"] == "public_event"), None)
    return (np.nan, np.nan) if c is None else (_ts(c.get("public_start")), _ts(c.get("public_end")))


def phase_of(issued: np.ndarray, start: float, end: float, pre_s: float = PRE_S
             ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """-> (pre_start flag, pre_end flag, sampling category with priority pre_start > pre_end > other)."""
    ps = (issued >= start - pre_s) & (issued < start)
    pe = (issued >= end - pre_s) & (issued < end)
    cat = np.where(ps, "pre_start", np.where(pe, "pre_end", "other"))
    return ps, pe, cat


def lead_category(issued: np.ndarray, start, end, bands_min: list[int]) -> np.ndarray:
    """One deterministic sampling/reporting category per window from the event lead at issue time:
    `start_<a>_<b>` when issued in [start - b min, start - a min), else `end_<a>_<b>` for the end boundary (start
    has priority when both apply; the separate pre_start / pre_end flags keep the overlap), else `other`
    (event active / recovery, or no focal schedule)."""
    out = np.full(len(issued), "other", dtype=object)
    for name, b in (("end", end), ("start", start)):     # start last = start wins overlaps
        lead = (np.asarray(b, float) - issued) / 60.0
        for lo, hi in zip(bands_min[:-1], bands_min[1:]):
            out[(lead > lo) & (lead <= hi)] = f"{name}_{lo}_{hi}"
    return out


def clear_roads(a: RunArrays, o: int, strict: bool = False) -> np.ndarray:
    """[N] bool: directly observed, finite, not closed and congestion < 0.3 in bucket o-1 (and o-2 if strict)."""
    ok = None
    for k in ((1, 2) if strict else (1,)):
        z = np.asarray(a.z[o - k])
        cong = np.clip(1 - np.exp(-np.where(np.isfinite(z), z, 0.0)), 0, 1)
        m = np.asarray(a.obs[o - k]) & np.isfinite(z) & ~np.asarray(a.closed[o - k]) & (cong < CLEAR_MAX)
        ok = m if ok is None else ok & m
    return ok


def missing_history(a: RunArrays, o: int) -> np.ndarray:
    """[N] roads with no real observation in the last completed bucket (filled-only or missing)."""
    return ~(np.asarray(a.obs[o - 1]) & np.isfinite(np.asarray(a.z[o - 1])))


@dataclass
class Neighbourhoods:
    near: np.ndarray       # [N] within near_radius_m of the focal footprint
    far: np.ndarray        # [N] beyond context_radius_m (3 km): the preserve region of event runs


def neighbourhoods(ctx: dict, graph, cfg: Config) -> Neighbourhoods:
    from scipy.spatial import cKDTree
    from .events import focal_footprint
    fp = focal_footprint(ctx, graph)
    if not len(fp):
        return Neighbourhoods(np.zeros(graph.n, bool), np.ones(graph.n, bool))
    d = cKDTree(graph.xy[fp]).query(graph.xy)[0]
    return Neighbourhoods(d <= cfg.events.near_radius_m, d > cfg.events.context_radius_m)


def build_index(cfg: Config, data, counts: bool = True, pre_s: float = PRE_S,
                lead_bands_min: list[int] | None = None) -> tuple[pd.DataFrame, dict]:
    """Every frozen window + run metadata, phase flags, matched pair and (optionally) support counts.
    `data` is a forecast.train.Data. Returns (index, audit)."""
    man = read_json(cfg.dataset_dir / "manifest.json")
    meta = {r["run_id"]: r for r in man["selected_runs"]}
    missing_seed = [r for r, m in meta.items() if "seed" not in m]
    if missing_seed:
        raise SystemExit(f"manifest runs without a seed: {missing_seed[:3]}")
    w = data.windows.copy().reset_index(drop=True)
    w["seed"] = w.run_id.map(lambda r: int(meta[r]["seed"]))
    w["window_kind"] = w.run_id.map(lambda r: meta[r].get("window"))
    # the event run of each (family, seed): the source of focal schedule / neighbourhood for both runs of the pair
    ev_run = {}
    for r, m in meta.items():
        if m["with_event"]:
            key = (m["family_id"], int(m["seed"]))
            if key in ev_run:
                raise SystemExit(f"ambiguous event run for family {key}: {ev_run[key]} and {r}")
            ev_run[key] = r
    w["event_run"] = [ev_run.get((f, s)) for f, s in zip(w.family_id, w.seed)]
    sched = {r: focal_schedule(data.run(r).context) for r in set(w.event_run.dropna())}
    st = np.array([sched[r][0] if r else np.nan for r in w.event_run])
    en = np.array([sched[r][1] if r else np.nan for r in w.event_run])
    ps, pe, cat = phase_of(w.issued_at.to_numpy().astype(float), st, en, pre_s)
    if lead_bands_min:
        w["lead_cat"] = lead_category(w.issued_at.to_numpy().astype(float), st, en, lead_bands_min)
    w["public_start"], w["public_end"] = st, en
    w["min_to_start"] = (st - w.issued_at) / 60.0
    w["min_to_end"] = (en - w.issued_at) / 60.0
    w["pre_start"], w["pre_end"], w["phase"] = ps, pe, cat
    # matched event/control windows: family + actual seed + issue timestamp (never family alone)
    key = list(zip(w.family_id, w.seed, w.issued_at))
    by_key: dict = {}
    for i, (k, we) in enumerate(zip(key, w.with_event)):
        by_key.setdefault((k, bool(we)), []).append(i)
    pair, ambiguous = [], 0
    for i, (k, we) in enumerate(zip(key, w.with_event)):
        other = by_key.get((k, not bool(we)), [])
        if len(other) > 1 or len(by_key[(k, bool(we))]) > 1:
            ambiguous += 1
            pair.append(-1)
            continue
        j = other[0] if other else -1
        if j >= 0 and (w.partition[j] != w.partition[i] or w.origin[j] < 0):
            raise SystemExit(f"pair {w.run_id[i]} / {w.run_id[j]} crosses partitions")
        pair.append(j)
    if ambiguous:
        raise SystemExit(f"{ambiguous} windows have ambiguous event/control matches")
    w["pair"] = pair
    audit = {"windows": len(w), "event_windows": int(w.with_event.sum()),
             "event_windows_with_control": int((w.with_event & (w.pair >= 0)).sum()),
             "event_windows_without_control": int((w.with_event & (w.pair < 0)).sum()),
             "control_windows_without_event": int((~w.with_event & (w.pair < 0)).sum())}
    if counts:
        _support(cfg, data, w)
        audit["support"] = support_table(w)
    return w, audit


def _support(cfg: Config, data, w: pd.DataFrame) -> None:
    """Per window: near roads, directly observed clear near roads (primary / strict), and future labels and
    positive build-ups on those roads. Diagnostics only."""
    H = cfg.data.horizon_steps
    thr = cfg.eval.buildup_congestion
    nb_cache = {}
    cols = {k: np.zeros(len(w), np.int64) for k in ("near_roads", "clear_near", "clear_near_strict", "antic_labels",
                                                    "antic_positives", "antic_labels_strict")}
    for i, r in enumerate(w.itertuples()):
        if r.event_run is None or not r.with_event:
            continue
        if r.event_run not in nb_cache:
            nb_cache[r.event_run] = neighbourhoods(data.run(r.event_run).context, data.graph, cfg)
        near = nb_cache[r.event_run].near
        a = data.run(r.run_id)
        o = int(r.origin)
        c1 = clear_roads(a, o) & near
        c2 = clear_roads(a, o, strict=True) & near
        m = target_mask(a, o, H)
        cong = np.asarray(a.cong[o:o + H])
        cols["near_roads"][i] = int(near.sum())
        cols["clear_near"][i] = int(c1.sum())
        cols["clear_near_strict"][i] = int(c2.sum())
        cols["antic_labels"][i] = int((m & c1[None]).sum())
        cols["antic_labels_strict"][i] = int((m & c2[None]).sum())
        cols["antic_positives"][i] = int((m & c1[None] & (cong >= thr)).sum())
    for k, v in cols.items():
        w[k] = v


def support_table(w: pd.DataFrame) -> list[dict]:
    ev = w[w.with_event]
    rows = []
    for (p, ph), g in ev.groupby(["partition", "phase"]):
        rows.append({"partition": p, "phase": ph, "families": int(g.family_id.nunique()),
                     "seeds": int(g[["family_id", "seed"]].drop_duplicates().shape[0]), "windows": len(g),
                     "windows_with_clear_near": int((g.clear_near > 0).sum()),
                     "clear_near_roads": int(g.clear_near.sum()), "anticipation_labels": int(g.antic_labels.sum()),
                     "anticipation_positives": int(g.antic_positives.sum()),
                     "anticipation_labels_strict": int(g.antic_labels_strict.sum())})
    return rows


def epoch_sample(w: pd.DataFrame, per_family: int, rng: np.random.Generator,
                 targets=(("pre_start", 0.5), ("pre_end", 0.25), ("other", 0.25))) -> tuple[list[int], dict]:
    """Family-balanced, event/control-balanced, phase-balanced TRAIN windows for one epoch.

    Per family: per_family windows, half from event runs and half from control runs; within each half the phase
    targets 50/25/25. A category with no windows gives its quota to the remaining ones in proportion to their
    targets (logged). Sampling is without replacement where possible."""
    tr = w[w.partition == "train"]
    idx, realized = [], {"requested": 0, "reallocated": 0}
    for fam, g in sorted(tr.groupby("family_id"), key=lambda kv: kv[0]):
        halves = [(True, per_family - per_family // 2), (False, per_family // 2)]
        for we, n in halves:
            gg = g[g.with_event == we]
            if gg.empty or n == 0:
                continue
            avail = {ph: gg.index[gg.phase == ph].to_numpy() for ph, _ in targets}
            tot = sum(t for ph, t in targets if len(avail[ph]))
            quotas = {ph: (t / tot if len(avail[ph]) else 0.0) for ph, t in targets}
            if tot < 1 - 1e-9:
                realized["reallocated"] += 1
            counts = {ph: int(np.floor(n * q)) for ph, q in quotas.items()}
            rest = n - sum(counts.values())
            for ph, _ in sorted(targets, key=lambda kv: -quotas[kv[0]]):
                if rest <= 0:
                    break
                if quotas[ph] > 0:
                    counts[ph] += 1
                    rest -= 1
            for ph, k in counts.items():
                if k:
                    rows = avail[ph]
                    idx += list(rng.choice(rows, size=k, replace=len(rows) < k))
            realized["requested"] += n
    rng.shuffle(idx)
    sel = w.loc[idx]
    realized["phase_share"] = {f"{'event' if we else 'control'}/{ph}": round(float(n) / max(len(sel), 1), 4)
                               for (we, ph), n in sel.groupby(["with_event", "phase"]).size().items()}
    return [int(i) for i in idx], realized
