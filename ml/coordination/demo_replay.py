"""Export fireworks replays (independent vs coordinated routing) in the demo replay page's data format.

    python -m coordination.demo_replay --baseline <episode dir> --coordinated <episode dir> \
        --label "Coordinated (heuristic, lam 500)" --out ml/reports/fireworks_replay/data.js

The page is `demo/baseline.html` + `demo/replay.js` on main; its data schema is the one written by
`demo/sumo/view.py` (window.BASELINE). Inputs are episode folders of `coordination.rl.sumo_env` runs of the
b6_fireworks scenarios (eventsim/fireworks_demo.py) made with keep_outputs, TP_FCD_PERIOD_S=1 and
TP_FCD_PREFIX=user- (1 s positions of the 1000 app users, SUMO's per-second summary, 5-min edge data).

Like view.py nothing is interpolated: every app-user second is an FCD sample, except seconds in which SUMO
teleported the car (stuck > 300 s, moved past the jam). Those have no position; the car is held at its last sample
(not marked waiting: SUMO's waitingTime excludes teleport time), and the count of such seconds is recorded in the
data (`teleport_seconds`).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path

from eventsim import fireworks_demo as fd

T0 = fd.DAY_S["cohort_zero"]                          # 21:00 local = replay second 0
END = fd.DAY_S["sim_end"] - fd.DAY_S["cohort_zero"]   # 01:00


def _open(p: Path):
    return gzip.open(p, "rb") if p.suffix == ".gz" else open(p, "rb")


def tripinfo(p: Path) -> dict:
    return {e.get("id"): dict(e.attrib) for e in ET.parse(p).getroot().iter("tripinfo")}


def summarize(rows: dict, expected) -> dict:
    """demo/sumo/kit.py summarize(): status of every expected car, completed-only mean / nearest-rank p95."""
    statuses, complete = {}, {}
    for vid in expected:
        v = rows.get(vid)
        status = "missing"
        if v:
            if v.get("vaporized") not in ("", "end", None) or int(v.get("rerouteNo", "0")):
                status = "failed"
            elif float(v["depart"]) < 0:
                status = "not_departed"
            elif float(v["arrival"]) < 0:
                status = "unfinished"
            else:
                status = "completed"
                vals = {k: float(v[k]) for k in ("departDelay", "duration", "waitingTime", "timeLoss", "routeLength")}
                vals["total_seconds"] = vals["departDelay"] + vals["duration"]
                complete[vid] = vals
        statuses[vid] = status
    metrics = {}
    for k in next(iter(complete.values()), {}):
        xs = sorted(v[k] for v in complete.values())
        metrics[k] = dict(mean=statistics.mean(xs), p95=xs[math.ceil(.95 * len(xs)) - 1])
    return dict(counts={k: list(statuses.values()).count(k)
                        for k in ("completed", "unfinished", "not_departed", "failed", "missing")},
                metrics=metrics)


def _to_lonlat():
    """net_v3 has no geo projection (projParameter "!"), so SUMO's `--fcd-output.geo` still writes network metres.
    The network was built in eventsim's local equirectangular frame around prepared/patch.json `proj`."""
    from eventsim.geo import LocalProj
    pj = json.loads((fd.ROOT / "prepared" / "patch.json").read_text())["proj"]
    lp = LocalProj(pj["lon0"], pj["lat0"])
    return lambda x, y: (x / lp.kx + lp.lon0, y / lp.ky + lp.lat0) if abs(x) > 180 or abs(y) > 90 else (x, y)


