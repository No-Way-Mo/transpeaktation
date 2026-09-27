"""Stage 7: closed-loop routing replay on held-out scenarios.

    python -m eventsim replay --event castro --runs 3 --probe-share 0.3

For each selected test event run, SUMO is re-run once per routing policy with the *same* demand, restrictions and
seed. A fixed share of trips ("probes", same vehicles for every policy) is routed by the policy:

    no_info      free-flow travel times (posted limits), i.e. a navigator without traffic data
    persistence  current observed travel times
    event_rule   persistence x hand-written event multiplier near the footprint
    learned      persistence + learned residual (10-min horizon)

Every policy gets the same information: its own run's provider-like observations up to the last closed 10-min
bucket (features.ObsModel), the published closure schedule, the declared event hours and estimate. No policy sees
future simulator states. Known closures are unusable for every policy (lane permissions). Probes are routed at
departure and re-routed at each new bucket. Background vehicles keep their own SUMO rerouting behaviour.

Outputs: ml/data/<event>/replay/<run>/<policy>/{trips.csv, summary.json}, ml/reports/<event>_replay.md
"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .config import BUCKET_S, REPORTS_DIR
from .features import (MIN_SAMPLED_S, ObsModel, Static, build_features, declared_estimate, event_rule, persistence)
from .simulate import (Context, build_trips, closure_mask, parse_stats, parse_tripinfo, restrictions_for, sumo_cmd,
                       variant_net, write_additional, write_routes)

POLICIES = ("no_info", "persistence", "event_rule", "learned")
STEP_CHUNK = 5     # s; TraCI advance + edge speed sampling period (divides BUCKET_S)


def probe_ids(trips: list[dict], share: float, seed: int) -> set[str]:
    rng = np.random.default_rng(seed)
    return {t["id"] for t in trips if rng.random() < share}


def replay_one(ev_key: str, run: dict, policy: str, share: float) -> dict:
    import traci
    import traci.constants as tc
    ctx = Context(ev_key)
    st = Static(ctx)
    fam = ctx.fams[run["family_id"]]
    t_cfg = ctx.scen["time"]
    out = ctx.dir / "replay" / run["run_id"] / policy
    out.mkdir(parents=True, exist_ok=True)
    trips = build_trips(ctx, run)
    probes = probe_ids(trips, share, run["seed"] + 5)
    write_routes(trips, fam, out / "trips.rou.xml", probe_ids=probes)
    restr = restrictions_for(ctx, fam, run["with_event"])
    net = variant_net(ctx, fam, write_additional(ctx, restr, out))
    closed = closure_mask(ctx, restr).astype(bool)
    T = closed.shape[0]
    model = None
    if policy == "learned":
        from .train import load_model
        model = load_model(ev_key)
    obs = ObsModel(st, fam["observation"], run["seed"] + 2, T)
    est = declared_estimate(fam, run["with_event"], np.random.default_rng(run["seed"] + 3))
    declared = tuple(ctx.scen["declared_event_hours_s"]) if run["with_event"] else None
    # traci.start has no cwd: make run-local files absolute
    local = {"trips.rou.xml", "closures.add.xml", "tripinfo.xml", "stats.xml"}
    cmd = [str(out / c) if c in local else c for c in sumo_cmd(ctx, fam, run, net)]
    label = f"{run['run_id']}_{policy}_{os.getpid()}"
    t0 = time.time()
    traci.start(cmd, label=label, stdout=open(os.devnull, "w"))
    con = traci.getConnection(label)
    sim_ids = [s for s, ok in zip(ctx.seg_ids, st.in_sim) if ok]
    sim_idx = np.array([ctx.idx[s] for s in sim_ids])
    for s in sim_ids:
        con.edge.subscribe(s, [tc.LAST_STEP_MEAN_SPEED, tc.LAST_STEP_VEHICLE_NUMBER])
    acc_sv = np.zeros(st.n)
    acc_n = np.zeros(st.n)
    tt_now = st.ff_tt.copy()
    active_probes: set[str] = set()
    seen: set[str] = set()
    n_reroutes = 0

    def push_weights(tt):
        for s, j in zip(sim_ids, sim_idx):
            con.edge.adaptTraveltime(s, float(tt[j]))

    push_weights(tt_now)
    now = float(t_cfg["sim_begin_s"])
    end = t_cfg["sim_end_s"]
    while now < end:
        now += STEP_CHUNK   # advance in chunks: one TraCI round-trip per STEP_CHUNK simulated seconds
        con.simulationStep(now)
        alive = set(con.vehicle.getIDList())
        for v in alive - seen:
            if v in probes:  # route right after departure with the policy's current travel times
                active_probes.add(v)
                con.vehicle.rerouteTraveltime(v, False)
                n_reroutes += 1
        seen |= alive
        res = con.edge.getAllSubscriptionResults()
        for s, j in zip(sim_ids, sim_idx):
            r = res.get(s)
            if r:
                n = r[tc.LAST_STEP_VEHICLE_NUMBER]
                if n:
                    acc_sv[j] += r[tc.LAST_STEP_MEAN_SPEED] * n
                    acc_n[j] += n
        if (now - t_cfg["sim_begin_s"]) % BUCKET_S == 0:
            b = int((now - t_cfg["sim_begin_s"]) // BUCKET_S) - 1
            if 0 <= b < T:
                speed = np.where(acc_n > 0, acc_sv / np.maximum(acc_n, 1), np.nan)
                measured = acc_n * STEP_CHUNK >= MIN_SAMPLED_S
                obs.observe(b, np.nan_to_num(speed), measured)
                acc_sv[:] = 0
                acc_n[:] = 0
                if policy != "no_info":
                    base = persistence(st, obs, b)
                    if policy == "persistence":
                        tt_now = base[0]
                    elif policy == "event_rule":
                        target_s = t_cfg["sim_begin_s"] + (b + 1) * BUCKET_S + BUCKET_S / 2
                        tt_now = event_rule(st, base[0], target_s, declared)
                    else:
                        X = build_features(st, obs, b, 1, sim_begin_s=t_cfg["sim_begin_s"], closed=closed,
                                           declared=declared, event_estimate=est, base=base)
                        tt_now = model.predict_tt(X, base[0], np.arange(st.n))
                    push_weights(tt_now)
                    active_probes &= alive
                    for v in active_probes:
                        try:
                            con.vehicle.rerouteTraveltime(v, False)
                            n_reroutes += 1
                        except traci.TraCIException:
                            pass
    con.close()
    runtime = time.time() - t0
    kinds = {t["id"]: t["kind"] for t in trips}
    ti = parse_tripinfo(out / "tripinfo.xml", kinds)
    missing = sorted(set(kinds) - set(ti["id"]))
    if missing:
        ti = pd.concat([ti, pd.DataFrame({"id": missing, "kind": [kinds[i] for i in missing], "arrived": False})],
                       ignore_index=True)
    ti["probe"] = ti["id"].isin(probes)
    ti.to_csv(out / "trips.csv", index=False)
    stats = parse_stats(out / "stats.xml")
    for f in ("edgedata.xml", "tripinfo.xml"):
        try:
            (out / f).unlink(missing_ok=True)
        except PermissionError:
            pass
    arr = ti[ti.arrived]
    summ = {
        "run_id": run["run_id"], "family_id": run["family_id"], "policy": policy, "seed": run["seed"],
        "probe_share": share, "probes": len(probes), "trips": len(ti), "runtime_s": round(runtime, 1),
        "reroutes": n_reroutes, "arrived": int(ti.arrived.sum()), "unfinished": int((~ti.arrived).sum()),
        "teleports": int(stats.get("teleports", {}).get("total", 0)),
        "mean_duration_all_s": float(arr.duration.mean()), "mean_timeloss_all_s": float(arr.time_loss.mean()),
        "mean_duration_probe_s": float(arr[arr.probe].duration.mean()),
        "mean_timeloss_probe_s": float(arr[arr.probe].time_loss.mean()),
        "mean_duration_nonprobe_s": float(arr[~arr.probe].duration.mean()),
        "total_timeloss_veh_h": float(arr.time_loss.sum() / 3600),
        "unfinished_probe": int((~ti.arrived & ti.probe).sum()),
    }
    (out / "summary.json").write_text(json.dumps(summ, indent=1))
    return summ


def pick_runs(ctx: Context, n: int) -> list[dict]:
    split = json.loads((ctx.dir / "dataset" / "splits.json").read_text())["families"]
    test_fams = sorted(f for f, s in split.items() if s == "test")
    runs = []
    for f in test_fams:
        r = next((r for r in ctx.scen["runs"] if r["family_id"] == f and r["with_event"]), None)
        if r:
            runs.append(r)
    return runs[:n]


def run(ev, n_runs: int, share: float, workers: int) -> dict:
    ctx = Context(ev.key)
    runs = pick_runs(ctx, n_runs)
    jobs = [(r, p) for r in runs for p in POLICIES]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(replay_one, [ev.key] * len(jobs), [j[0] for j in jobs], [j[1] for j in jobs],
                          [share] * len(jobs)))
    df = pd.DataFrame(res)
    df.to_csv(ctx.dir / "replay" / "replay_summary.csv", index=False)
    write_report(ev, df, share)
    piv = df.pivot_table(index="run_id", columns="policy", values="mean_duration_probe_s")
    return {"runs": [r["run_id"] for r in runs], "mean_probe_duration_s": piv.round(1).to_dict()}


def write_report(ev, df: pd.DataFrame, share: float) -> None:
    cols = ["run_id", "policy", "mean_duration_probe_s", "mean_timeloss_probe_s", "mean_duration_nonprobe_s",
            "mean_duration_all_s", "total_timeloss_veh_h", "arrived", "unfinished", "unfinished_probe", "teleports",
            "runtime_s"]
    t = df[cols].sort_values(["run_id", "policy"])
    lines = [f"# Routing replay: {ev.name}", "",
             f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} by `python -m eventsim replay --event {ev.key}`.",
             "", "**Simulated outcomes.** Each held-out test scenario is re-simulated once per policy with identical demand, "
             f"restrictions and seed; {share:.0%} of trips (the same vehicles in every policy) are routed by the policy, "
             "at departure and at each new 10-min bucket. Route choices change congestion, so every number below comes "
             "from its own simulation, not from re-scoring paths on a fixed trace. Durations are actual simulated "
             "vehicle traversal times.", "",
             "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in t.itertuples(index=False):
        lines.append("| " + " | ".join(f"{v:.1f}" if isinstance(v, float) else str(v) for v in r) + " |")
    base = df[df.policy == "persistence"].set_index("run_id")
    lines += ["", "## Relative to persistence routing (probe mean duration)", ""]
    for p in POLICIES:
        if p == "persistence":
            continue
        cur = df[df.policy == p].set_index("run_id")
        diff = 100 * (cur.mean_duration_probe_s / base.mean_duration_probe_s - 1)
        allv = 100 * (cur.mean_duration_all_s / base.mean_duration_all_s - 1)
        lines.append(f"- {p}: probes {diff.mean():+.1f}% (per run: {', '.join(f'{x:+.1f}%' for x in diff)}); all vehicles "
                     f"{allv.mean():+.1f}%")
    lines += ["", "Negative = faster than persistence. Results vary by scenario and include runs where a policy is worse."]
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / f"{ev.key}_replay.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
