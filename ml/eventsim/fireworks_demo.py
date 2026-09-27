"""July 4 fireworks exodus (the demo's SUMO scenario) rebuilt on the v3 network as a routing scenario batch.

    python -m eventsim.fireworks_demo build [--batch b6_fireworks] [--crowds 3000 6000 12000]

Source: `demo/sumo/kit.py` (scenario version 3, seed 42) and `demo/sumo/HISTORICAL_INPUTS.md` on main. The demo's
constants and random draws are reproduced here (no import across folders): 1000 app users (25% go to a viewing
site 21:00-21:30, 75% leave one 21:45-22:45) and N non-app crowd cars parked on ordinary streets within 400 m of the
seven viewing sites, leaving 21:45-22:45 for the same ten home areas. Event context for the forecaster: PredictHQ
"Fourth of July fireworks on Golden Gate Bridge", 300,000 expected attendance, show 21:30-21:45 PDT.

Differences from the demo, by necessity: our network (net_v3, the forecaster's road graph) instead of the demo's
own OSM import, so snapped edges and the crowd cars' parked edges differ; trips are SUMO-routed from origin to
destination edge instead of fixed pre-computed paths. As in the demo: no other citywide traffic, crowd cars do not
reroute, and no closures (the Golden Gate Bridge closure does not touch these SF-internal trips; the crowd street
restrictions are not itemised in any source). SYNTHETIC: no measured July 4 traffic exists (0 Tiger rows).

Each crowd size N gets two runs:
  `_app`  crowd cars are vType `crowd` (never eligible to use the app); only the 1000 app users can be coordinated
  `_all`  crowd cars are vType `car`: everyone may use the app (participation then applies to all 1000 + N)
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1] / "data" / "sf_citywide"

# ---- verbatim from demo/sumo/kit.py (version 3) ----------------------------------------------------------------
START = datetime.fromisoformat('2026-07-04T20:00:00-07:00')
PLACES = {
    'mission': [-122.4194, 37.7599], 'castro': [-122.4350, 37.7609],
    'sunset': [-122.4660, 37.7637], 'richmond': [-122.4661, 37.7810],
    'union_square': [-122.4075, 37.7880], 'caltrain': [-122.3952, 37.7764],
    'marina': [-122.4368, 37.8005], 'ferry': [-122.3940, 37.7955],
    'wharf': [-122.4157, 37.8075], 'oracle': [-122.3893, 37.7786],
}
HOMES = ['mission', 'castro', 'sunset', 'richmond', 'caltrain', 'oracle',
         'pacific_heights', 'hayes_valley', 'noe_valley', 'soma']
PLACES |= {
    'pier_39': [-122.4098, 37.8086], 'ghirardelli': [-122.4225, 37.8057],
    'fort_mason': [-122.4325, 37.8052], 'marina_green': [-122.4400, 37.8056],
    'north_beach': [-122.4098, 37.8003], 'chinatown': [-122.4077, 37.7939],
    'pacific_heights': [-122.4340, 37.7898], 'hayes_valley': [-122.4240, 37.7765],
    'noe_valley': [-122.4318, 37.7516], 'soma': [-122.4016, 37.7839],
}
VIEW = ['golden_gate', 'crissy_field', 'marina_green', 'fort_mason', 'ghirardelli', 'wharf', 'pier_39']
PLACES |= {'golden_gate': [-122.4742, 37.8065], 'crissy_field': [-122.4510, 37.8047]}
EVENT = dict(source='PredictHQ', title='Fourth of July fireworks on Golden Gate Bridge',
             start='2026-07-04T21:30:00-07:00', phq_attendance=300000)
V3_START = START + timedelta(hours=1)
ARRIVE, LEAVE = (0, 1800), (2700, 6300)


def exodus(rng):
    return rng.choice(VIEW), rng.choice(HOMES), rng.randrange(*LEAVE)


def cohort(seed: int = 42) -> list[dict]:
    """kit.scenario(seed, version=3)['trips'] (same random calls, same order)."""
    rng = random.Random(seed)
    trips = []
    for i in range(1000):
        if rng.random() < 0.25:
            a, b, depart = rng.choice(HOMES), rng.choice(VIEW), rng.randrange(*ARRIVE)
        else:
            a, b, depart = exodus(rng)
        trips.append(dict(id=f'user-{i:04d}', origin=PLACES[a], destination=PLACES[b], origin_name=a,
                          destination_name=b, depart=depart,
                          depart_at=(V3_START + timedelta(seconds=depart)).isoformat()))
    return sorted(trips, key=lambda t: (t['depart'], t['id']))
# -----------------------------------------------------------------------------------------------------------------

DAY_S = {"sim_begin": 20 * 3600, "cohort_zero": 21 * 3600, "depart_end": 22 * 3600 + 2700, "sim_end": 25 * 3600}
SHOW_S = (21 * 3600 + 1800, 21 * 3600 + 2700)          # 21:30-21:45 PDT


def _net():
    from coordination import config
    from coordination.runtime import load_network
    return load_network(config.load("configs/coordinated_routing_backtest.yaml"))


def _snap_id(net, lonlat, radius: float, origin: bool) -> str:
    ok = (net.outdeg > 0 if origin else net.indeg > 0) & np.isin(net.static_availability, ["open"])
    s = net.snap(list(lonlat), allowed=ok, max_m=radius)
    if not s:
        raise SystemExit(f"no open road within {radius} m of {lonlat}")
    return str(net.ids[s[0].road])


def _parked(net, site: str, spread: float) -> list[str]:
    """Ordinary open streets (no freeway/trunk incl. their ramps) within `spread` m of a viewing site that the
    coordinator graph can route from: the demo's rule, applied to our network's road geometry."""
    p = net.to_xy(np.asarray(PLACES[site], float))[0]
    out = []
    for i, g in enumerate(net.geometry):
        if net.hw[i] in ("motorway", "trunk") or net.outdeg[i] == 0 or net.static_availability[i] != "open":
            continue
        xy = net.to_xy(np.asarray(g, float))
        if np.min(np.hypot(xy[:, 0] - p[0], xy[:, 1] - p[1])) <= spread:
            out.append(str(net.ids[i]))
    if not out:
        raise SystemExit(f"no parked street within {spread} m of {site}")
    return sorted(set(out))


def build(batch: str, crowds: list[int], seed: int = 42, radius: float = 120.0, spread: float = 400.0) -> dict:
    out = ROOT / "batches" / batch
    if (out / "scenarios.json").exists():
        raise SystemExit(f"{batch} exists; scenarios are frozen. Use a new batch id.")
    net = _net()
    net_file = ROOT / "net_v3" / "net_c90.net.xml"
    snap = {}

    def edge(lonlat, origin):
        k = (tuple(lonlat), origin)
        if k not in snap:
            snap[k] = _snap_id(net, lonlat, radius, origin)
        return snap[k]
    users = cohort(seed)
    app = [(t["id"], DAY_S["cohort_zero"] + t["depart"], edge(t["origin"], True), edge(t["destination"], False))
           for t in users]
    parked = {s: _parked(net, s, spread) for s in VIEW}
    homes = {h: edge(PLACES[h], False) for h in HOMES}
    vtypes = ('<vType id="car" carFollowModel="Krauss" sigma="0.392" tau="1.354" speedDev="0.083" minGap="2.83" />'
              '<vType id="crowd" carFollowModel="Krauss" sigma="0.392" tau="1.354" speedDev="0.083" minGap="2.83" />'
              '<vType id="probe" carFollowModel="Krauss" sigma="0.392" tau="1.354" speedDev="0.083" minGap="2.83">'
              '<param key="has.rerouting.device" value="false" /></vType>')
    fams, runs = [], []
    for n in crowds:
        rng = random.Random(seed)                     # the demo's `background --seed 42` draw sequence
        crowd = []
        for i in range(n):
            site, home, depart = exodus(rng)
            crowd.append((f"crowd-{i:05d}", DAY_S["cohort_zero"] + depart, rng.choice(parked[site]), homes[home]))
        for variant in ("app", "all"):
            ctype = "crowd" if variant == "app" else "car"
            trips = sorted([(i, d, f, t, "car") for i, d, f, t in app] + [(i, d, f, t, ctype) for i, d, f, t in crowd],
                           key=lambda r: (r[1], r[0]))
            fid = f"{batch}_n{n}_{variant}"
            run_id = f"{fid}_s0_event"
            rdir = out / "runs" / run_id
            rdir.mkdir(parents=True, exist_ok=True)
            body = "".join(f'<trip id="{i}" type="{ty}" depart="{d:.1f}" from="{f}" to="{t}" departLane="best" '
                           f'departSpeed="max" />' for i, d, f, t, ty in trips)
            (rdir / "trips.rou.xml").write_text(f"<?xml version='1.0' encoding='utf-8'?>\n<routes>{vtypes}{body}</routes>",
                                                encoding="utf-8")
            (rdir / "closures.add.xml").write_text("<?xml version='1.0' encoding='utf-8'?>\n<additional />",
                                                   encoding="utf-8")
            fam = {"family_id": fid, "family_group": "fireworks", "event_key": "fireworks",
                   "case_num": "phq_fireworks_2026_07_04", "date": "2026-07-04", "window": "full",
                   "low_demand_control": False,
                   "time": {"sim_begin_s": DAY_S["sim_begin"], "analysis_begin_s": DAY_S["sim_begin"],
                            "depart_end_s": DAY_S["depart_end"], "sim_end_s": DAY_S["sim_end"], "warmup_s": 3600,
                            "drain_s": DAY_S["sim_end"] - DAY_S["depart_end"]},
                   "public_hours_s": list(SHOW_S),
                   "sourced": {"public_hours": "PredictHQ start 21:30 PDT; SFMTA advisory show ~21:30-21:45"},
                   "routing": {"reroute_probability": 0.0, "reroute_period_s": 300},
                   "background": {"crowd_cars": n, "crowd_can_use_app": variant == "all", "app_users": len(app),
                                  "spread_m": spread, "citywide_background": 0},
                   "event": {"attendance_claim": EVENT["phq_attendance"], "title": EVENT["title"]}}
            fams.append(fam)
            runs.append({"run_id": run_id, "family_id": fid, "family_group": "fireworks", "event_key": "fireworks",
                         "with_event": True, "seed": seed, "restrictions": []})
            (rdir / "summary.json").write_text(json.dumps({
                "run_id": run_id, "family_id": fid, "with_event": True, "net": net_file.name,
                "trips_generated": len(trips), "app_users": len(app), "crowd_cars": n, "crowd_type": ctype,
                "dataset_status": "synthetic_demo_port_not_ground_truth", "time": fam["time"]}, indent=1))
    sc = {"schema_version": 3, "batch": batch, "network_dir": "net_v3", "families": fams, "runs": runs,
          "event_pool": {"fireworks": {"attendance_claim": EVENT["phq_attendance"],
                                       "attendance_source": "PredictHQ expected attendance (demo/sumo/HISTORICAL_INPUTS.md)",
                                       "title": EVENT["title"]}},
          "source": "demo/sumo/kit.py scenario --version 3 --seed 42 + background --spread 400 (rules reproduced on net_v3)",
          "parked_edges": {s: len(v) for s, v in parked.items()},
          "provenance": "SYNTHETIC. Demo cohort and assumed crowd sizes; no measured July 4 traffic exists."}
    (out / "scenarios.json").write_text(json.dumps(sc, indent=1))
    (out / "quality.csv").write_text("run_id,quality_flag\n" + "".join(f"{r['run_id']},ok\n" for r in runs))
    (out / "gate.json").write_text(json.dumps({"passed": True, "note": "demo-scenario port for routing tests; not a "
                                               "forecaster training batch"}))
    sp = Path(__file__).resolve().parents[1] / "data" / "coordination" / "fireworks" / "splits.json"
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps({"train": [], "val": [], "test": ["fireworks"],
                              "note": "fireworks demo port: evaluation only"}))
    return {"batch": batch, "runs": [r["run_id"] for r in runs], "app_users": len(app), "crowds": crowds,
            "parked_edges": sc["parked_edges"], "splits": str(sp)}


def main():
    p = argparse.ArgumentParser(prog="python -m eventsim.fireworks_demo")
    p.add_argument("stage", choices=["build"])
    p.add_argument("--batch", default="b6_fireworks")
    p.add_argument("--crowds", type=int, nargs="+", default=[3000, 6000, 12000])
    p.add_argument("--seed", type=int, default=42)
    a = p.parse_args()
    print(json.dumps(build(a.batch, a.crowds, a.seed), indent=1))


if __name__ == "__main__":
    main()