def vehicles(fcd: Path, trips: dict, users: dict) -> tuple[list, dict]:
    ll = _to_lonlat()
    samples: dict = {}
    for _, e in ET.iterparse(_open(fcd)):
        if e.tag == "timestep":
            t = round(float(e.get("time"))) - T0
            for v in e.iter("vehicle"):
                if v.get("id") in users:
                    lon, lat = ll(float(v.get("x")), float(v.get("y")))
                    samples.setdefault(v.get("id"), []).append(
                        (t, lon, lat, float(v.get("speed")), float(v.get("waiting", 0))))
            e.clear()
    out, stats = [], {"teleport_seconds": 0, "cars_teleported": 0, "waiting_mismatch": 0}
    for vid in sorted(users):
        u, ti = users[vid], trips.get(vid)
        dep = round(float(ti["depart"])) - T0 if ti and float(ti["depart"]) >= 0 else None
        if dep is None:
            out.append([vid, u["depart"], None, False, u["origin_name"], u["destination_name"], []])
            continue
        arr = round(float(ti["arrival"])) - T0 if float(ti["arrival"]) >= 0 else None
        stop = min(arr if arr is not None else END, END)
        by_t = {s[0]: s for s in samples.get(vid, [])}
        if not by_t:
            raise SystemExit(f"{vid}: departed but has no FCD samples (was the run made with TP_FCD_PREFIX=user-?)")
        flat, px, py, last, gap = [], 0, 0, None, 0
        for t in range(dep, stop):
            s = by_t.get(t)
            if s is None:                 # teleporting: no position; hold the last sample. SUMO counts teleport time
                gap += 1                  # neither as waiting nor as halting, so it is not marked as waiting here
                s = (t, last[1], last[2], 0.0, 0.0) if last else (t, *next(iter(by_t.values()))[1:3], 0.0, 0.0)
            last = s
            x, y = round(s[1] * 1e5), round(s[2] * 1e5)
            row = [x - px, y - py, 0 if s[4] > 0 else 1 + round(s[3] * 10)]
            if row == [0, 0, 0] and len(flat) >= 3 and flat[-3:-1] == [0, 0] and flat[-1] <= 0:
                flat[-1] -= 1 if flat[-1] < 0 else 2
            else:
                flat += row
            px, py = x, y
        stats["teleport_seconds"] += gap
        stats["cars_teleported"] += int(gap > 0)
        waited = sum(1 for s in samples.get(vid, []) if dep <= s[0] < stop and s[4] > 0)
        stats["waiting_mismatch"] += int(arr is not None and not gap and waited != round(float(ti["waitingTime"])))
        out.append([vid, u["depart"], dep, arr is not None and arr <= END, u["origin_name"], u["destination_name"], flat])
    return out, stats


def totals(summary: Path) -> dict:
    rows = {}
    for _, e in ET.iterparse(_open(summary)):
        if e.tag == "step":
            t = round(float(e.get("time"))) - T0
            if 0 <= t < END:
                rows[t] = (int(e.get("running")), int(e.get("halting")), int(e.get("waiting")), int(e.get("arrived")))
            e.clear()
    last = (0, 0, 0, 0)
    out = {k: [] for k in ("running", "halting", "waiting", "arrived")}
    for t in range(END):            # after the run ended (every car arrived) the network stays empty
        r = rows.get(t)
        if r is None:
            r = (0, 0, 0, last[3]) if t > max(rows, default=-1) else last
        last = r
        for i, k in enumerate(out):
            out[k].append(r[i])
    return out


def roads(edgedata: Path, road_ids: dict, period: int) -> list:
    """Per interval: [road index, speedRelative in 0.05 steps, mean cars x10] for roads averaging >= 0.5 cars."""
    frames = [[] for _ in range(math.ceil(END / period))]
    for _, e in ET.iterparse(_open(edgedata)):
        if e.tag == "interval":
            b, en = float(e.get("begin")), float(e.get("end"))
            i = math.floor((b - T0) / period)
            if 0 <= i < len(frames):
                f = []
                for r in e.iter("edge"):
                    cars = float(r.get("sampledSeconds", 0)) / max(en - b, 1)
                    if cars >= 0.5 and r.get("speedRelative") is not None:
                        f += [road_ids.setdefault(r.get("id"), len(road_ids)), round(float(r.get("speedRelative")) * 20),
                              round(cars * 10)]
                frames[i] = f
            e.clear()
    return frames


