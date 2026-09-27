"""Stage 3b: run SUMO for each scenario run and extract canonical-segment measurements + trip outcomes.

    python -m eventsim simulate --event castro --workers 4

Per run (ml/data/<event>/runs/<run_id>/):
    trips.rou.xml, closures.add.xml       inputs (demand + timed restrictions)
    measurements.npz                      [bucket x segment] speed/tt/volume/closure arrays (SUMO edge = segment, 1:1)
    trips.csv                             trip outcomes incl. unfinished trips
    summary.json                          provenance: seed, SUMO version, runtime, lost/teleported vehicles

Synthetic output. It is never written to `traffic_metrics`; see export.py for run-tagged
`simulation_metrics`-shaped files.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import threading
import subprocess
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

from .config import BUCKET_S, event_dir
from .sumonet import sumo_bin

MEASURE_ATTRS = ("speed", "sampledSeconds", "entered", "left", "waitingTime", "timeLoss", "density")


# ---------------------------------------------------------------- inputs

class Context:
    """Everything a run needs that doesn't depend on the run: patch, scenarios, derived edge sets."""

    def __init__(self, ev_key: str, net_dir: str = "net"):
        d = event_dir(ev_key)
        self.dir = d
        self.net_dir = d / net_dir     # versioned network folder (citywide v3 uses "net_v3")
        self.trigger_fn = None         # optional: closed edges -> rerouter trigger edges (default: direct upstream)
        self.patch = json.loads((d / "prepared" / "patch.json").read_text(encoding="utf-8"))
        self.scen = json.loads((d / "scenarios.json").read_text(encoding="utf-8"))
        self.fams = {f["family_id"]: f for f in self.scen["families"]}
        seg = self.patch["segments"]
        self.seg_ids = sorted(seg)
        self.idx = {s: i for i, s in enumerate(self.seg_ids)}
        self.length = np.array([seg[s]["length_m"] for s in self.seg_ids])
        self.ff_speed = np.array([seg[s]["fallback_free_flow_mph"] / 2.2369362920544 for s in self.seg_ids])
        routable = set(json.loads((self.net_dir / "routable_edges.json").read_text(encoding="utf-8")))
        self.od_edges = [s for s in self.seg_ids if s in routable and seg[s]["length_m"] >= 20]
        self.entries = [s for s in self.patch["entry_edges"] if s in routable]
        self.exits = [s for s in self.patch["exit_edges"] if s in routable]
        closed_event = {c["segment_id"] for c in self.patch["closure_edges"]}
        self.market = {s for s in closed_event if "market" in str(seg[s]["name"]).lower() or seg[s]["name"] is None}
        # upstream edges notify vehicles about closures (routing at insertion already respects them)
        cw = pd.read_csv(self.net_dir / "crosswalk.csv")
        self.lanes = dict(zip(cw.road_segment_id, cw.lanes.fillna(0).astype(int)))
        # segments absorbed into a joined junction have no SUMO edge and therefore no measurements
        present = set(cw.loc[cw.n_sumo_edges > 0, "road_segment_id"])
        self.in_sim = np.array([s in present for s in self.seg_ids])
        self.incoming: dict[str, list[str]] = {}
        for s, x in seg.items():
            self.incoming.setdefault(x["v"], []).append(s)

    def net_path(self, fam: dict) -> Path:
        tls = fam["network"].get("signal_control", "static")
        name = f"net_c{fam['network']['tls_cycle_s']}.net.xml" if tls == "static" else f"net_{tls}.net.xml"
        return self.net_dir / name


def restrictions_for(ctx: Context, fam: dict, with_event: bool) -> list[dict]:
    """Timed restrictions for a run. The event permit (and its hypothetical variants) only applies to event
    runs; other sourced restrictions (e.g. Noe St shared space) apply to controls too."""
    out = []
    for r in ctx.scen["restrictions"]:
        if r["source"] == "event_permit":
            if not with_event:
                continue
            v = fam["closure_variant"]
            full = [s for s in r["segment_ids"] if not (v != "permit" and s in ctx.market)]
            out.append({**r, "segment_ids": full, "restriction": "full"})
            if v == "permit_market_one_lane":
                out.append({**r, "segment_ids": sorted(ctx.market), "restriction": "partial", "id": r["id"] + "_market"})
        else:
            out.append(r)
    return out


def _weighted(rng, items, weights, n):
    w = np.asarray(weights, float)
    return [items[i] for i in rng.choice(len(items), size=n, p=w / w.sum())]


