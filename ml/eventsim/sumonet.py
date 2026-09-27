"""Stage 2: prepared patch -> SUMO network(s) + explicit crosswalk to canonical OSM segments.

    python -m eventsim network --event castro

The network is built from plain XML (not SUMO's own OSM import) so every SUMO edge id *is* the
canonical `u-v-key` and no edge is split: the crosswalk is 1:1 and is verified, not assumed.
Signal timing is unknown, so one network is built per cycle-time variant; scenarios pick one.

Outputs (ml/data/<event>/net/): net_c<cycle>.net.xml, crosswalk.csv, network.json
"""
from __future__ import annotations

import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd

from .config import MPS_TO_MPH, event_dir
from .geo import LocalProj

CYCLES = (70, 90, 110)  # seconds; SF signal plans are not in the data -> scenario variants

# Per-direction lanes when OSM has no `lanes` tag (assumption, reported). OSM `lanes` on a two-way
# way counts both directions.
DEFAULT_LANES = {"primary": 2, "secondary": 1, "tertiary": 1, "residential": 1, "unclassified": 1}
DEFAULT_LANES_ONEWAY = {"primary": 2, "secondary": 2, "tertiary": 2}


def sumo_bin(name: str) -> str:
    try:
        import sumo
        p = Path(sumo.SUMO_HOME) / "bin" / name
        if p.with_suffix(".exe").exists() or p.exists():
            return str(p)
    except ImportError:
        pass
    return name


