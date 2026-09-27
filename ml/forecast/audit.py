"""Dataset eligibility, integrity checks, frozen event-group split and the immutable dataset manifest.

A completed summary alone is not accepted: each selected run's export is opened and checked (row count = buckets x
roads, road order identical to segments.parquet, consecutive 10-min UTC buckets, phase labels, provenance columns,
closure mask vs the scheduled restrictions in scenarios.json).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from functools import lru_cache

from .config import ML_DIR, Config, SF_TZ, read_json, save_json, sha256_file

MANIFEST_VERSION = 1


def local_to_utc(date: str, sec: float) -> datetime:
    """Seconds since local midnight of `date` (SF) -> aware UTC datetime (DST-correct)."""
    midnight = datetime.fromisoformat(date).replace(tzinfo=SF_TZ)
    return (midnight + timedelta(seconds=float(sec))).astimezone(timezone.utc)


def inventory(cfg: Config) -> list[dict]:
    """Status of every batch on disk (read-only; running generation jobs are not touched)."""
    rows = []
    for b in sorted((cfg.sim_root / "batches").iterdir()):
        if not (b / "scenarios.json").exists():
            continue
        sc = read_json(b / "scenarios.json")
        runs = [r["run_id"] for r in sc.get("runs", [])]
        done = [r for r in runs if (b / "runs" / r / "summary.json").exists()]
        exported = [r for r in runs if (b / "export" / f"sim_{r}.parquet").exists()]
        rows.append({"batch": b.name, "schema_version": sc.get("schema_version"), "planned": len(runs),
                     "completed": len(done), "exported": len(exported), "quality_report": (b / "quality.csv").exists(),
                     "network_corrections": sc.get("network_corrections"), "review_version": sc.get("review_version")})
    return rows


def network_version(cfg: Config) -> dict:
    net = cfg.net_dir
    cw_cols = pd.read_csv(net / "crosswalk.csv", nrows=1).columns.tolist()
    files = ["network.json", "crosswalk.csv", "arcs_c90.json", "patch.con.xml", "net_c90.net.xml"]
    hashes = {f: sha256_file(net / f) for f in files if (net / f).exists()}
    tag = "v3" if "merged_parallel_into" in cw_cols else "v2"
    return {"dir": cfg.data.network, "family": tag, "files": hashes,
            "version": f"{cfg.data.network}-{hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()[:12]}",
            "network_json": read_json(net / "network.json")}


def _expected_network(sc: dict) -> str:
    corr = str(sc.get("network_corrections", ""))
    return "v3" if corr.startswith("v3") or sc.get("schema_version", 0) >= 3 else "v2"


@lru_cache(maxsize=8)
def _represented(net_dir: str) -> dict:
    p = ML_DIR / "data" / "sf_citywide" / net_dir / "crosswalk.csv"
    if not p.exists():
        return {}
    cw = pd.read_csv(p)
    if "merged_parallel_into" not in cw.columns:
        return {}
    return {r: m for r, m in zip(cw.road_segment_id, cw.merged_parallel_into) if isinstance(m, str)}


def represented_map(sc: dict) -> dict:
    """Network v3 merges parallel carriageways into one SUMO edge: segment id -> the id that carries it. A closure on
    a merged carriageway is simulated (and measured) on the representing edge (citywide_batch.BatchContext)."""
    return _represented(sc.get("network_dir") or "net")


def with_represented(ids, rep: dict) -> list[str]:
    return sorted(set(ids) | {rep[s] for s in ids if s in rep})


def scheduled_closed(run: dict, fam: dict, times: pd.DatetimeIndex, roads: pd.Index, bucket_s: int,
                     represented: dict | None = None) -> np.ndarray:
    """[T, R] fraction of each bucket covered by a scheduled full restriction (from scenarios.json only). With
    `represented`, a closed merged carriageway also closes the edge that represents it (as simulated)."""
    out = np.zeros((len(times), len(roads)), np.float32)
    t0 = times.asi8 // 10**9
    for r in run["restrictions"]:
        if r.get("restriction") != "full":
            continue
        b = local_to_utc(fam["date"], r["begin_s"]).timestamp()
        e = local_to_utc(fam["date"], r["end_s"]).timestamp()
        cover = np.clip((np.minimum(t0 + bucket_s, e) - np.maximum(t0, b)) / bucket_s, 0, 1)
        ids = with_represented(r["segment_ids"], represented) if represented else r["segment_ids"]
        idx = roads.get_indexer([s for s in ids if s in roads])
        idx = idx[idx >= 0]
        if len(idx):
            out[:, idx] = np.maximum(out[:, idx], cover[:, None])
    return out


def check_run(cfg: Config, run: dict, fam: dict, seg: pd.DataFrame, represented: dict | None = None) -> dict:
    path = cfg.batch_dir / "export" / f"sim_{run['run_id']}.parquet"
    res = {"run_id": run["run_id"], "file": path.name, "problems": []}
    if not path.exists():
        res["problems"].append("export parquet missing")
        return res
    if not (cfg.batch_dir / "runs" / run["run_id"] / "summary.json").exists():
        res["problems"].append("run summary.json missing")
    meta = pq.ParquetFile(path).metadata
    R = len(seg)
    need = {"time", "road_segment_id", "speed_mph", "free_flow_speed_mph", "congestion_ratio", "travel_time_s",
            "observed", "closed", "in_sumo", "phase", "run_id", "synthetic", "source", "with_event"}
    cols = set(pq.ParquetFile(path).schema_arrow.names)
    if need - cols:
        res["problems"].append(f"missing columns {sorted(need - cols)}")
        return res
    if meta.num_rows % R:
        res["problems"].append(f"rows {meta.num_rows} not a multiple of {R} roads")
        return res
    T = meta.num_rows // R
    t = pq.read_table(path, columns=["time", "road_segment_id", "phase", "closed", "observed", "in_sumo", "run_id",
                                     "synthetic", "source", "with_event", "travel_time_s"]).to_pandas()
    ids = t.road_segment_id.to_numpy().reshape(T, R)
    if not (ids == seg.road_segment_id.to_numpy()[None, :]).all():
        res["problems"].append("road order differs from segments.parquet")
    tv = t.time.values.astype("datetime64[s]").astype(np.int64).reshape(T, R)   # UTC epoch seconds
    times = pd.to_datetime(tv[:, 0], unit="s", utc=True)
    if (tv != tv[:, :1]).any():
        res["problems"].append("time not constant within a bucket")
    step = np.diff(times.asi8 // 10**9)
    if len(step) and not (step == cfg.data.bucket_min * 60).all():
        res["problems"].append("buckets not consecutive 10-min steps")
    if set(t.run_id.astype(str).unique()) != {run["run_id"]}:
        res["problems"].append("run_id column mismatch")
    if not t.synthetic.all() or set(t.source.astype(str).unique()) != {"sumo_synthetic"}:
        res["problems"].append("provenance columns not synthetic/sumo_synthetic")
    if bool(t.with_event.iloc[0]) != bool(run["with_event"]):
        res["problems"].append("with_event mismatch")
    phase = t.phase.to_numpy().reshape(T, R)[:, 0].astype(str)
    obs = t.observed.to_numpy().reshape(T, R)
    tt = t.travel_time_s.to_numpy().reshape(T, R)
    if (obs & ~np.isfinite(tt)).any() or (~obs & np.isfinite(tt)).any():
        res["problems"].append("observed mask disagrees with travel_time_s nulls")
    in_sumo = seg.in_sumo.to_numpy()
    if obs[:, ~in_sumo].any():
        res["problems"].append("observations on roads without a SUMO edge")
    closed = t.closed.to_numpy().reshape(T, R)
    sched = scheduled_closed(run, fam, times, pd.Index(seg.road_segment_id), cfg.data.bucket_min * 60, represented)
    cmp = in_sumo[None, :]
    full = (sched >= 1.0) & cmp
    anyc = (sched > 0) & cmp
    res.update({
        "buckets": T, "first_bucket_utc": times[0].isoformat(), "last_bucket_utc": times[-1].isoformat(),
        "phase_counts": {p: int((phase == p).sum()) for p in ("warmup", "demand", "drain")},
        "observed_share_in_sumo": round(float(obs[:, in_sumo].mean()), 4),
        "closed_cells": int(closed.sum()),
        "closure_schedule_check": {
            "sim_closed_and_scheduled_full": int((closed & full).sum()),
            "sim_closed_not_scheduled_any": int((closed & ~anyc & cmp).sum()),
            "scheduled_full_not_sim_closed": int((full & ~closed).sum()),
        },
        "observed_while_closed": int((obs & closed).sum()),
    })
    if res["closure_schedule_check"]["sim_closed_not_scheduled_any"]:
        res["problems"].append("closed mask outside any scheduled restriction")
    return res


def split_groups(groups: list[str], cfg: Config) -> dict:
    """Deterministic event-group split: order groups by sha256(salt:group); first n_test -> test, next n_val -> val."""
    fx = cfg.data.fixed_split
    if fx:   # explicit event groups (keeps val/test stable when event groups are added)
        missing = [g for p in ("val", "test") for g in fx[p] if g not in groups]
        if missing:
            raise SystemExit(f"fixed_split groups have no selected runs: {missing}")
        held = set(fx["val"]) | set(fx["test"])
        return {"test": list(fx["test"]), "val": list(fx["val"]), "train": sorted(g for g in groups if g not in held),
                "kind": "primary" if len(groups) >= len(held) + 2 else "development (too few event groups)",
                "rule": f"fixed: val {fx['val']}, test {fx['test']}, all other groups train"}
    order = sorted(groups, key=lambda g: hashlib.sha256(f"{cfg.data.split_salt}:{g}".encode()).hexdigest())
    n_t, n_v = cfg.data.n_test_groups, cfg.data.n_val_groups
    kind = "primary"
    if len(order) < n_t + n_v + 2:
        kind = "development (too few event groups for a held-out generalization claim)"
    return {"test": order[:n_t], "val": order[n_t:n_t + n_v], "train": order[n_t + n_v:], "kind": kind,
            "rule": f"groups ordered by sha256('{cfg.data.split_salt}:<family_group>'); first {n_t} test, next {n_v} val"}


def run(cfg: Config) -> dict:
    from .data import HIST_FEATURES, STATIC_FEATURES, TIME_FEATURES, FUTURE_BASE_FEATURES
    from .events import EVENT_PAIR_FEATURES

    bdir = cfg.batch_dir
    if cfg.data.batch in cfg.data.excluded_batches:
        raise SystemExit(f"{cfg.data.batch} is excluded by config")
    inv = inventory(cfg)
    sc = read_json(bdir / "scenarios.json")
    netv = network_version(cfg)
    if _expected_network(sc) != netv["family"]:
        raise SystemExit(f"batch {cfg.data.batch} was simulated on a {_expected_network(sc)} network but "
                         f"{cfg.data.network} is {netv['family']}; refusing to mix network versions")
    if sc.get("network_dir") and sc["network_dir"] != cfg.data.network:
        raise SystemExit(f"batch network_dir={sc['network_dir']} but config network={cfg.data.network}")
    gate = read_json(bdir / "gate.json") if (bdir / "gate.json").exists() else None
    if gate is not None and not gate.get("passed"):
        raise SystemExit(f"{cfg.data.batch} did not pass its quality gate; not overriding it")
    seg = pd.read_parquet(bdir / "export" / "segments.parquet")
    exp_manifest = read_json(bdir / "export" / "manifest.json")
    quality = pd.read_csv(bdir / "quality.csv").set_index("run_id")
    fams = {f["family_id"]: f for f in sc["families"]}
    cw = pd.read_csv(cfg.net_dir / "crosswalk.csv").set_index("road_segment_id")
    problems = []
    if list(seg.road_segment_id) != sorted(seg.road_segment_id):
        problems.append("segments.parquet not in sorted canonical order")
    if ((cw.loc[seg.road_segment_id, "n_sumo_edges"].to_numpy() > 0) != seg.in_sumo.to_numpy()).any():
        problems.append("segments.parquet in_sumo disagrees with network crosswalk")

    checks, runs_by_family = {}, {}
    for r in sc["runs"]:
        print(f"checking {r['run_id']}", flush=True)
        checks[r["run_id"]] = check_run(cfg, r, fams[r["family_id"]], seg, represented_map(sc))
        runs_by_family.setdefault(r["family_id"], []).append(r)

    selected, excluded = [], []
    for fid, runs in runs_by_family.items():
        reasons = {}
        for r in runs:
            rid = r["run_id"]
            q = quality.loc[rid, "quality_flag"] if rid in quality.index else "unreported"
            why = []
            if q != "ok":
                row = quality.loc[rid] if rid in quality.index else None
                detail = "" if row is None else (f" (unfinished={row.unfinished}, teleports/1k={row.teleports_per_1k}, "
                                                 f"steady closed entries={row.closed_entries_steady})")
                why.append(f"quality_flag={q}{detail}")
            why += checks[rid]["problems"]
            reasons[rid] = why
        kinds = {bool(r["with_event"]) for r in runs}
        pair_ok = kinds == {True, False} and not any(reasons.values())
        for r in runs:
            rid = r["run_id"]
            rec = {"run_id": rid, "family_id": fid, "family_group": r["family_group"], "event_key": r["event_key"],
                   "with_event": r["with_event"], "seed": r["seed"], "window": fams[fid]["window"]}
            if pair_ok:
                selected.append(rec)
            else:
                own = reasons[rid]
                partner = [f"{o}: {', '.join(v)}" for o, v in reasons.items() if o != rid and v]
                rec["reasons"] = own + ([f"paired run excluded ({'; '.join(partner)})"] if partner else [])
                excluded.append(rec)
    groups = sorted({r["family_group"] for r in selected})
    split = split_groups(groups, cfg)
    part = {g: p for p in ("train", "val", "test") for g in split[p]}
    for r in selected:
        r["partition"] = part[r["family_group"]]

    in_files = {"scenarios.json": bdir / "scenarios.json", "quality.csv": bdir / "quality.csv",
                "export/manifest.json": bdir / "export" / "manifest.json",
                "export/segments.parquet": bdir / "export" / "segments.parquet",
                "prepared/patch.json": cfg.sim_root / "prepared" / "patch.json"}
    if gate is not None:
        in_files["gate.json"] = bdir / "gate.json"
    in_files.update({f"export/sim_{r['run_id']}.parquet": bdir / "export" / f"sim_{r['run_id']}.parquet"
                     for r in selected})
    print("hashing inputs", flush=True)
    hashes = {k: sha256_file(p) for k, p in in_files.items()}
    all_roads = seg.road_segment_id.tolist()
    model_mask = seg.in_sumo.to_numpy() & (seg.car_access == "yes").to_numpy()
    model_roads = seg.road_segment_id[model_mask].tolist()
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "dataset_id": cfg.data.dataset_id,
        "batch": cfg.data.batch,
        "batch_schema_version": sc.get("schema_version"),
        "network": {k: v for k, v in netv.items() if k != "network_json"},
        "network_summary": netv["network_json"],
        "review_version": sc.get("review_version"),
        "sampler_version": sc.get("sampler_version"),
        "quality_gate": gate,
        "bucket_s": cfg.data.bucket_min * 60,
        "time_convention": "UTC bucket start; bucket covers [time, time + 10 min); SF local time for calendar features",
        "history_steps": cfg.data.history_steps, "horizon_steps": cfg.data.horizon_steps,
        "window_phases": cfg.data.phases,
        "selected_runs": sorted(selected, key=lambda r: r["run_id"]),
        "excluded_runs": sorted(excluded, key=lambda r: r["run_id"]),
        "excluded_batches": [{"batch": b["batch"], "reason": _batch_reason(b, cfg)} for b in inv
                             if b["batch"] != cfg.data.batch],
        "roads": {"all_count": len(all_roads), "model_count": len(model_roads),
                  "all_order": "segments.parquet order (sorted canonical OSM u-v-key)",
                  "all_sha256": hashlib.sha256("\n".join(all_roads).encode()).hexdigest(),
                  "model_rule": "in_sumo and car_access == 'yes' (others: unavailable / restricted, never predicted)",
                  "model_sha256": hashlib.sha256("\n".join(model_roads).encode()).hexdigest(),
                  "not_modelled": {"not_in_sumo": seg.gap[~seg.in_sumo].value_counts().to_dict(),
                                   "no_passenger_access": seg.car_access[seg.in_sumo & (seg.car_access != "yes")]
                                   .value_counts().to_dict()}},
        "feature_schema": {"history": HIST_FEATURES, "time": TIME_FEATURES, "static": STATIC_FEATURES,
                           "future_base": FUTURE_BASE_FEATURES, "event_pair": EVENT_PAIR_FEATURES,
                           "target": "z = log(travel_time_s / (length_m / free_flow_mps)); travel_time_s = "
                                     "length_m / max(speed_mps, 0.1) from the export",
                           "excluded_inputs": ["throughput_vph", "vehicles_entered", "sampled_vehicle_s",
                                               "exact event vehicle counts / attendance sampled for the run",
                                               "arrival curves, driver/routing parameters", "batch/family/seed/partition ids"]},
        "input_sha256": hashes,
        "provenance": {"scenarios": sc.get("provenance"), "export_status": exp_manifest.get("status"),
                       "export_separation": exp_manifest.get("separation"), "source": "sumo_synthetic",
                       "synthetic": True},
        "split": {**split, "assignments": {r["run_id"]: r["partition"] for r in selected}},
    }
    ddir = cfg.dataset_dir
    mpath = ddir / "manifest.json"
    if mpath.exists():
        old = read_json(mpath)
        old_core = {k: v for k, v in old.items() if k != "created_at"}
        if json.dumps(old_core, sort_keys=True, default=str) != json.dumps(manifest, sort_keys=True, default=str):
            raise SystemExit(f"{mpath} exists with different content; datasets are immutable. "
                             "Set data.dataset_id to a new id.")
        print(f"manifest unchanged: {mpath}")
    else:
        manifest["created_at"] = datetime.now(timezone.utc).isoformat()
        save_json(mpath, manifest)
    splits = {"dataset_id": cfg.data.dataset_id, **split,
              "runs": {p: sorted(r["run_id"] for r in selected if r["partition"] == p) for p in ("train", "val", "test")}}
    if not (ddir / "splits.json").exists():
        save_json(ddir / "splits.json", splits)
    elif read_json(ddir / "splits.json") != json.loads(json.dumps(splits)):
        raise SystemExit("splits.json exists with different assignments; splits are frozen")
    save_json(ddir / "audit.json", {"inventory": inv, "checks": checks, "problems": problems})
    return {"manifest": str(mpath), "selected": len(selected), "excluded": len(excluded), "groups": groups,
            "split": {p: split[p] for p in ("train", "val", "test")}, "problems": problems}


def _batch_reason(b: dict, cfg: Config) -> str:
    if b["batch"] in cfg.data.excluded_batches:
        return "calibration runs (config.excluded_batches)"
    if not b["quality_report"] or b["exported"] < b["planned"]:
        return (f"not ready: {b['completed']}/{b['planned']} runs completed, {b['exported']} exported, "
                f"quality report {'present' if b['quality_report'] else 'missing'}")
    return (f"complete, but a different batch/network generation (schema v{b['schema_version']}) than the selected "
            "dataset; one network version per dataset (no v2/v3 mixing)")
