"""POST /ingest/refresh + GET /ingest/status/<id> (worker/server.py) and the refresh service they call
(worker/service.py). Offline: fixture snapshots, fake sinks, a mocked `python -m pull`; no live feeds or databases."""
from __future__ import annotations

import http.client
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from worker import server, service
from worker.db import ConfigError, DryRunSink

from tests.incident_fixtures import all_rows, write_raw_dir

TOKEN = "t" * 24


class FakeMongo(DryRunSink):
    """Stands in for MongoSink: records what the real pipeline would upsert."""


class ServiceRefresh(unittest.TestCase):
    """service.refresh runs the existing pull + IncidentJob with the CLI's semantics."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raw = write_raw_dir(Path(self.tmp.name) / "raw", all_rows())
        self.patches = [mock.patch.object(service, "DATA_DIR", self.raw),
                        mock.patch.object(service, "MANIFEST", self.raw / "_manifest.json"),
                        mock.patch.object(service, "GRAPHML", Path(self.tmp.name) / "no.graphml")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_dry_run_uses_the_real_incident_pipeline_and_reports_its_counts(self):
        out = service.refresh(("incidents",), pull=False, dry_run=True, use_geocoder=False)
        self.assertTrue(out["ok"])
        rep = out["jobs"]["incidents"]["report"]
        self.assertEqual(rep["street_closures"]["status"], "ok")
        self.assertGreater(rep["_dry_run"]["would_write"]["road_incidents"], 0)
        self.assertIn("no OSM graph: road_segment_ids not computed", rep["_notes"])

    def test_write_reports_what_the_sink_wrote(self):
        sink = FakeMongo()
        with mock.patch.object(service, "MongoSink", return_value=sink):
            out = service.refresh(("incidents",), pull=False, use_geocoder=False)
        self.assertTrue(out["ok"])
        self.assertEqual(out["jobs"]["incidents"]["report"]["_written"], {"road_incidents": sink.counts["road_incidents"]})
        self.assertGreater(sink.counts["road_incidents"], 0)

    def test_failed_upstream_feed_is_reported_and_the_rest_still_runs(self):
        def fake_pull(names):  # like pull.__main__.main: one feed fails, the others succeed, manifest records both
            m = {n: {"status": "ok", "count": 1} for n in names}
            m["chp_incidents"] = {"status": "fail", "error": "URLError: <urlopen error timed out> https://x/?token=abc123"}
            (self.raw / "_manifest.json").write_text(json.dumps(m))
            return 1
        with mock.patch("pull.__main__.main", side_effect=fake_pull):
            out = service.refresh(("incidents",), dry_run=True, use_geocoder=False)
        self.assertTrue(out["ok"])  # a feed failure doesn't fail the job (same as the scheduler)
        # The failed pull, plus IncidentJob's own "missing" for the one feed the fixtures don't include.
        self.assertEqual([(f["source"], f["stage"]) for f in out["failures"]],
                         [("chp_incidents", "pull"), ("street_use_permits", "normalize")])
        self.assertIn("token=***", out["failures"][0]["error"])
        self.assertEqual(out["failures"][1]["error"], "missing")
        self.assertNotIn("abc123", json.dumps(out, default=str))
        self.assertGreater(out["jobs"]["incidents"]["report"]["_dry_run"]["would_write"]["road_incidents"], 0)

    def test_missing_database_config_fails_the_job_with_a_safe_message(self):
        with mock.patch.object(service, "MongoSink", side_effect=ConfigError("set MONGODB_URI in ingest/.env (currently empty)")):
            out = service.refresh(("incidents",), pull=False, use_geocoder=False)
        self.assertFalse(out["ok"])
        self.assertEqual(out["jobs"]["incidents"], {"status": "failed", "error": "set MONGODB_URI in ingest/.env (currently empty)"})

    def test_driver_errors_never_leak_connection_strings(self):
        boom = RuntimeError("auth failed for mongodb+srv://admin:hunter2@cluster0.abcd.mongodb.net/db")
        with mock.patch.object(service, "MongoSink", side_effect=boom), \
                mock.patch("sys.stderr", new_callable=lambda: open(os.devnull, "w")):
            out = service.refresh(("incidents",), pull=False, use_geocoder=False)
        self.assertEqual(out["jobs"]["incidents"]["error"], "RuntimeError")
        self.assertNotIn("hunter2", json.dumps(out, default=str))
        self.assertNotIn("cluster0", json.dumps(out, default=str))

    def test_one_failed_job_does_not_stop_the_next(self):
        out = service.refresh(("traffic", "incidents"), pull=False, dry_run=True, use_geocoder=False)
        self.assertEqual(out["jobs"]["traffic"]["status"], "failed")  # no OSM graph in the temp dir
        self.assertIn("no OSM graph", out["jobs"]["traffic"]["error"])
        self.assertEqual(out["jobs"]["incidents"]["status"], "ok")
        self.assertFalse(out["ok"])

    def test_unknown_job_is_rejected(self):
        with self.assertRaises(ValueError):
            service.refresh(("everything",))

    def test_redact(self):
        self.assertEqual(service.redact("postgres://u:p@h:5432/db?sslmode=require"), "postgres://***@h:5432/db?sslmode=require")
        self.assertEqual(service.redact({"e": ["x?api_key=K&y=1"]}), {"e": ["x?api_key=***&y=1"]})


class Gate:
    """A fake refresh the test releases on demand, to hold a job in 'running'."""

    def __init__(self, result=None, error=None):
        self.go, self.started, self.calls = threading.Event(), threading.Event(), []
        self.result, self.error = result or {"ok": True, "jobs": {"incidents": {"status": "ok"}}, "failures": []}, error

    def __call__(self, **kw):
        self.calls.append(kw)
        self.started.set()
        self.go.wait(5)
        if self.error:
            raise self.error
        return self.result


class Http(unittest.TestCase):
    def start(self, runner):
        self.registry = server.JobRegistry(runner)
        self.srv = server.make_server("127.0.0.1", 0, self.registry)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def setUp(self):
        env = mock.patch.dict(os.environ, {"INGEST_TOKEN": TOKEN})
        env.start()
        self.addCleanup(env.stop)
        quiet = mock.patch.object(server.Handler, "log_message", lambda *a: None)
        quiet.start()
        self.addCleanup(quiet.stop)

    def call(self, method, path, body=None, token=TOKEN):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        c.request(method, path, body=None if body is None else json.dumps(body) if not isinstance(body, bytes) else body,
                  headers=headers)
        r = c.getresponse()
        out = (r.status, json.loads(r.read() or b"null"))
        c.close()
        return out

    def wait(self, job_id, status):
        for _ in range(100):
            code, job = self.call("GET", f"/ingest/status/{job_id}")
            if job["status"] == status:
                return job
            time.sleep(0.02)
        self.fail(f"job {job_id} never reached {status}: {job}")

    def test_trigger_then_poll_to_completed(self):
        gate = Gate()
        self.start(gate)
        code, job = self.call("POST", "/ingest/refresh", {"jobs": ["incidents"], "dry_run": True})
        self.assertEqual(code, 202)
        self.assertEqual(set(job), {"job_id", "status", "requested", "created_at", "started_at", "finished_at",
                                    "summary", "error", "status_url"})
        self.assertEqual((job["status"], job["status_url"]), ("queued", f"/ingest/status/{job['job_id']}"))
        self.assertEqual(job["requested"], {"jobs": ["incidents"], "pull": True, "dry_run": True})
        gate.started.wait(5)
        self.assertEqual(self.call("GET", job["status_url"])[1]["status"], "running")
        gate.go.set()
        done = self.wait(job["job_id"], "completed")
        self.assertEqual(done["summary"], gate.result)
        self.assertIsNotNone(done["finished_at"])
        self.assertEqual(gate.calls, [{"jobs": ["incidents"], "pull": True, "dry_run": True}])

    def test_second_trigger_while_running_is_409_with_the_running_job(self):
        gate = Gate()
        self.start(gate)
        first = self.call("POST", "/ingest/refresh")[1]
        gate.started.wait(5)
        code, body = self.call("POST", "/ingest/refresh", {"jobs": ["traffic"]})
        self.assertEqual(code, 409)
        self.assertEqual(body["job"]["job_id"], first["job_id"])
        gate.go.set()
        self.wait(first["job_id"], "completed")
        self.assertEqual(len(gate.calls), 1)  # the duplicate never ran
        code, again = self.call("POST", "/ingest/refresh")  # finished: a new run is allowed
        self.assertEqual(code, 202)
        self.assertNotEqual(again["job_id"], first["job_id"])

    def test_concurrent_triggers_start_exactly_one_job(self):
        gate = Gate()
        self.start(gate)
        codes, lock = [], threading.Lock()

        def hit():
            code = self.call("POST", "/ingest/refresh")[0]
            with lock:
                codes.append(code)
        ts = [threading.Thread(target=hit) for _ in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(sorted(codes), [202] + [409] * 7)
        gate.go.set()

    def test_refresh_reporting_failure_is_a_failed_job(self):
        result = {"ok": False, "jobs": {"incidents": {"status": "failed", "error": "set MONGODB_URI in ingest/.env"}},
                  "failures": [{"job": "incidents", "stage": "run", "error": "set MONGODB_URI in ingest/.env"}]}
        gate = Gate(result=result)
        gate.go.set()
        self.start(gate)
        job = self.wait(self.call("POST", "/ingest/refresh")[1]["job_id"], "failed")
        self.assertEqual(job["summary"]["failures"][0]["error"], "set MONGODB_URI in ingest/.env")

    def test_crash_is_a_failed_job_without_secrets_and_the_server_stays_up(self):
        gate = Gate(error=RuntimeError("connect mongodb://root:s3cret@10.0.0.5:27017 refused"))
        gate.go.set()
        self.start(gate)
        with mock.patch("sys.stderr", new_callable=lambda: open(os.devnull, "w")):
            job = self.wait(self.call("POST", "/ingest/refresh")[1]["job_id"], "failed")
        self.assertEqual((job["error"], job["summary"]), ("RuntimeError", None))
        self.assertNotIn("s3cret", json.dumps(job))
        self.assertEqual(self.call("GET", "/health")[0], 200)                 # still alive
        self.assertEqual(self.call("POST", "/ingest/refresh")[0], 202)        # and accepts a new run

    def test_auth_required_and_disabled_without_a_token(self):
        self.start(Gate())
        self.assertEqual(self.call("POST", "/ingest/refresh", token=None)[0], 401)
        self.assertEqual(self.call("POST", "/ingest/refresh", token="wrong-token-wrong-token")[0], 401)
        self.assertEqual(self.call("GET", "/ingest/status/abc", token=None)[0], 401)
        for value in ("", "short"):
            with mock.patch.dict(os.environ, {"INGEST_TOKEN": value}):
                code, body = self.call("POST", "/ingest/refresh")
                self.assertEqual(code, 503)
                self.assertIn("disabled", body["error"])
        self.assertEqual(self.registry.jobs, {})  # nothing ever started
        code, health = self.call("GET", "/health", token=None)
        self.assertEqual((code, health), (200, {"ok": True, "ingest_endpoint": "enabled"}))
        self.assertNotIn(TOKEN, json.dumps(health))

    def test_bad_bodies_are_400_and_start_nothing(self):
        self.start(Gate())
        for body in ({"jobs": ["everything"]}, {"jobs": []}, {"jobs": "incidents"}, {"dry_run": "yes"},
                     {"surprise": 1}, [1, 2], b"{not json"):
            self.assertEqual(self.call("POST", "/ingest/refresh", body)[0], 400, body)
        self.assertEqual(self.registry.jobs, {})

    def test_unknown_job_id_and_paths(self):
        self.start(Gate())
        self.assertEqual(self.call("GET", "/ingest/status/nope"), (404, {"error": "unknown job id"}))
        self.assertEqual(self.call("GET", "/ingest/refresh")[0], 404)
        self.assertEqual(self.call("POST", "/ingest/status/x")[0], 404)


if __name__ == "__main__":
    unittest.main()