def lanes_per_direction(s: dict) -> tuple[int, str]:
    if s["lanes"]:
        n = s["lanes"] if s["oneway"] else max(1, s["lanes"] // 2)
        return max(1, n), "osm"
    table = DEFAULT_LANES_ONEWAY if s["oneway"] else DEFAULT_LANES
    return table.get(s["highway"] or "", 1), "assumed_default"


def junction_types(patch: dict) -> dict[str, str]:
    """OSM-tagged signals -> traffic_light. Unsignalised SF junctions between minor streets are mostly
    all-way stops (assumption); larger roads get priority."""
    seg = patch["segments"]
    legs: dict[str, set] = {}
    rank: dict[str, int] = {}
    for s in seg.values():
        for n, other in ((s["u"], s["v"]), (s["v"], s["u"])):
            legs.setdefault(n, set()).add(other)
            rank[n] = max(rank.get(n, 0), s["rank"])
    sig = set(patch["signals"])
    out = {}
    for n in patch["nodes"]:
        if n in sig:
            out[n] = "traffic_light"
        elif len(legs.get(n, ())) >= 3 and rank.get(n, 0) <= 3:
            out[n] = "allway_stop"
        else:
            out[n] = "priority"
    return out


JOIN_SIGNAL_M = 25.0  # signalised nodes this close (divided-road crossings) become one SUMO junction
JOIN_STUB_M = 10.0


def signal_clusters(patch: dict, protected: frozenset = frozenset()) -> list[list[str]]:
    """Pairs of OSM signal nodes linked by a short edge (e.g. both carriageways of Dolores St) -> one junction.
    Separate programs on a 13 m median edge deadlock in SUMO. Restricted edges are never absorbed, and `protected`
    segments (e.g. every accepted closure segment citywide) are never absorbed by either rule."""
    sig = set(patch["signals"])
    restricted = {s for t in patch["timed_restrictions"] for s in t["segment_ids"]}
    parent = {n: n for n in sig}

    def find(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    for sid, s in patch["segments"].items():
        pair = s["u"] in sig and s["v"] in sig and s["length_m"] <= JOIN_SIGNAL_M and sid not in restricted
        # stubs <= 10 m touching a signal (e.g. the Market/Noe/16th complex) join even if restricted: the
        # long closed blocks next to them stay real edges, so closures are still enforced there
        stub = (s["u"] in sig or s["v"] in sig) and s["length_m"] <= JOIN_STUB_M
        if (pair or stub) and sid not in protected:
            for n in (s["u"], s["v"]):
                parent.setdefault(n, n)
            parent[find(s["u"])] = find(s["v"])
    groups: dict[str, list[str]] = {}
    for n in parent:
        groups.setdefault(find(n), []).append(n)
    # A cluster containing both ends of a protected segment would absorb it through other short edges: keep
    # such junctions separate (the protected piece must stay closable and measurable).
    swallow = {find(s["u"]) for sid, s in patch["segments"].items()
               if sid in protected and s["u"] in parent and s["v"] in parent and find(s["u"]) == find(s["v"])}
    return sorted(sorted(g) for r, g in groups.items() if len(g) > 1 and r not in swallow)


def parallel_groups(patch: dict) -> dict[str, str]:
    """OSM multi-edges (same u and v, different key; e.g. Ocean Ave's two carriageways drawn between the same
    nodes) -> {dropped segment: kept segment}. SUMO junction logic deadlocks on them (network v3 merges them)."""
    groups: dict[tuple, list[str]] = {}
    for sid, s in patch["segments"].items():
        if s["u"] != s["v"]:
            groups.setdefault((s["u"], s["v"]), []).append(sid)
    out = {}
    for sids in groups.values():
        if len(sids) > 1:
            keep = min(sids, key=lambda x: (int(patch["segments"][x]["key"]), x))
            out.update({d: keep for d in sids if d != keep})
    return out


def write_plain(patch: dict, out: Path, merge_parallel: bool = False, protected: frozenset = frozenset()) -> dict:
    proj = LocalProj(**patch["proj"])
    jt = junction_types(patch)
    boundary = set(patch["boundary_nodes"])
    nod = ET.Element("nodes")
    for n, (lon, lat) in patch["nodes"].items():
        x, y = proj.fwd([(lon, lat)])[0]
        # boundary nodes connect to the rest of the city; keep them simple priority junctions
        t = "priority" if (n in boundary and jt[n] != "traffic_light") else jt[n]
        ET.SubElement(nod, "node", id=n, x=f"{x:.2f}", y=f"{y:.2f}", type=t)
    clusters = signal_clusters(patch, protected)
    merged = parallel_groups(patch) if merge_parallel else {}
    extra_lanes: dict[str, int] = {}
    for d, k in merged.items():  # the kept edge carries the dropped carriageway's lanes (capacity preserved)
        extra_lanes[k] = extra_lanes.get(k, 0) + lanes_per_direction(patch["segments"][d])[0]
    for g in clusters:
        ET.SubElement(nod, "join", nodes=" ".join(g))
    edg = ET.Element("edges")
    lane_src = {}
    for sid, s in patch["segments"].items():
        nl, src = lanes_per_direction(s)
        lane_src[sid] = (nl, src)
        if sid in merged:
            continue
        if sid in extra_lanes:
            nl += extra_lanes[sid]
            lane_src[sid] = (nl, src + "+merged_parallel")
        xy = proj.fwd(s["coords"])
        ET.SubElement(edg, "edge", id=sid, attrib={
            "from": s["u"], "to": s["v"], "numLanes": str(nl), "priority": str(s["rank"]),
            "speed": f"{s['fallback_free_flow_mph'] / MPS_TO_MPH:.3f}",
            "shape": " ".join(f"{x:.2f},{y:.2f}" for x, y in xy),
            "spreadType": "center" if s["oneway"] else "right",
        })
    con = ET.Element("connections")
    for f, t in sorted({(merged.get(f, f), merged.get(t, t)) for f, t in patch["turn_prohibitions"]}):
        ET.SubElement(con, "delete", attrib={"from": f, "to": t})
    for el, name in ((nod, "patch.nod.xml"), (edg, "patch.edg.xml"), (con, "patch.con.xml")):
        ET.ElementTree(el).write(out / name, encoding="utf-8", xml_declaration=True)
    return {"lanes": lane_src, "junctions": jt, "clusters": clusters, "merged_parallel": merged}


def build(out: Path, cycle: int, tls_type: str = "static") -> Path:
    net = out / (f"net_c{cycle}.net.xml" if tls_type == "static" else f"net_{tls_type}.net.xml")
    cmd = [sumo_bin("netconvert"), "--node-files", str(out / "patch.nod.xml"), "--edge-files", str(out / "patch.edg.xml"),
           "--connection-files", str(out / "patch.con.xml"), "--output-file", str(net),
           "--offset.disable-normalization", "true", "--no-turnarounds.except-deadend", "true",
           "--tls.default-type", tls_type, "--tls.cycle.time", str(cycle), "--tls.join", "true", "--tls.join-dist", "30",
           "--junctions.join", "false", "--geometry.remove", "false", "--no-warnings", "true"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"netconvert failed:\n{r.stderr[-3000:]}")
    return net


def crosswalk(patch: dict, net_path: Path, lane_info: dict, clusters: list[list[str]],
              merged: dict[str, str] | None = None) -> pd.DataFrame:
    """Canonical segment -> SUMO edge. 1:1 except short connectors inside a joined signal cluster, which
    become junction-internal lanes (`absorbed_junction`) and have no edge measurement."""
    import sumolib
    net = sumolib.net.readNet(str(net_path))
    in_cluster = {n: "_".join(g) for g in clusters for n in g}
    rows = []
    for sid, s in patch["segments"].items():
        present = net.hasEdge(sid)
        e = net.getEdge(sid) if present else None
        absorbed = None
        if not present and in_cluster.get(s["u"]) and in_cluster.get(s["u"]) == in_cluster.get(s["v"]):
            absorbed = in_cluster[s["u"]]
        rows.append({"road_segment_id": sid, "sumo_edges": sid if present else "", "n_sumo_edges": int(present),
                     "absorbed_junction": absorbed, "merged_parallel_into": (merged or {}).get(sid),
                     "osm_length_m": s["length_m"], "sumo_length_m": round(e.getLength(), 2) if e else None,
                     "direction": "same" if present else None, "lanes": e.getLaneNumber() if e else None,
                     "lanes_source": lane_info[sid][1], "speed_mps": round(e.getSpeed(), 3) if e else None,
                     "from_node": s["u"], "to_node": s["v"]})
    return pd.DataFrame(rows)


def routable_edges(patch: dict, net_path: Path) -> list[str]:
    """Largest strongly connected edge set of the *SUMO* network (turn bans, junction connections)
    with every timed-restricted edge removed. Trip origins/destinations come from here, so every
    trip has a route in every scenario and the event/control pair shares the same background."""
    import sumolib
    from .prepare import largest_scc
    net = sumolib.net.readNet(str(net_path))
    restricted = {s for t in patch["timed_restrictions"] for s in t["segment_ids"]}
    arcs = [(e.getID(), o.getID()) for e in net.getEdges() if e.getID() not in restricted
            for o in e.getOutgoing() if o.getID() not in restricted]
    return sorted(largest_scc(arcs))


def run(ev) -> dict:
    d = event_dir(ev.key)
    patch = json.loads((d / "prepared" / "patch.json").read_text(encoding="utf-8"))
    out = d / "net"
    out.mkdir(parents=True, exist_ok=True)
    info = write_plain(patch, out)
    nets = {c: build(out, c) for c in CYCLES}
    cw = crosswalk(patch, nets[CYCLES[0]], info["lanes"], info["clusters"])
    cw.to_csv(out / "crosswalk.csv", index=False)
    routable = routable_edges(patch, nets[CYCLES[0]])
    (out / "routable_edges.json").write_text(json.dumps(routable), encoding="utf-8")
    missing = cw[cw.n_sumo_edges == 0]
    ratio = (cw.sumo_length_m / cw.osm_length_m).replace([np.inf], np.nan)
    import sumolib
    net = sumolib.net.readNet(str(nets[CYCLES[0]]))
    summary = {
        "segments": len(cw), "absorbed_into_joined_junctions": int(cw.absorbed_junction.notna().sum()),
        "joined_signal_clusters": len(info["clusters"]),
        "missing_in_sumo_unexplained": int((cw.n_sumo_edges == 0).sum() - cw.absorbed_junction.notna().sum()), "split_edges": int((cw.n_sumo_edges > 1).sum()),
        "length_ratio_p05_p50_p95": [round(float(x), 3) for x in ratio.quantile([.05, .5, .95])],
        "lanes_assumed": int((cw.lanes_source != "osm").sum()),
        "routable_od_edges": len(routable),
        "junction_types": pd.Series(info["junctions"]).value_counts().to_dict(),
        "tls": len(net.getTrafficLights()), "cycles": list(CYCLES),
        "nets": {c: str(p.name) for c, p in nets.items()},
    }
    (out / "network.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    if summary["missing_in_sumo_unexplained"]:
        print(f"WARNING: {len(missing)} segments missing in SUMO net: {missing.road_segment_id.tolist()[:10]}")
    return summary
