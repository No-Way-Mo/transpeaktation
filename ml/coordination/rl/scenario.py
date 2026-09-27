"""Frozen routing scenarios from a completed, quality-gated SUMO batch.

* Demand = the run's exact SUMO demand (`runs/<run>/trips.rou.xml`). b3_verify has no requests.parquet, so the
  request stream is reconstructed from those trips: id, departure (local s), origin road, destination road. It is
  identical for every policy. Participation and compliance are seeded per (scenario, vehicle), never by
  policy-dependent random-call order.
* Eligible participants: ordinary point-to-point car trips (no intermediate stop, e.g. ride-hail dwell stays in
  unchanged background traffic), departing inside the decision window, both roads routable in the coordinator graph.
* Splits reuse the forecaster's event groups (`splits.json`), so val/test groups are held out from both the
  forecaster and the routing policy. Train-group scenarios are in-sample for the forecaster; reports say so.
"""
from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from ..config import Config
from ..network import RoadNetwork, sha256_file

SF_TZ = ZoneInfo("America/Los_Angeles")


@dataclass
class Trip:
    id: str
    depart: float            # local seconds of the scenario day
    frm: str
    to: str
    vtype: str
    has_stop: bool


@dataclass
class ScenarioSpec:
    scenario_id: str
    batch: str
    family_id: str
    group: str
    split: str
    date: str
    time: dict               # sim_begin_s, analysis_begin_s, depart_end_s, sim_end_s (local seconds)
    run_seed: int
    net_file: Path
    rou_src: Path
    add_src: Path
    routing: dict            # reroute_probability, reroute_period_s (background SUMO routing)
    trips: list | None       # None = parsed lazily from rou_src (get_trips), so specs stay small to copy
    restrictions: list       # [{segment_ids, restriction, begin_s, end_s}] (local s), merged-parallel mapped
    forecast_context: dict   # forecast.events.run_context(...) (scheduled context only)
    provenance: dict = field(default_factory=dict)
    n_trips: int | None = None

    def get_trips(self) -> list:
        """The run's exact SUMO demand. Parsed on first use and cached per process (a few scenarios at a time):
        vectorised trainers copy the scenario list into every worker, so it must not carry every trip."""
        return self.trips if self.trips is not None else _trips_cached(str(self.rou_src))

    def utc(self, local_s: float) -> float:
        midnight = datetime.fromisoformat(self.date).replace(tzinfo=SF_TZ)
        return (midnight + timedelta(seconds=float(local_s))).astimezone(timezone.utc).timestamp()

    def local(self, epoch: float) -> float:
        midnight = datetime.fromisoformat(self.date).replace(tzinfo=SF_TZ)
        return (datetime.fromtimestamp(epoch, timezone.utc) - midnight.astimezone(timezone.utc)).total_seconds()


def _u(h: str) -> float:
    return int(hashlib.sha1(h.encode()).hexdigest()[:12], 16) / float(16 ** 12)


def draw(scenario_id: str, vid: str, what: str) -> float:
    """Uniform [0,1) keyed by scenario, vehicle and purpose: independent of any policy or call order."""
    return _u(f"{scenario_id}|{vid}|{what}")


def parse_trips(rou: Path) -> list[Trip]:
    out = []
    for _, el in ET.iterparse(rou, events=("end",)):
        if el.tag == "trip":
            out.append(Trip(el.get("id"), float(el.get("depart")), el.get("from"), el.get("to"),
                            el.get("type", "car"), any(c.tag == "stop" for c in el)))
            el.clear()
    return out


@lru_cache(maxsize=2)
def _trips_cached(rou: str) -> list:
    return parse_trips(Path(rou))


def participants(spec: ScenarioSpec, net: RoadNetwork, start_s: float, end_s: float, share: float,
                 cap: int) -> list[Trip]:
    ok_o = (net.outdeg > 0) & np.isin(net.static_availability, ["open"])
    ok_d = (net.indeg > 0) & np.isin(net.static_availability, ["open"])
    elig = [t for t in spec.get_trips()
            if start_s <= t.depart < end_s and not t.has_stop and t.vtype == "car" and t.frm != t.to
            and t.frm in net.pos and t.to in net.pos and ok_o[net.pos[t.frm]] and ok_d[net.pos[t.to]]]
    chosen = sorted((draw(spec.scenario_id, t.id, "participate"), t.id, t) for t in elig)
    chosen = [t for u, _, t in chosen if u < share][:cap]
    return sorted(chosen, key=lambda t: (t.depart, t.id))


