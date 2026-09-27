"""Deployed coordinator: replay input mode + hardened HTTP service (python -m unittest tests.test_coordination_deploy).
Tiny synthetic network; the forecast service is replaced by an in-process fake."""
from __future__ import annotations

import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pandas as pd

from coordination.config import Config
from coordination.replay import ReplayRuntime, ReplaySource, read_bundle
from coordination.service import make_handler
from tests.test_coordination import closures_df, forecast_df, grid, make_net, mid

B = 600
T_FIRST = pd.Timestamp("2026-09-27T18:00:00Z")          # first recorded bucket
N_BUCKETS = 9                                            # issue times 19:00 .. 19:30


def write_run(d: Path, net) -> tuple[Path, Path]:
    rows = [{"time": T_FIRST + pd.Timedelta(seconds=B * k), "road_segment_id": s, "speed_mph": 20.0 + k,
             "observed": True, "closed": False} for k in range(N_BUCKETS) for s in net.ids]
    run, ctx = d / "run.parquet", d / "run.context.json"
    pd.DataFrame(rows).to_parquet(run, index=False)
    ctx.write_text(json.dumps({"cases": [], "network_version": net.version,
                               "provenance": {"source": "sumo_synthetic", "run_id": "toy_run"}}))
    return run, ctx


class FakeForecast:
    """Stands in for `python -m forecast serve`: a contract-shaped forecast issued at the context's issue time."""

    def __init__(self, net):
        self.net, self.calls, self.fail = net, [], False

    def bundle(self, hist, ctx):
        if self.fail:
            raise RuntimeError("forecast service down")
        self.calls.append((hist, ctx))
        t = pd.Timestamp(ctx["issued_at"])
        return forecast_df(self.net, issued=t), closures_df([]), {"seconds": 0.1, "checkpoint_sha256": "abc"}


class Wall:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class TestReplaySource(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)   # sqlite stays open on Windows
        nodes, roads = grid()
        self.net = make_net(nodes, roads)
        self.src = ReplaySource(*write_run(Path(self.tmp.name), self.net))

    def tearDown(self):
        self.tmp.cleanup()

    def test_issue_range_and_completed_history_only(self):
        self.assertEqual(self.src.first_issue, (T_FIRST + pd.Timedelta(minutes=60)).timestamp())
        self.assertEqual(self.src.last_issue, (T_FIRST + pd.Timedelta(minutes=10 * N_BUCKETS)).timestamp())
        issue = self.src.first_issue + B
        hist, ctx = self.src.snapshot(issue)
        t = hist.time.astype("int64") // 10**9
        self.assertEqual(hist.time.nunique(), 6)
        self.assertTrue((t < issue).all() and (t >= issue - 6 * B).all())
        self.assertEqual(ctx["provenance"]["source"], "sumo_synthetic_replay")
        self.assertTrue(ctx["provenance"]["replay"])

    def test_refuses_off_grid_or_out_of_range(self):
        for bad in (self.src.first_issue - B, self.src.last_issue + B, self.src.first_issue + 60):
            with self.assertRaises(ValueError):
                self.src.snapshot(bad)


