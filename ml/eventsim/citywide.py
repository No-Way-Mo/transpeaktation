"""Citywide data generation, independent of model training.

python -m eventsim.citywide {prepare,network,simulate,report,export}
The first batch is a diagnostic, not a calibrated reconstruction of SF traffic.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import subprocess
import time

import numpy as np
import pandas as pd

from .config import BUCKET_S, MPS_TO_MPH, RAW_DIR, REPORTS_DIR, SF_TZ, event_dir
from .geo import LocalProj, midpoint, point_polyline_dist, sample_polyline
from .osm import fallback_free_flow_mph, load_graphml, norm_street
from . import prepare as prep, simulate as sim, sumonet

KEY = "sf_citywide"
ROOT = event_dir(KEY)
# Public dates/hours are independent of permit setup/teardown dates.
EVENTS = {
    "castro": {"case_num": "1534041", "date": "2026-10-04", "start_hour": 11, "end_hour": 18,
               "source": "https://castrostreetfair.org/2026/06/01/52nd-annual-castro-street-fair-announces-2026-theme-where-we-belong/"},
    "folsom": {"case_num": "1532891", "date": "2026-09-27", "start_hour": 11, "end_hour": 18,
               "source": "https://www.folsomstreet.org/folsom-street-fair"},
}


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, default=str), encoding="utf-8")
    tmp.replace(path)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class BoxIndex:
    """Conservative spatial candidate index; exact geometry checks still decide matches."""
    def __init__(self, lines, cell=100.0):
        self.cell, self.grid = cell, defaultdict(set)
        for key, xy in lines.items():
            for c in self.cells(xy.min(0), xy.max(0)):
                self.grid[c].add(key)

    def cells(self, lo, hi):
        a, b = np.floor(np.asarray(lo) / self.cell).astype(int), np.floor(np.asarray(hi) / self.cell).astype(int)
        for x in range(a[0], b[0] + 1):
            for y in range(a[1], b[1] + 1):
                yield x, y

    def query(self, lo, hi):
        found = set()
        for c in self.cells(lo, hi):
            found.update(self.grid.get(c, ()))
        return sorted(found)


def cnn_join(edges, proj, streets, limits):
    lines, meta = {}, {}
    for row in streets:
        for k, line in enumerate(prep._lines_of(row.get("line"))):
            key = f"{row['cnn']}:{k}"
            lines[key] = proj.fwd(line)
            meta[key] = (row["cnn"], norm_street(row.get("streetname") or row.get("street")))
    idx, out = BoxIndex(lines), {}
    for sid, edge in edges.items():
        p = midpoint(proj.fwd(edge.coords))
        best = None
        for k in idx.query(p - prep.CNN_MATCH_M, p + prep.CNN_MATCH_M):
            d = float(point_polyline_dist(p[None], lines[k])[0][0])
            cnn, name = meta[k]
            if d <= prep.CNN_MATCH_M:
                candidate = (d - (10 if name and name == norm_street(edge.name) else 0), cnn, d)
                if best is None or candidate < best:
                    best = candidate
        cnn = best[1] if best else None
        limit = limits.get(cnn)
        posted = float(limit) if limit is not None and 0 < limit < 99 else (25.0 if limit == 0 else None)
        out[sid] = {"cnn": cnn, "cnn_distance_m": best[2] if best else None, "posted_mph": posted,
                    "limit_record": limit, "posted_is_default": limit == 0}
    return out


def source_join(edges, proj, feed, allow_reverse):
    geoms = prep._geometry(feed, np.array([-123.0, 37.0]), np.array([-122.0, 38.5]))
    lines = {k: proj.fwd(g["coords"]) for k, g in geoms.items() if len(g["coords"]) >= 2}
    idx, joined = BoxIndex(lines), {}
    for sid, edge in edges.items():
        xy = proj.fwd(edge.coords)
        pts, dirs = sample_polyline(xy, 10.0)
        best = (0.0, None)
        for k in idx.query(xy.min(0) - prep.SNAP_M, xy.max(0) + prep.SNAP_M):
            d, ld = point_polyline_dist(pts, lines[k])
            cosine = (dirs * ld).sum(1)
            share = float(((d <= prep.SNAP_M) & (cosine >= prep.SNAP_ANGLE_COS)).mean())
            if allow_reverse:
                share = max(share, float(((d <= prep.SNAP_M) & (cosine <= -prep.SNAP_ANGLE_COS)).mean()))
            if share > best[0]:
                best = share, k
        if best[0] >= prep.SNAP_COVER_MIN:
            joined[sid] = best[1]
    return joined


def prepare():
    out = ROOT / "prepared"
    if (out / "patch.json").exists():
        raise SystemExit("Citywide preparation exists. Preserve this version; use ML_DATA_DIR for a new dataset version.")
    nodes, edges = load_graphml(RAW_DIR / "osm_drive_graph.graphml")
    proj = LocalProj(-122.44, 37.76)
    streets, _ = prep._load_records("streets")
    limits, _ = prep._load_records("speed_limits")
    closures, closure_meta = prep._load_records("street_closures")
    restrictions, _ = prep._load_records("osm_turn_restrictions")
    limit_by_cnn = {str(r["cnn"]): float(r["speedlimit"]) for r in limits if r.get("speedlimit") is not None}
    print(f"Joining {len(edges)} directed roads to DataSF and provider geometry...", flush=True)
    cnn = cnn_join(edges, proj, streets, limit_by_cnn)
    tt = source_join(edges, proj, "tomtom_flow", False)
    print(f"TomTom geometry matched: {len(tt)}", flush=True)
    mb = source_join(edges, proj, "mapbox_traffic", True)
    seg = {}
    for sid, edge in edges.items():
        ff, src = fallback_free_flow_mph(edge, cnn[sid]["posted_mph"])
        seg[sid] = {"segment_id": sid, "u": edge.u, "v": edge.v, "key": edge.key, "coords": edge.coords,
                    "length_m": edge.length_m, "name": edge.name, "highway": edge.highway, "rank": edge.rank,
                    "oneway": edge.oneway, "osmids": edge.osmids, "lanes": edge.lanes,
                    "fallback_free_flow_mph": ff, "fallback_free_flow_source": src,
                    "signal_at_v": nodes[edge.v].highway == "traffic_signals", "closed": False,
                    "tomtom_line": sid in tt, "mapbox_line": sid in mb, **cnn[sid]}
    print("Matching real event footprints across the whole city...", flush=True)
    xy = {sid: proj.fwd(e.coords) for sid, e in edges.items()}
    idx = BoxIndex(xy)
    by_cnn = {r["cnn"]: r for r in streets}
    catalog, matches = {}, []
    for row in closures:
        if row.get("type") != "Special Event":
            continue
        case = str(row["case_num"])
        event = catalog.setdefault(case, {"case_num": case, "name": row["case_name"], "rows": [], "segment_ids": set()})
        lines = prep._lines_of(row.get("shape"))
        if not lines:
            candidates = {}
        else:
            points = np.vstack([proj.fwd(l) for l in lines])
            candidates = {k: edges[k] for k in idx.query(points.min(0) - 60, points.max(0) + 60)}
        found, report = prep.match_closures([row], candidates, proj, by_cnn)
        m = report[0]
        matches.append({"case_num": case, "case_name": row["case_name"], **m})
        record = {k: row.get(k) for k in ("objectid", "cnn", "status", "start_utc", "end_utc", "veh_imp", "direction")}
        record.update(segment_ids=sorted(found), match_status=m["status"], flags=m.get("flags", []))
        event["rows"].append(record)
        event["segment_ids"].update(found)
    for event in catalog.values():
        event["segment_ids"] = sorted(event["segment_ids"])
    bans, ban_stats = prep.turn_prohibitions(restrictions, edges, set(edges))
    patch = {"event_key": KEY, "proj": {"lon0": proj.lon0, "lat0": proj.lat0}, "segments": seg,
             "nodes": {n: [v.lon, v.lat] for n, v in nodes.items()}, "signals": [n for n, v in nodes.items() if v.highway == "traffic_signals"],
             "boundary_nodes": [], "entry_edges": [], "exit_edges": [], "closure_edges": [],
             "turn_prohibitions": bans, "timed_restrictions": []}
    save(out / "event_catalog.json", {"source": closure_meta, "events": catalog})
    save(out / "closure_matches.json", matches)
    save(out / "patch.json", patch)
    save(out / "source_mapping.json", {"tomtom": tt, "mapbox_tiles": mb})
    save(out / "source_manifest.json", {"generated_at": datetime.now(timezone.utc).isoformat(),
         "files": [{"path": str(p.relative_to(RAW_DIR)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                   for p in (RAW_DIR / n for n in ("osm_drive_graph.graphml", "streets.json", "speed_limits.json", "street_closures.json"))],
         "turn_restrictions": dict(ban_stats), "canonical_segment_count": len(seg),
         "tomtom_geometry_segments": len(tt), "mapbox_geometry_segments": len(mb), "event_cases": len(catalog),
         "note": "Geometry coverage is not time coverage. No traffic observation or synthetic measurement is fabricated for empty roads."})
    print(f"Prepared full network, {len(catalog)} real event cases. No model training.", flush=True)
    return {"segments": len(seg), "event_cases": len(catalog), "matched_event_rows": sum(bool(x["edges"]) for x in matches)}


def network():
    if any((ROOT / "runs").glob("*/summary.json")):
        raise SystemExit("Completed runs exist. Preserve their network; use ML_DATA_DIR for a new version.")
    patch = read(ROOT / "prepared" / "patch.json")
    out = ROOT / "net"
    out.mkdir(parents=True, exist_ok=True)
    info = sumonet.write_plain(patch, out)
    netpath = sumonet.build(out, 90)
    cw = sumonet.crosswalk(patch, netpath, info["lanes"], info["clusters"])
    cw.to_csv(out / "crosswalk.csv", index=False)
    routable = sumonet.routable_edges(patch, netpath)
    save(out / "routable_edges.json", routable)
    result = {"canonical_segments": len(cw), "sumo_segments": int((cw.n_sumo_edges > 0).sum()),
              "absorbed_junction_segments": int(cw.absorbed_junction.notna().sum()),
              "missing_unexplained": int(((cw.n_sumo_edges == 0) & cw.absorbed_junction.isna()).sum()),
              "routable_od_segments": len(routable), "assumed_lanes": int((cw.lanes_source != "osm").sum()),
              "signal_cycle_s": 90, "signal_timing_source": "assumption"}
    save(out / "network.json", result)
    return result


def event_restrictions(catalog, key, begin, end):
    """Use only resolved full closures, retaining every ambiguity as an explicit scenario assumption."""
    event = catalog[EVENTS[key]["case_num"]]
    midnight = datetime.fromisoformat(EVENTS[key]["date"]).replace(tzinfo=SF_TZ)
    result = []
    for row in event["rows"]:
        if row["status"] != "Permitted" or row["veh_imp"] != "all-lanes-closed" or not row["segment_ids"]:
            continue
        a = (prep._parse_utc(row["start_utc"]).astimezone(SF_TZ) - midnight).total_seconds()
        b = (prep._parse_utc(row["end_utc"]).astimezone(SF_TZ) - midnight).total_seconds()
        if a < end and b > begin:
            result.append({"id": row["objectid"], "source": "event_permit", "segment_ids": row["segment_ids"],
                           "restriction": "full", "begin_s": a, "end_s": b, "match_status": row["match_status"],
                           "assumptions": row["flags"]})
    return result


def make_scenarios(hours, vph, seed):
    if hours < 2 or hours > 24 or hours * 6 != int(hours * 6) or vph <= 0:
        raise ValueError("hours must be 2..24 in 10-minute increments; vph must be positive")
    catalog = read(ROOT / "prepared" / "event_catalog.json")["events"]
    begin, end = 9 * 3600 + 1800, int((9.5 + hours) * 3600)
    families, runs = [], []
    for i, key in enumerate(EVENTS):
        family = {"family_id": f"{key}_arrival_v1", "event_key": key, "background_vph": vph,
                  "network": {"tls_cycle_s": 90}, "driver": {"tau": 1.2, "sigma": .4, "speed_dev": .1, "min_gap": 2.5},
                  "routing": {"reroute_probability": .25, "reroute_period_s": 300},
                  "event_vehicle_trips": 1500 if key == "castro" else 3000,
                  "demand_source": "assumed diagnostic demand, not observed attendance or citywide OD calibration"}
        families.append(family)
        for active in (False, True):
            runs.append({"run_id": f"{family['family_id']}_{'event' if active else 'control'}", "family_id": family["family_id"],
                         "with_event": active, "event_key": key, "seed": seed + i,
                         "restrictions": event_restrictions(catalog, key, begin, end) if active else []})
    return {"time": {"sim_begin_s": begin, "analysis_begin_s": begin + 1800, "depart_end_s": end - 3600, "sim_end_s": end},
            "families": families, "runs": runs, "public_schedules": EVENTS, "schema_version": 1,
            "provenance": "CITYWIDE DIAGNOSTIC: real network and selected permitted event footprints; assumed demand; closure ambiguities retained for review. Other concurrent restrictions are not yet included. Not training-approved."}


def city_trips(ctx, run):
    """Same background OD/departures in each event/control pair; local and cross-city journeys."""
    fam, cfg = ctx.fams[run["family_id"]], ctx.scen["time"]
    rng = np.random.default_rng(run["seed"])
    # Use the common connected set with the selected event's closures removed for BOTH paired runs.
    ids = ctx.od_by_event[run["event_key"]]
    if len(ids) < 2:
        raise ValueError("not enough connected OD edges")
    seg = ctx.patch["segments"]
    centers = np.array([np.asarray(seg[s]["coords"]).mean(0) for s in ids])
    xy = LocalProj(**ctx.patch["proj"]).fwd(centers)
    grid = defaultdict(list)
    for i, p in enumerate(xy):
        grid[tuple(np.floor(p / 2000).astype(int))].append(i)
    n = rng.poisson(fam["background_vph"] * (cfg["depart_end_s"] - cfg["sim_begin_s"]) / 3600)
    trips = []
    for i, depart in enumerate(np.sort(rng.uniform(cfg["sim_begin_s"], cfg["depart_end_s"], n))):
        a = int(rng.integers(len(ids)))
        local = grid[tuple(np.floor(xy[a] / 2000).astype(int))]
        b = int(rng.choice(local)) if rng.random() < .6 and len(local) > 1 else int(rng.integers(len(ids)))
        if a == b:
            b = (b + 1) % len(ids)
        trips.append({"id": f"bg{i}", "kind": "background", "depart": float(depart), "from": ids[a], "to": ids[b]})
    if run["with_event"]:
        event = ctx.catalog[EVENTS[run["event_key"]]["case_num"]]
        footprint = np.vstack([np.asarray(seg[s]["coords"]) for s in event["segment_ids"] if s in seg])
        distance = np.linalg.norm(xy - LocalProj(**ctx.patch["proj"]).fwd(footprint.mean(0))[0], axis=1)
        dest = np.flatnonzero((distance > 100) & (distance < 900))
        if not len(dest):
            raise ValueError("no open event destinations")
        erng = np.random.default_rng(run["seed"] + 10_000)
        total = fam["event_vehicle_trips"]
        arrival = erng.normal(EVENTS[run["event_key"]]["start_hour"] * 3600, 45 * 60, total)
        departure = erng.normal(EVENTS[run["event_key"]]["end_hour"] * 3600, 45 * 60, total)
        for i in range(total):
            o, d = ids[int(erng.integers(len(ids)))], ids[int(erng.choice(dest))]
            for kind, t, src, dst in (("arrival", arrival[i], o, d), ("departure", departure[i], d, o)):
                if cfg["sim_begin_s"] <= t < cfg["depart_end_s"] and src != dst:
                    trips.append({"id": f"ev_{kind}{i}", "kind": f"event_{kind}", "depart": float(t), "from": src, "to": dst})
    return sorted(trips, key=lambda x: x["depart"])


def context():
    ctx = sim.Context(KEY)
    ctx.catalog = read(ROOT / "prepared" / "event_catalog.json")["events"]
    ctx.od_by_event = {}
    for key in EVENTS:
        restrictions = next(r["restrictions"] for r in ctx.scen["runs"] if r["event_key"] == key and r["with_event"])
        patch = {**ctx.patch, "timed_restrictions": restrictions}
        ctx.od_by_event[key] = [s for s in sumonet.routable_edges(patch, ROOT / "net" / "net_c90.net.xml")
                                if ctx.patch["segments"][s]["length_m"] >= 20]
    return ctx


def simulate_one(ctx, run):
    out = ROOT / "runs" / run["run_id"]
    if (out / "summary.json").exists():
        return read(out / "summary.json")
    out.mkdir(parents=True, exist_ok=True)
    fam, restr = ctx.fams[run["family_id"]], run["restrictions"]
    trips = city_trips(ctx, run)
    sim.write_routes(trips, fam, out / "trips.rou.xml")
    net = sim.variant_net(ctx, fam, sim.write_additional(ctx, restr, out))
    print(f"Starting {run['run_id']}: {len(trips):,} trips", flush=True)
    t0 = time.time()
    completed = subprocess.run(sim.sumo_cmd(ctx, fam, run, net), cwd=out, capture_output=True, text=True)
    (out / "sumo.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
    if completed.returncode:
        raise RuntimeError(f"{run['run_id']}: {completed.stderr[-1200:]}")
    result = sim.extract(ctx, run, out, trips, restr, time.time() - t0, completed.stderr, net)
    result.update(event_key=run["event_key"], synthetic=True, dataset_status="diagnostic_not_training_approved",
                  local_day=EVENTS[run["event_key"]]["date"], assumptions=ctx.scen["provenance"])
    save(out / "summary.json", result)
    return result


def simulate(hours, vph, seed, workers, only):
    proposed = make_scenarios(hours, vph, seed)
    path = ROOT / "scenarios.json"
    if path.exists() and read(path) != proposed:
        raise SystemExit("Different scenario settings already exist. Set ML_DATA_DIR to version a new batch; no existing runs overwritten.")
    save(path, proposed)
    ctx = context()
    chosen = [r for r in ctx.scen["runs"] if not only or r["run_id"] in only]
    if not chosen:
        raise ValueError("no selected runs")
    done, failures = [], []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(simulate_one, ctx, r): r["run_id"] for r in chosen}
        for f in as_completed(futures):
            try:
                result = f.result()
                done.append(result)
                print(json.dumps(result), flush=True)
            except Exception as e:
                failures.append({"run": futures[f], "error": str(e)})
                print(f"FAILED {futures[f]}: {e}", flush=True)
    return {"completed": len(done), "failures": failures, "report": report()}


REVIEW_VERSION = "closure_review_v2"
SHORT_CLOSURE_COVER = 0.8   # closure line length lying on one same-named edge (edge may be longer)


def same_street(a, b, compact: bool) -> bool:
    """v3 compares names without spaces: DataSF 'OFARRELL ST' / 'SEACLIFF AVE' vs OSM "O'Farrell Street" /
    'Sea Cliff Avenue' (norm_street turns the apostrophe into a space)."""
    na, nb = norm_street(a), norm_street(b)
    return (na.replace(" ", "") == nb.replace(" ", "")) if compact else na == nb


def along_names(row, segments, proj, index) -> dict:
    """Drivable edges (any name) running along the closure line, with the share of the line they cover."""
    lines = prep._lines_of(row.get("shape"))
    if not lines:
        return {}
    geo = [sample_polyline(proj.fwd(l), 5.0) for l in lines]
    pts, dirs = np.vstack([g[0] for g in geo]), np.vstack([g[1] for g in geo])
    out = {}
    for sid in index.query(pts.min(0) - 20, pts.max(0) + 20):
        d, ed = point_polyline_dist(pts, proj.fwd(segments[sid]["coords"]))
        cov = float(((d <= prep.CLOSURE_MATCH_M) & (np.abs((dirs * ed).sum(1)) >= prep.CLOSURE_ANGLE_COS)).mean())
        if cov > 0.2:
            name = str(segments[sid]["name"])
            out[name] = max(out.get(name, 0.0), round(cov, 2))
    return out


def review_row(row, match, segments, proj, index, v3: bool = False):
    """Decision for one Special Event closure row, with the reason. Never edits the prepared matches."""
    base = {"objectid": row["objectid"], "case_num": str(row["case_num"]), "cnn": row["cnn"], "street": row["street"],
            "status": row["status"], "veh_imp": row["veh_imp"], "direction": row["direction"],
            "start_utc": row["start_utc"], "end_utc": row["end_utc"], "match_status": match["status"],
            "match_flags": match.get("flags", []), "segment_ids": sorted(e["segment_id"] for e in match["edges"])}
    if row["status"] != "Permitted":
        return {**base, "decision": "reject", "reason": f"permit status {row['status']}"}
    if row["veh_imp"] != "all-lanes-closed":
        return {**base, "decision": "partial_restriction", "reason": f"{row['veh_imp']}: not a full closure"}
    flags = set(match.get("flags", []))
    if v3 and match["edges"]:
        match = {**match, "edges": [{**e, "name_match": e["name_match"] or same_street(e["osm_name"], row["street"], True)}
                                    for e in match["edges"]]}
        if "name_mismatch" in flags and all(e["name_match"] or e["osm_name"] is None for e in match["edges"]):
            flags = (flags - {"name_mismatch"}) | ({"name_mismatch"} if any(e["osm_name"] is None for e in match["edges"]) else set())
    if match["status"] == "matched":
        return {**base, "decision": "accept", "reason": "overlap, name and heading agree"}
    if match["status"] == "ambiguous":
        rest = flags - {f for f in flags if f.startswith("direction_")}
        unnamed_only = all(e["name_match"] or (e["osm_name"] is None and e["overlap"] >= 0.9) for e in match["edges"])
        if rest <= {"name_mismatch"} and (not rest or unnamed_only):
            why = ["all lanes closed, so an undefined direction closes both"] if flags - rest else []
            if rest:
                why.append("mismatched edges are unnamed links with >=90% overlap")
            return {**base, "decision": "accept", "reason": "; ".join(why)}
        if rest == {"partial_coverage"} and match["edges"] and all(e["name_match"] for e in match["edges"]):
            # The uncovered part of the closure line: if no drivable edge of any name lies under it (e.g. 17th St at
            # Castro is the pedestrian Jane Warner Plaza), there is nothing else to close.
            geo = [sample_polyline(proj.fwd(l), 2.0) for l in prep._lines_of(row.get("shape"))]
            pts, dirs = np.vstack([g[0] for g in geo]), np.vstack([g[1] for g in geo])
            covered = np.zeros(len(pts), bool)
            for sid in base["segment_ids"]:
                covered |= point_polyline_dist(pts, proj.fwd(segments[sid]["coords"]))[0] <= prep.CLOSURE_MATCH_M
            rest_pts, rest_dirs = pts[~covered], dirs[~covered]

            def runs_along(sid):  # cross streets touching the line at an intersection don't count
                d, ed = point_polyline_dist(rest_pts, proj.fwd(segments[sid]["coords"]))
                return ((d <= prep.CLOSURE_MATCH_M) & (np.abs((rest_dirs * ed).sum(1)) >= prep.CLOSURE_ANGLE_COS)).any()
            under = len(rest_pts) > 0 and any(runs_along(s) for s in index.query(rest_pts.min(0) - 20, rest_pts.max(0) + 20))
            if not under:
                return {**base, "decision": "accept", "match_flags": sorted(flags | {"remainder_not_in_drive_graph"}),
                        "reason": f"{2 * len(rest_pts)} m of the closure line has no drivable road under it"}
        return {**base, "decision": "needs_review", "reason": f"flags {sorted(flags)}"}
    # unmatched: a short closure on a longer edge of the same street (edge overlap < 50% by construction)
    lines = prep._lines_of(row.get("shape"))
    if not lines:
        return {**base, "decision": "needs_review", "reason": "no closure geometry"}
    pts = np.vstack([sample_polyline(proj.fwd(l), 5.0)[0] for l in lines])
    dirs = np.vstack([sample_polyline(proj.fwd(l), 5.0)[1] for l in lines])
    found = []
    for sid in index.query(pts.min(0) - 30, pts.max(0) + 30):
        seg = segments[sid]
        if not same_street(seg["name"], row["street"], v3):
            continue
        d, ed = point_polyline_dist(pts, proj.fwd(seg["coords"]))
        cover = float(((d <= prep.CLOSURE_MATCH_M) & (np.abs((dirs * ed).sum(1)) >= prep.CLOSURE_ANGLE_COS)).mean())
        if cover >= SHORT_CLOSURE_COVER:
            found.append(sid)
    if found:
        return {**base, "segment_ids": sorted(found), "decision": "accept",
                "reason": "closure shorter than a same-named edge: whole edge closed (conservative)",
                "match_flags": sorted(flags | {"edge_longer_than_closure"})}
    if v3 and not along_names(row, segments, proj, index):
        return {**base, "segment_ids": [], "decision": "no_drivable_road",
                "reason": "no drivable OSM road runs along the closure line (alley/plaza not in the drive graph): "
                          "the closure removes nothing from the simulated network"}
    return {**base, "decision": "needs_review", "reason": "no same-named edge under the closure line"}


DECIDE_OTHER_NAME_COVER = 0.8   # a differently named road is accepted only if it carries most of the closure line


_TYPE = {"STREET": "ST", "AVENUE": "AVE", "BOULEVARD": "BLVD", "DRIVE": "DR", "ROAD": "RD", "PLACE": "PL",
         "TERRACE": "TER", "COURT": "CT", "LANE": "LN", "ALLEY": "ALY", "HIGHWAY": "HWY", "WAY": "WAY"}


def same_type(osm_name, permit_street) -> bool:
    """Street type must agree too: a permit on 'OCTAVIA ST' (the frontage lanes) is not Octavia Boulevard (the
    main lanes). Unknown types (no suffix) don't block a match."""
    def t(n):
        w = str(n or "").upper().replace(".", "").split()
        return _TYPE.get(w[-1], w[-1]) if w and (w[-1] in _TYPE or w[-1] in _TYPE.values()) else None
    a, b = t(osm_name), t(permit_street)
    return a is None or b is None or a == b


