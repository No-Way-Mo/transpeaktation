"""Live congestion map: Tiger/Mongo inputs -> forecast rows -> routing (python -m unittest tests.test_live_routing).
No databases: pure transformations plus fakes for the forecaster and the map store."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from coordination.config import Config
from coordination.live import LiveRuntime, to_contract
from coordination.schemas import RouteRequest
from tests.test_coordination import closures_df, forecast_df, grid, make_net, mid

try:
    import torch  # noqa: F401  (forecast.live imports the predictor)
    from forecast import live as flive
    HAVE_TORCH = True
except ImportError:
    HAVE_TORCH = False

B = 600
ISSUE = pd.Timestamp("2026-09-27T02:40:00Z").timestamp()


def ts(x):
    return pd.Timestamp(x, unit="s", tz="UTC")


@unittest.skipUnless(HAVE_TORCH, "torch not installed")
class TestLiveInputs(unittest.TestCase):
    def test_issue_is_newest_complete_bucket(self):
        counts = pd.DataFrame({"time": [ts(ISSUE - B * k) for k in (4, 3, 2, 1)], "n": [8700, 8710, 8690, 300]})
        # 02:30 bucket is thin (still being written) -> issue at its start; nothing later than floor(now)
        self.assertEqual(flive.choose_issue(counts, ISSUE + 60), ISSUE - B)
        counts.loc[3, "n"] = 8700
        self.assertEqual(flive.choose_issue(counts, ISSUE + 60), ISSUE)
        self.assertEqual(flive.choose_issue(counts, ISSUE - 60), ISSUE - B)    # 02:30 bucket not over yet
        self.assertIsNone(flive.choose_issue(pd.DataFrame(columns=["time", "n"]), ISSUE))

    def test_fusion_priority_excludes_muni_and_keeps_missing_missing(self):
        starts = ISSUE - B * np.arange(6, 0, -1).astype(float)
        ids, ff = np.array(["a", "b", "c"]), np.array([30.0, 20.0, 25.0])
        t = pd.DataFrame([
            (ts(starts[-1]), "a", "mapbox_tiles", 0.65), (ts(starts[-1]), "a", "tomtom", 0.2),
            (ts(starts[-1]), "a", "tomtom", 0.4),                                   # same source averaged first
            (ts(starts[-1]), "b", "muni", 0.9),                                     # never used
            (ts(starts[-1]), "c", "mapbox_tiles", 0.85), (ts(starts[-1]), "zzz", "tomtom", 0.1),
            (ts(starts[-1] + 300), "a", "tomtom", 0.9)],                            # off the bucket grid
            columns=["time", "road_segment_id", "source", "congestion_ratio"])
        h = flive.fuse_history(t, ids, ff, starts)
        last = h[h.time == h.time.max()].set_index("road_segment_id")
        self.assertAlmostEqual(last.speed_mph["a"], 30.0 * (1 - 0.3))
        self.assertFalse(last.observed["b"])
        self.assertAlmostEqual(last.speed_mph["c"], 25.0 * (1 - 0.85))
        self.assertEqual(len(h), 6 * 3)
        self.assertEqual(int(h.observed.sum()), 2)

    def test_cases_restrictions_and_event_match(self):
        lo, hi = ISSUE - 6 * B, ISSUE + 6 * B
        dt = lambda x: datetime.fromtimestamp(x, timezone.utc)
        inc = [
            {"source": "street_closures", "source_id": "1", "category": "street_closure", "road_segment_ids": ["a"],
             "start_time": dt(ISSUE - 86400), "end_time": dt(ISSUE + 86400), "details": {},
             "location": {"type": "Point", "coordinates": [-122.41, 37.77]}},
            {"source": "street_closures", "source_id": "2", "category": "street_closure", "road_segment_ids": ["b"],
             "start_time": dt(ISSUE + 1200), "end_time": dt(ISSUE + 7200), "details": {"is_special_event": True},
             "location": {"type": "LineString", "coordinates": [[-122.40, 37.78], [-122.401, 37.78]]}},
            {"source": "caltrans_lane_closures", "source_id": "3", "category": "lane_closure",
             "road_segment_ids": ["c"], "start_time": dt(ISSUE - 60), "end_time": None,
             "details": {"lanes_closed": "1", "type_of_closure": "Lane"}, "location": None},
            {"source": "street_closures", "source_id": "4", "road_segment_ids": ["d"],     # ended before the window
             "start_time": dt(lo - 7200), "end_time": dt(lo - 3600), "details": {}, "location": None}]
        ev = [{"title": "Show", "venue_id": "v", "location": {"type": "Point", "coordinates": [-122.4005, 37.7802]},
               "start_time": dt(ISSUE + 3600), "end_time": dt(ISSUE + 9000)},
              {"title": "Far", "location": {"type": "Point", "coordinates": [-122.30, 37.70]},
               "start_time": dt(ISSUE), "end_time": dt(ISSUE + 9000)}]
        cases = {c["case_num"]: c for c in flive.build_cases(inc, ev, ISSUE, lo, hi)}
        self.assertEqual(set(cases), {"street_closures:1", "street_closures:2", "caltrans_lane_closures:3"})
        self.assertEqual(cases["street_closures:2"]["kind"], "public_event")
        self.assertEqual(cases["street_closures:2"]["event_key"], "Show")
        self.assertIsNone(cases["street_closures:2"]["declared_attendance"])
        self.assertEqual(cases["caltrans_lane_closures:3"]["restrictions"][0]["restriction"], "lane")
        self.assertEqual(pd.Timestamp(cases["caltrans_lane_closures:3"]["restrictions"][0]["end"]).timestamp(), hi)
        keep = flive.event_case_nums(list(cases.values()), lo, hi)
        self.assertNotIn("street_closures:1", keep)                  # steady for days: closure table only
        self.assertIn("street_closures:2", keep)
        self.assertIn("caltrans_lane_closures:3", keep)


class FakeForecaster:
    def __init__(self):
        self.issue, self.calls, self.fail = ISSUE, 0, False

    def live(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("forecaster down")
        return {"run_id": f"m|{self.issue}", "issued_at": ts(self.issue).isoformat(), "reused": False}


class FakeReader:
    """Round-trips the contract rows through the prediction_metrics column shape, like the real Tiger reader."""

    def __init__(self, net):
        self.net = net

    def run(self, rid):
        issue = float(rid.split("|")[1])
        return {"_id": rid, "issued_at": ts(issue), "model_version": "test-model", "horizons": 6,
                "dataset_id": "test", "training_source": "test", "synthetic_training": True,
                "closures": [{"road_segment_id": self.net.ids[0], "case_num": "c", "kind": "permit",
                              "restriction": "full", "closure_begin": ts(issue), "closure_end": ts(issue + 300)}]}

    def read(self, run):
        df = forecast_df(self.net, issued=run["issued_at"])
        rows = [(r.road_segment_id, r.issued_at, r.valid_from, r.valid_to, r.horizon_min, r.predicted_travel_time_sec,
                 r.predicted_speed_mph, r.predicted_congestion_ratio, r.availability, r.restriction_reason,
                 r.prediction_source, r.represented_by, r.model_version, r.network_version, "live_tiger_mongo")
                for r in df.itertuples()]
        return to_contract(rows, run)


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class TestLiveRuntime(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)   # sqlite stays open on Windows
        self.nodes, roads = grid()
        self.net = make_net(self.nodes, roads)
        cfg = Config()
        cfg.live.state_dir = self.tmp.name
        cfg.forecast.max_issue_age_min = 45
        self.clock = Clock(ISSUE + 15 * 60)
        self.fc = FakeForecaster()
        self.rt = LiveRuntime(cfg, self.net, self.fc, FakeReader(self.net), "heuristic", clock=self.clock)

    def tearDown(self):
        self.tmp.cleanup()

    def route(self, rid):
        self.rt.before_request()
        return self.rt.coord.recommend(RouteRequest(rid, mid(self.nodes, "n00", "n10"), mid(self.nodes, "n12", "n22"),
                                                    self.clock()))

    def test_first_request_waits_for_a_map_then_routes(self):
        r = self.route("r1")
        self.assertEqual(r["outcome"], "recommendation")
        self.assertEqual(self.rt.coord.store.current.issued_at, ISSUE)
        self.assertEqual(len(self.rt.coord.store.current.closures), 1)       # exact closures came with the map
        self.assertEqual(self.fc.calls, 1)

    def test_no_check_until_due_and_background_refresh_when_usable(self):
        self.route("r1")
        self.clock.t += 30
        self.route("r2")
        self.assertEqual(self.fc.calls, 1)                                   # checked < check_s ago
        self.clock.t += 60
        self.fc.issue = ISSUE + B
        self.route("r3")                                                     # usable map: refresh in background
        for _ in range(100):
            if self.rt.coord.store.current.issued_at == ISSUE + B:
                break
            import time
            time.sleep(0.05)
        self.assertEqual(self.rt.coord.store.current.issued_at, ISSUE + B)

    def test_failure_keeps_last_good_and_stale_map_is_refused(self):
        self.route("r1")
        self.fc.fail = True
        self.clock.t += 31 * 60                                              # map 46 min old: stale
        r = self.route("r2")
        self.assertEqual((r["outcome"], r["reason"]), ("unsupported", "forecast_stale"))
        self.assertEqual(self.rt.failures, 1)
        self.assertEqual(self.rt.coord.store.current.issued_at, ISSUE)


if __name__ == "__main__":
    unittest.main()