def build_trips(ctx: Context, run: dict) -> list[dict]:
    """Background trips (identical for a run's event/control pair) + event trips."""
    fam = ctx.fams[run["family_id"]]
    t = ctx.scen["time"]
    seg = ctx.patch["segments"]
    rng = np.random.default_rng(run["seed"])
    trips = []
    # background: Poisson arrivals with the hourly shape
    for hour in range(t["sim_begin_s"] // 3600, t["depart_end_s"] // 3600 + 1):
        a, b = max(hour * 3600, t["sim_begin_s"]), min((hour + 1) * 3600, t["depart_end_s"])
        if b <= a:
            continue
        rate = fam["background_vph"] * ctx.scen["hourly_shape"][str(hour)] * (b - a) / 3600
        for dep in np.sort(rng.uniform(a, b, rng.poisson(rate))):
            if rng.random() < fam["through_share"]:
                o, d = ctx.entries[rng.integers(len(ctx.entries))], ctx.exits[rng.integers(len(ctx.exits))]
            else:
                inner = ctx.od_edges[rng.integers(len(ctx.od_edges))]
                if rng.random() < 0.5:
                    o, d = ctx.entries[rng.integers(len(ctx.entries))], inner
                else:
                    o, d = inner, ctx.exits[rng.integers(len(ctx.exits))]
            if seg[o]["v"] == seg[d]["u"] and o == d:
                continue
            trips.append({"id": f"bg{len(trips)}", "kind": "background", "depart": float(dep), "from": o, "to": d})
    if not run["with_event"]:
        return trips
    ev = fam["event"]
    rng = np.random.default_rng(run["seed"] + 1)
    r0, r1 = ev["dest_radius_m"]
    dests = [s for s in ctx.od_edges if r0 <= seg[s]["dist_to_footprint_m"] <= r1 and seg[s]["length_m"] >= 30]
    dw = [seg[s]["length_m"] for s in dests]
    n = int(round(ev["vehicle_trips"] * ev["turnout_factor"]))
    lo, hi = t["sim_begin_s"], t["depart_end_s"]
    arr = np.clip(rng.normal(ev["arrival_mu_s"], ev["arrival_sigma_s"], n), lo, hi - 600)
    ride = rng.random(n) < ev["ridehail_share"]
    dest = _weighted(rng, dests, dw, n)
    k = 0
    for i in range(n):
        o = ctx.entries[rng.integers(len(ctx.entries))]
        if ride[i]:
            x = ctx.exits[rng.integers(len(ctx.exits))]
            trips.append({"id": f"rha{k}", "kind": "ridehail_dropoff", "depart": float(arr[i]), "from": o, "to": x,
                          "stop": dest[i], "dwell": float(rng.uniform(*ev["dwell_s"]))})
        else:
            trips.append({"id": f"eva{k}", "kind": "event_arrival", "depart": float(arr[i]), "from": o, "to": dest[i]})
            dep = max(arr[i] + 1800, rng.normal(ev["departure_mu_s"], ev["departure_sigma_s"]))
            if dep < hi:
                trips.append({"id": f"evd{k}", "kind": "event_departure", "depart": float(dep), "from": dest[i],
                              "to": ctx.exits[rng.integers(len(ctx.exits))]})
        k += 1
    n_pick = int(ride.sum() * rng.uniform(0.8, 1.1))
    pick_dest = _weighted(rng, dests, dw, n_pick)
    for j in range(n_pick):
        dep = rng.normal(ev["departure_mu_s"], ev["departure_sigma_s"]) - 300
        if not lo <= dep < hi:
            continue
        trips.append({"id": f"rhp{j}", "kind": "ridehail_pickup", "depart": float(dep),
                      "from": ctx.entries[rng.integers(len(ctx.entries))], "to": ctx.exits[rng.integers(len(ctx.exits))],
                      "stop": pick_dest[j], "dwell": float(rng.uniform(*ev["dwell_s"]))})
    return sorted(trips, key=lambda x: x["depart"])


def write_routes(trips: list[dict], fam: dict, path: Path, probe_ids: set[str] = frozenset()) -> None:
    dr = fam["driver"]
    root = ET.Element("routes")
    for tid in ("car", "probe"):
        vt = ET.SubElement(root, "vType", id=tid, carFollowModel="Krauss", sigma=f"{dr['sigma']:.3f}",
                           tau=f"{dr['tau']:.3f}", speedDev=f"{dr['speed_dev']:.3f}", minGap=f"{dr['min_gap']:.2f}")
        if tid == "probe":  # probes are routed only by the replay policy (replay.py), never by SUMO's device
            ET.SubElement(vt, "param", key="has.rerouting.device", value="false")
    for tr in trips:
        el = ET.SubElement(root, "trip", id=tr["id"], type="probe" if tr["id"] in probe_ids else "car",
                           depart=f"{tr['depart']:.1f}", attrib={"from": tr["from"], "to": tr["to"]},
                           departLane="best", departSpeed="max")
        if "stop" in tr:
            attrs = {"edge": tr["stop"], "duration": f"{tr['dwell']:.0f}"}
            if tr.get("off_lane"):  # curb pull-over: the stopped vehicle leaves the travel lane (SUMO parking stop)
                attrs["parking"] = "true"
            ET.SubElement(el, "stop", attrib=attrs)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _lanes_closed(ctx: Context, r: dict, s: str) -> list[int]:
    """Lane indices a restriction closes. Partial: all but the leftmost lane (not modelled on 1-lane edges)."""
    n = ctx.lanes[s]
    return list(range(n)) if r["restriction"] == "full" else list(range(n - 1))


def write_additional(ctx: Context, restr: list[dict], out: Path) -> list[tuple[str, int]]:
    """Restrictions active for the whole simulated window are returned as static (edge, lane) closures, baked
    into the run's network so no route can ever use them (SUMO routes trips at load time, before a rerouter
    interval opens). Restrictions that start/end inside the window become rerouters triggered upstream."""
    t = ctx.scen["time"]
    root = ET.Element("additional")
    ET.SubElement(root, "edgeData", id="ed", file="edgedata.xml", period=str(BUCKET_S), begin=str(t["sim_begin_s"]),
                  end=str(t["sim_end_s"]), excludeEmpty="true")
    seg = ctx.patch["segments"]
    static: set[tuple[str, int]] = set()
    for i, r in enumerate(restr):
        b, e = max(r["begin_s"], t["sim_begin_s"]), min(r["end_s"], t["sim_end_s"])
        if e <= b or not r["segment_ids"]:
            continue
        if b <= t["sim_begin_s"] and e >= t["sim_end_s"]:
            static |= {(s, li) for s in r["segment_ids"] if ctx.lanes[s] for li in _lanes_closed(ctx, r, s)}
            continue
        closed = {s for s in r["segment_ids"] if ctx.lanes[s]}
        if getattr(ctx, "trigger_fn", None):
            trig = sorted(set(ctx.trigger_fn(closed)) - closed)
        else:
            trig = sorted({u for s in closed for u in ctx.incoming.get(seg[s]["u"], []) if ctx.lanes[u]} - closed)
        rr = ET.SubElement(root, "rerouter", id=f"closure{i}", edges=" ".join(trig))
        iv = ET.SubElement(rr, "interval", begin=f"{b:.0f}", end=f"{e:.0f}")
        for s in sorted(closed):
            if r["restriction"] == "full":
                ET.SubElement(iv, "closingReroute", id=s, disallow="passenger")
            else:
                for li in _lanes_closed(ctx, r, s):
                    ET.SubElement(iv, "closingLaneReroute", id=f"{s}_{li}", disallow="passenger")
    ET.ElementTree(root).write(out / "closures.add.xml", encoding="utf-8", xml_declaration=True)
    return sorted(static)


_NET_LOCK = threading.Lock()


def variant_net(ctx: Context, fam: dict, static: list[tuple[str, int]]) -> Path:
    """Base network for the family's signal cycle with static closures as lane permissions (cached by content)."""
    base = ctx.net_path(fam)
    if not static:
        return base
    h = hashlib.sha1(json.dumps(static).encode()).hexdigest()[:10]
    vdir = getattr(ctx, "net_dir", ctx.dir / "net") / "variants"
    path = vdir / f"{base.stem.replace('.net', '')}_{h}.net.xml"
    with _NET_LOCK:
        if path.exists():
            return path
        vdir.mkdir(exist_ok=True)
        root = ET.Element("edges")
        by_edge: dict[str, list[int]] = {}
        for s, li in static:
            by_edge.setdefault(s, []).append(li)
        for s, lanes in sorted(by_edge.items()):
            el = ET.SubElement(root, "edge", id=s)
            for li in sorted(lanes):
                ET.SubElement(el, "lane", index=str(li), disallow="passenger")
        patch = vdir / f"{h}.edg.xml"
        ET.ElementTree(root).write(patch, encoding="utf-8", xml_declaration=True)
        tmp = path.with_suffix(".tmp.xml")
        r = subprocess.run([sumo_bin("netconvert"), "--sumo-net-file", str(base), "--edge-files", str(patch),
                            "--output-file", str(tmp), "--offset.disable-normalization", "true", "--no-warnings", "true"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"netconvert variant failed: {r.stderr[-1500:]}")
        tmp.replace(path)
    return path


def closure_mask(ctx: Context, restr: list[dict]) -> np.ndarray:
    """[bucket x segment] 1 = fully closed during (part of) that bucket. Known to routing, not predicted."""
    t = ctx.scen["time"]
    nb = (t["sim_end_s"] - t["sim_begin_s"]) // BUCKET_S
    m = np.zeros((nb, len(ctx.seg_ids)), np.int8)
    for r in restr:
        if r["restriction"] != "full":
            continue
        for s in r["segment_ids"]:
            b0 = int(max(0, (r["begin_s"] - t["sim_begin_s"]) // BUCKET_S))
            b1 = int(min(nb, np.ceil((r["end_s"] - t["sim_begin_s"]) / BUCKET_S)))
            if b1 > b0:
                m[b0:b1, ctx.idx[s]] = 1
    return m


# ---------------------------------------------------------------- outputs

def parse_edgedata(ctx: Context, path: Path) -> dict[str, np.ndarray]:
    t = ctx.scen["time"]
    nb = (t["sim_end_s"] - t["sim_begin_s"]) // BUCKET_S
    arr = {a: np.full((nb, len(ctx.seg_ids)), np.nan) for a in MEASURE_ATTRS}
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "interval":
            continue
        b = int((float(el.get("begin")) - t["sim_begin_s"]) // BUCKET_S)
        if 0 <= b < nb:
            for e in el.iter("edge"):
                j = ctx.idx.get(e.get("id"))
                if j is None:
                    continue
                for a in MEASURE_ATTRS:
                    v = e.get(a)
                    if v is not None:
                        arr[a][b, j] = float(v)
        el.clear()
    return arr


def parse_tripinfo(path: Path, kinds: dict[str, str]) -> pd.DataFrame:
    rows = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "tripinfo":
            continue
        arrival = float(el.get("arrival", -1))
        rows.append({"id": el.get("id"), "kind": kinds.get(el.get("id"), "?"), "depart": float(el.get("depart", -1)),
                     "arrival": arrival, "duration": float(el.get("duration", -1)),
                     "route_length": float(el.get("routeLength", 0)), "time_loss": float(el.get("timeLoss", 0)),
                     "waiting_time": float(el.get("waitingTime", 0)), "reroutes": int(el.get("rerouteNo", 0)),
                     "depart_delay": float(el.get("departDelay", 0)),
                     "vaporized": el.get("vaporized") or "", "arrived": arrival >= 0})
        el.clear()
    return pd.DataFrame(rows)


def parse_stats(path: Path) -> dict:
    out = {}
    if not path.exists():
        return out
    root = ET.parse(path).getroot()
    for tag in ("vehicles", "teleports", "vehicleTripStatistics"):
        el = root.find(tag)
        if el is not None:
            out[tag] = {k: float(v) for k, v in el.attrib.items()}
    return out


def sumo_version() -> str:
    r = subprocess.run([sumo_bin("sumo"), "--version"], capture_output=True, text=True)
    return r.stdout.splitlines()[0] if r.stdout else "unknown"


def sumo_cmd(ctx: Context, fam: dict, run: dict, net: Path) -> list[str]:
    t = ctx.scen["time"]
    return [sumo_bin("sumo"), "-n", str(net), "-r", "trips.rou.xml", "-a", "closures.add.xml",
            "--begin", str(t["sim_begin_s"]), "--end", str(t["sim_end_s"]), "--seed", str(run["seed"] % 2**31),
            "--tripinfo-output", "tripinfo.xml", "--tripinfo-output.write-unfinished", "true",
            "--statistic-output", "stats.xml", "--device.rerouting.probability", f"{fam['routing']['reroute_probability']:.3f}",
            "--device.rerouting.period", str(fam["routing"]["reroute_period_s"]), "--device.rerouting.adaptation-steps", "18",
            "--time-to-teleport", "300", "--ignore-route-errors", "true", "--no-step-log", "true",
            "--no-warnings", "true", "--routing-algorithm", "astar", "--threads", "1"]


def simulate_run(ctx: Context, run: dict, force: bool = False) -> dict:
    out = ctx.dir / "runs" / run["run_id"]
    if (out / "summary.json").exists() and not force:
        return json.loads((out / "summary.json").read_text())
    out.mkdir(parents=True, exist_ok=True)
    fam = ctx.fams[run["family_id"]]
    trips = build_trips(ctx, run)
    restr = restrictions_for(ctx, fam, run["with_event"])
    write_routes(trips, fam, out / "trips.rou.xml")
    net = variant_net(ctx, fam, write_additional(ctx, restr, out))
    t0 = time.time()
    r = subprocess.run(sumo_cmd(ctx, fam, run, net), cwd=out, capture_output=True, text=True)
    runtime = time.time() - t0
    if r.returncode != 0:
        raise RuntimeError(f"{run['run_id']}: sumo exit {r.returncode}\n{(r.stdout + r.stderr)[-2000:]}")
    summary = extract(ctx, run, out, trips, restr, runtime, r.stderr, net)
    for f in ("edgedata.xml", "tripinfo.xml"):  # large raw outputs; best effort (Windows scanners can hold them)
        for _ in range(5):
            try:
                (out / f).unlink(missing_ok=True)
                break
            except PermissionError:
                time.sleep(1)
    return summary


def extract(ctx: Context, run: dict, out: Path, trips: list[dict], restr: list[dict], runtime: float,
            stderr: str, net: Path) -> dict:
    fam = ctx.fams[run["family_id"]]
    m = parse_edgedata(ctx, out / "edgedata.xml")
    closed = closure_mask(ctx, restr)
    np.savez_compressed(out / "measurements.npz", closed=closed, **{a: m[a].astype(np.float32) for a in MEASURE_ATTRS})
    kinds = {tr["id"]: tr["kind"] for tr in trips}
    ti = parse_tripinfo(out / "tripinfo.xml", kinds)
    missing = sorted(set(kinds) - set(ti["id"])) if len(ti) else sorted(kinds)
    if missing:  # never loaded/inserted (e.g. no route to a destination cut off by closures)
        ti = pd.concat([ti, pd.DataFrame({"id": missing, "kind": [kinds[i] for i in missing], "arrived": False,
                                          "depart": -1.0, "vaporized": "not_inserted_or_no_route"})], ignore_index=True)
    ti.to_csv(out / "trips.csv", index=False)
    st = parse_stats(out / "stats.xml")
    tel = st.get("teleports", {})
    summary = {
        "run_id": run["run_id"], "family_id": run["family_id"], "with_event": run["with_event"], "seed": run["seed"],
        "sumo": sumo_version(), "runtime_s": round(runtime, 1), "net": net.name,
        "trips_generated": len(trips), "trips_by_kind": pd.Series(kinds).value_counts().to_dict(),
        "arrived": int(ti["arrived"].sum()), "unfinished": int((~ti["arrived"]).sum()),
        "not_inserted_or_no_route": len(missing),
        "teleports": {k: int(v) for k, v in tel.items()},
        "no_route_warnings": stderr.count("No connection") + stderr.count("no valid route"),
        "mean_duration_arrived_s": float(ti.loc[ti.arrived, "duration"].mean()) if ti["arrived"].any() else None,
        "restrictions": [{"id": r["id"], "restriction": r["restriction"], "edges": len(r["segment_ids"]),
                          "begin_s": r["begin_s"], "end_s": r["end_s"]} for r in restr],
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    return summary


def run(ev, workers: int, only=None, force=False) -> dict:
    ctx = Context(ev.key)
    runs = [r for r in ctx.scen["runs"] if not only or r["run_id"] in only]
    if shutil.which(sumo_bin("sumo")) is None and not Path(sumo_bin("sumo") + ".exe").exists():
        raise SystemExit("SUMO not found: pip install eclipse-sumo")
    t0 = time.time()
    done, failed = [], []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(simulate_run, ctx, r, force): r["run_id"] for r in runs}
        for f in as_completed(futs):
            try:
                s = f.result()
                done.append(s)
                print(f"{s['run_id']}: {s['runtime_s']}s trips={s['trips_generated']} unfinished={s['unfinished']} "
                      f"teleports={s['teleports'].get('total', 0)}", flush=True)
            except Exception as e:  # keep going; report at the end
                failed.append((futs[f], str(e)[:500]))
                print(f"FAILED {futs[f]}: {str(e)[:300]}", flush=True)
    return {"runs": len(done), "failed": failed, "wall_s": round(time.time() - t0, 1),
            "mean_runtime_s": round(float(np.mean([d["runtime_s"] for d in done])), 1) if done else None}
