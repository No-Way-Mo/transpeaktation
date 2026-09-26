"""HTTP trigger for the ingestion worker: the same `service.refresh` the scheduler runs, on demand.

    INGEST_TOKEN=<random, 16+ chars> python -m worker serve [--host 127.0.0.1] [--port 8100]

    POST /ingest/refresh       body (all optional): {"jobs": ["incidents"], "pull": true, "dry_run": false}
                               202 {job}   queued; poll status_url
                               409 {job}   a refresh is already queued or running (that job is returned)
    GET  /ingest/status/<id>   200 {job} | 404
    GET  /health               200, no auth

A refresh re-pulls six feeds and upserts ~17k documents (tens of seconds to minutes), so it runs as a background job,
not inside the request. Hackathon/dev design: the job registry lives in this process's memory (lost on restart, one
process only); `python -m worker schedule` in another process is not coordinated with it.

Mutating and expensive, so: every /ingest/* call needs `Authorization: Bearer $INGEST_TOKEN` (constant-time compare);
with no INGEST_TOKEN (or a short one) the endpoints answer 503 and do nothing. Binds to localhost unless --host says
otherwise. No CORS headers, so browsers can't call it; web/ never does. Only ingest/ runs this; api/ stays read-only.
"""
from __future__ import annotations

import hmac
import json
import os
import sys
import threading
import traceback
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from . import service

MIN_TOKEN_LEN = 16
MAX_BODY = 4096
KEEP_JOBS = 50
PARAMS = {"jobs": list, "pull": bool, "dry_run": bool}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobRegistry:
    """In-memory refresh jobs. At most one queued/running at a time: a second request gets the running job back
    instead of starting an identical run (which would double the upstream pulls and race on the same snapshots,
    watermarks and upserts)."""

    def __init__(self, runner: Callable[..., dict] = service.refresh):
        self.runner = runner
        self.jobs: OrderedDict[str, dict] = OrderedDict()
        self.lock = threading.Lock()

    def active(self) -> dict | None:
        return next((j for j in self.jobs.values() if j["status"] in ("queued", "running")), None)

    def submit(self, params: dict) -> tuple[dict, bool]:
        """(job, created). created=False means a refresh was already in flight and `job` is that one."""
        with self.lock:
            if running := self.active():
                return dict(running), False
            job = {"job_id": uuid.uuid4().hex[:12], "status": "queued", "requested": params,
                   "created_at": _now(), "started_at": None, "finished_at": None, "summary": None, "error": None}
            self.jobs[job["job_id"]] = job
            while len(self.jobs) > KEEP_JOBS:
                self.jobs.popitem(last=False)
            threading.Thread(target=self._run, args=(job,), name=f"refresh-{job['job_id']}", daemon=True).start()
            return dict(job), True

    def _run(self, job: dict) -> None:
        with self.lock:
            job.update(status="running", started_at=_now())
        try:
            summary = self.runner(**job["requested"])
            status, error = ("completed" if summary.get("ok") else "failed"), None
        except Exception as e:  # never let a refresh take the server down; details go to the operator's console
            print(f"refresh {job['job_id']} crashed:\n{service.redact(traceback.format_exc())}", file=sys.stderr, flush=True)
            summary, status, error = None, "failed", service.safe_error(e)
        with self.lock:
            job.update(status=status, summary=summary, error=error, finished_at=_now())

    def get(self, job_id: str) -> dict | None:
        with self.lock:
            job = self.jobs.get(job_id)
            return dict(job) if job else None


def parse_params(raw: bytes) -> dict:
    """Request body -> refresh() kwargs. Raises ValueError with a message safe to return."""
    body = json.loads(raw or b"{}")
    if not isinstance(body, dict):
        raise ValueError("body must be a JSON object")
    unknown = sorted(set(body) - set(PARAMS))
    if unknown:
        raise ValueError(f"unknown field(s) {unknown}; allowed: {sorted(PARAMS)}")
    for k, v in body.items():
        if not isinstance(v, PARAMS[k]):
            raise ValueError(f"{k} must be a {PARAMS[k].__name__}")
    jobs = body.get("jobs", ["incidents"])
    if not jobs or any(j not in service.JOBS for j in jobs):
        raise ValueError(f"jobs must be a non-empty subset of {list(service.JOBS)}")
    return {"jobs": list(dict.fromkeys(jobs)), "pull": body.get("pull", True), "dry_run": body.get("dry_run", False)}


def _token() -> str | None:
    t = (os.environ.get("INGEST_TOKEN") or "").strip()
    return t if len(t) >= MIN_TOKEN_LEN else None


class Handler(BaseHTTPRequestHandler):
    server_version = "transpeaktation-ingest"
    registry: JobRegistry  # set by make_server

    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self) -> bool:
        token = _token()
        if token is None:
            self._send(503, {"error": f"ingestion endpoint disabled: set INGEST_TOKEN ({MIN_TOKEN_LEN}+ chars)"})
            return False
        given = self.headers.get("Authorization", "")
        if not hmac.compare_digest(given.encode(), f"Bearer {token}".encode()):
            self._send(401, {"error": "missing or wrong bearer token"})
            return False
        return True

    def _job(self, job: dict) -> dict:
        return {**job, "status_url": f"/ingest/status/{job['job_id']}"}

    def do_GET(self) -> None:
        if self.path == "/health":
            return self._send(200, {"ok": True, "ingest_endpoint": "enabled" if _token() else "disabled"})
        if self.path.startswith("/ingest/status/"):
            if not self._authorized():
                return
            job = self.registry.get(self.path.rsplit("/", 1)[-1])
            return self._send(200, self._job(job)) if job else self._send(404, {"error": "unknown job id"})
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/ingest/refresh":
            return self._send(404, {"error": "not found"})
        if not self._authorized():
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._send(413, {"error": "body too large"})
        try:
            params = parse_params(self.rfile.read(length))
        except ValueError as e:  # includes JSONDecodeError
            return self._send(400, {"error": str(e)})
        job, created = self.registry.submit(params)
        if not created:
            return self._send(409, {"error": "a refresh is already queued or running", "job": self._job(job)})
        self._send(202, self._job(job))

    def log_message(self, fmt: str, *args: Any) -> None:  # request line only; never headers (bearer token)
        sys.stderr.write(f"[ingest-http] {self.address_string()} {fmt % args}\n")


def make_server(host: str, port: int, registry: JobRegistry | None = None) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"registry": registry or JobRegistry()})
    return ThreadingHTTPServer((host, port), handler)


def serve(host: str = "127.0.0.1", port: int = 8100) -> None:
    srv = make_server(host, port)
    state = "enabled" if _token() else f"DISABLED until INGEST_TOKEN ({MIN_TOKEN_LEN}+ chars) is set"
    print(f"ingest HTTP on http://{host}:{srv.server_port}  (POST /ingest/refresh {state})", flush=True)
    try:
        srv.serve_forever()
    finally:
        srv.server_close()