def decide_row(x, row, segments, proj, index) -> dict:
    """Close out a needs_review row by one fixed rule (decided without human verification; labelled as such):
    1. close the permit's own street wherever it runs along the closure line (any coverage);
    2. else accept the aligned road of another name only if it covers >= 80% of the line (map naming conflict,
       e.g. the Woodland Ave permit line lies on the road OSM calls Willard St);
    3. else apply no closure (a closure we can't place is safer left out than guessed onto the wrong road)."""
    lines = prep._lines_of(row.get("shape"))
    geo = [sample_polyline(proj.fwd(l), 5.0) for l in lines]
    pts, dirs = np.vstack([g[0] for g in geo]), np.vstack([g[1] for g in geo])
    same, other = [], []
    for sid in index.query(pts.min(0) - 20, pts.max(0) + 20):
        d, ed = point_polyline_dist(pts, proj.fwd(segments[sid]["coords"]))
        on = (d <= prep.CLOSURE_MATCH_M) & (np.abs((dirs * ed).sum(1)) >= prep.CLOSURE_ANGLE_COS)
        # the edge itself must mostly lie along the line (not a cross street touching it)
        epts, edirs = sample_polyline(proj.fwd(segments[sid]["coords"]), 5.0)
        de, ld = point_polyline_dist(epts, np.vstack([proj.fwd(l) for l in lines]))
        edge_on = ((de <= prep.CLOSURE_MATCH_M) & (np.abs((edirs * ld).sum(1)) >= prep.CLOSURE_ANGLE_COS)).mean()
        if on.mean() <= 0.05:
            continue
        if same_street(segments[sid]["name"], row["street"], True) and same_type(segments[sid]["name"], row["street"]):
            same.append((sid, float(on.mean())))  # the permit's street may extend past a short closure
        elif edge_on >= 0.5:                        # other names must actually run along the line
            other.append((sid, float(on.mean())))
    tag = {"decided_by": "claude (rule-based, not human-verified)"}
    if same:
        cover = max(c for _, c in same)
        return {**x, **tag, "decision": "accept", "segment_ids": sorted(s for s, _ in same),
                "match_flags": sorted(set(x["match_flags"]) | {"claude_decision"}),
                "reason": f"decided: permit street '{row['street']}' runs along {cover:.0%} of the line; only it is closed"}
    best = max((c for _, c in other), default=0.0)
    if best >= DECIDE_OTHER_NAME_COVER:
        segs = sorted(s for s, c in other if c >= 0.5)
        names = sorted({str(segments[s]["name"]) for s in segs})
        return {**x, **tag, "decision": "accept", "segment_ids": segs,
                "match_flags": sorted(set(x["match_flags"]) | {"claude_decision", "osm_name_differs"}),
                "reason": f"decided: the permit line lies on {', '.join(names)} ({best:.0%}); OSM names it differently"}
    return {**x, **tag, "decision": "no_closure_applied", "segment_ids": [],
            "reason": f"decided: no road of the permit's name under the line and no other road covers >= "
                      f"{DECIDE_OTHER_NAME_COVER:.0%} (best {best:.0%}); closure left out rather than guessed"}


