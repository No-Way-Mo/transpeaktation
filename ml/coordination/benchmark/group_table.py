"""Per-group routing table (standard section 5): app users vs everyone else, per participation level / crowd / policy, paired with forecast_only on the same
(scenario, seed): same app-user set (participation digest-checked per block by the runner).

    python -m coordination.benchmark.group_table <experiment data dir> <out.md> "<title>"

<experiment data dir> holds heldout_*/runs/<policy>/<scenario>_s<seed>.json (a backtest / fireworks out_dir).
Writes <out.md> (full) and <out>_compact.md (one row per participation x crowd x policy)."""
import json, re, sys
from pathlib import Path
import numpy as np, pandas as pd


def main(argv: list[str]) -> None:
    root, out, title = Path(argv[0]), Path(argv[1]), argv[2]
    rows = []
    for f in root.glob("heldout_*/runs/*/*.json"):
        d = json.loads(f.read_text()); s = d.get("summary") or {}
        if d.get("status") != "ok" or not s:
            continue
        p = int(re.search(r"_p(\d+)_c", d["experiment_id"]).group(1))
        o = s["outcomes"]; P = s["participants"]; N = s["in_scope_vehicles"]
        rows.append({"participation": p, "crowd": int(re.search(r"_n(\d+)_", d["scenario"]).group(1)), "scenario": d["scenario"],
                     "seed": d["seed_offset"], "policy": d["policy"], "teleports": s["teleports"],
                     "vh_all": s["in_scope_vehicle_hours"], "app_n": P, "other_n": N - P,
                     "app_home": o["participants"]["arrived"], "other_home": o["others"]["arrived"],
                     "app_trip": o["participants"]["trip_s_mean"], "app_p95": o["participants"]["trip_s_p95"],
                     "other_trip": o["others"]["trip_s_mean"], "other_p95": o["others"]["trip_s_p95"],
                     "app_loss": o["participants"]["time_loss_s_mean"], "other_loss": o["others"].get("time_loss_s_mean"),
                     "app_km": o["participants"]["route_m_mean"] / 1000, "other_km": (o["others"].get("route_m_mean") or np.nan) / 1000,
                     "app_kmh": o["participants"]["route_m_mean"] / o["participants"]["trip_s_mean"] * 3.6,
                     "other_kmh": ((o["others"].get("route_m_mean") or np.nan) / o["others"]["trip_s_mean"] * 3.6) if o["others"].get("trip_s_mean") else np.nan,
                     "congested_h": s["congestion"]["congested_h_scope"], "stopped_h": s["congestion"]["stopped_h_scope"]})
    df = pd.DataFrame(rows)
    base = df[df.policy == "forecast_only"].set_index(["participation", "scenario", "seed"])
    res = []
    for (p, c, pol), g in df[df.policy != "forecast_only"].groupby(["participation", "crowd", "policy"]):
        j = g.set_index(["participation", "scenario", "seed"]).join(base, rsuffix="_b", how="inner")
        if j.empty:
            continue
        assert (j.app_n == j.app_n_b).all(), "app-user count differs within a block"
        pct = lambda a, b: 100 * ((j[a] - j[b]) / j[b]).mean()
        res.append({"participation %": p, "crowd cars": c, "policy": pol, "pairs": len(j),
                    "app users": int(j.app_n.mean()),
                    "APP home by 01:00 (base -> policy)": f"{j.app_home_b.mean() / j.app_n.mean():.1%} -> {j.app_home.mean() / j.app_n.mean():.1%}",
                    "APP mean trip min (base -> policy)": f"{j.app_trip_b.mean() / 60:.1f} -> {j.app_trip.mean() / 60:.1f}",
                    "APP mean trip %": round(pct("app_trip", "app_trip_b"), 1),
                    "APP p95 trip %": round(pct("app_p95", "app_p95_b"), 1),
                    "OTHERS home (base -> policy)": (f"{j.other_home_b.mean() / j.other_n.mean():.1%} -> {j.other_home.mean() / j.other_n.mean():.1%}"
                                                     if j.other_n.mean() else "-"),
                    "OTHERS mean trip %": round(pct("other_trip", "other_trip_b"), 1) if j.other_n.mean() else None,
                    "OTHERS p95 trip %": round(pct("other_p95", "other_p95_b"), 1) if j.other_n.mean() else None,
                    "APP avg speed km/h (base -> policy)": f"{j.app_kmh_b.mean():.1f} -> {j.app_kmh.mean():.1f}",
                    "APP time lost min (base -> policy)": f"{j.app_loss_b.mean() / 60:.1f} -> {j.app_loss.mean() / 60:.1f}",
                    "APP route km (base -> policy)": f"{j.app_km_b.mean():.1f} -> {j.app_km.mean():.1f}",
                    "OTHERS avg speed km/h (base -> policy)": (f"{j.other_kmh_b.mean():.1f} -> {j.other_kmh.mean():.1f}" if j.other_n.mean() else "-"),
                    "OTHERS time lost min (base -> policy)": (f"{j.other_loss_b.mean() / 60:.1f} -> {j.other_loss.mean() / 60:.1f}" if j.other_n.mean() else "-"),
                    "network congested h %": round(pct("congested_h", "congested_h_b"), 1),
                    "network stopped h %": round(pct("stopped_h", "stopped_h_b"), 1),
                    "ALL vehicle-hours %": round(pct("vh_all", "vh_all_b"), 1),
                    "teleports": int(j.teleports.sum() + j.teleports_b.sum())})
    r = pd.DataFrame(res).sort_values(["participation %", "crowd cars", "policy"], ascending=[False, True, True])
    md = lambda t: "\n".join(["| " + " | ".join(map(str, t.columns)) + " |", "|" + "---|" * len(t.columns)] +
                             ["| " + " | ".join("" if v is None or (isinstance(v, float) and np.isnan(v)) else str(v) for v in row) + " |" for row in t.itertuples(index=False)])
    L = [f"# {title}: app users vs everyone else", "",
         "> **Synthetic** (SUMO, Rule 0: no teleporting). Each row: mean over the matched (scenario, seed) pairs of the policy "
         "vs `forecast_only` with the SAME app-user set. `home` = share of that group that reached its destination by 01:00. "
         "Trip times are means / p95 over trips completed by 01:00, counted from the scheduled departure (include waits); "
         "read them together with `home`, because a policy that leaves more cars out has a shorter completed-trip average. "
         "Negative % = better. Average speed = mean route length / mean trip time of completed trips; time lost = SUMO "
         "timeLoss (time below the free-flow speed). Network congested / stopped hours: all in-scope vehicles, speed <= 50% "
         "of free flow / < 0.1 m/s.", "", md(r), ""]
    out.write_text("\n".join(L), encoding="utf-8")
    print(out)
    full = pd.DataFrame({
        "part.": r["participation %"].astype(str) + "%", "crowd": r["crowd cars"], "policy": r["policy"].str.replace("heuristic@lam=500", "heuristic").str.replace("rl_ppo", "PPO"),
        "app home": r["APP home by 01:00 (base -> policy)"], "app trip %": r["APP mean trip %"], "app p95 %": r["APP p95 trip %"],
        "app km/h": r["APP avg speed km/h (base -> policy)"],
        "others home": r["OTHERS home (base -> policy)"], "others trip %": r["OTHERS mean trip %"], "others p95 %": r["OTHERS p95 trip %"],
        "others km/h": r["OTHERS avg speed km/h (base -> policy)"],
        "all veh-h %": r["ALL vehicle-hours %"], "congested h %": r["network congested h %"], "teleports": r["teleports"]})
    print(md(full))
    Path(str(out).replace(".md", "_compact.md")).write_text(md(full), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
