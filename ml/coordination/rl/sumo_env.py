"""Action-responsive SUMO route-choice environment (Gymnasium) around the SAME coordinator used in serving.

One episode = one frozen scenario (run) x one simulation seed:

1. History period: simulate from the run's start for `history_s` (6 completed 10-min buckets) while measuring
   roads exactly like the forecaster's training export, or load a verified saved state of that moment
   (identical for every policy).
2. Decision window: participants (seeded subset of eligible trips) are revealed at their scheduled departure,
   one at a time, in (departure, id) order; later requests are never revealed early. For each: coordinator
   candidates on the current forecast -> observation/mask (features.encode) -> action -> coordinator validation and
   commit (accepted) -> the route is registered in SUMO BEFORE insertion (TraCI route.add + vehicle.add) and read
   back. Requests with one valid candidate are committed directly (no agent step, still part of the dynamics);
   requests without candidates follow the common fallback (SUMO's own routing) and stay in all metrics.
3. Between decisions SUMO advances in real simulated time; forecasts refresh every 10 min from this run's own
   measurements; ledger progress/completion/expiry follow simulated time (the coordinator's clock is the
   simulation clock, never wall time).
4. After the window: drain until every in-scope vehicle arrives (terminated) or the cap (truncated).

Participants use vType `probe` (no SUMO rerouting device), so background automatic rerouting cannot overwrite an
assignment. Background vehicles keep the run's own rerouting behaviour. Non-compliant participants (seeded draw)
drive SUMO's route and their assignment is cancelled at the first off-route observation.
An invalid (masked) action raises InvalidAction without changing the simulation or the demand.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import gymnasium as gym
import numpy as np

from ..config import Config
from ..coordinator import Conflict, Coordinator
from ..forecast_store import ForecastStore
from ..network import MPH_PER_MPS, RoadNetwork, Snap, sha256_file
from ..schemas import RouteRequest, SelectionResult
from ..storage import Storage
from . import features as feat
from .forecast_bridge import ForecastBridge, Measurements
from .rewards import CongestionExposure, VehicleTime
from .scenario import ScenarioSpec, Trip, draw, participants

_LABELS = itertools.count()


class InvalidAction(ValueError):
    pass


def sumo_binary() -> str:
    from eventsim.sumonet import sumo_bin
    return sumo_bin("sumo")


_SUMO_VERSION: list = []


def sumo_version() -> str:
    """First line of `sumo --version` (cached per process); part of the warm-state identity."""
    if not _SUMO_VERSION:
        try:
            out = subprocess.run([sumo_binary(), "--version"], capture_output=True, text=True, timeout=60).stdout
            _SUMO_VERSION.append(out.strip().splitlines()[0] if out.strip() else "unknown")
        except Exception:
            _SUMO_VERSION.append("unknown")
    return _SUMO_VERSION[0]


_FILE_SHA: dict = {}


def _file_sha(p: Path) -> str:
    """sha256 of an input file, cached per process by (path, size, mtime)."""
    st = p.stat()
    k = (str(p), st.st_size, st.st_mtime_ns)
    if k not in _FILE_SHA:
        _FILE_SHA[k] = sha256_file(p)
    return _FILE_SHA[k]


def _digest(rows) -> str:
    return hashlib.sha256("\n".join(map(str, rows)).encode()).hexdigest()[:16]


def sumo_backend(configured: str = "traci") -> str:
    """`traci` (SUMO in a child process over a socket) or `libsumo` (SUMO in this process: no socket round trip per
    call, much faster for per-step subscriptions, but one simulation per process). TP_SUMO_BACKEND overrides."""
    b = os.environ.get("TP_SUMO_BACKEND") or configured or "traci"
    if b not in ("traci", "libsumo"):
        raise ValueError(f"unknown SUMO backend {b!r}")
    return b


class SumoSim:
    """One owned simulation (closed on reset/error; never touches other processes). The libsumo backend exposes the
    same call surface as a TraCI connection (`con.simulation`, `con.vehicle`, `con.simulationStep`, `con.close`)."""

    def __init__(self, backend: str = "traci"):
        self.con = None
        self.label = None
        self.backend = sumo_backend(backend)

    def start(self, cmd: list[str]) -> None:
        import traci.constants as tc
        if self.backend == "libsumo":
            import libsumo
            libsumo.start(cmd)
            self.con = libsumo
        else:
            import traci
            self.label = f"rlenv_{os.getpid()}_{next(_LABELS)}"
            traci.start(cmd, label=self.label, stdout=subprocess.DEVNULL)
            self.con = traci.getConnection(self.label)
        self.con.simulation.subscribe([tc.VAR_DEPARTED_VEHICLES_IDS, tc.VAR_ARRIVED_VEHICLES_IDS,
                                       tc.VAR_PENDING_VEHICLES, tc.VAR_TELEPORT_STARTING_VEHICLES_NUMBER])

    def subscribe_vehicles(self, ids) -> None:
        import traci.constants as tc
        for v in ids:
            try:
                self.con.vehicle.subscribe(v, [tc.VAR_ROAD_ID, tc.VAR_SPEED])
            except Exception:
                pass

    def step(self) -> tuple[list, list, list, int, dict]:
        import traci.constants as tc
        self.con.simulationStep()
        try:
            r = self.con.simulation.getSubscriptionResults()
        except TypeError:                     # libsumo overload that takes the (empty) simulation object id
            r = self.con.simulation.getSubscriptionResults("")
        dep = list(r.get(tc.VAR_DEPARTED_VEHICLES_IDS, ()))
        arr = list(r.get(tc.VAR_ARRIVED_VEHICLES_IDS, ()))
        pend = list(r.get(tc.VAR_PENDING_VEHICLES, ()))
        tel = int(r.get(tc.VAR_TELEPORT_STARTING_VEHICLES_NUMBER, 0))
        self.subscribe_vehicles(dep)
        return dep, arr, pend, tel, self.con.vehicle.getAllSubscriptionResults()

    def close(self) -> None:
        if self.con is not None:
            try:
                self.con.close()
            except Exception:
                pass
        self.con = None


def _strip_participants(src: Path, dst: Path, remove: set) -> None:
    tree = ET.parse(src)
    root = tree.getroot()
    for el in list(root):
        if el.tag == "trip" and el.get("id") in remove:
            root.remove(el)
    tree.write(dst, encoding="utf-8", xml_declaration=True)


def _strip_edgedata(src: Path, dst: Path) -> None:
    tree = ET.parse(src)
    root = tree.getroot()
    for el in list(root):
        if el.tag == "edgeData":
            root.remove(el)
    tree.write(dst, encoding="utf-8", xml_declaration=True)


class RouteChoiceEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, cfg: Config, net: RoadNetwork, specs: list[ScenarioSpec], policy_name: str = "rl",
                 allow_debug_forecast: bool = False, seed: int = 0, tag: str = "train"):
        super().__init__()
        if cfg.rl.k != cfg.candidates.k:
            raise ValueError("rl.k must equal candidates.k (the action/candidate slot schema)")
        if not specs:
            raise ValueError("no scenarios")
        self.cfg, self.net, self.specs = cfg, net, specs
        self.K = cfg.rl.k
        self.policy_name = policy_name
        self.allow_debug = allow_debug_forecast
        self.tag = tag
        self.observation_space = gym.spaces.Box(-np.inf, np.inf, (feat.obs_dim(self.K),), np.float32)
        self.action_space = gym.spaces.Discrete(self.K)
        self.sim = SumoSim(cfg.env.sumo_backend)
        self._mask = np.zeros(self.K, bool)
        self._pending = None
        self.episode = 0
        self.last_summary: dict | None = None
        self._base_seed = seed

    # ---- gym API -----------------------------------------------------------------------------------------------------
    def action_masks(self) -> np.ndarray:
        return self._mask.copy()

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed if seed is not None else (self._base_seed + self.episode))
        self._close()
        options = options or {}
        if "scenario" in options:
            spec = next(s for s in self.specs if s.scenario_id == options["scenario"])
        else:
            spec = self.specs[int(self.np_random.integers(len(self.specs)))]
        off = options.get("seed_offset")
        if off is None:
            offs = self.cfg.env.sim_seed_offsets
            off = offs[int(self.np_random.integers(len(offs)))]
        self._begin(spec, int(off))
        self.episode += 1
        obs = self._next_decision()
        if obs is None and "scenario" not in options and options.get("_retry", 0) < 5:
            # training draws scenarios at random: a draw without any nontrivial decision is drained, logged and
            # replaced by another draw, so vectorised trainers never get a step-less episode
            self._drain()
            self.skipped_empty = getattr(self, "skipped_empty", 0) + 1
            self._finish()
            return self.reset(options={**options, "_retry": options.get("_retry", 0) + 1})
        if obs is None:                         # no nontrivial decision at all: drain and report an empty episode
            self._drain()
            info = self._finish()
            return np.zeros(self.observation_space.shape, np.float32), {"action_mask": self._mask.copy(),
                                                                          "empty_episode": True, **info}
        return obs, {"action_mask": self._mask.copy(), "scenario": spec.scenario_id, "seed_offset": off}

    def step(self, action):
        if self._pending is None:
            raise RuntimeError("step() without a pending decision; call reset()")
        a = int(action)
        if not (0 <= a < self.K) or not self._mask[a]:
            raise InvalidAction(f"action {a} is masked (valid: {np.flatnonzero(self._mask).tolist()})")
        trip, item = self._pending
        res = SelectionResult(choices={item.request.request_id: a}, policy=self.policy_name,
                              policy_version=self.policy_name)
        self._commit_and_apply(trip, item, res, trivial=False)
        self._pending = None
        self.stats["decisions"] += 1
        self.stats["non_fastest"] += int(a != 0)
        obs = self._next_decision()
        terminated = truncated = False
        info: dict = {}
        if obs is None:
            terminated, truncated = self._drain()
            info = self._finish()
            obs = np.zeros(self.observation_space.shape, np.float32)
        reward = self.acct.take_reward()
        info["action_mask"] = self._mask.copy()
        return obs, reward, terminated, truncated, info

    def close(self):
        self._close()

    # ---- episode lifecycle -------------------------------------------------------------------------------------------
    def _close(self):
        self.sim.close()
        self._pending = None
        self._mask[:] = False

    def _paths(self, spec: ScenarioSpec, parts: list[Trip]) -> tuple[Path, Path, Path]:
        ec = self.cfg.env
        # everything the saved state depends on: demand, closures, network, participants (removed from the file),
        # history length, step, teleport rule and SUMO version (the simulation seed is in the state file name)
        ident = ["|".join(t.id for t in parts), ec.history_s, ec.step_s, ec.time_to_teleport_s, sumo_version(),
                 self.sim.backend,
                 _file_sha(spec.rou_src), _file_sha(spec.add_src), spec.net_file.name, spec.net_file.stat().st_size,
                 spec.run_seed, json.dumps(spec.routing, sort_keys=True)]
        ph = hashlib.sha1("|".join(map(str, ident)).encode()).hexdigest()[:10]
        cdir = self.cfg.path(ec.out_dir) / "cache" / spec.scenario_id / ph
        cdir.mkdir(parents=True, exist_ok=True)
        rou, add = cdir / "trips.rou.xml", cdir / "closures.add.xml"
        tag = f".{os.getpid()}.tmp"              # per-process temp names: environments share this cache folder
        if not rou.exists():
            _strip_participants(spec.rou_src, rou.with_suffix(tag), {t.id for t in parts})
            os.replace(rou.with_suffix(tag), rou)
        if not add.exists():
            _strip_edgedata(spec.add_src, add.with_suffix(tag))
            os.replace(add.with_suffix(tag), add)
        return cdir, rou, add

    def _cmd(self, spec, rou, add, edir, seed_off, begin, end, load_state=None) -> list[str]:
        r = spec.routing
        adds, extra = [str(add)], []
        if self.cfg.env.keep_outputs:           # full per-vehicle / per-road record for replays and re-analysis
            ed = edir / "edgedata.add.xml"
            ed.write_text('<additional><edgeData id="tp_edges" period="300" file="edgedata.xml.gz" '
                          'excludeEmpty="true"/></additional>')
            adds.append(str(ed))
            extra = ["--vehroute-output", str(edir / "vehroutes.xml.gz"), "--vehroute-output.exit-times", "true",
                     "--summary-output", str(edir / "sumo_summary.xml.gz")]
            fcd = float(os.environ.get("TP_FCD_PERIOD_S", "0") or 0)
            if fcd > 0:                         # vehicle positions for replays (large): opt-in per node
                extra += ["--fcd-output", str(edir / "fcd.xml.gz"), "--fcd-output.geo", "true",
                          "--device.fcd.period", str(fcd), "--fcd-output.attributes", "x,y,speed,waiting"]
                pre = os.environ.get("TP_FCD_PREFIX", "")
                if pre:                         # only these vehicles (e.g. the demo's app users "user-")
                    ids = sorted(t.id for t in spec.get_trips() if t.id.startswith(pre))
                    if ids:
                        extra += ["--device.fcd.explicit", ",".join(ids)]
        cmd = [sumo_binary(), "-n", str(spec.net_file), "-r", str(rou), "-a", ",".join(adds), *extra,
               "--begin", str(int(begin)), "--end", str(int(end)), "--seed", str((spec.run_seed + seed_off) % 2**31),
               "--tripinfo-output", str(edir / "tripinfo.xml"), "--tripinfo-output.write-unfinished", "true",
               "--statistic-output", str(edir / "stats.xml"),
               "--device.rerouting.probability", f"{r['reroute_probability']:.3f}",
               "--device.rerouting.period", str(r["reroute_period_s"]), "--device.rerouting.adaptation-steps", "18",
               "--time-to-teleport", str(int(self.cfg.env.time_to_teleport_s)), "--ignore-route-errors", "true", "--no-step-log", "true",
               "--no-warnings", "true", "--routing-algorithm", "astar", "--threads", "1",
               "--step-length", str(self.cfg.env.step_s), "--save-state.rng", "true"]
        if load_state:
            cmd += ["--load-state", str(load_state)]
        return cmd

    def _begin(self, spec: ScenarioSpec, seed_off: int) -> None:
        ec, cfg = self.cfg.env, self.cfg
        self.spec, self.seed_off = spec, seed_off
        self.wall = {"sim_s": 0.0, "forecast_s": 0.0, "prepare_s": 0.0, "commit_s": 0.0, "startup_s": 0.0}
        t_start = time.perf_counter()
        t0 = spec.time["sim_begin_s"]
        self.t_dec0 = t0 + ec.history_s
        self.t_dec1 = min(self.t_dec0 + ec.decision_window_s, spec.time["depart_end_s"])
        if self.t_dec1 <= self.t_dec0:
            raise ValueError(f"{spec.scenario_id}: no decision window after {ec.history_s} s of history")
        self.t_end = self.t_dec1 + ec.max_drain_s
        self.parts = participants(spec, self.net, self.t_dec0, self.t_dec1, ec.participation, ec.max_participants)
        trips = spec.get_trips()
        self.depart_of = {t.id: t.depart for t in trips}
        in_scope = {t.id for t in trips if t.depart < self.t_dec1}
        self.acct = VehicleTime(in_scope, ec.reward_scale_s)
        self.expo = CongestionExposure(self.net.free_flow_mph / MPH_PER_MPS, self.acct.P)
        self.identity = {
            "demand_sha": _digest(sorted(f"{t.id},{t.frm},{t.to},{t.depart:.2f}" for t in trips if t.id in in_scope)),
            "participants_sha": _digest(sorted(t.id for t in self.parts)),
            "noncompliant_sha": _digest(sorted(t.id for t in self.parts
                                               if draw(spec.scenario_id, t.id, "comply") >= ec.compliance)),
            "in_scope": len(in_scope), "t_dec0": self.t_dec0, "t_dec1": self.t_dec1, "t_end": self.t_end}
        cdir, rou, add = self._paths(spec, self.parts)
        self.edir = cfg.path(ec.out_dir) / self.tag / f"{spec.scenario_id}_s{seed_off}_ep{self.episode}_{os.getpid()}"
        self.edir.mkdir(parents=True, exist_ok=True)
        self.meas = Measurements(self.net)
        self.bridge = ForecastBridge(self.net, spec, ec.forecast_mode, cfg.path(ec.forecast_checkpoint)
                                     if ec.forecast_mode == "model" else "", ec.forecast_device,
                                     allow_debug=self.allow_debug)
        self.t = float(t0)
        self.coord = Coordinator(cfg, self.net, ForecastStore(self.net, 10, 6, cfg.forecast.max_issue_age_min),
                                 Storage(":memory:"), clock=lambda: spec.utc(self.t), selector="heuristic",
                                 strict=True)
        self.stats = {"participants": len(self.parts), "decisions": 0, "trivial": 0, "unsupported_fallback": 0,
                      "noncompliant": 0, "invalid_route": 0, "route_readback_mismatch": 0, "off_route_cancelled": 0,
                      "completed": 0, "non_fastest": 0, "teleports": 0, "forecast_refreshes": 0,
                      "forecast_refresh_failures": 0, "unsupported_reasons": {}}
        self.active: dict[str, str] = {}          # vehicle -> assignment
        self.veh_road: dict[str, str] = {}
        self.queue = list(self.parts)
        state = cdir / f"state_s{seed_off}.xml"
        smeta = cdir / f"state_s{seed_off}.json"
        self.used_warm_state = False
        if ec.warm_state_cache and state.exists() and smeta.exists():
            self.used_warm_state = self._load_state(spec, rou, add, seed_off, state, smeta)
        if not self.used_warm_state:
            self.sim.start(self._cmd(spec, rou, add, self.edir, seed_off, t0, self.t_end))
            self._run_until(self.t_dec0)
            if ec.warm_state_cache:
                self._save_state(state, smeta)
        self.acct.start_scoring(self.sim.con.vehicle.getIDList(), self.sim.con.simulation.getPendingVehicles(),
                                self.depart_of, self.t)
        self.expo.start(self.t)
        self.identity["initial_running_sha"] = _digest(sorted(self.sim.con.vehicle.getIDList()))
        self._refresh_forecast()
        self.wall["startup_s"] = time.perf_counter() - t_start

    def _save_state(self, state: Path, smeta: Path) -> None:
        """Atomic (temp file + rename, metadata last): parallel environments may save the same warm state."""
        ids = sorted(self.sim.con.vehicle.getIDList())
        tag = f".{os.getpid()}.tmp"
        self.sim.con.simulation.saveState(str(state) + tag)
        os.replace(str(state) + tag, state)
        with open(str(state.with_suffix(".npz")) + tag, "wb") as f:
            np.savez_compressed(f, **self.meas.state())
        os.replace(str(state.with_suffix(".npz")) + tag, state.with_suffix(".npz"))
        Path(str(smeta) + tag).write_text(json.dumps({"time": self.t, "vehicles": len(ids),
                                                     "ids_sha": hashlib.sha1("|".join(ids).encode()).hexdigest(),
                                                     "note": "verified on load by time and running-vehicle set"}))
        os.replace(str(smeta) + tag, smeta)

    def _load_state(self, spec, rou, add, seed_off, state: Path, smeta: Path) -> bool:
        meta = json.loads(smeta.read_text())
        if abs(meta["time"] - self.t_dec0) > 1e-6:
            return False
        self.sim.start(self._cmd(spec, rou, add, self.edir, seed_off, self.t_dec0, self.t_end, load_state=state))
        ids = sorted(self.sim.con.vehicle.getIDList())
        t_now = self.sim.con.simulation.getTime()
        ok = (abs(t_now - self.t_dec0) < 1e-6 and len(ids) == meta["vehicles"]
              and hashlib.sha1("|".join(ids).encode()).hexdigest() == meta["ids_sha"])
        if not ok:
            self.sim.close()
            for p in (state, smeta, state.with_suffix(".npz")):
                p.unlink(missing_ok=True)
            return False
        with np.load(state.with_suffix(".npz")) as z:
            self.meas.load_state({k: z[k] for k in z.files})
        self.sim.subscribe_vehicles(ids)
        self.t = float(self.t_dec0)
        return True

    # ---- simulation advance ------------------------------------------------------------------------------------------
    def _run_until(self, t_target: float) -> None:
        dt = float(self.cfg.env.step_s)
        pos = self.net.pos
        t_begin = self.spec.time["sim_begin_s"]
        while self.t + 1e-9 < t_target:
            ts = time.perf_counter()
            dep, arr, pend, tel, veh = self.sim.step()
            self.wall["sim_s"] += time.perf_counter() - ts
            roads, speeds, scope = [], [], []
            P = self.acct.P
            for v, r in veh.items():
                rd = r.get(0x50)
                if rd and rd[0] != ":":
                    i = pos.get(rd)
                    if i is not None:
                        roads.append(i)
                        speeds.append(r.get(0x40, 0.0))
                        scope.append(v in P)
                if v in self.active:
                    self.veh_road[v] = rd
            roads_a, speeds_a = np.asarray(roads, np.int64), np.asarray(speeds, float)
            self.meas.sample(roads_a, speeds_a, dt)
            self.acct.departed(dep)
            self.acct.arrived(arr)
            self.acct.accrue(pend, dt)
            if self.expo.scoring:
                self.expo.sample(roads_a, speeds_a, np.asarray(scope, bool), sum(1 for v in pend if v in P),
                                 sum(1 for v in arr if v in P), dt, self.t + dt)
            self.stats["teleports"] += tel
            self.t += dt
            for v in arr:
                aid = self.active.pop(v, None)
                self.veh_road.pop(v, None)
                if aid:
                    try:
                        self.coord.complete(aid)
                        self.stats["completed"] += 1
                    except Conflict:
                        pass
            if (self.t - t_begin) % self.meas.bucket_s == 0:
                self.meas.close_bucket(self.t - self.meas.bucket_s)
                if self.t > self.t_dec0:
                    self._refresh_forecast()
            if self.t >= self.t_dec0 and (self.t - t_begin) % self.cfg.env.progress_every_s == 0:
                self._progress()

    def _refresh_forecast(self) -> None:
        ts = time.perf_counter()
        try:
            snap = self.bridge.refresh(self.meas, self.t)
            r = self.coord.refresh_forecast(snap)
            if r.get("published"):
                self.stats["forecast_refreshes"] += 1
            else:
                self.stats["forecast_refresh_failures"] += 1
        except Exception as e:
            self.stats["forecast_refresh_failures"] += 1
            self.stats.setdefault("forecast_errors", []).append(f"{self.t}: {type(e).__name__}: {e}"[:300])
        self.wall["forecast_s"] += time.perf_counter() - ts

    def _progress(self) -> None:
        self.coord.sweep()
        for v, aid in list(self.active.items()):
            rd = self.veh_road.get(v)
            if not rd or rd[0] == ":":
                continue
            a = self.coord.ledger.assignments.get(aid)
            if a is None:
                self.active.pop(v, None)
                continue
            rest = a.route[a.progress_idx:]
            try:
                if rd in rest:
                    if rd != a.route[a.progress_idx] or a.status != "active":
                        self.coord.progress(aid, None, rd, at=self.spec.utc(self.t))
                else:
                    self.coord.cancel(aid)
                    self.active.pop(v, None)
                    self.stats["off_route_cancelled"] += 1
            except Conflict:
                self.active.pop(v, None)

    # ---- decisions ---------------------------------------------------------------------------------------------------
    def _request(self, trip: Trip) -> tuple[RouteRequest, list, list]:
        o, d = self.net.pos[trip.frm], self.net.pos[trip.to]
        req = RouteRequest(request_id=f"{self.spec.scenario_id}|{trip.id}", origin=tuple(self.net.point_at(o, 0.0)),
                           destination=tuple(self.net.point_at(d, 1.0)), depart_at=self.spec.utc(trip.depart))
        return req, [Snap(o, 0.0, 0.0, req.origin)], [Snap(d, 1.0, 0.0, req.destination)]

    def _next_decision(self):
        """Advance to the next participant that needs a policy choice; handle trivial/unsupported ones on the way."""
        self._mask[:] = False
        while self.queue:
            trip = self.queue[0]
            self._run_until(max(self.t, math.ceil(trip.depart) - self.cfg.env.step_s))
            self.queue.pop(0)
            req, o, d = self._request(trip)
            ts = time.perf_counter()
            item = self.coord.prepare_request(req, o, d)
            self.wall["prepare_s"] += time.perf_counter() - ts
            if isinstance(item, dict):
                reason = item.get("reason", "unsupported")
                self.stats["unsupported_fallback"] += 1
                self.stats["unsupported_reasons"][reason] = self.stats["unsupported_reasons"].get(reason, 0) + 1
                self._add_fallback(trip)
                continue
            valid = [j for j, ok in enumerate(item.mask) if ok and j < self.K]
            if len(valid) == 1:
                res = SelectionResult(choices={req.request_id: valid[0]}, policy="direct_single_candidate",
                                      policy_version="direct")
                self._commit_and_apply(trip, item, res, trivial=True)
                self.stats["trivial"] += 1
                continue
            ctx = self.coord.selection_context([item])
            obs, mask = feat.encode(ctx, 0, None, self.K)
            self._pending = (trip, item)
            self._mask[:] = mask
            return obs
        return None

    def _commit_and_apply(self, trip: Trip, item, res: SelectionResult, trivial: bool,
                          depart: float | None = None) -> None:
        """`depart` (local s) overrides the scheduled departure, e.g. after a batching delay; the caller accounts
        the delay as waiting time."""
        ts = time.perf_counter()
        a = self.coord.commit_selection([item], res, accept=True)[0]
        self.wall["commit_s"] += time.perf_counter() - ts
        dep = trip.depart if depart is None else depart
        comply = draw(self.spec.scenario_id, trip.id, "comply") < self.cfg.env.compliance
        if not comply:
            self.stats["noncompliant"] += 1
            self._add_fallback(trip, count=False, depart=dep)
            self.active[trip.id] = a.assignment_id
            return
        con = self.sim.con
        rid = f"rl_{trip.id}"
        try:
            con.route.add(rid, a.route)
            con.vehicle.add(trip.id, rid, typeID="probe", depart=f"{dep:.2f}", departLane="best",
                            departSpeed="max")
            if list(con.vehicle.getRoute(trip.id)) != list(a.route):
                self.stats["route_readback_mismatch"] += 1
            self.active[trip.id] = a.assignment_id
        except Exception:
            self.stats["invalid_route"] += 1
            try:
                self.coord.cancel(a.assignment_id)
            except Conflict:
                pass
            self._add_fallback(trip, count=False, depart=dep)

    def _add_fallback(self, trip: Trip, count: bool = True, depart: float | None = None) -> None:
        """Common fallback: the vehicle keeps its trip and SUMO routes it (never deleted from demand)."""
        con = self.sim.con
        try:
            edges = list(con.simulation.findRoute(trip.frm, trip.to).edges) or [trip.frm, trip.to]
            rid = f"fb_{trip.id}"
            con.route.add(rid, edges)
            con.vehicle.add(trip.id, rid, typeID="car",
                            depart=f"{(trip.depart if depart is None else depart):.2f}", departLane="best",
                            departSpeed="max")
        except Exception as e:
            self.stats.setdefault("fallback_errors", []).append(f"{trip.id}: {e}"[:200])

    def _drain(self) -> tuple[bool, bool]:
        self._run_until(self.t_dec1)
        while not self.acct.done() and self.t < self.t_end:
            self._run_until(min(self.t + 60, self.t_end))
        return self.acct.done(), not self.acct.done()

    def _finish(self) -> dict:
        cens = self.acct.censored(self.t, self.depart_of) if not self.acct.done() else {"unfinished": 0}
        self.sim.close()
        self.expo.flush(self.t)
        (self.edir / "congestion_series.json").write_text(json.dumps(self.expo.series))
        np.savez_compressed(self.edir / "congestion_roads.npz", congested_s=self.expo.road_congested_s.astype(np.float32),
                            observed_s=self.expo.road_observed_s.astype(np.float32))
        parts = {t.id for t in self.parts}
        dur, loss = [], []
        tip = self.edir / "tripinfo.xml"
        if tip.exists():
            try:
                for _, el in ET.iterparse(tip, events=("end",)):
                    if el.tag == "tripinfo" and el.get("id") in parts and el.get("arrival", "-1") not in ("-1", "-1.00"):
                        dur.append(float(el.get("duration")))
                        loss.append(float(el.get("timeLoss")))
                    el.clear()
            except ET.ParseError:
                pass
        sim_min = max((self.t_dec1 - self.t_dec0) / 60.0, 1e-9)
        s = {"scenario": self.spec.scenario_id, "split": self.spec.split, "seed_offset": self.seed_off,
             "forecast_mode": self.cfg.env.forecast_mode, "used_warm_state": self.used_warm_state,
             "in_scope_vehicles": len(self.acct.P), "in_scope_vehicle_hours": self.acct.total_s / 3600.0,
             "terminated": self.acct.done(), **cens, **{k: v for k, v in self.stats.items()},
             "dropped_trips": len(self.stats.get("fallback_errors", [])), "congestion": self.expo.summary(),
             "identity": self.identity, "time_to_teleport_s": self.cfg.env.time_to_teleport_s,
             "sumo_backend": self.sim.backend,
             "outputs": {"keep_outputs": self.cfg.env.keep_outputs,
                         "fcd_period_s": float(os.environ.get("TP_FCD_PERIOD_S", "0") or 0)
                         if self.cfg.env.keep_outputs else 0.0},
             "decisions_per_sim_min": self.stats["decisions"] / sim_min,
             "participant_mean_duration_s": float(np.mean(dur)) if dur else None,
             "participant_mean_time_loss_s": float(np.mean(loss)) if loss else None,
             "participants_arrived": len(dur), "sim_end_local_s": self.t, "wall": {k: round(v, 2) for k, v in self.wall.items()},
             "episode_dir": str(self.edir)}
        self.last_summary = s
        (self.edir / "summary.json").write_text(json.dumps(s, indent=1, default=str))
        return {"episode_summary": s}