def review(version: str = REVIEW_VERSION):
    """Versioned, auditable closure review over all 1,105 special-event rows -> which permit cases are verified
    scenario locations. Writes prepared/closure_review_v2.json; prepared/closure_matches.json is left as is."""
    patch = read(ROOT / "prepared" / "patch.json")
    segments, proj = patch["segments"], LocalProj(**patch["proj"])
    matches = read(ROOT / "prepared" / "closure_matches.json")
    raw = [r for r in prep._load_records("street_closures")[0] if r.get("type") == "Special Event"]
    if len(raw) != len(matches):
        raise SystemExit("closure snapshot changed since prepare; re-prepare into a new ML_DATA_DIR version")
    index = BoxIndex({s: proj.fwd(v["coords"]) for s, v in segments.items()})
    cw = pd.read_csv(ROOT / "net" / "crosswalk.csv")
    in_sumo = set(cw.loc[cw.n_sumo_edges > 0, "road_segment_id"])
    v3 = version == "closure_review_v3"
    rows = [review_row(r, m, segments, proj, index, v3) for r, m in zip(raw, matches)]
    if v3:  # close out the remaining rows by rule; keep the evidence and the decision side by side
        evidence = []
        for i, (x, r) in enumerate(zip(rows, raw)):
            if x["decision"] != "needs_review":
                continue
            rows[i] = decide_row(x, r, segments, proj, index)
            evidence.append({**{k: x[k] for k in ("case_num", "objectid", "cnn", "street")}, "case_name": r["case_name"],
                             "from_st": r.get("from_st"), "to_st": r.get("to_st"), "loc_desc": r.get("loc_desc"),
                             "open_reason": x["reason"],
                             "drivable_roads_along_line": json.dumps(along_names(r, segments, proj, index)),
                             "decision": rows[i]["decision"], "decision_reason": rows[i]["reason"],
                             "segment_ids": " ".join(rows[i]["segment_ids"]), "decided_by": rows[i]["decided_by"]})
        pd.DataFrame(evidence).to_csv(ROOT / "prepared" / f"{version}_decisions.csv", index=False)
    cases = defaultdict(list)
    for r in rows:
        cases[r["case_num"]].append(r)
    names = {str(r["case_num"]): r["case_name"] for r in raw}
    inventory = []
    for case, rs in cases.items():
        # no_drivable_road / no_closure_applied: nothing to close for that row
        full = [r for r in rs if r["decision"] in ("accept", "needs_review")]
        acc = [r for r in rs if r["decision"] == "accept"]
        segs = sorted({s for r in acc for s in r["segment_ids"]})
        absorbed = [s for s in segs if s not in in_sumo]
        occ = sorted({(r["start_utc"], r["end_utc"]) for r in full})
        status = ("verified" if full and len(acc) == len(full) and segs else
                  "partial" if acc else "unverified")
        inventory.append({"case_num": case, "name": names[case], "status": status, "rows": len(rs),
                          "full_closure_rows": len(full), "accepted_rows": len(acc),
                          "needs_review_rows": len(full) - len(acc),
                          "partial_restriction_rows": sum(r["decision"] == "partial_restriction" for r in rs),
                          "rejected_rows": sum(r["decision"] == "reject" for r in rs),
                          "segments": len(segs), "segments_absorbed_in_junctions": len(absorbed),
                          "occurrences_utc": occ, "first_start_utc": occ[0][0] if occ else None})
    inventory.sort(key=lambda x: (x["status"] != "verified", -x["segments"]))
    result = {"version": version, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "rules": {"accept": ["matched", "undefined direction on all-lanes-closed rows", "unnamed links >=90% overlap",
                                   f"closure line >= {SHORT_CLOSURE_COVER:.0%} on one same-named edge (edge closed whole)"],
                        "needs_review": "partial coverage, named cross/parallel streets, missing geometry",
                        "not_simulated": "cancelled/other status, partial-lane restrictions"},
              "row_decisions": pd.Series([r["decision"] for r in rows]).value_counts().to_dict(),
              "case_status": pd.Series([c["status"] for c in inventory]).value_counts().to_dict(),
              "rows": rows, "cases": inventory}
    save(ROOT / "prepared" / f"{version}.json", result)
    return {k: result[k] for k in ("version", "row_decisions", "case_status")}