class TestReplayRuntime(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)   # sqlite stays open on Windows
        d = Path(self.tmp.name)
        self.nodes, roads = grid()
        self.net = make_net(self.nodes, roads)
        self.src = ReplaySource(*write_run(d, self.net))
        self.cfg = Config()
        self.cfg.replay.state_dir = str(d / "state")
        self.fake = FakeForecast(self.net)
        self.wall = Wall(1_000_000.0)

    def tearDown(self):
        self.tmp.cleanup()

    def runtime(self):
        return ReplayRuntime(self.cfg, self.net, self.src, self.fake, "heuristic", wall=self.wall)

    def recommend(self, rt, rid="r1"):
        from coordination.schemas import RouteRequest
        return rt.coord.recommend(RouteRequest(rid, mid(self.nodes, "n00", "n10"), mid(self.nodes, "n12", "n22"),
                                               rt.coord.clock()))

    def test_refresh_publishes_each_bucket_on_the_replay_clock(self):
        rt = self.runtime()
        self.assertEqual(rt.coord.clock(), self.src.first_issue)
        rt.step()
        self.assertEqual(rt.coord.store.current.issued_at, self.src.first_issue)
        self.assertEqual(self.recommend(rt)["outcome"], "recommendation")
        rt.step()
        self.assertEqual(len(self.fake.calls), 1)                          # same bucket: no second forecast
        self.wall.t += B
        rt.step()
        self.assertEqual(rt.coord.store.current.issued_at, self.src.first_issue + B)
        self.assertEqual(rt.info()["input_mode"], "replay")

    def test_failed_refresh_keeps_last_good_until_stale(self):
        rt = self.runtime()
        rt.step()
        v = rt.coord.store.current.version
        self.fake.fail = True
        self.wall.t += B
        self.assertEqual(rt.step(), self.cfg.replay.retry_s)
        self.assertEqual((rt.coord.store.current.version, rt.refresh_failures), (v, 1))
        self.assertEqual(rt.coord.store.status(rt.coord.clock())[0], "ok")
        self.wall.t += 2 * B
        self.assertEqual(rt.coord.store.status(rt.coord.clock())[0], "stale")

    def test_restart_resumes_session_and_ledger(self):
        rt = self.runtime()
        rt.step()
        r = self.recommend(rt)
        rt.coord.accept(r["assignment"]["assignment_id"], r["assignment"]["version"])
        sid = rt.session["session_id"]
        self.wall.t += 30
        rt2 = self.runtime()
        self.assertEqual((rt2.session["session_id"], rt2.session["resumed"]), (sid, 1))
        self.assertEqual(rt2.coord.recovered, 1)
        self.assertAlmostEqual(rt2.coord.clock(), self.src.first_issue + 30)

    def test_rollover_starts_a_new_session_with_an_empty_ledger(self):
        rt = self.runtime()
        rt.step()
        r = self.recommend(rt)
        rt.coord.accept(r["assignment"]["assignment_id"], r["assignment"]["version"])
        sid = rt.session["session_id"]
        self.wall.t += self.src.last_issue + B - self.src.first_issue
        rt.step()
        self.assertNotEqual(rt.session["session_id"], sid)
        self.assertEqual(rt.coord.clock(), self.src.first_issue)
        self.assertEqual(len(rt.coord.ledger.live()), 0)
        self.assertEqual(rt.coord.store.current.issued_at, self.src.first_issue)


class TestBundle(unittest.TestCase):
    def test_unexpected_members_refused(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("../forecast.parquet", b"x")
        with self.assertRaises(ValueError):
            read_bundle(buf.getvalue())

    def test_round_trip_with_forecast_service_writer(self):
        try:
            from forecast.serve import bundle_bytes
        except ImportError:
            self.skipTest("torch not installed")
        nodes, roads = grid()
        net = make_net(nodes, roads)
        df, cl = forecast_df(net), closures_df([(net.ids[0], 0, 600, "full")])
        f, c, m = read_bundle(bundle_bytes(df, cl, {"issued_at": "x"}))
        self.assertEqual((len(f), len(c), m["issued_at"]), (len(df), 1, "x"))


class TestService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)   # sqlite stays open on Windows
        d = Path(cls.tmp.name)
        cls.nodes, roads = grid()
        net = make_net(cls.nodes, roads)
        cfg = Config()
        cfg.replay.state_dir = str(d / "state")
        cfg.service.max_body_bytes = 2000
        cls.rt = ReplayRuntime(cfg, net, ReplaySource(*write_run(d, net)), FakeForecast(net), "heuristic",
                               wall=Wall(1_000_000.0))
        cls.rt.step()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(lambda: cls.rt.coord, None, "tok", cls.rt))
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def call(self, path, body=None, token="tok", raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.url + path, data=data, method="POST" if data is not None else "GET")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def req(self, rid, **kw):
        return {"request_id": rid, "origin": list(mid(self.nodes, "n00", "n10")),
                "destination": list(mid(self.nodes, "n12", "n22")), **kw}

    def test_health_is_public_and_labeled(self):
        code, h = self.call("/v1/health", token=None)
        self.assertEqual((code, h["input_mode"], h["forecast_status"]), (200, "replay", "ok"))

    def test_token_required(self):
        self.assertEqual(self.call("/v1/recommendations", self.req("a"), token=None)[0], 401)
        self.assertEqual(self.call("/v1/recommendations", self.req("a"), token="wrong")[0], 401)
        self.assertEqual(self.call("/v1/assignments/abc", token=None)[0], 401)

    def test_selector_allowlist_and_requested_label(self):
        self.assertEqual(self.call("/v1/recommendations", self.req("b", selector="rl"))[0], 400)
        code, r = self.call("/v1/recommendations", self.req("c", selector="batch"))
        self.assertEqual(code, 200)
        self.assertEqual((r["selector"]["name"], r["selector"]["requested"]), ("batch", "batch"))

    def test_body_limit_and_refresh_disabled(self):
        self.assertEqual(self.call("/v1/recommendations", raw=b"x" * 5000)[0], 413)
        self.assertEqual(self.call("/v1/forecast/refresh", {"path": "../x"})[0], 409)


if __name__ == "__main__":
    unittest.main()
