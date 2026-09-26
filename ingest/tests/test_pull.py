import unittest
from datetime import datetime, timezone

from datasf import DATASETS
from pull.check import PASS, WARN, check_datasf, chp_point, chp_time, coords
from pull.feeds import parse_chp

CHP_XML = '''<?xml version="1.0" ?>
<State><Center ID = "GGHB">
<Dispatch ID = "GGCC">
		<Log ID = "260925GG0001">
			<LogTime>"Sep 25 2026  5:59PM"</LogTime>
			<LogType>"1183-Trfc Collision-Unkn Inj"</LogType>
			<Location>"I280 N / Bunker Hill Dr Ofr"</Location>
			<Area>"San Francisco FSP"</Area>
			<LATLON>"37775000:122419000"</LATLON>
			<LogDetails><details>
			<DetailTime>"Sep 25 2026  6:01PM"</DetailTime>
			<IncidentDetail>"[1] 2 VEHS BLKG #2 LN"</IncidentDetail></details>
			<units><UnitTime>"Sep 25 2026  6:02PM"</UnitTime><UnitDetail>"Enroute"</UnitDetail></units></LogDetails>
		</Log>
		<Log ID = "260925GG0002">
			<LogTime>"Sep 25 2026  6:04PM"</LogTime>
			<LogType>"1125-Traffic Hazard"</LogType>
'''  # cut off mid-entry, like the live feed


class ChpParseTests(unittest.TestCase):
    def test_truncated_feed_keeps_complete_entries(self):
        records, complete = parse_chp(CHP_XML)
        self.assertFalse(complete)
        self.assertEqual(len(records), 1)
        r = records[0]
        self.assertEqual((r["center"], r["dispatch"], r["log_id"]), ("GGHB", "GGCC", "260925GG0001"))
        self.assertEqual(r["Location"], "I280 N / Bunker Hill Dr Ofr")
        self.assertEqual(r["details"], [{"time": "Sep 25 2026  6:01PM", "text": "[1] 2 VEHS BLKG #2 LN"}])
        self.assertNotIn("UnitDetail", r)  # unit rows don't leak into top-level fields

    def test_chp_time_and_point(self):
        r = parse_chp(CHP_XML)[0][0]
        self.assertEqual(chp_time(r), datetime(2026, 9, 26, 0, 59, tzinfo=timezone.utc))
        self.assertEqual(chp_point(r), [(-122.419, 37.775)])
        self.assertEqual(chp_point({"LATLON": "0:0"}), [])


class CoordsTests(unittest.TestCase):
    def test_geojson_and_location_dicts(self):
        self.assertEqual(coords({"type": "Point", "coordinates": [-122.4, 37.7]}), [(-122.4, 37.7)])
        self.assertEqual(len(coords({"type": "MultiLineString", "coordinates": [[[-122.4, 37.7], [-122.41, 37.71]]]})), 2)
        self.assertEqual(coords({"latitude": "37.7", "longitude": "-122.4", "human_address": "{}"}), [(-122.4, 37.7)])
        self.assertEqual(coords(None), [])
        self.assertEqual(coords({"latitude": "", "longitude": ""}), [])


class WhereTests(unittest.TestCase):
    def test_where_fills_now_and_horizon_in_dataset_zone(self):
        now = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
        self.assertEqual(DATASETS["street_closures"].where_at(now), "end_utc >= '2026-09-26T12:00:00'")
        w = DATASETS["street_use_permits"].where_at(now)
        self.assertIn("permit_end_date >= '2026-09-26T05:00:00'", w)  # SF local
        self.assertIn("permit_start_date <= '2026-10-26T05:00:00'", w)
        self.assertIsNone(DATASETS["speed_limits"].where_at(now))


class DataSFCheckTests(unittest.TestCase):
    def test_flags_duplicates_missing_geometry_and_unjoinable_cnn(self):
        loc = {"latitude": "37.77", "longitude": "-122.42"}
        sign = {"signid": "1", "cnn": "100", "sideofstreet": "N", "location_2": loc,
                "datetimeentered": "2026-09-25T10:00:00.000", "startdate": "09/25/2026", "enddate": "09/27/2026"}
        rows = [
            sign,
            dict(sign),  # same sign, same segment and side -> duplicate
            {**sign, "cnn": "200", "sideofstreet": "S"},  # same sign id on another segment is fine
            {"signid": "2", "cnn": "999", "sideofstreet": "S", "datetimeentered": "2026-09-25T11:00:00.000",
             "startdate": "bad", "enddate": "09/27/2026"},
        ]
        ctx = {"now": datetime(2026, 9, 26, 12, tzinfo=timezone.utc), "street_cnns": {"100"}, "node_cnns": {"200"}}
        found = {f.check: f for f in check_datasf("parking_signs", rows, ctx)}
        self.assertEqual(found["unique ids"].level, WARN)
        self.assertIn("0 missing, 1 duplicates", found["unique ids"].detail)
        self.assertEqual(found["geometry"].detail, "75.0% of rows have coordinates")
        self.assertEqual(found["joins streets"].level, WARN)
        self.assertIn("(1 segments, 1 intersections)", found["joins streets"].detail)
        self.assertEqual(found["timestamps"].level, PASS)
        self.assertIn("1 unparseable", found["sign dates"].detail)


if __name__ == "__main__":
    unittest.main()