TELEPORT_RE = re.compile(r"Teleporting vehicle '([^']+)'; (?:waited too long \(([^)]+)\)|(collision)[^,]*), "
                         r"lane='([^']+)'.*?time=([0-9]+(?:\.[0-9]+)?)")


def lane_junction(lane, segments):
    """SUMO lane -> junction where the vehicle was stuck (internal ':J_i_k' lanes, or the edge's downstream node)."""
    if lane.startswith(":"):
        return lane[1:].rsplit("_", 2)[0]
    edge = lane.rsplit("_", 1)[0]
    return segments[edge]["v"] if edge in segments else edge


def diagnose(only, workers):
    """Re-run completed runs with SUMO warnings on, in diagnostics/<run>/ (pilot outputs untouched), and locate
    teleports by junction so problem intersections can be fixed instead of hidden."""
    scenarios = read(ROOT / "scenarios.json")
    ctx = sim.Context(KEY)
    runs = [r for r in scenarios["runs"] if (ROOT / "runs" / r["run_id"] / "summary.json").exists()
            and (not only or r["run_id"] in only)]

    def one(run):
        src, out = ROOT / "runs" / run["run_id"], ROOT / "diagnostics" / run["run_id"]
        out.mkdir(parents=True, exist_ok=True)
        for name in ("trips.rou.xml", "closures.add.xml"):
            (out / name).write_bytes((src / name).read_bytes())
        summary = read(src / "summary.json")
        net = next(p for p in (ROOT / "net" / "variants" / summary["net"], ROOT / "net" / summary["net"]) if p.exists())
        cmd = sim.sumo_cmd(ctx, ctx.fams[run["family_id"]], run, net)
        i = cmd.index("--no-warnings")
        del cmd[i:i + 2]  # same inputs, seed and settings as the pilot, but with warnings logged
        log = out / "sumo_warnings.log"
        if log.exists() and (out / "stats.xml").exists() and "teleports" in (out / "stats.xml").read_text(errors="replace"):
            done = subprocess.CompletedProcess(cmd, 0, "", log.read_text(encoding="utf-8"))  # finished earlier: reuse
        else:
            done = subprocess.run(cmd + ["--collision-output", "collisions.xml"], cwd=out, capture_output=True, text=True)
            log.write_text(done.stderr, encoding="utf-8")
        rows = []
        for m in TELEPORT_RE.finditer(done.stderr):
            veh, reason, coll, lane, t = m.groups()
            rows.append({"run_id": run["run_id"], "vehicle": veh, "reason": reason or coll, "lane": lane,
                         "junction": lane_junction(lane, ctx.patch["segments"]), "time_s": float(t)})
        stats = sim.parse_stats(out / "stats.xml")
        return rows, {"run_id": run["run_id"], "returncode": done.returncode, "teleports_logged": len(rows),
                      "teleports_stats": stats.get("teleports", {}), "matches_pilot": stats.get("teleports", {}) == {
                          k: float(v) for k, v in summary["teleports"].items()}}

    rows, checks = [], []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for r, c in pool.map(one, runs):
            rows += r
            checks.append(c)
    tel = pd.DataFrame(rows, columns=["run_id", "vehicle", "reason", "lane", "junction", "time_s"])
    out = ROOT / "diagnostics"
    tel.to_csv(out / "teleports.csv", index=False)
    net = sumonet_junction_types(ROOT / "net" / "net_c90.net.xml")
    cw = pd.read_csv(ROOT / "net" / "crosswalk.csv")
    joined = {j for c in cw.absorbed_junction.dropna() for j in str(c).split("_")}
    closed = {s for r in scenarios["runs"] for x in r["restrictions"] for s in x["segment_ids"]}
    near_closure = {ctx.patch["segments"][s][k] for s in closed for k in ("u", "v")}
    hot = (tel.groupby("junction").agg(teleports=("vehicle", "size"), runs=("run_id", "nunique"),
                                       reasons=("reason", lambda s: ", ".join(f"{k}:{v}" for k, v in s.value_counts().items())))
           .sort_values("teleports", ascending=False).reset_index()) if len(tel) else pd.DataFrame(
        columns=["junction", "teleports", "runs", "reasons"])
    nodes = ctx.patch["nodes"]
    hot["lon"] = [nodes.get(j.split("_")[0], [None, None])[0] for j in hot.junction]
    hot["lat"] = [nodes.get(j.split("_")[0], [None, None])[1] for j in hot.junction]
    hot["sumo_type"] = [net.get(j) for j in hot.junction]
    hot["merged_signal_cluster"] = [any(p in joined for p in j.split("_")) for j in hot.junction]
    hot["touches_event_closure"] = [any(p in near_closure for p in j.split("_")) for j in hot.junction]
    hot.to_csv(out / "teleport_hotspots.csv", index=False)
    result = {"runs": checks, "teleports": len(tel), "junctions": len(hot),
              "top10_share_pct": round(100 * hot.teleports.head(10).sum() / max(len(tel), 1), 1),
              "by_reason": tel.reason.value_counts().to_dict(), "by_sumo_type": hot.groupby("sumo_type").teleports.sum().to_dict(),
              "at_event_closures": int(hot.loc[hot.touches_event_closure, "teleports"].sum())}
    save(out / "diagnostics.json", result)
    return result