def export(baseline: Path, coordinated: Path, label: str, out: Path, run_file: Path, net_file: Path) -> dict:
    from coordination import config
    from coordination.runtime import load_network
    net = load_network(config.load("configs/coordinated_routing_fireworks.yaml"))
    users = {t["id"]: t for t in fd.cohort(42)}
    road_ids: dict = {}
    variants, notes = {}, {}
    for key, d in (("baseline", baseline), ("ml", coordinated)):
        every = tripinfo(d / "tripinfo.xml")
        cars, st = vehicles(d / "fcd.xml.gz", {k: v for k, v in every.items() if k in users}, users)
        variants[key] = dict(**summarize(every, users), all=summarize(every, every), vehicles=cars,
                             totals=totals(d / "sumo_summary.xml.gz"), roads=roads(d / "edgedata.xml.gz", road_ids, 300))
        s = json.loads((d / "summary.json").read_text())
        notes[key] = {**st, "sumo_teleports_all_cars": s.get("teleports"), "vehicle_hours": s.get("in_scope_vehicle_hours"),
                      "policy": key, "episode": d.name}
    node = {}
    for i, g in enumerate(net.geometry):
        parts = str(net.ids[i]).split("-")
        if len(parts) == 3 and len(g):
            node.setdefault(parts[0], g[0])
            node.setdefault(parts[1], g[-1])
    signals = []
    for _, e in ET.iterparse(net_file):
        if e.tag == "junction":
            if e.get("type") == "traffic_light" and e.get("id") in node:
                lon, lat = node[e.get("id")]
                signals += [round(lon * 1e5), round(lat * 1e5)]
            e.clear()
        elif e.tag in ("edge", "connection", "request"):
            e.clear()
    shapes = [None] * len(road_ids)
    for rid, i in road_ids.items():
        j = net.pos.get(rid)
        flat, px, py = [], 0, 0
        for lon, lat in (net.geometry[j] if j is not None else []):
            x, y = round(lon * 1e5), round(lat * 1e5)
            flat += [x - px, y - py]
            px, py = x, y
        shapes[i] = flat or [0, 0]
    crowd = [float(t.get("depart")) - T0 for _, t in ET.iterparse(run_file) if t.tag == "trip" and t.get("id", "").startswith("crowd-")]
    pins = {}
    for u in users.values():
        for end in ("origin", "destination"):
            p = pins.setdefault(u[f"{end}_name"], {"name": u[f"{end}_name"], "lonlat": u[end], "from": 0, "to": 0})
            p["from" if end == "origin" else "to"] += 1
    sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
    data = {"run": f"{baseline.parent.name} vs {coordinated.parent.name}", "replay": "1 s app-user positions (TP_FCD_PERIOD_S=1)",
            "sumo": "1.27.1", "start": fd.V3_START.isoformat(), "admission": fd.LEAVE[1], "seed": 42, "end": END, "radius": 120.0,
            "background": True, "scenario_sha256": sha(run_file), "network_sha256": sha(net_file), "osm_snapshot": "net_v3",
            "event": fd.EVENT, "description": "demo cohort (kit.py v3, seed 42) + crowd cars, rebuilt on net_v3; everyone uses the app",
            "period": 300, "road_shapes": shapes,
            "crowd": {"count": len(crowd), "first_depart": min(crowd), "last_depart": max(crowd)} if crowd else None,
            "ml_models": [label], "placeholder": False, "users": len(users), "signals": signals,
            "pins": sorted(pins.values(), key=lambda p: p["name"]), "variants": variants, "replay_notes": notes, "label": label}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("// Generated by ml/coordination/demo_replay.py from SUMO output; do not edit.\nwindow.BASELINE = "
                   + json.dumps(data, separators=(",", ":")) + ";\n", encoding="utf-8")
    return {"out": str(out), "mb": round(out.stat().st_size / 1e6, 1), "signals": len(signals) // 2, "roads": len(road_ids),
            "notes": notes, "counts": {k: v["all"]["counts"] for k, v in variants.items()}}


def main():
    ap = argparse.ArgumentParser(prog="python -m coordination.demo_replay")
    ap.add_argument("--baseline", required=True, type=Path)
    ap.add_argument("--coordinated", required=True, type=Path)
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--run-file", type=Path,
                    default=Path("data/sf_citywide/batches/b6_fireworks/runs/b6_fireworks_n6000_all_s0_event/trips.rou.xml"))
    ap.add_argument("--net", type=Path, default=Path("data/sf_citywide/net_v3/net_c90.net.xml"))
    a = ap.parse_args()
    print(json.dumps(export(a.baseline, a.coordinated, a.label, a.out, a.run_file, a.net), indent=1, default=str))


if __name__ == "__main__":
    main()