def _gate(bdir: Path) -> dict:
    """A verification batch carries its own gate.json; a large batch run by `citywide_pipeline run` records the
    verification gate it was started under in pipeline_manifest.json."""
    if (bdir / "gate.json").exists():
        return json.loads((bdir / "gate.json").read_text())
    if (bdir / "pipeline_manifest.json").exists():
        m = json.loads((bdir / "pipeline_manifest.json").read_text())
        if m.get("gate_overridden"):
            return {"passed": False, "reason": "gate overridden"}
        return m.get("gate") or {}
    return {}


def load(cfg: Config, split: str | None = None, run_ids: list | None = None) -> list[ScenarioSpec]:
    ec = cfg.env
    bdir = cfg.path(ec.sim_root) / "batches" / ec.batch
    sc = json.loads((bdir / "scenarios.json").read_text())
    gate = _gate(bdir)
    if not gate.get("passed"):
        raise SystemExit(f"batch {ec.batch} has not passed its quality gate; refusing to build RL scenarios")
    qpath = bdir / "quality.csv"
    flags = dict(pd.read_csv(qpath, usecols=["run_id", "quality_flag"]).itertuples(index=False)) if qpath.exists() else {}
    splits = json.loads(cfg.path(ec.splits).read_text())
    group_split = {g: s for s in ("train", "val", "test") for g in splits.get(s, [])}
    fams = {f["family_id"]: f for f in sc["families"]}
    net_dir = cfg.path(ec.sim_root) / sc.get("network_dir", "net")
    cw = pd.read_csv(net_dir / "crosswalk.csv")
    rep = ({r.road_segment_id: r.merged_parallel_into for r in cw.itertuples() if isinstance(r.merged_parallel_into, str)}
           if "merged_parallel_into" in cw else {})
    from forecast.events import run_context
    out = []
    for run in sc["runs"]:
        if run_ids and run["run_id"] not in run_ids:
            continue
        rdir = bdir / "runs" / run["run_id"]
        if not (rdir / "summary.json").exists():
            continue
        if flags.get(run["run_id"], "ok") != "ok":   # per-run quality flag (e.g. review: gridlock teleports)
            continue
        summ = json.loads((rdir / "summary.json").read_text())
        fam = fams[run["family_id"]]
        sp = group_split.get(run["family_group"], "unassigned")
        if split and sp != split:
            continue
        restr = [{"segment_ids": sorted({rep.get(s, s) for s in r["segment_ids"]}), "restriction": r["restriction"],
                  "begin_s": float(r["begin_s"]), "end_s": float(r["end_s"])} for r in run["restrictions"]]
        spec = ScenarioSpec(
            scenario_id=run["run_id"], batch=ec.batch, family_id=run["family_id"], group=run["family_group"], split=sp,
            date=fam["date"], time=fam["time"], run_seed=int(run["seed"]), net_file=net_dir / "variants" / summ["net"]
            if (net_dir / "variants" / summ["net"]).exists() else net_dir / summ["net"],
            rou_src=rdir / "trips.rou.xml", add_src=rdir / "closures.add.xml", routing=fam["routing"],
            trips=None, n_trips=summ.get("trips_generated"), restrictions=restr, forecast_context=run_context(sc, run),
            provenance={"demand": "reconstructed from the run's trips.rou.xml (exact SUMO demand)",
                        "rou_sha256": sha256_file(rdir / "trips.rou.xml"), "summary_status": summ.get("dataset_status"),
                        "forecaster_split_note": "train-group scenarios are in-sample for the forecaster" if sp == "train"
                        else "event group held out from the forecaster and the routing policy"})
        if not spec.net_file.exists():
            raise SystemExit(f"{run['run_id']}: network {spec.net_file} missing")
        out.append(spec)
    return out


def manifest(cfg: Config, specs: list[ScenarioSpec]) -> dict:
    """Frozen description of an experiment's scenarios (hashes, splits, windows)."""
    ec = cfg.env
    return {"batch": ec.batch, "splits_file": str(cfg.path(ec.splits)), "splits_sha256": sha256_file(cfg.path(ec.splits)),
            "history_s": ec.history_s, "decision_window_s": ec.decision_window_s, "max_drain_s": ec.max_drain_s,
            "participation": ec.participation, "max_participants": ec.max_participants, "compliance": ec.compliance,
            "sim_seed_offsets": ec.sim_seed_offsets,
            "scenarios": [{"scenario_id": s.scenario_id, "group": s.group, "split": s.split, "date": s.date,
                           "trips": s.n_trips if s.trips is None else len(s.trips), "net": s.net_file.name, **s.provenance} for s in specs]}