def sumonet_junction_types(path):
    import xml.etree.ElementTree as ET
    types = {}
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "junction":
            types[el.get("id")] = el.get("type")
            el.clear()
        elif el.tag in ("edge", "connection", "tlLogic"):
            el.clear()
    return types


def normalized_rows(patch, scenarios, run, data):
    """Canonical IDs, mph, UTC buckets and provenance; unused roads are absent, never filled."""
    ids = sorted(patch["segments"])
    valid = (data["sampledSeconds"] > 0) & np.isfinite(data["speed"]) & (data["speed"] >= 0)
    buckets, columns = np.nonzero(valid)
    midnight = datetime.fromisoformat(EVENTS[run["event_key"]]["date"]).replace(tzinfo=SF_TZ)
    cfg = scenarios["time"]
    local_seconds = cfg["sim_begin_s"] + np.arange(valid.shape[0]) * BUCKET_S
    times = [(midnight + timedelta(seconds=int(s))).astimezone(timezone.utc).isoformat() for s in local_seconds]
    ff = np.array([patch["segments"][s]["fallback_free_flow_mph"] for s in ids])[columns]
    speed = data["speed"][buckets, columns] * MPS_TO_MPH
    return pd.DataFrame({"time": np.asarray(times)[buckets], "road_segment_id": np.asarray(ids)[columns],
                         "run_id": run["run_id"], "scenario": run["family_id"], "event_key": run["event_key"],
                         "synthetic": True, "source": "sumo", "speed_mph": speed,
                         "free_flow_speed_mph": ff, "congestion_ratio": np.clip(1 - speed / ff, 0, 1),
                         "throughput_vph": data["left"][buckets, columns] * 3600 / BUCKET_S,
                         "entered_vehicles": data["entered"][buckets, columns],
                         "sampled_seconds": data["sampledSeconds"][buckets, columns],
                         "closed": data["closed"][buckets, columns].astype(bool),
                         "phase": np.where(local_seconds[buckets] < cfg["analysis_begin_s"], "warmup",
                                           np.where(local_seconds[buckets] >= cfg["depart_end_s"], "drain", "demand"))})


