"""Stage 1: join a permitted event's closures to canonical OSM segments and real traffic context.

    python -m eventsim prepare --event castro

Outputs (ml/data/<event>/prepared/):
    event.json         sourced closure facts + explicit scenario assumptions
    patch.json         directed OSM segments of the simulation patch, attributes + their provenance,
                       closure edges, turn prohibitions, boundary edges
    observations.csv   real observations on patch segments, 10-min UTC buckets, per source (AGENTS.md)
and a readable report: ml/reports/<event>_join_report.md
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .config import (FREEWAY_SENTINEL, KMH_TO_MPH, RAW_DIR, REPORTS_DIR, SF_TZ, TILE_CONGESTION_RATIO, TS_DIR,
                     UNPOSTED_MPH, EventDef, event_dir)
from .geo import LocalProj, midpoint, point_polyline_dist, sample_polyline
from .osm import Edge, fallback_free_flow_mph, load_graphml, norm_street

CLOSURE_MATCH_M = 12.0      # edge sample within this of the closure line counts as overlapping
CLOSURE_ANGLE_COS = math.cos(math.radians(30))
EDGE_OVERLAP_MIN = 0.5      # share of an edge's length that must lie along the closure line
CNN_MATCH_M = 15.0          # patch edge midpoint -> DataSF street line
SNAP_M = 15.0               # provider line -> edge sample distance
SNAP_ANGLE_COS = math.cos(math.radians(45))
SNAP_COVER_MIN = 0.5
TOMTOM_PAIR_MAX_S = 20 * 60  # absolute/relative readings must be this close to form a free-flow estimate
TOMTOM_MIN_RELATIVE = 0.05


def _load_records(name: str) -> tuple[list[dict], dict]:
    d = json.loads((RAW_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return d["records"], {k: d.get(k) for k in ("pulled_at", "count", "source")}


def _parse_utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "")).replace(tzinfo=timezone.utc)


def _lines_of(geom: dict | None) -> list[list[tuple[float, float]]]:
    if not geom:
        return []
    if geom["type"] == "LineString":
        return [geom["coordinates"]]
    if geom["type"] == "MultiLineString":
        return list(geom["coordinates"])
    return []


# ---------------------------------------------------------------- closures

def event_closures(ev: EventDef, closures: list[dict]) -> tuple[list[dict], list[dict]]:
    """Rows for the permit case, with UTC/local consistency checks. Returns (rows, issues)."""
    rows, issues = [], []
    for r in closures:
        if r.get("case_num") != ev.case_num:
            continue
        out = {k: r.get(k) for k in ("objectid", "case_num", "case_name", "type", "status", "cnn", "street", "from_st",
                                     "to_st", "loc_desc", "direction", "veh_imp", "start_dt", "end_dt", "start_utc",
                                     "end_utc", "data_loaded_at")}
        out["shape"] = r.get("shape")
        # Source UTC is authoritative; local fields are checked with America/Los_Angeles rules, never rewritten.
        for side in ("start", "end"):
            utc = _parse_utc(r[f"{side}_utc"])
            local = datetime.fromisoformat(r[f"{side}_dt"]).replace(tzinfo=SF_TZ)
            if local.astimezone(timezone.utc) != utc:
                issues.append({"objectid": r["objectid"], "field": side, "utc": r[f"{side}_utc"],
                               "local": r[f"{side}_dt"], "local_as_utc": local.astimezone(timezone.utc).isoformat()})
        rows.append(out)
    return rows, issues


def occurrences(rows: list[dict]) -> list[dict]:
    occ = defaultdict(list)
    for r in rows:
        occ[(r["start_utc"], r["end_utc"])].append(r)
    return [{"start_utc": s, "end_utc": e, "n_rows": len(v), "cnns": sorted({r["cnn"] for r in v})}
            for (s, e), v in sorted(occ.items())]


def match_closures(rows, edges: dict[str, Edge], proj: LocalProj, streets_by_cnn: dict) -> tuple[dict, list[dict]]:
    """Closure row -> directed OSM edges by overlap + street identity + direction, not nearest point.

    Returns ({segment_id: closure info}, per-row match report).
    """
    exy = {sid: proj.fwd(e.coords) for sid, e in edges.items()}
    closed: dict[str, dict] = {}
    report = []
    for r in rows:
        lines = _lines_of(r.get("shape"))
        src = "closure_shape"
        if not lines and r["cnn"] in streets_by_cnn:
            lines, src = _lines_of(streets_by_cnn[r["cnn"]].get("line")), "streets_line"
        row = {"objectid": r["objectid"], "cnn": r["cnn"], "street": r["street"], "from_st": r["from_st"],
               "to_st": r["to_st"], "direction": r["direction"], "veh_imp": r["veh_imp"], "geometry_source": src,
               "in_streets": r["cnn"] in streets_by_cnn, "edges": [], "status": "unmatched"}
        if not lines:
            report.append(row)
            continue
        cxy = [proj.fwd(l) for l in lines]
        cpts = np.vstack([sample_polyline(c, 5.0)[0] for c in cxy])
        lo, hi = cpts.min(0) - 60, cpts.max(0) + 60
        want_name = norm_street(r["street"])
        covered = np.zeros(len(cpts), bool)
        for sid, xy in exy.items():
            if (xy.max(0) < lo).any() or (xy.min(0) > hi).any():
                continue
            pts, dirs = sample_polyline(xy, 5.0)
            best_d = np.full(len(pts), np.inf)
            best_cos = np.zeros(len(pts))
            for c in cxy:
                d, cd = point_polyline_dist(pts, c)
                better = d < best_d
                best_d[better] = d[better]
                best_cos[better] = np.abs((dirs * cd).sum(1))[better]
            ok = (best_d <= CLOSURE_MATCH_M) & (best_cos >= CLOSURE_ANGLE_COS)
            share = ok.mean()
            if share < EDGE_OVERLAP_MIN:
                continue
            e = edges[sid]
            name_ok = norm_street(e.name) == want_name
            # A differently named street is a cross/parallel street (intersection stubs sit inside the
            # buffer), so this row never closes it. Unnamed links (turn lanes, slip roads) need
            # near-complete overlap and some length.
            if not name_ok and (e.name is not None or share < 0.9 or e.length_m < 10):
                row.setdefault("rejected_name_mismatch", []).append({"segment_id": sid, "osm_name": e.name,
                                                                     "overlap": round(float(share), 2)})
                continue
            d_c, _ = point_polyline_dist(cpts, xy)
            covered |= d_c <= CLOSURE_MATCH_M
            row["edges"].append({"segment_id": sid, "overlap": round(float(share), 2), "osm_name": e.name,
                                 "name_match": name_ok})
        row["closure_length_covered"] = round(float(covered.mean()), 2)
        if row["edges"]:
            flags = []
            if row["closure_length_covered"] < 0.8:
                flags.append("partial_coverage")
            if not all(x["name_match"] for x in row["edges"]):
                flags.append("name_mismatch")
            if r["direction"] not in ("both",):
                flags.append(f"direction_{r['direction']}_treated_as_both")
            row["status"] = "matched" if not flags else "ambiguous"
            row["flags"] = flags
            for x in row["edges"]:
                c = closed.setdefault(x["segment_id"], {"cnns": [], "veh_imp": set(), "objectids": []})
                c["cnns"].append(r["cnn"])
                c["veh_imp"].add(r["veh_imp"])
                c["objectids"].append(r["objectid"])
        report.append(row)
    for c in closed.values():
        c["veh_imp"] = sorted(c["veh_imp"])
        # all-lanes-closed on any source row wins; partial restrictions keep a lane-reduction assumption
        c["restriction"] = "full" if "all-lanes-closed" in c["veh_imp"] else "partial"
    return closed, report


# ---------------------------------------------------------------- patch

def largest_scc(arcs: list[tuple[str, str]]) -> set[str]:
    """Largest strongly connected component (iterative Kosaraju)."""
    fwd, rev = defaultdict(list), defaultdict(list)
    for a, b in arcs:
        fwd[a].append(b)
        rev[b].append(a)
    verts = set(fwd) | set(rev)
    order, seen = [], set()
    for s in verts:
        if s in seen:
            continue
        seen.add(s)
        stack = [(s, iter(fwd[s]))]
        while stack:
            v, it = stack[-1]
            nxt = next((w for w in it if w not in seen), None)
            if nxt is None:
                order.append(v)
                stack.pop()
            else:
                seen.add(nxt)
                stack.append((nxt, iter(fwd[nxt])))
    comp, best = set(), set()
    for s in reversed(order):
        if s in comp:
            continue
        cur, stack = {s}, [s]
        comp.add(s)
        while stack:
            for w in rev[stack.pop()]:
                if w not in comp:
                    comp.add(w)
                    cur.add(w)
                    stack.append(w)
        if len(cur) > len(best):
            best = cur
    return best


def build_patch(nodes, edges: dict[str, Edge], closed_ids: set[str], proj: LocalProj, radius: float):
    """Closure footprint + approaches/exits/alternatives: every edge with both ends within `radius`
    of the footprint, reduced to the largest strongly connected component."""
    foot = np.vstack([sample_polyline(proj.fwd(edges[s].coords), 10.0)[0] for s in closed_ids])
    nid = list(nodes)
    nxy = proj.fwd([(nodes[n].lon, nodes[n].lat) for n in nid])
    # distance from each node to the footprint (chunked brute force; footprint is small)
    dist = np.min(np.hypot(nxy[:, None, 0] - foot[None, :, 0], nxy[:, None, 1] - foot[None, :, 1]), axis=1)
    node_d = dict(zip(nid, dist))
    inside = {n for n, d in node_d.items() if d <= radius}
    cand = {sid for sid, e in edges.items() if e.u in inside and e.v in inside and e.u != e.v}
    scc = largest_scc([(edges[s].u, edges[s].v) for s in cand])
    keep = {sid for sid in cand if edges[sid].u in scc and edges[sid].v in scc}
    dropped_scc = len(cand) - len(keep)
    # boundary: patch nodes that connect to the rest of the city (trip sources/sinks for through traffic)
    out_deg, in_deg = Counter(), Counter()
    for e in edges.values():
        if e.u in scc and e.v not in scc:
            out_deg[e.u] += 1
        if e.v in scc and e.u not in scc:
            in_deg[e.v] += 1
    boundary = {n for n in scc if out_deg[n] or in_deg[n]}
    entries = sorted(s for s in keep if edges[s].u in boundary and in_deg[edges[s].u])
    exits = sorted(s for s in keep if edges[s].v in boundary and out_deg[edges[s].v])
    return keep, node_d, boundary, entries, exits, dropped_scc


def turn_prohibitions(restrictions, edges: dict[str, Edge], keep: set[str]) -> tuple[list[list[str]], Counter]:
    """OSM restriction relations (from way, via node, to way) -> forbidden (from_edge, to_edge) pairs."""
    stats = Counter()
    by_way_v, by_way_u, out_of = defaultdict(list), defaultdict(list), defaultdict(list)
    for sid in keep:
        e = edges[sid]
        out_of[e.u].append(sid)
        for w in e.osmids:
            by_way_v[(w, e.v)].append(sid)
            by_way_u[(w, e.u)].append(sid)
    pairs = set()
    for r in restrictions:
        tag = (r.get("tags") or {}).get("restriction", "")
        m = {x["role"]: x for x in r.get("members", [])}
        if not tag or "from" not in m or "to" not in m or "via" not in m:
            stats["incomplete"] += 1
            continue
        if m["via"]["type"] != "node":
            stats["via_way_skipped"] += 1
            continue
        via = str(m["via"]["ref"])
        froms = by_way_v.get((m["from"]["ref"], via), [])
        tos = by_way_u.get((m["to"]["ref"], via), [])
        if not froms:
            stats["outside_patch"] += 1
            continue
        if tag.startswith("no_"):
            new = {(f, t) for f in froms for t in tos}
        elif tag.startswith("only_"):
            new = {(f, t) for f in froms for t in out_of[via] if t not in tos}
        else:
            stats["other_tag"] += 1
            continue
        stats["resolved" if new else "unresolved_in_patch"] += 1
        pairs |= new
    return sorted([list(p) for p in pairs]), stats


def join_cnn(edges: dict[str, Edge], keep: set[str], proj: LocalProj, streets, limits_by_cnn) -> dict[str, dict]:
    """Patch edge -> DataSF cnn (midpoint within 15 m, same street name preferred) -> posted limit."""
    sxy = []
    for s in streets:
        for l in _lines_of(s.get("line")):
            sxy.append((s["cnn"], norm_street(s.get("streetname") or s.get("street")), proj.fwd(l)))
    bbox = np.vstack([proj.fwd(edges[s].coords) for s in keep])
    lo, hi = bbox.min(0) - 100, bbox.max(0) + 100
    sxy = [(c, n, xy) for c, n, xy in sxy if not ((xy.max(0) < lo).any() or (xy.min(0) > hi).any())]
    out = {}
    for sid in keep:
        e = edges[sid]
        mid = midpoint(proj.fwd(e.coords))
        best = None
        for cnn, name, lxy in sxy:
            d = float(point_polyline_dist(mid[None], lxy)[0][0])
            if d > CNN_MATCH_M:
                continue
            score = d - (10.0 if name and name == norm_street(e.name) else 0.0)
            if best is None or score < best[0]:
                best = (score, cnn, d, name == norm_street(e.name))
        info = {"cnn": None, "cnn_dist_m": None, "cnn_name_match": None, "posted_mph": None, "limit_record": None}
        if best:
            info.update(cnn=best[1], cnn_dist_m=round(best[2], 1), cnn_name_match=best[3])
            lim = limits_by_cnn.get(best[1])
            if lim is not None:
                info["limit_record"] = lim
                if 0 < lim < FREEWAY_SENTINEL:
                    info["posted_mph"] = float(lim)
                elif lim == 0:
                    info["posted_mph"] = UNPOSTED_MPH   # AGENTS.md: 0 = unposted = 25 mph default
        out[sid] = info
    return out


# ---------------------------------------------------------------- observations

def _geometry(feed: str, lo_ll, hi_ll) -> dict[str, dict]:
    out = {}
    p = TS_DIR / feed / "geometry.jsonl"
    if not p.exists():
        return out
    for line in p.open(encoding="utf-8"):
        g = json.loads(line)
        c = np.asarray(g["coords"], float)
        if (c.max(0) < lo_ll).any() or (c.min(0) > hi_ll).any():
            continue
        out[g["key"]] = g
    return out


def snap_lines(geoms: dict[str, dict], edges: dict[str, Edge], keep: set[str], proj: LocalProj,
               allow_reverse: bool) -> tuple[dict[str, str], dict[str, str]]:
    """Each patch edge -> provider line covering >= half its length in the same direction.

    Provider geometry never leaves this function: the output is keyed by canonical segment_id.
    """
    gxy = {k: proj.fwd(g["coords"]) for k, g in geoms.items()}
    edge_line, how = {}, {}
    for sid in keep:
        xy = proj.fwd(edges[sid].coords)
        pts, dirs = sample_polyline(xy, 10.0)
        lo, hi = xy.min(0) - SNAP_M, xy.max(0) + SNAP_M
        best = (0.0, None, None)
        for k, lxy in gxy.items():
            if (lxy.max(0) < lo).any() or (lxy.min(0) > hi).any() or len(lxy) < 2:
                continue
            d, ld = point_polyline_dist(pts, lxy)
            cos = (dirs * ld).sum(1)
            same = ((d <= SNAP_M) & (cos >= SNAP_ANGLE_COS)).mean()
            rev = ((d <= SNAP_M) & (cos <= -SNAP_ANGLE_COS)).mean() if allow_reverse else 0.0
            if same > best[0]:
                best = (same, k, "same_direction")
            if rev > best[0] + 0.25:  # only when clearly better than any same-direction line
                best = (rev, k, "undirected_line")
        if best[0] >= SNAP_COVER_MIN:
            edge_line[sid], how[sid] = best[1], best[2]
    return edge_line, how


def _bucket(ts: str) -> datetime:
    t = datetime.fromisoformat(ts).astimezone(timezone.utc)
    return t.replace(minute=t.minute - t.minute % 10, second=0, microsecond=0)


def load_observations(edge_line_tt, edge_line_mb, free_flow_fallback: dict[str, tuple[float, str]]):
    """Real feeds -> rows (time, road_segment_id, source, speed_mph, free_flow_speed_mph, congestion_ratio, ...)."""
    key_to_edges_tt, key_to_edges_mb = defaultdict(list), defaultdict(list)
    for s, k in edge_line_tt.items():
        key_to_edges_tt[k].append(s)
    for s, k in edge_line_mb.items():
        key_to_edges_mb[k].append(s)
    abs_read, rel_read = [], []   # (time, key, value, closed)
    for p in sorted((TS_DIR / "tomtom_flow").glob("20*.jsonl")):
        for line in p.open(encoding="utf-8"):
            r = json.loads(line)
            if not r.get("ok"):
                continue
            t = datetime.fromisoformat(r["polled_at"]).astimezone(timezone.utc)
            for item in r["lines"]:
                if item[0] in key_to_edges_tt and item[1] is not None:
                    (abs_read if r["style"] == "absolute" else rel_read).append((t, item[0], float(item[1]), bool(item[3])))
    # Free flow = absolute / relative from readings close in time, cached per line (never an old ratio).
    rel_by_key = defaultdict(list)
    for t, k, v, _ in rel_read:
        rel_by_key[k].append((t, v))
    ff_samples = defaultdict(list)
    zero_rel = 0
    for t, k, v, _ in abs_read:
        near = [(abs((t - rt).total_seconds()), rv) for rt, rv in rel_by_key.get(k, [])]
        near = [x for x in near if x[0] <= TOMTOM_PAIR_MAX_S]
        if not near:
            continue
        rv = min(near)[1]
        if rv < TOMTOM_MIN_RELATIVE:
            zero_rel += 1
            continue
        ff_samples[k].append(v / rv)
    ff_cache = {k: float(np.median(v)) * KMH_TO_MPH for k, v in ff_samples.items()}
    rows = []
    for t, k, v, closed in abs_read:
        for sid in key_to_edges_tt[k]:
            ff, ff_src = (ff_cache[k], "tomtom_abs_over_rel") if k in ff_cache else free_flow_fallback[sid]
            spd = v * KMH_TO_MPH
            rows.append({"time": _bucket(t.isoformat()), "road_segment_id": sid, "source": "tomtom", "speed_mph": spd,
                         "free_flow_speed_mph": ff, "free_flow_source": ff_src, "category": None,
                         "provider_closed": closed})
    for p in sorted((TS_DIR / "mapbox_traffic").glob("20*.jsonl")):
        for line in p.open(encoding="utf-8"):
            r = json.loads(line)
            if not r.get("ok"):
                continue
            b = _bucket(r["polled_at"])
            for item in r["lines"]:
                if item[0] in key_to_edges_mb:
                    for sid in key_to_edges_mb[item[0]]:
                        rows.append({"time": b, "road_segment_id": sid, "source": "mapbox_tiles", "speed_mph": None,
                                     "free_flow_speed_mph": None, "free_flow_source": None, "category": item[1],
                                     "provider_closed": bool(item[3]) if len(item) > 3 else False})
    if not rows:
        return pd.DataFrame(), {"ff_lines": 0, "zero_relative": zero_rel}
    df = pd.DataFrame(rows)
    df["cat_ratio"] = df["category"].map(TILE_CONGESTION_RATIO)
    agg = df.groupby(["time", "road_segment_id", "source"], as_index=False).agg(
        speed_mph=("speed_mph", "mean"), free_flow_speed_mph=("free_flow_speed_mph", "first"),
        free_flow_source=("free_flow_source", "first"), category_ratio=("cat_ratio", "mean"),
        category=("category", lambda s: s.mode().iloc[0] if s.notna().any() else None),
        provider_closed=("provider_closed", "max"), n_readings=("source", "size"))
    ratio = 1 - agg["speed_mph"] / agg["free_flow_speed_mph"]
    # measured speed -> ratio; category stays a category-derived ratio (never a speed label)
    agg["congestion_ratio"] = np.where(agg["source"] == "tomtom", ratio.clip(0, 1), agg["category_ratio"])
    agg["ratio_from"] = np.where(agg["source"] == "tomtom", "measured_speed", "category_lookup_uncalibrated")
    return agg.drop(columns=["category_ratio"]), {"ff_lines": len(ff_cache), "zero_relative": zero_rel,
                                                  "abs_readings": len(abs_read), "rel_readings": len(rel_read)}


def other_restrictions(closures, ev: EventDef, day_start: datetime, day_end: datetime, lo_ll, hi_ll):
    """Other timed restrictions in the patch bbox that overlap the event day (closures + 511 events)."""
    out = []
    for r in closures:
        if r.get("case_num") == ev.case_num:
            continue
        s, e = _parse_utc(r["start_utc"]), _parse_utc(r["end_utc"])
        if e < day_start or s > day_end:
            continue
        c = [p for l in _lines_of(r.get("shape")) for p in l]
        if not c:
            continue
        a = np.asarray(c)
        if (a.max(0) < lo_ll).any() or (a.min(0) > hi_ll).any():
            continue
        out.append({"source": "street_closures", "id": r["objectid"], "objectid": r["objectid"],
                    "case_name": r.get("case_name"), "type": r.get("type"), "status": r.get("status"),
                    "loc_desc": r.get("loc_desc"), "veh_imp": r.get("veh_imp"), "cnn": r.get("cnn"),
                    "street": r.get("street"), "from_st": r.get("from_st"), "to_st": r.get("to_st"),
                    "direction": r.get("direction"), "start_utc": r["start_utc"], "end_utc": r["end_utc"],
                    "shape": r.get("shape")})
    seen = {}
    for p in sorted((TS_DIR / "sf511_events").glob("20*.jsonl")):
        for line in p.open(encoding="utf-8"):
            r = json.loads(line)
            g = r.get("geography") or {}
            pts = [g["coordinates"]] if g.get("type") == "Point" else []
            if not pts or not ((np.asarray(pts[0]) >= lo_ll).all() and (np.asarray(pts[0]) <= hi_ll).all()):
                continue
            seen[r["id"]] = {"source": "sf511_events", "id": r["id"], "headline": r.get("headline"),
                             "status": r.get("status"), "event_type": r.get("event_type"), "updated": r.get("updated")}
    return out, list(seen.values())


# ---------------------------------------------------------------- main

def run(ev: EventDef) -> dict:
    out_dir = event_dir(ev.key) / "prepared"
    out_dir.mkdir(parents=True, exist_ok=True)
    closures, closures_meta = _load_records("street_closures")
    streets, streets_meta = _load_records("streets")
    limits, _ = _load_records("speed_limits")
    restrictions, _ = _load_records("osm_turn_restrictions")
    nodes, edges = load_graphml(RAW_DIR / "osm_drive_graph.graphml")
    streets_by_cnn = {s["cnn"]: s for s in streets}
    limits_by_cnn: dict[str, int] = {}
    for l in limits:
        try:
            v = int(float(l.get("speedlimit") or 0))
        except ValueError:
            continue
        limits_by_cnn[l["cnn"]] = max(limits_by_cnn.get(l["cnn"], 0), v)

    rows, time_issues = event_closures(ev, closures)
    if not rows:
        raise SystemExit(f"no closure rows for case {ev.case_num}")
    statuses = Counter(r["status"] for r in rows)
    lon0 = float(np.mean([p[0] for r in rows for l in _lines_of(r["shape"]) for p in l]))
    lat0 = float(np.mean([p[1] for r in rows for l in _lines_of(r["shape"]) for p in l]))
    proj = LocalProj(lon0, lat0)
    closed, match_report = match_closures(rows, edges, proj, streets_by_cnn)
    keep, node_d, boundary, entries, exits, dropped_scc = build_patch(nodes, edges, set(closed), proj,
                                                                      ev.patch_radius_m)
    excluded_closed = sorted(set(closed) - keep)
    cnn_info = join_cnn(edges, keep, proj, streets, limits_by_cnn)
    prohib, prohib_stats = turn_prohibitions(restrictions, edges, keep)

    ll = np.array([p for s in keep for p in edges[s].coords])
    lo_ll, hi_ll = ll.min(0) - 0.0005, ll.max(0) + 0.0005
    tt_geo = _geometry("tomtom_flow", lo_ll, hi_ll)
    mb_geo = _geometry("mapbox_traffic", lo_ll, hi_ll)
    edge_tt, how_tt = snap_lines(tt_geo, edges, keep, proj, allow_reverse=False)
    edge_mb, how_mb = snap_lines(mb_geo, edges, keep, proj, allow_reverse=True)

    seg = {}
    for sid in sorted(keep):
        e = edges[sid]
        info = cnn_info[sid]
        ff, ff_src = fallback_free_flow_mph(e, info["posted_mph"])
        xy = proj.fwd(e.coords)
        dfoot = min(node_d[e.u], node_d[e.v])
        seg[sid] = {
            "segment_id": sid, "u": e.u, "v": e.v, "key": e.key, "coords": e.coords, "length_m": round(e.length_m, 2),
            "name": e.name, "highway": e.highway, "rank": e.rank, "oneway": e.oneway, "osmids": e.osmids,
            "lanes": e.lanes, "lanes_source": "osm" if e.lanes else "missing",
            "cnn": info["cnn"], "cnn_name_match": info["cnn_name_match"], "posted_mph": info["posted_mph"],
            "speed_limit_record": info["limit_record"],
            "fallback_free_flow_mph": ff, "fallback_free_flow_source": ff_src,
            "signal_at_v": nodes[e.v].highway == "traffic_signals",
            "dist_to_footprint_m": round(float(dfoot), 1), "closed": sid in closed,
            "tomtom_line": sid in edge_tt, "mapbox_line": sid in edge_mb,
            "heading_rad": float(math.atan2(*(xy[-1] - xy[0])[::-1])),
        }
    closure_edges = [{"segment_id": s, **{k: v for k, v in c.items()}} for s, c in sorted(closed.items()) if s in keep]
    occ = occurrences(rows)
    event_occ = occ[0]
    start_utc, end_utc = _parse_utc(event_occ["start_utc"]), _parse_utc(event_occ["end_utc"])
    local_day = start_utc.astimezone(SF_TZ).date()
    day_start = datetime.combine(local_day, datetime.min.time(), SF_TZ).astimezone(timezone.utc)
    day_end = day_start + timedelta(days=1)
    others, sf511 = other_restrictions(closures, ev, day_start, day_end, lo_ll, hi_ll)
    # Timed restrictions the simulator enforces: the event permit + other permitted restrictions that
    # resolve to patch edges on the event day. Partial (some-lanes) ones reduce lanes where possible.
    timed = [{"source": "event_permit", "id": ev.case_num, "name": ev.name, "segment_ids": [c["segment_id"] for c in closure_edges],
              "restriction": "full", "start_utc": event_occ["start_utc"] + "Z", "end_utc": event_occ["end_utc"] + "Z"}]
    patch_edges = {s_: edges[s_] for s_ in keep}
    for o in others:
        m, rep = match_closures([o], patch_edges, proj, streets_by_cnn)
        o["matched_segment_ids"] = sorted(m)
        o["match_status"] = rep[0]["status"] if rep else "unmatched"
        if m and o.get("status") == "Permitted":
            timed.append({"source": "street_closures", "id": o["objectid"], "name": o.get("case_name"),
                          "segment_ids": sorted(m), "start_utc": o["start_utc"] + "Z", "end_utc": o["end_utc"] + "Z",
                          "restriction": "full" if o.get("veh_imp") == "all-lanes-closed" else "partial"})

    obs, obs_stats = load_observations(edge_tt, edge_mb, {s: (seg[s]["fallback_free_flow_mph"],
                                                               seg[s]["fallback_free_flow_source"]) for s in keep})
    if len(obs):
        obs.sort_values(["time", "road_segment_id", "source"]).to_csv(out_dir / "observations.csv", index=False)

    fp_xy = np.vstack([sample_polyline(proj.fwd(edges[c["segment_id"]].coords), 10.0)[0] for c in closure_edges])
    centroid = proj.inv(fp_xy.mean(0))[0]
    h0, h1 = ev.assumed_public_start_local, ev.assumed_public_end_local
    pub_start = datetime.combine(local_day, datetime.strptime(h0, "%H:%M").time(), SF_TZ)
    pub_end = datetime.combine(local_day, datetime.strptime(h1, "%H:%M").time(), SF_TZ)
    event = {
        "event_key": ev.key, "case_num": ev.case_num, "name": ev.name,
        "sourced": {
            "dataset": "DataSF street closures (8x25-yybr)", "pulled_at": closures_meta["pulled_at"],
            "status_counts": dict(statuses), "types": sorted({r["type"] for r in rows}),
            "occurrences": occ, "affected_cnns": sorted({r["cnn"] for r in rows}),
            "rows": [{k: v for k, v in r.items() if k != "shape"} for r in rows],
            "closure_window_utc": [event_occ["start_utc"] + "Z", event_occ["end_utc"] + "Z"],
            "closure_window_local": [start_utc.astimezone(SF_TZ).isoformat(), end_utc.astimezone(SF_TZ).isoformat()],
            "utc_local_disagreements": time_issues,
        },
        "assumptions": {
            "public_hours_local": [pub_start.isoformat(), pub_end.isoformat()],
            "public_hours_source": ev.schedule_source,
            "undefined_direction_rows": "closed in both directions",
            "partial_restrictions": "lane reduction per scenario config",
            "attendance_vehicle_trips": "not in records; varied directly as event vehicle trips in scenarios",
        },
        "footprint_centroid_lonlat": [float(centroid[0]), float(centroid[1])],
        "local_day": local_day.isoformat(),
    }
    (out_dir / "event.json").write_text(json.dumps(event, indent=1, default=str), encoding="utf-8")
    patch = {
        "event_key": ev.key, "proj": {"lon0": lon0, "lat0": lat0}, "radius_m": ev.patch_radius_m,
        "segments": seg, "closure_edges": closure_edges, "turn_prohibitions": prohib,
        "boundary_nodes": sorted(boundary), "entry_edges": entries, "exit_edges": exits,
        "signals": sorted({n for s in keep for n in (edges[s].u, edges[s].v) if nodes[n].highway == "traffic_signals"}),
        "nodes": {n: [nodes[n].lon, nodes[n].lat] for n in sorted({x for s in keep for x in (edges[s].u, edges[s].v)})},
        "other_restrictions": others, "sf511_in_bbox": sf511, "timed_restrictions": timed,
    }
    (out_dir / "patch.json").write_text(json.dumps(patch, default=str), encoding="utf-8")

    summary = write_report(ev, event, patch, match_report, excluded_closed, dropped_scc, prohib_stats, obs, obs_stats,
                           how_tt, how_mb, start_utc, end_utc)
    return summary


def write_report(ev, event, patch, match_report, excluded_closed, dropped_scc, prohib_stats, obs, obs_stats,
                 how_tt, how_mb, start_utc, end_utc) -> dict:
    seg = patch["segments"]
    n = len(seg)
    closed_in = [c["segment_id"] for c in patch["closure_edges"]]
    approach = [s for s, x in seg.items() if not x["closed"] and x["dist_to_footprint_m"] <= 300]
    miss = Counter()
    for x in seg.values():
        miss["lanes"] += x["lanes"] is None
        miss["cnn"] += x["cnn"] is None
        miss["posted_limit"] += x["posted_mph"] is None
    ff_src = Counter(x["fallback_free_flow_source"] for x in seg.values())
    lines = [f"# Join report: {event['name']} (case {event['case_num']})", "",
             f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} by `python -m eventsim prepare --event {ev.key}`.",
             "Data sources are local `ingest/data` snapshots; rerun to pick up new polling.", "",
             "## Event (sourced)", "",
             f"- Permit status: {event['sourced']['status_counts']}; types: {event['sourced']['types']}",
             f"- Closure window (UTC, source): {event['sourced']['closure_window_utc'][0]} → {event['sourced']['closure_window_utc'][1]}",
             f"- Closure window (SF local): {event['sourced']['closure_window_local'][0]} → {event['sourced']['closure_window_local'][1]}",
             f"- Occurrences (case/start/end): {len(event['sourced']['occurrences'])}",
             f"- Distinct affected `cnn`: {len(event['sourced']['affected_cnns'])}",
             f"- UTC vs local field disagreements: {len(event['sourced']['utc_local_disagreements'])}", "",
             "## Assumptions (not sourced)", ""]
    lines += [f"- **{k}**: {v}" for k, v in event["assumptions"].items()]
    lines += ["", "## Closure rows → OSM directed edges", "",
              "Matching uses overlap along the closure line (≤12 m, ≤30° heading difference, ≥50% of the edge), "
              "street-name identity, and both travel directions; not a single nearest point.", "",
              "| cnn | street | from → to | direction | impact | status | edges | closure covered | flags |",
              "|---|---|---|---|---|---|---:|---:|---|"]
    for r in match_report:
        lines.append(f"| {r['cnn']} | {r['street']} | {r['from_st']} → {r['to_st']} | {r['direction']} | {r['veh_imp']} | "
                     f"{r['status']} | {len(r['edges'])} | {r.get('closure_length_covered', 0):.0%} | "
                     f"{', '.join(r.get('flags', [])) or '—'} |")
    st = Counter(r["status"] for r in match_report)
    lines += ["", f"Rows: {dict(st)}. Closed directed edges in patch: {len(closed_in)}; closed edges excluded "
                  f"(outside patch SCC): {len(excluded_closed)} {excluded_closed or ''}.", ""]
    rej = [(r["cnn"], x) for r in match_report for x in r.get("rejected_name_mismatch", [])]
    if rej:
        lines += ["Rejected overlaps (street name differs, overlap < 90%, reviewed as parallel/cross streets):", ""]
        lines += [f"- cnn {c}: `{x['segment_id']}` {x['osm_name']} ({x['overlap']:.0%})" for c, x in rej[:30]]
        lines.append("")
    lines += ["## Simulation patch", "",
              f"- Radius around the closure footprint: {patch['radius_m']:.0f} m; largest strongly connected component kept "
              f"({dropped_scc} edges dropped as disconnected).",
              f"- **Directed segments: {n}**; nodes: {len(patch['nodes'])}; signalised nodes (OSM tag): {len(patch['signals'])}",
              f"- Boundary nodes: {len(patch['boundary_nodes'])}; entry edges: {len(patch['entry_edges'])}; "
              f"exit edges: {len(patch['exit_edges'])}",
              f"- Approach/exit segments (≤300 m of footprint, open): {len(approach)}",
              f"- Turn prohibitions resolved: {len(patch['turn_prohibitions'])} pairs; relation stats: {dict(prohib_stats)}",
              f"- Missing attributes: lanes {miss['lanes']}/{n} (assumed per road class), DataSF cnn {miss['cnn']}/{n}, "
              f"posted limit {miss['posted_limit']}/{n}",
              f"- Fallback free-flow source (posted limit is a fallback, not a measurement): {dict(ff_src)}",
              "- Not available: signal timings (SUMO defaults, varied per scenario), capacities, demand (scenario assumptions).",
              "", "## Other timed restrictions on the event day in the patch bbox", ""]
    if patch["other_restrictions"]:
        lines += [f"- {o['type']} · {o['status']} · {o['case_name']} · {o['loc_desc']} · {o['veh_imp']} · "
                  f"{o['start_utc']}Z → {o['end_utc']}Z · patch edges: {len(o.get('matched_segment_ids', []))}"
                  for o in patch["other_restrictions"]]
        lines.append(f"- Enforced in simulation (event permit + permitted matches): "
                     f"{[(t['name'], t['restriction'], len(t['segment_ids'])) for t in patch['timed_restrictions']]}")
    else:
        lines.append("- none in `street_closures`")
    lines.append(f"- 511 events located in bbox (any date): {len(patch['sf511_in_bbox'])}")
    lines += ["", "## Real traffic context", ""]
    tt_cov = sum(x["tomtom_line"] for x in seg.values())
    mb_cov = sum(x["mapbox_line"] for x in seg.values())
    lines += [f"- Segments with a TomTom speed line (same direction): {tt_cov}/{n} ({tt_cov / n:.0%}); approach/exit: "
              f"{sum(seg[s]['tomtom_line'] for s in approach)}/{len(approach)}",
              f"- Segments with a Mapbox congestion line: {mb_cov}/{n} ({mb_cov / n:.0%}); matched as undirected line: "
              f"{sum(1 for v in how_mb.values() if v != 'same_direction')}",
              f"- TomTom readings joined: absolute {obs_stats.get('abs_readings', 0)}, relative {obs_stats.get('rel_readings', 0)}; "
              f"lines with an abs/rel free-flow estimate: {obs_stats.get('ff_lines', 0)}; relative < 0.05 skipped: "
              f"{obs_stats.get('zero_relative', 0)}"]
    if len(obs):
        t0, t1 = obs["time"].min(), obs["time"].max()
        overlap = not (t1 + timedelta(minutes=10) <= start_utc or t0 >= end_utc)
        lines += [f"- Observation buckets: {t0.isoformat()} → {t1.isoformat()} "
                  f"({obs['time'].nunique()} buckets); overlaps closure window: **{overlap}**"]
        tt = obs[obs.source == "tomtom"]
        if len(tt):
            r = (tt["speed_mph"] / tt["free_flow_speed_mph"])
            lines += [f"- TomTom speed / free-flow: median {r.median():.2f}, p10 {r.quantile(.1):.2f}, p90 {r.quantile(.9):.2f} "
                      f"(units check; overnight context, not event traffic)",
                      f"- TomTom median speed {tt['speed_mph'].median():.1f} mph; free-flow sources: "
                      f"{tt.drop_duplicates('road_segment_id')['free_flow_source'].value_counts().to_dict()}"]
        mb = obs[obs.source == "mapbox_tiles"]
        if len(mb):
            lines.append(f"- Mapbox categories: {mb['category'].value_counts().to_dict()}")
    else:
        lines.append("- No observations joined.")
    lines += ["", "## Status", "",
              "All closure rows are resolved or listed above; review `ambiguous` rows before trusting closure geometry."
              " Synthetic outputs built from this patch are simulation, not observed traffic."]
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{ev.key}_join_report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"report": str(path), "segments": n, "closed_edges": len(closed_in), "rows": dict(st),
            "tomtom_coverage": tt_cov / n, "mapbox_coverage": mb_cov / n}
