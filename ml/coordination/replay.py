"""Replay input mode for the deployed coordinator (MODEL_TO_ROUTING_DEPLOYMENT_PLAN.md §5.2-5.3).

No live input producer exists yet, so a deployed coordinator is fed by ONE recorded synthetic SUMO run:

    replay clock   replay time = session start + (wall time - wall anchor); the coordinator, expiry, departures and
                   forecast freshness all use it. Every health answer carries `input_mode: replay` and the run id.
    refresh        at each completed 10-min replay bucket: cut the last `history_steps` completed buckets from the run
                   (never a later one), POST them with the run's scheduled context to the forecast service
                   (`/v1/forecast?format=bundle&store=0`), validate the returned forecast + exact closures, publish.
                   A failed refresh keeps the last good snapshot until it goes stale; retried every `retry_s`.
    session        one ledger per session (sqlite under state_dir). A restart resumes the session in session.json
                   (same anchor, same ledger: live assignments are recovered). When the run is exhausted a new
                   session starts at the beginning with an empty ledger; the old session's assignments end with it.

Route choices cannot change the recorded traffic: this demonstrates the serving chain, not congestion reduction.
"""
from __future__ import annotations

import io
import json
import os
import threading
import time
import traceback
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path

import pandas as pd

from .config import Config
from .coordinator import Coordinator
from .forecast_store import ForecastInvalid, ForecastSnapshot, ForecastStore, validate
from .network import RoadNetwork
from .schemas import iso
from .storage import Storage

HISTORY_COLUMNS = ["time", "road_segment_id", "speed_mph", "observed", "closed"]


class ReplaySource:
    """Completed history buckets of one recorded run, cut at an issue time."""

    def __init__(self, run_path, context_path, bucket_min: int = 10, history_steps: int = 6):
        self.run_path = Path(run_path)
        self.table = pd.read_parquet(self.run_path, columns=HISTORY_COLUMNS)
        self.table["time"] = pd.to_datetime(self.table.time, utc=True)
        self.t = self.table.time.astype("int64").to_numpy() // 10**9
        self.ctx = json.loads(Path(context_path).read_text())
        self.B, self.Th = bucket_min * 60, history_steps
        times = sorted(set(self.t.tolist()))
        if len(times) < history_steps:
            raise ValueError(f"{self.run_path.name}: {len(times)} buckets, need at least {history_steps}")
        self.first_issue = float(times[history_steps - 1] + self.B)   # first issue time with a full history
        self.last_issue = float(times[-1] + self.B)                   # the last bucket has just completed
        self.run_id = (self.ctx.get("provenance") or {}).get("run_id") or self.run_path.stem

    def snapshot(self, issue: float) -> tuple[pd.DataFrame, dict]:
        if issue % self.B or not (self.first_issue <= issue <= self.last_issue):
            raise ValueError(f"issue time {iso(issue)} is not a bucket boundary inside the run")
        lo = issue - self.Th * self.B
        hist = self.table[(self.t >= lo) & (self.t < issue)]               # completed buckets only
        if hist.time.nunique() != self.Th:
            raise ValueError(f"{hist.time.nunique()} history buckets before {iso(issue)}, need {self.Th}")
        prov = dict(self.ctx.get("provenance") or {})
        prov.update({"source": "sumo_synthetic_replay", "synthetic": True, "replay": True, "run_id": self.run_id})
        ctx = {**self.ctx, "issued_at": pd.Timestamp(issue, unit="s", tz="UTC").isoformat(), "provenance": prov}
        return hist, ctx