def export():
    patch = read(ROOT / "prepared" / "patch.json")
    scenarios = read(ROOT / "scenarios.json")
    out = ROOT / "export"
    out.mkdir(exist_ok=True)
    files = []
    for run in scenarios["runs"]:
        source = ROOT / "runs" / run["run_id"]
        if not (source / "summary.json").exists():
            continue
        with np.load(source / "measurements.npz") as data:
            rows = normalized_rows(patch, scenarios, run, data)
        path = out / f"simulation_observations_{run['run_id']}.csv.gz"
        rows.to_csv(path, index=False, compression="gzip")
        files.append({"path": path.name, "rows": len(rows)})
    save(out / "manifest.json", {"synthetic": True, "status": "diagnostic_not_training_approved",
         "bucket_s": BUCKET_S, "speed_unit": "mph", "timezone": "UTC", "files": files,
         "notes": "Offline files only; never load into observed traffic_metrics. Missing roads remain absent. Closure masks and full road geometry are in runs/ and prepared/patch.json. Signal timing, free flow and demand include assumptions; no model predictions are exported."})
    return {"files": files}


def report():
    patch = read(ROOT / "prepared" / "patch.json")
    manifest = read(ROOT / "prepared" / "source_manifest.json")
    net = read(ROOT / "net" / "network.json")
    cw = pd.read_csv(ROOT / "net" / "crosswalk.csv")
    missing = set(cw.loc[(cw.n_sumo_edges == 0) & cw.absorbed_junction.isna(), "road_segment_id"])
    loops = [s for s in missing if patch["segments"][s]["u"] == patch["segments"][s]["v"]]
    net = {**net, "omitted_self_loops": len(loops), "missing_unexplained": len(missing) - len(loops)}
    ids = sorted(patch["segments"])
    lengths = np.array([patch["segments"][s]["length_m"] for s in ids])
    rows, union = [], np.zeros(len(ids), bool)
    # Distinct physical geometries prevent counting two directions as two streets.
    groups = defaultdict(list)
    for i, sid in enumerate(ids):
        p = patch["segments"][sid]
        c = tuple(tuple(round(float(v), 6) for v in q) for q in p["coords"])
        groups[min(c, c[::-1])].append(i)
    phys_length = sum(float(lengths[index].max()) for index in groups.values())
    for path in sorted((ROOT / "runs").glob("*/summary.json")):
        summary = read(path)
        with np.load(path.parent / "measurements.npz") as data:
            seen = np.nan_to_num(data["sampledSeconds"]).sum(0) > 0
            union |= seen
            closed_entries = float(np.nan_to_num(data["entered"])[data["closed"].astype(bool)].sum())
            valid_buckets = int((np.nan_to_num(data["sampledSeconds"]) > 0).sum())
        s = {"run_id": summary["run_id"], "trips": summary["trips_generated"], "unfinished": summary["unfinished"],
             "unroutable": summary["not_inserted_or_no_route"], "teleports": summary["teleports"].get("total", 0),
             "teleports_per_100_trips": round(100 * summary["teleports"].get("total", 0) / max(summary["trips_generated"], 1), 2),
             "runtime_s": summary["runtime_s"], "segments_with_traffic": int(seen.sum()),
             "directed_length_coverage_pct": round(float(lengths[seen].sum() / lengths.sum() * 100), 2),
             "physical_street_length_coverage_pct": round(sum(float(lengths[ix].max()) for ix in groups.values() if seen[ix].any()) / phys_length * 100, 2),
             "segment_bucket_measurements": valid_buckets, "closed_edge_entries": closed_entries}
        rows.append(s)
    catalog = read(ROOT / "prepared" / "event_catalog.json")["events"]
    all_matches = [r for event in catalog.values() for r in event["rows"]]
    match_stats = {status: sum(r["match_status"] == status for r in all_matches)
                   for status in sorted({r["match_status"] for r in all_matches})}
    stats = {"network": net, "source_manifest": manifest, "runs": rows,
             "union_segments_with_traffic": int(union.sum()),
             "union_directed_length_coverage_pct": round(float(lengths[union].sum() / lengths.sum() * 100), 2),
             "union_physical_street_length_coverage_pct": round(sum(float(lengths[ix].max()) for ix in groups.values() if union[ix].any()) / phys_length * 100, 2),
             "event_cases": len(catalog), "closure_row_match_status": match_stats, "trained_model": False,
             "quality_status": "diagnostic: review geometry, demand, teleports, unfinished trips and closure matches before training"}
    save(ROOT / "coverage.json", stats)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = ["# Citywide simulation data pilot", "", "This batch generates data only. No model has been trained.", "",
             f"- Canonical SF graph: {len(ids):,} directed segments.",
             f"- SUMO network: {net['sumo_segments']:,} explicit road edges; {net['absorbed_junction_segments']:,} junction connectors absorbed; {net['omitted_self_loops']} self-loop roads omitted by conversion; {net['missing_unexplained']} unexplained omissions.",
             f"- Real special-event permit cases indexed for matching: {len(catalog)} (recurrences and multiple road rows retained; unresolved matches remain explicit).",
             f"- Event closure-row matching: {match_stats}.",
             f"- Roads carrying traffic in at least one completed run: {stats['union_directed_length_coverage_pct']}% of directed length; {stats['union_physical_street_length_coverage_pct']}% of physical street length.",
             "- Physical coverage counts coincident reverse geometries once; it is based on the local OSM graph, not an external administrative-road inventory.",
             "- Missing or unused roads stay unobserved. They are not filled with invented speeds.", "",
             "| Run | Trips | Unfinished (includes uninstered trips) | Not inserted/no route | Teleports | Physical length covered | Closed-edge entries | Runtime s |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        lines.append(f"| {r['run_id']} | {r['trips']} | {r['unfinished']} | {r['unroutable']} | {r['teleports']} | {r['physical_street_length_coverage_pct']}% | {r['closed_edge_entries']} | {r['runtime_s']} |")
    lines += ["", "## What is sourced and what is assumed", "",
              "Road topology, named event footprints, permit restrictions, street IDs and available speed limits come from real snapshots. Public schedules for Castro and Folsom are separately sourced in citywide.py. The simulator uses assumed OD demand, 90-second signal cycles, missing lane defaults, and event vehicle demand. It is not a measured or calibrated reconstruction of either event.", "",
              "Event runs use only the selected event's matched full-closure rows. Ambiguous direction rows are explicitly treated as both directions; unresolved rows and other concurrent restrictions are not yet enforced. Those cases remain in prepared/closure_matches.json for review. This pilot must not be treated as training-approved merely because the processes finish.", "",
              "## Artifacts", "", "Under ml/data/sf_citywide/: prepared/patch.json, event_catalog.json, closure_matches.json, source_mapping.json, source_manifest.json; net/crosswalk.csv and net_c90.net.xml; scenarios.json; runs/<run>/measurements.npz, trips.csv, summary.json and raw SUMO outputs; coverage.json.", "",
              "Raw measurements use canonical road IDs and 10-minute buckets with SUMO speed in m/s. The export stage produces mph, 10-minute UTC timestamps, congestion ratios, run IDs and synthetic provenance in export/*.csv.gz. Empty-road values remain missing. Model-ready windowing, large-batch generation, full-day demand diversity, replay presentation, and real-event validation are subsequent stages."]
    (REPORTS_DIR / "citywide_data_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return stats


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage", choices=["prepare", "network", "simulate", "report", "export", "diagnose", "review"])
    p.add_argument("--hours", type=float, default=3, help="diagnostic window starting 09:30 local, final hour drains trips")
    p.add_argument("--vph", type=float, default=12000, help="assumed citywide background trips per hour")
    p.add_argument("--seed", type=int, default=41)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--only", nargs="*")
    p.add_argument("--review-version", default=REVIEW_VERSION, choices=[REVIEW_VERSION, "closure_review_v3"])
    a = p.parse_args()
    if a.workers < 1:
        p.error("workers must be positive")
    started = time.time()
    if a.stage == "prepare":
        result = prepare()
    elif a.stage == "network":
        result = network()
    elif a.stage == "simulate":
        result = simulate(a.hours, a.vph, a.seed, a.workers, a.only)
    elif a.stage == "export":
        result = export()
    elif a.stage == "review":
        result = review(a.review_version)
    elif a.stage == "diagnose":
        result = diagnose(a.only, a.workers)
    else:
        result = report()
    print(json.dumps({"stage": a.stage, "elapsed_s": round(time.time() - started, 1), "result": result}, default=str), flush=True)
    if isinstance(result, dict) and result.get("failures"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
