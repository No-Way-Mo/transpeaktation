import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from pull import poll
from pull.check import PASS, WARN, check_polls, inside
from pull.corridors import CORRIDORS, requests_per_poll
from pull.feeds import SF_BBOX

# Shape per https://docs.mapbox.com/api/navigation/directions/ (driving-traffic, geojson, annotations)
MAPBOX_OK = {
    "code": "Ok",
    "routes": [{
        "duration": 180.0, "duration_typical": 150.0, "distance": 900.0,
        "geometry": {"type": "LineString", "coordinates": [[-122.40, 37.78], [-122.401, 37.781], [-122.402, 37.782]]},
        "legs": [{"annotation": {
            "distance": [450.0, 450.0], "duration": [90.0, 90.0], "speed": [5.0, 5.0],
            "congestion": ["moderate", "heavy"], "congestion_numeric": [45, 80],
            "maxspeed": [{"speed": 25, "unit": "mph"}, {"unknown": True}],
        }}],
    }],
}


class ParseTests(unittest.TestCase):
    def test_parse_route_keeps_segment_arrays(self):
        r = poll.parse_route(MAPBOX_OK)
        self.assertEqual((r["duration_s"], r["duration_typical_s"], r["distance_m"]), (180.0, 150.0, 900.0))
        self.assertEqual(r["segments"]["speed_mps"], [5.0, 5.0])
        self.assertEqual(r["segments"]["congestion"], ["moderate", "heavy"])
        self.assertEqual(len(r["geometry"]), 3)

    def test_no_route_raises(self):
        with self.assertRaises(ValueError):
            poll.parse_route({"code": "NoRoute", "message": "No route found", "routes": []})


class BudgetTests(unittest.TestCase):
    def test_default_schedule_fits_free_tier(self):
        self.assertEqual(requests_per_poll(), 17)
        self.assertLess(poll.monthly_requests(600, requests_per_poll()), poll.BUDGET)
        self.assertGreater(poll.monthly_requests(300, requests_per_poll()), poll.BUDGET)

    def test_corridor_endpoints_are_in_sf(self):
        for c in CORRIDORS:
            self.assertTrue(inside(c.a, SF_BBOX) and inside(c.b, SF_BBOX), c.key)

    def test_main_refuses_over_budget_schedule(self):
        with mock.patch.dict("os.environ", {"MAPBOX_TOKEN": "t"}), mock.patch.object(poll, "load_dotenv"), \
                mock.patch.object(poll, "poll_once") as p:
            self.assertEqual(poll.main(["--every", "60"]), 2)
        p.assert_not_called()


class PollOnceTests(unittest.TestCase):
    def test_appends_one_row_per_leg_and_records_failures(self):
        calls = iter([MAPBOX_OK, {"code": "NoRoute", "routes": []}] + [MAPBOX_OK] * 100)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(poll, "TS_DIR", Path(tmp)), \
                mock.patch.object(poll, "fetch_route", side_effect=lambda a, b, t: next(calls)):
            ok, total = poll.poll_once("t")
            rows = [json.loads(line) for f in Path(tmp).glob("*.jsonl") for line in f.read_text().splitlines()]
        self.assertEqual((ok, total), (16, 17))
        self.assertEqual(len(rows), 17)
        self.assertFalse(rows[1]["ok"])
        self.assertIn("NoRoute", rows[1]["error"])
        self.assertEqual({r["corridor"] for r in rows}, {c.key for c in CORRIDORS})


class PollCheckTests(unittest.TestCase):
    def test_flags_gaps_and_reports_typical_ratio(self):
        now = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
        parsed = poll.parse_route(MAPBOX_OK)
        times = [now - timedelta(minutes=m) for m in (120, 110, 100, 90, 10, 0)]  # 80 min hole
        rows = [{"polled_at": t.isoformat(), "corridor": "howard", "direction": "ab", "ok": True, **parsed}
                for t in times]
        found = {f.check: f for f in check_polls(rows, now)}
        self.assertEqual(found["success"].level, PASS)
        self.assertEqual(found["coverage"].level, WARN)
        self.assertIn("1 gaps", found["coverage"].detail)
        self.assertEqual(found["segment arrays"].level, PASS)
        self.assertIn("1.20", found["vs typical"].detail)


if __name__ == "__main__":
    unittest.main()


class MuniTests(unittest.TestCase):
    def test_muni_rows_compacts_and_skips_bad_locations(self):
        activity = [
            {"RecordedAtTime": "2026-09-26T08:53:49Z", "MonitoredVehicleJourney": {
                "VehicleRef": "10", "LineRef": "14", "DirectionRef": "IB", "Bearing": "90.0",
                "Occupancy": "seatsAvailable", "VehicleLocation": {"Longitude": "-122.41", "Latitude": "37.79"}}},
            {"RecordedAtTime": "2026-09-26T08:53:49Z", "MonitoredVehicleJourney": {
                "VehicleRef": "11", "VehicleLocation": {"Longitude": "", "Latitude": ""}}},
        ]
        rows = poll.muni_rows(activity, datetime(2026, 9, 26, 8, 54, tzinfo=timezone.utc))
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["vehicle"], rows[0]["line"], rows[0]["lon"], rows[0]["bearing"]), ("10", "14", -122.41, 90.0))


class EventPollerTests(unittest.TestCase):
    def test_writes_only_new_or_updated_events(self):
        batches = iter([
            ([{"id": "a", "updated": "1", "headline": "x"}, {"id": "b", "updated": "1", "headline": "y"}], {}),
            # a: only `updated` bumped (511 does this constantly) -> skipped; b: content changed -> written
            ([{"id": "a", "updated": "2", "headline": "x"}, {"id": "b", "updated": "2", "headline": "y2"}], {}),
        ])
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(poll, "EVENTS_DIR", Path(tmp)), \
                mock.patch.object(poll.feeds, "sf511_traffic_events", side_effect=lambda: next(batches)):
            poller = poll.EventPoller()
            self.assertEqual(poller(), (2, 2))
            self.assertEqual(poller(), (1, 2))
            rows = [json.loads(line) for f in Path(tmp).glob("*.jsonl") for line in f.read_text().splitlines()]
        self.assertEqual([(r["id"], r["updated"]) for r in rows], [("a", "1"), ("b", "1"), ("b", "2")])


class Sf511BudgetTests(unittest.TestCase):
    def test_refuses_muni_schedule_over_hourly_limit(self):
        env = {"SF511_API_KEY": "k"}
        with mock.patch.dict("os.environ", env), mock.patch.object(poll, "load_dotenv"), \
                mock.patch.object(poll, "poll_muni") as p:
            self.assertEqual(poll.main(["--only", "muni", "--muni-every", "30"]), 2)
        p.assert_not_called()


class TileMathTests(unittest.TestCase):
    def test_sf_zoom13_tiles_and_corner_roundtrip(self):
        from pull.tiles import tile_point_to_lonlat, tiles_for_bbox
        tiles = tiles_for_bbox(z=13)
        self.assertEqual(len(tiles), 25)
        z, x, y = tiles[0]
        lon, lat = tile_point_to_lonlat(z, x, y, 0, 0, 4096)  # tile's north-west corner
        self.assertLessEqual(lon, SF_BBOX[0])
        self.assertGreaterEqual(lat, SF_BBOX[3])

    def test_line_key_is_stable_under_float_noise(self):
        from pull.tiles import line_key
        self.assertEqual(line_key([(-122.4, 37.78), (-122.401, 37.781)]),
                         line_key([(-122.4000001, 37.7800001), (-122.401, 37.781)]))