class ForecastClient:
    """HTTP client of `python -m forecast serve` (bundle = forecast rows + exact closures + meta)."""

    def __init__(self, url: str, token: str | None, timeout_s: float = 180.0):
        self.url, self.token, self.timeout = url.rstrip("/"), token, timeout_s

    def _open(self, req):
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        return urllib.request.urlopen(req, timeout=self.timeout)

    def health(self) -> dict:
        with self._open(urllib.request.Request(f"{self.url}/v1/health")) as r:
            return json.loads(r.read())

    def live(self) -> dict:
        """POST /v1/live/forecast: the newest complete bucket's congestion map run (computed if missing)."""
        req = urllib.request.Request(f"{self.url}/v1/live/forecast", data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with self._open(req) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"forecast service {e.code}: {e.read()[:300]!r}") from None

    def bundle(self, hist: pd.DataFrame, ctx: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
        h = hist.copy()
        h["time"] = h.time.map(lambda t: t.isoformat())
        body = json.dumps({"context": ctx, "history": {c: h[c].tolist() for c in HISTORY_COLUMNS}}).encode()
        req = urllib.request.Request(f"{self.url}/v1/forecast?format=bundle&store=0", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with self._open(req) as r:
                data = r.read()
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"forecast service {e.code}: {e.read()[:300]!r}") from None
        return read_bundle(data)


def read_bundle(data: bytes) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = set(z.namelist())
        if names != {"forecast.parquet", "closures.parquet", "meta.json"}:    # fixed names: nothing is extracted
            raise ValueError(f"unexpected bundle members {sorted(names)}")
        return (pd.read_parquet(io.BytesIO(z.read("forecast.parquet"))),
                pd.read_parquet(io.BytesIO(z.read("closures.parquet"))), json.loads(z.read("meta.json")))


class SessionClock:
    def __init__(self, replay_start: float, wall_anchor: float, wall=time.time):
        self.replay_start, self.wall_anchor, self.wall = replay_start, wall_anchor, wall

    def __call__(self) -> float:
        return self.replay_start + (self.wall() - self.wall_anchor)


class ReplayRuntime:
    """Owns the current session's coordinator and keeps its forecast fresh. `coord` is swapped atomically at a
    session rollover; request handlers read it once per request."""

    def __init__(self, cfg: Config, net: RoadNetwork, source: ReplaySource, client: ForecastClient,
                 selector: str | None = None, wall=time.time):
        self.cfg, self.net, self.source, self.client, self.selector, self.wall = cfg, net, source, client, selector, wall
        self.state_dir = cfg.path(cfg.replay.state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.coord: Coordinator | None = None
        self.session: dict = {}
        self.last_refresh: dict | None = None
        self.refresh_failures = 0
        self.last_error: str | None = None
        self.published_issue: float | None = None
        self._stop = threading.Event()
        self._start_session(resume=True)

    # ---- sessions ---------------------------------------------------------------------------------------------------
    def _session_file(self) -> Path:
        return self.state_dir / "session.json"

    def _start_session(self, resume: bool) -> None:
        s = None
        f = self._session_file()
        if resume and f.exists():
            s = json.loads(f.read_text())
            end = s["replay_start"] + (self.wall() - s["wall_anchor"])
            if s.get("run") != self.source.run_path.name or end >= self.source.last_issue + self.source.B:
                s = None                                          # other run, or this one is exhausted
        if s is None:
            s = {"session_id": time.strftime("%Y%m%dT%H%M%S", time.gmtime(self.wall())) + "-" + uuid.uuid4().hex[:6],
                 "run": self.source.run_path.name, "run_id": self.source.run_id,
                 "replay_start": self.source.first_issue + 60.0 * self.cfg.replay.start_offset_min,
                 "wall_anchor": self.wall(), "resumed": 0}
        else:
            s["resumed"] = s.get("resumed", 0) + 1
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(s, indent=1))
        tmp.replace(f)
        clock = SessionClock(s["replay_start"], s["wall_anchor"], self.wall)
        fc = self.cfg.forecast
        store = ForecastStore(self.net, fc.bucket_min, fc.horizons, fc.max_issue_age_min)
        storage = Storage(self.state_dir / f"ledger_{s['session_id']}.sqlite")
        coord = Coordinator(self.cfg, self.net, store, storage, clock=clock, selector=self.selector)
        self.session, self.published_issue = s, None
        self.coord = coord                                        # atomic swap for request handlers

    # ---- refresh ----------------------------------------------------------------------------------------------------
    def due_issue(self) -> float:
        now = self.coord.clock()
        return max(self.source.first_issue, now // self.source.B * self.source.B)

    def refresh(self) -> dict:
        """Forecast the current replay bucket and publish it into this session's coordinator."""
        issue = self.due_issue()
        t0 = time.perf_counter()
        hist, ctx = self.source.snapshot(issue)
        df, closures, meta = self.client.bundle(hist, ctx)
        fc = self.cfg.forecast
        snap: ForecastSnapshot = validate(df, closures, self.net, fc.bucket_min, fc.horizons,
                                          {**meta, "input_mode": "replay", "session_id": self.session["session_id"]})
        r = self.coord.refresh_forecast(snap)
        if not r.get("published"):
            raise ForecastInvalid([r.get("error", "refused")])
        self.published_issue = issue
        self.last_refresh = {"issued_at": iso(issue), "forecast_version": snap.version, "retimed": r["retimed"],
                             "model_version": snap.model_version, "checkpoint_sha256": meta.get("checkpoint_sha256"),
                             "model_seconds": meta.get("seconds"), "closure_rows": len(closures),
                             "latency_s": round(time.perf_counter() - t0, 2), "wall": iso(self.wall())}
        return self.last_refresh

    def step(self) -> float:
        """One loop iteration; returns seconds to sleep."""
        B = self.source.B
        if self.coord.clock() >= self.source.last_issue + B:
            self._start_session(resume=False)
        if self.published_issue != self.due_issue():
            try:
                self.refresh()
                self.refresh_failures = 0
            except Exception as e:                                # keep the last good snapshot; retry
                self.refresh_failures += 1
                self.last_error = f"{type(e).__name__}: {e}"[:500]
                print(f"replay refresh failed ({self.refresh_failures}): {self.last_error}", flush=True)
                return self.cfg.replay.retry_s
        self.coord.sweep()
        to_next = B - (self.coord.clock() % B) + 1.0
        return max(1.0, min(to_next, self.cfg.service.sweep_s))

    def run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                wait = self.step()
            except Exception:                                     # never let the loop die silently
                traceback.print_exc()
                wait = self.cfg.replay.retry_s
            self._stop.wait(wait)

    def before_request(self) -> None:
        """Replay refreshes on its own clock (run_forever), not per request."""

    def start(self) -> "ReplayRuntime":
        threading.Thread(target=self.run_forever, daemon=True, name="replay-refresh").start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def info(self) -> dict:
        s = self.session
        now = self.coord.clock()
        return {"input_mode": "replay",
                "note": "recorded synthetic SUMO run under a replay clock; not live traffic. Route choices do not "
                        "change the recorded traffic.",
                "run_id": s.get("run_id"), "session_id": s.get("session_id"), "resumed": s.get("resumed"),
                "replay_now": iso(now), "session_ends_at": iso(self.source.last_issue + self.source.B),
                "last_refresh": self.last_refresh, "refresh_failures": self.refresh_failures,
                "last_refresh_error": self.last_error if self.refresh_failures else None}


def from_config(cfg: Config, net: RoadNetwork, selector: str | None = None) -> ReplayRuntime:
    rc = cfg.replay
    if not rc.run or not rc.context:
        raise SystemExit("replay.run and replay.context must be set for --input replay")
    src = ReplaySource(cfg.path(rc.run), cfg.path(rc.context), cfg.forecast.bucket_min)
    client = ForecastClient(rc.forecast_url, os.environ.get("FORECAST_API_TOKEN"), rc.timeout_s)
    return ReplayRuntime(cfg, net, src, client, selector)


def build_context(batch_dir: Path, run_id: str, network_version: str) -> dict:
    """context.json of one recorded run (scheduled cases/restrictions), as `forecast snapshot` writes it."""
    from forecast import events as ev_mod                        # local packaging step only (needs torch)
    sc = json.loads((batch_dir / "scenarios.json").read_text())
    run = next(r for r in sc["runs"] if r["run_id"] == run_id)
    ctx = ev_mod.run_context(sc, run)
    ctx.update({"network_version": network_version,
                "provenance": {"source": "sumo_synthetic", "synthetic": True, "batch": batch_dir.name,
                               "run_id": run_id,
                               "status": "synthetic scenarios grounded in real roads and permits; not observed "
                                         "traffic, not event ground truth"}})
    return ctx
