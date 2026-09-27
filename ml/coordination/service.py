"""ML-internal HTTP service (stdlib only; the API talks to it over HTTP, the web app never does directly).

    GET  /v1/health
    POST /v1/recommendations                 {request_id, origin:[lon,lat], destination:[lon,lat], depart_at?, reserve?, user_id?}
    GET  /v1/assignments/{id}
    POST /v1/assignments/{id}/accept         {expected_version, candidate_id?}
    POST /v1/assignments/{id}/progress       {expected_version, road_segment_id, at?, fraction?}
    POST /v1/assignments/{id}/reroute        {expected_version, road_segment_id, fraction?}
    POST /v1/assignments/{id}/cancel         {expected_version}
    POST /v1/assignments/{id}/complete       {expected_version}
    POST /v1/forecast/refresh                {path}   (file input only; the path must lie in forecast.path's folder)

Every call except /v1/health needs `Authorization: Bearer $COORDINATION_API_TOKEN` when that variable is set; it
must be set to bind a non-local address. Bodies over service.max_body_bytes are refused; a per-request `selector`
must be in service.allowed_selectors. Expired reservations are swept every service.sweep_s even with no traffic.
With `--input replay` (coordination/replay.py) the forecast refreshes itself and /v1/health carries the session;
with `--input live` (coordination/live.py) a recommendation request loads a newer congestion map when due.

request_id is the idempotency key. With the batch selector, requests are collected for up to max_requests or
max_wait_ms (whichever first) and decided together; the wait is included in the reported latency. No request ever
sees a later arrival.
"""
from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
from concurrent.futures import Future
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .coordinator import Conflict, Coordinator
from .schemas import RouteRequest


class MicroBatcher:
    def __init__(self, get_coord, max_requests: int, max_wait_ms: float):
        self.get_coord, self.max_requests, self.max_wait = get_coord, max_requests, max_wait_ms / 1000.0
        self.q: queue.Queue = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    def submit(self, req: RouteRequest) -> dict:
        f: Future = Future()
        self.q.put((req, f, time.perf_counter()))
        return f.result(timeout=30)

    def _run(self):
        while True:
            first = self.q.get()
            batch = [first]
            deadline = first[2] + self.max_wait
            while len(batch) < self.max_requests:
                rest = deadline - time.perf_counter()
                if rest <= 0:
                    break
                try:
                    batch.append(self.q.get(timeout=rest))
                except queue.Empty:
                    break
            t = time.perf_counter()
            try:
                res = self.get_coord().recommend_batch([b[0] for b in batch],
                                                       batch_wait_ms=(t - first[2]) * 1000)
                for (_, f, _), r in zip(batch, res):
                    f.set_result(r)
            except Exception as e:
                for _, f, _ in batch:
                    f.set_exception(e)


