import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from worker.db import DryRunSink
from worker.network import Network, read_graphml
from worker.state import State
from worker.traffic import TrafficJob, bucket_of, day_files, route_plan_id

from .worker_graph import A, B, C, D, EAST, NORTH, WEST, along, write_graph, write_jsonl

DAY = "2026-09-26"
NOW = datetime(2026, 9, 26, 10, 30, tzinfo=timezone.utc)  # buckets before 10:20 are closed (5 min lag)
T0 = datetime(2026, 9, 26, 10, 0, tzinfo=timezone.utc)


def ts(hh, mm, ss=0):
    return f"{DAY}T{hh:02d}:{mm:02d}:{ss:02d}+00:00"


class TrafficTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.graphml = write_graph(root)
        self.net = Network(read_graphml(self.graphml))
        self.dirs = {s: root / s for s in ("tomtom", "mapbox_route", "mapbox_tiles", "muni")}
        self.state_dir = root / "state"

    def tearDown(self):
        self.tmp.cleanup()

    def run_job(self, *sources, now=NOW):
        sink = DryRunSink(samples=100)
        state = State(self.state_dir)
        report = TrafficJob(self.net, state, sink, graph_sig="g1", now=now, dirs=self.dirs).run(sources)
        return sink, report

    def rows(self, sink, source=None):
        return [r for r in sink.samples.get("traffic_metrics", []) if source is None or r["source"] == source]

    # --- tomtom -------------------------------------------------------------------

    def write_tomtom(self, rows):
        write_jsonl(self.dirs["tomtom"] / "geometry.jsonl",
                    [{"key": "east", "coords": along(A, B, 4)}, {"key": "north", "coords": along(C, D, 2)}])
        write_jsonl(self.dirs["tomtom"] / f"{DAY}.jsonl", rows)

    def test_tomtom_speed_free_flow_ratio(self):
        self.write_tomtom([
            {"polled_at": ts(4, 0), "style": "relative", "ok": True, "lines": [["east", 0.5, "x", False]]},
            {"polled_at": ts(10, 1), "style": "absolute", "ok": True,
             "lines": [["east", 20, "x", False], ["north", 30, "x", True]]},
        ])
        sink, report = self.run_job("tomtom")
        east = next(r for r in self.rows(sink) if r["road_segment_id"] == EAST)
        self.assertEqual(east["time"], T0)
        self.assertAlmostEqual(east["speed_mph"], 20 * 0.621371, places=2)
        self.assertAlmostEqual(east["free_flow_speed_mph"], 40 * 0.621371, places=2)  # absolute / relative
        self.assertAlmostEqual(east["congestion_ratio"], 0.5, places=3)
        self.assertAlmostEqual(east["travel_time_sec"], 88 / (20 * 0.621371 * 0.44704), places=0)
        north = next(r for r in self.rows(sink) if r["road_segment_id"] == NORTH)
        self.assertEqual((north["speed_mph"], north["congestion_ratio"], north["travel_time_sec"]), (0.0, 1.0, None))
        self.assertNotIn(WEST, {r["road_segment_id"] for r in self.rows(sink)})  # line only runs east
        self.assertEqual(report["tomtom"]["traffic_rows"], 2)

    def test_open_bucket_waits_and_reruns_add_nothing(self):
        self.write_tomtom([
            {"polled_at": ts(10, 1), "style": "absolute", "ok": True, "lines": [["east", 20, "x", False]]},
            {"polled_at": ts(10, 21), "style": "absolute", "ok": True, "lines": [["east", 10, "x", False]]},
        ])
        sink, _ = self.run_job("tomtom")
        self.assertEqual([r["time"] for r in self.rows(sink)], [T0])  # 10:20 bucket still open
        sink, _ = self.run_job("tomtom")
        self.assertEqual(self.rows(sink), [])  # watermark moved: nothing rewritten
        sink, _ = self.run_job("tomtom", now=datetime(2026, 9, 26, 10, 40, tzinfo=timezone.utc))
        self.assertEqual([r["time"] for r in self.rows(sink)], [datetime(2026, 9, 26, 10, 20, tzinfo=timezone.utc)])

    def test_tomtom_free_flow_falls_back_without_relative(self):
        self.write_tomtom([{"polled_at": ts(10, 1), "style": "absolute", "ok": True, "lines": [["east", 20, "x", False]]}])
        sink, _ = self.run_job("tomtom")
        self.assertEqual(self.rows(sink)[0]["free_flow_speed_mph"], 25.0)  # OSM maxspeed

    # --- mapbox route -------------------------------------------------------------

    def mapbox_row(self, coords, speeds_mps, polled=ts(10, 2)):
        n = len(coords) - 1
        from worker.geo import haversine_m
        dist = [haversine_m(tuple(coords[i]), tuple(coords[i + 1])) for i in range(n)]
        return {"polled_at": polled, "corridor": "test", "direction": "ab", "ok": True,
                "duration_s": 60.0, "duration_typical_s": 50.0, "distance_m": sum(dist),
                "segments": {"distance_m": dist, "duration_s": [d / s for d, s in zip(dist, speeds_mps)]},
                "geometry": coords}

    def test_mapbox_route_speed_eta_and_plan(self):
        coords = along(A, B, 4)
        write_jsonl(self.dirs["mapbox_route"] / f"{DAY}.jsonl", [self.mapbox_row(coords, [10, 10, 5, 5])])
        sink, _ = self.run_job("mapbox_route")
        [row] = self.rows(sink)
        self.assertEqual((row["road_segment_id"], row["source"]), (EAST, "mapbox_route"))
        self.assertAlmostEqual(row["speed_mph"], (88 / (44 / 10 + 44 / 5)) * 2.236936, delta=0.3)  # metres / seconds
        [eta] = sink.samples["route_eta_metrics"]
        self.assertEqual((eta["duration_sec"], eta["typical_duration_sec"], eta["departure_time"]),
                         (60.0, 50.0, datetime(2026, 9, 26, 10, 2, tzinfo=timezone.utc)))
        [plan] = sink.samples["route_plans"]
        self.assertEqual((plan["_id"], plan["segment_ids"]), (route_plan_id("mapbox", coords), [EAST]))

    def test_mapbox_partial_edge_is_skipped(self):
        coords = along(A, (-122.3997, 37.78), 2)  # only ~26 of 88 m
        write_jsonl(self.dirs["mapbox_route"] / f"{DAY}.jsonl", [self.mapbox_row(coords, [10, 10])])
        sink, _ = self.run_job("mapbox_route")
        self.assertEqual(self.rows(sink), [])
        self.assertEqual(len(sink.samples["route_eta_metrics"]), 1)  # route ETA still recorded

    # --- mapbox tiles -------------------------------------------------------------

    def test_mapbox_tiles_ratio_only(self):
        write_jsonl(self.dirs["mapbox_tiles"] / "geometry.jsonl", [{"key": "w", "coords": along(B, A, 3)}])
        write_jsonl(self.dirs["mapbox_tiles"] / f"{DAY}.jsonl", [
            {"polled_at": ts(10, 5), "style": "congestion", "ok": True, "lines": [["w", "heavy", "street", False]]}])
        sink, _ = self.run_job("mapbox_tiles")
        [row] = self.rows(sink)
        self.assertEqual((row["road_segment_id"], row["speed_mph"], row["congestion_ratio"]), (WEST, None, 0.65))
        self.assertEqual(row["free_flow_speed_mph"], 25.0)

    # --- muni ---------------------------------------------------------------------

    def test_muni_speed_from_consecutive_fixes(self):
        mid = (-122.3995, 37.78)
        write_jsonl(self.dirs["muni"] / f"{DAY}.jsonl", [
            {"polled_at": ts(9, 58, 30), "vehicle": "v1", "line": "38", "lon": A[0] + 0.0001, "lat": A[1]},
            {"polled_at": ts(10, 0, 0), "vehicle": "v1", "line": "38", "lon": mid[0] + 0.0002, "lat": mid[1]},
            {"polled_at": ts(10, 1, 30), "vehicle": "v1", "line": "38", "lon": mid[0] + 0.00021, "lat": mid[1],
             "bearing": 90.0},  # stopped: bearing decides the direction
            {"polled_at": ts(10, 0, 0), "vehicle": "v2", "line": None, "lon": A[0], "lat": A[1]},  # out of service
            {"polled_at": ts(10, 1, 30), "vehicle": "v2", "line": None, "lon": mid[0], "lat": mid[1]},
        ])
        sink, report = self.run_job("muni")
        [row] = self.rows(sink)
        self.assertEqual((row["road_segment_id"], row["time"], row["source"]), (EAST, T0, "muni"))
        from worker.geo import haversine_m
        moving = haversine_m((A[0] + 0.0001, A[1]), (mid[0] + 0.0002, mid[1])) / 90
        stopped = haversine_m((mid[0] + 0.0002, mid[1]), (mid[0] + 0.00021, mid[1])) / 90
        self.assertAlmostEqual(row["speed_mph"], (moving + stopped) / 2 * 2.2369363, places=2)
        self.assertIsNone(row["travel_time_sec"])
        self.assertEqual(report["muni"]["readings"], 2)

    # --- misc ---------------------------------------------------------------------

    def test_day_files_skip_non_dates(self):
        d = self.dirs["tomtom"]
        write_jsonl(d / "geometry.jsonl", [{}])
        write_jsonl(d / "2026-09-25.jsonl", [{}])
        write_jsonl(d / f"{DAY}.jsonl", [{}])
        self.assertEqual([p.name for p in day_files(d, datetime(2026, 9, 26).date(), datetime(2026, 9, 26).date())],
                         [f"{DAY}.jsonl"])

    def test_bad_lines_are_counted_not_fatal(self):
        (self.dirs["mapbox_route"]).mkdir(parents=True)
        (self.dirs["mapbox_route"] / f"{DAY}.jsonl").write_text('not json\n{"ok": true, "polled_at": "nope"}\n')
        sink, report = self.run_job("mapbox_route")
        self.assertEqual((report["mapbox_route"]["bad_lines"], report["mapbox_route"]["bad_rows"]), (1, 1))

    def test_bucket_of(self):
        self.assertEqual(bucket_of(datetime(2026, 9, 26, 10, 19, 59, tzinfo=timezone.utc)),
                         datetime(2026, 9, 26, 10, 10, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
