"""Simulation dynamics checks over all finished runs (event run vs its no-event control).

    python -m eventsim check --event castro      -> ml/reports/<event>_sim_checks.md (+ data/<event>/checks.csv)

Checks: closure enforcement, trip completion / lost / teleported vehicles, queue buildup and recovery,
detours onto alternative roads, boundary (insertion) backlog. A run that "looks fast" because only
fast trips finished is caught by the unfinished / not-inserted counts and depart delays.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .config import BUCKET_S, REPORTS_DIR
from .simulate import Context


def load_run(ctx: Context, rid: str):
    d = ctx.dir / "runs" / rid
    if not (d / "summary.json").exists():
        return None
    return (json.loads((d / "summary.json").read_text()), np.load(d / "measurements.npz"),
            pd.read_csv(d / "trips.csv"))


def pair_metrics(ctx: Context, ev, ctl, fam: dict) -> dict:
    t = ctx.scen["time"]
    s_e, m_e, t_e = ev
    s_c, m_c, t_c = ctl
    closed = m_e["closed"].astype(bool)
    ent = np.nan_to_num(m_e["entered"])
    # steady state = closed for >= 2 previous buckets; the first 20 min after a mid-day closure opens can still
    # admit vehicles that were already past the last upstream trigger edge (reported separately as onset)
    steady = np.zeros_like(closed)
    steady[2:] = closed[2:] & closed[1:-1] & closed[:-2]
    onset = closed & ~steady
    loss_e = np.nan_to_num(m_e["timeLoss"]).sum(1)
    loss_c = np.nan_to_num(m_c["timeLoss"]).sum(1)
    delta = loss_e - loss_c
    b_of = lambda s: int((s - t["sim_begin_s"]) // BUCKET_S)
    peak_b = int(np.argmax(delta))
    dep_b = b_of(fam["event"]["departure_mu_s"])
    rec = next((b for b in range(max(peak_b, dep_b), len(delta)) if delta[b] < 0.1 * max(delta.max(), 1)), None)
    # detours: open edges carrying much more traffic in the event run during declared event hours
    h0, h1 = ctx.scen["declared_event_hours_s"]
    win = slice(b_of(h0), b_of(h1))
    vol_e = np.nan_to_num(m_e["entered"][win]).sum(0)
    vol_c = np.nan_to_num(m_c["entered"][win]).sum(0)
    hours = (h1 - h0) / 3600
    open_ = ~closed.any(0)
    det = open_ & (vol_e - vol_c >= 30 * hours) & (vol_e >= 1.5 * np.maximum(vol_c, 1))
    names = pd.Series([ctx.patch["segments"][ctx.seg_ids[j]]["name"] for j in np.nonzero(det)[0]]).value_counts()
    entries = [ctx.idx[s] for s in ctx.entries]
    return {
        "run_id": s_e["run_id"], "family_id": s_e["family_id"], "closure_variant": fam["closure_variant"],
        "event_vehicle_trips": int(fam["event"]["vehicle_trips"] * fam["event"]["turnout_factor"]),
        "background_vph": round(fam["background_vph"]),
        "runtime_s_ev": s_e["runtime_s"], "runtime_s_ctl": s_c["runtime_s"],
        "trips_ev": s_e["trips_generated"], "arrived_share_ev": s_e["arrived"] / max(s_e["trips_generated"], 1),
        "unfinished_ev": s_e["unfinished"], "unfinished_ctl": s_c["unfinished"],
        "not_inserted_ev": s_e["not_inserted_or_no_route"], "not_inserted_ctl": s_c["not_inserted_or_no_route"],
        "teleports_ev": s_e["teleports"].get("total", 0), "teleports_ctl": s_c["teleports"].get("total", 0),
        "closed_edge_entries": float(ent[steady].sum()),
        "closure_onset_entries": float(ent[onset].sum()),
        "mean_trip_s_ev": t_e.loc[t_e.arrived, "duration"].mean(), "mean_trip_s_ctl": t_c.loc[t_c.arrived, "duration"].mean(),
        "bg_timeloss_s_ev": t_e.loc[(t_e.kind == "background") & t_e.arrived, "time_loss"].mean(),
        "bg_timeloss_s_ctl": t_c.loc[(t_c.kind == "background") & t_c.arrived, "time_loss"].mean(),
        "depart_delay_s_ev": t_e["depart_delay"].mean(), "depart_delay_s_ctl": t_c["depart_delay"].mean(),
        "peak_extra_delay_veh_h": float(delta.max() / 3600), "peak_local_time": (t["sim_begin_s"] + peak_b * BUCKET_S) / 3600,
        "recovered_local_time": None if rec is None else (t["sim_begin_s"] + rec * BUCKET_S) / 3600,
        "detour_edges": int(det.sum()), "detour_streets": ", ".join(f"{k} ({v})" for k, v in names.head(4).items()),
        "entry_waiting_s_ev": float(np.nan_to_num(m_e["waitingTime"][:, entries]).sum()),
        "entry_waiting_s_ctl": float(np.nan_to_num(m_c["waitingTime"][:, entries]).sum()),
    }


def run(ev) -> dict:
    ctx = Context(ev.key)
    rows = []
    for r in ctx.scen["runs"]:
        if not r["with_event"]:
            continue
        e = load_run(ctx, r["run_id"])
        c = load_run(ctx, r["run_id"].replace("_ev", "_ctl"))
        if e is None or c is None:
            continue
        rows.append(pair_metrics(ctx, e, c, ctx.fams[r["family_id"]]))
    if not rows:
        raise SystemExit("no finished event/control pairs")
    df = pd.DataFrame(rows)
    df.to_csv(ctx.dir / "checks.csv", index=False)
    problems = []
    if (df.closed_edge_entries > 0).any():
        problems.append(f"closure leaks in {int((df.closed_edge_entries > 0).sum())} runs")
    if ((df.unfinished_ev + df.not_inserted_ev) > 0.01 * df.trips_ev).any():
        problems.append("runs with >1% unfinished/not-inserted trips")
    if ((df.teleports_ev > 0.01 * df.trips_ev)).any():
        problems.append("runs with >1% teleports")
    fmt = lambda x: "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{int(x)}:{int(round(x % 1 * 60)):02d}"
    lines = [f"# Simulation checks: {ev.name}", "",
             f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} by `python -m eventsim check --event {ev.key}`. "
             "Each row compares an event run with its no-event control (same seed and background demand). "
             "All numbers are simulated.", "",
             f"- Event/control pairs: {len(df)}; families: {df.family_id.nunique()}",
             f"- SUMO runtime per run: median {df.runtime_s_ev.median():.0f} s (event), {df.runtime_s_ctl.median():.0f} s (control)",
             f"- Vehicles entering fully closed edges in steady state: {df.closed_edge_entries.sum():.0f}; during the first 20 min "
             f"after a closure opens (vehicles already committed past the last trigger edge, or already on it): "
             f"{df.closure_onset_entries.sum():.0f}",
             f"- Unfinished at sim end (event runs): total {df.unfinished_ev.sum()}, max {df.unfinished_ev.max()}; not inserted / no route: {df.not_inserted_ev.sum()}",
             f"- Teleports: event runs median {df.teleports_ev.median():.0f} (max {df.teleports_ev.max()}), controls median {df.teleports_ctl.median():.0f}; "
             "teleported vehicles still count as arrived, so they are listed per run",
             f"- Background time loss: event {df.bg_timeloss_s_ev.mean():.0f} s vs control {df.bg_timeloss_s_ctl.mean():.0f} s per trip (mean over runs)",
             f"- Runs whose event adds ≥ 1 vehicle-hour of delay in its peak 10 min: {(df.peak_extra_delay_veh_h >= 1).sum()}/{len(df)}",
             f"- Runs recovering (extra delay < 10% of peak) before sim end: {df.recovered_local_time.notna().sum()}/{len(df)}",
             f"- Status: {'; '.join(problems) if problems else 'no check failed'}", "",
             "| run | variant | event veh | bg vph | trips | unfinished | tele (ev/ctl) | closed entries | bg loss ev/ctl s | depart delay ev/ctl s | peak extra veh·h @ | recovered | detour edges (top streets) |",
             "|---|---|---:|---:|---:|---:|---|---:|---|---|---|---|---|"]
    for r in df.sort_values("run_id").itertuples():
        lines.append(f"| {r.run_id} | {r.closure_variant} | {r.event_vehicle_trips} | {r.background_vph} | {r.trips_ev} | {r.unfinished_ev} | "
                     f"{r.teleports_ev}/{r.teleports_ctl} | {r.closed_edge_entries:.0f} | {r.bg_timeloss_s_ev:.0f}/{r.bg_timeloss_s_ctl:.0f} | "
                     f"{r.depart_delay_s_ev:.0f}/{r.depart_delay_s_ctl:.0f} | {r.peak_extra_delay_veh_h:.1f} @ {fmt(r.peak_local_time)} | "
                     f"{fmt(r.recovered_local_time)} | {r.detour_edges} ({r.detour_streets}) |")
    lines += ["", "Boundary effects: the patch is cut at ~700 m; vehicles queue at entry edges when the boundary backs up "
              "(visible as depart delay, since SUMO waits to insert). Large event/control gaps in depart delay mean the "
              "patch boundary is constraining queues and the radius should grow."]
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / f"{ev.key}_sim_checks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"pairs": len(df), "problems": problems, "report": str(REPORTS_DIR / f"{ev.key}_sim_checks.md")}