def make_handler(get_coord, batcher: MicroBatcher | None, token: str | None = None, runtime=None):
    """get_coord() returns the current coordinator (swapped by a replay session rollover)."""
    class H(BaseHTTPRequestHandler):
        server_version = "transpeaktation-coordination/0.2"

        def log_message(self, fmt, *args):
            pass

        def _send(self, code: int, body: dict):
            data = json.dumps(body, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n > get_coord().cfg.service.max_body_bytes:
                raise TooLarge()
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def _authorized(self) -> bool:
            if token and self.headers.get("Authorization", "") != f"Bearer {token}":
                self._send(401, {"error": "missing or wrong bearer token"})
                return False
            return True

        def do_GET(self):
            coord = get_coord()
            try:
                if self.path == "/v1/health":
                    h = coord.health()
                    h["input_mode"] = "file"
                    if runtime is not None:
                        h.update(runtime.info())
                    return self._send(200, h)
                if not self._authorized():
                    return
                m = re.fullmatch(r"/v1/assignments/([0-9a-f]+)", self.path)
                if m:
                    return self._send(200, coord.get(m.group(1)))
                self._send(404, {"error": "not_found"})
            except Conflict as e:
                self._send(e.status, {"error": e.reason})

        def do_POST(self):
            if not self._authorized():
                return
            coord = get_coord()
            try:
                b = self._body()
                if self.path == "/v1/recommendations":
                    if runtime is not None:
                        runtime.before_request()          # live: may load a newer map (waits only if none usable)
                        coord = get_coord()
                    req = RouteRequest.from_json(b, coord.clock())
                    sel = b.get("selector")
                    if sel is not None and sel not in coord.cfg.service.allowed_selectors:
                        return self._send(400, {"error": f"selector {sel!r} not allowed here",
                                                "allowed": coord.cfg.service.allowed_selectors})
                    if batcher is not None and sel is None:
                        r = batcher.submit(req)
                    else:
                        r = coord.recommend(req, sel)
                    code = 200 if r.get("outcome") in ("recommendation", "preview", "assignment") else 422
                    return self._send(code, r)
                if self.path == "/v1/forecast/refresh":
                    if runtime is not None:
                        return self._send(409, {"error": "forecast refresh is managed by the replay session"})
                    base = coord.cfg.path(coord.cfg.forecast.path).resolve().parent
                    p = (base / str(b["path"])).resolve()
                    if not p.is_relative_to(base):
                        return self._send(400, {"error": "path outside the forecast folder"})
                    return self._send(200, coord.refresh_forecast(p))
                m = re.fullmatch(r"/v1/assignments/([0-9a-f]+)/(accept|progress|reroute|cancel|complete)", self.path)
                if not m:
                    return self._send(404, {"error": "not_found"})
                aid, op = m.groups()
                ev = b.get("expected_version")
                if op == "accept":
                    r = coord.accept(aid, ev, b.get("candidate_id"))
                elif op == "progress":
                    r = coord.progress(aid, ev, b["road_segment_id"], b.get("at"), float(b.get("fraction", 0.0)))
                elif op == "reroute":
                    r = coord.reroute(aid, ev, b["road_segment_id"], float(b.get("fraction", 0.0)))
                elif op == "cancel":
                    r = coord.cancel(aid, ev)
                else:
                    r = coord.complete(aid, ev)
                self._send(200, r)
            except Conflict as e:
                body = {"error": e.reason}
                if e.assignment is not None:
                    body["current"] = {"version": e.assignment.version, "status": e.assignment.status}
                self._send(e.status, body)
            except TooLarge:
                self._send(413, {"error": "body too large"})
            except (KeyError, ValueError, TypeError, json.JSONDecodeError) as e:
                self._send(400, {"error": f"bad_request: {e}"})

    return H


class TooLarge(Exception):
    pass


def _sweeper(get_coord, period_s: float) -> None:
    while True:
        time.sleep(period_s)
        try:
            get_coord().sweep()
        except Exception as e:                   # keep sweeping; the error is visible in the journal
            print(f"sweep failed: {type(e).__name__}: {e}", flush=True)


def serve(coord: Coordinator | None, host: str, port: int, runtime=None) -> None:
    """File input: pass `coord`. Replay input: pass `runtime` (it owns the coordinator and sweeps it itself)."""
    token = os.environ.get("COORDINATION_API_TOKEN") or None
    if not token and host not in ("127.0.0.1", "localhost"):
        raise SystemExit("COORDINATION_API_TOKEN must be set when binding to a non-local address")
    get_coord = (lambda: runtime.coord) if runtime is not None else (lambda: coord)
    c = get_coord()
    batcher = None
    if c.selector_name == "batch":
        batcher = MicroBatcher(get_coord, c.cfg.batch.max_requests, c.cfg.batch.max_wait_ms)
    if not hasattr(runtime, "run_forever"):              # replay sweeps in its own loop; file/live need this
        threading.Thread(target=_sweeper, args=(get_coord, c.cfg.service.sweep_s), daemon=True).start()
    httpd = ThreadingHTTPServer((host, port), make_handler(get_coord, batcher, token, runtime))
    print(f"coordination service on http://{host}:{port}  selector={c.selector_name}  "
          f"input={runtime.info()['input_mode'] if runtime else 'file'}  auth={'bearer' if token else 'none (local only)'}  "
          f"forecast={c.store.current.version if c.store.current else None}", flush=True)
    httpd.serve_forever()
