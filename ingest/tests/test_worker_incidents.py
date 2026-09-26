"""Closures/incidents. Adapter, time, geometry, validation, dedupe and geocoding tests are ported
from ingestion-workers-v1; the rest cover the fixes and the job end to end."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from pull.feeds import parse_chp
from worker.db import DryRunSink
from worker.incidents import dedupe, geocode
from worker.incidents.adapters import NORMALIZERS
from worker.incidents.common import incident_category, location_tokens
from worker.incidents.geom import GeometryError, StreetIndex, normalize_geometry, valid_lonlat
from worker.incidents.job import IncidentJob, road_incident_doc, segment_ids_for
from worker.incidents.records import Record, RecordError, natural_key
from worker.incidents.timeutil import chp_ts, datasf_ts, epoch, iso, local_day
from worker.incidents.validate import validate
from worker.network import Network, read_graphml

from . import incident_fixtures as fx
from .worker_graph import A, B, C, D, EAST, NORTH, WEST, write_graph

UTC = timezone.utc
NOW = datetime(2026, 9, 26, 1, tzinfo=UTC)


def norm(source, row):
    return NORMALIZERS[source](row)


class TimeTests(unittest.TestCase):
    def test_datasf_local_vs_utc_columns(self):
        self.assertEqual(datasf_ts("received_datetime", "2026-09-25T17:10:00.000"), datetime(2026, 9, 26, 0, 10, tzinfo=UTC))
        self.assertEqual(datasf_ts("start_utc", "2026-09-26T10:00:00.000"), datetime(2026, 9, 26, 10, tzinfo=UTC))
        self.assertIsNone(datasf_ts("x", ""))
        with self.assertRaises(ValueError):
            datasf_ts("x", "not a time")

    def test_winter_offset_and_local_days(self):
        self.assertEqual(datasf_ts("d", "2026-01-15T12:00:00.000"), datetime(2026, 1, 15, 20, tzinfo=UTC))  # PST
        self.assertEqual(local_day("09/27/2026", end=True), datetime(2026, 9, 28, 7, tzinfo=UTC))

    def test_chp_and_epoch(self):
        self.assertEqual(chp_ts("Sep 25 2026  5:59PM"), datetime(2026, 9, 26, 0, 59, tzinfo=UTC))
        self.assertEqual(epoch(1790000000000), datetime.fromtimestamp(1790000000, UTC))  # ms
        self.assertIsNone(epoch("0"))
        self.assertEqual(iso(datetime(2026, 9, 26, tzinfo=UTC)), "2026-09-26T00:00:00Z")


class GeometryTests(unittest.TestCase):
    def test_coordinates_and_normalization(self):
        self.assertTrue(valid_lonlat(-122.4, 37.7))
        for bad in [(0, 0), (200, 37), ("x", 1), (float("nan"), 1)]:
            self.assertFalse(valid_lonlat(*bad), bad)
        g = normalize_geometry({"type": "LineString", "coordinates": [[-122.4, 37.7, 5], ["-122.41", "37.71"]]})
        self.assertEqual(g, {"type": "LineString", "coordinates": [[-122.4, 37.7], [-122.41, 37.71]]})
        self.assertEqual(normalize_geometry({"latitude": "37.7", "longitude": "-122.4"}),
                         {"type": "Point", "coordinates": [-122.4, 37.7]})
        for bad in [{"type": "Point", "coordinates": [0, 0]}, {"type": "LineString", "coordinates": [[-122, 37]]}, {"foo": 1}]:
            with self.assertRaises(GeometryError, msg=bad):
                normalize_geometry(bad)

    def test_street_index(self):
        idx = StreetIndex.from_rows(fx.STREETS)
        self.assertEqual((idx.classify("100"), idx.classify("901.0"), idx.classify("555")),
                         ("segment", "intersection", "unknown"))
        self.assertEqual(idx.geometry_for("901"), {"type": "Point", "coordinates": [-122.419, 37.77]})
        self.assertEqual(idx.nearest_segment((-122.4195, 37.77005))[0], "100")


class AdapterTests(unittest.TestCase):
    def test_keys(self):
        self.assertEqual(natural_key({"signid": "5", "cnn": "100"}, ("signid", "cnn")), "5|100")
        with self.assertRaises(RecordError):
            natural_key({"permit_number": "EX1"}, ("permit_number", "cnn"))
        self.assertEqual(norm("excavation_permits", fx.EXCAVATION[0]).id, "excavation_permits:EX1|100")

    def test_street_closure_is_a_closure(self):
        r = norm("street_closures", fx.STREET_CLOSURES[0])
        self.assertEqual(r.valid_from, datetime(2026, 9, 26, 10, tzinfo=UTC))
        self.assertTrue(r.attributes["is_special_event"] and r.attributes["is_closure"])
        self.assertEqual(validate(r), [])
        self.assertIn("valid_to before valid_from", validate(norm("street_closures", fx.STREET_CLOSURES[1])))

    def test_permits_are_not_closures(self):
        r = norm("excavation_permits", fx.EXCAVATION[0])
        self.assertFalse(r.attributes["is_closure"])
        self.assertIsNone(r.geometry)
        self.assertEqual(validate(r), [])  # a cnn is a location

    def test_caltrans_key_is_per_window(self):
        # Same closureID + logNumber, different weeks: both windows must survive.
        a, b = fx.caltrans_row(), fx.caltrans_row(start="1790604800", stop="1790634800")
        a["index"], b["index"] = "C1-0001-2026-09-25-22:00:00", "C1-0001-2026-10-02-22:00:00"
        ra, rb = norm("caltrans_lane_closures", a), norm("caltrans_lane_closures", b)
        self.assertNotEqual(ra.id, rb.id)
        self.assertEqual(ra.attributes["closure_id"], "C1")
        self.assertIsNone(norm("caltrans_lane_closures", fx.CALTRANS[1]))  # outside the Bay Area
        with self.assertRaises(RecordError):
            norm("caltrans_lane_closures", fx.CALTRANS[2])

    def test_caltrans_is_closure(self):
        full = fx.caltrans_row()
        full["closure"]["typeOfClosure"] = "Full"
        all_lanes = fx.caltrans_row()
        all_lanes["closure"].update(typeOfClosure="Lane", lanesClosed="All")
        lane = fx.caltrans_row()
        lane["closure"].update(typeOfClosure="Lane", lanesClosed="1, RShoulder")
        self.assertEqual([norm("caltrans_lane_closures", r).attributes["is_closure"] for r in (full, all_lanes, lane)],
                         [True, True, False])

    def test_police_keeps_traffic_calls_only(self):
        r = norm("police_dispatch", fx.POLICE[0])  # Traffic Collision
        self.assertEqual((r.observed_at, r.attributes["category"]), (datetime(2026, 9, 26, 0, 10, tzinfo=UTC), "collision"))
        self.assertIsNone(norm("police_dispatch", fx.POLICE[1]))  # Well Being Check: not traffic
        for call in ("TRAF VIOLATION CITE", "PASSING CALL", "SUSPICIOUS PERSON", "Traffic Stop"):
            self.assertIsNone(norm("police_dispatch", {"id": "x", "call_type_final_desc": call}), call)
        hazard = norm("police_dispatch", fx.POLICE[2])  # unlocated, not sensitive -> geocode query
        self.assertEqual(hazard.location_status, "unlocated")
        self.assertIn("MISSION ST", hazard.geocode_query)

    def test_withheld_traffic_call_is_never_geocoded(self):
        r = norm("police_dispatch", {"id": "s", "received_datetime": "2026-09-25T17:20:00.000",
                                     "call_type_final_desc": "Traffic Hazard", "sensitive_call": True})
        self.assertEqual((r.location_status, r.geocode_query), ("withheld", None))
        self.assertEqual(validate(r), [])

    def test_chp(self):
        rows = parse_chp(fx.CHP_XML)[0]
        located = norm("chp_incidents", rows[0])
        self.assertEqual(located.geometry, {"type": "Point", "coordinates": [-122.419, 37.775]})
        self.assertEqual(located.attributes["details"][0]["time"], "2026-09-26T00:02:00Z")
        zero = norm("chp_incidents", rows[1])  # 0:0 from Golden Gate dispatch: kept, unlocated
        self.assertEqual((zero.geometry, zero.location_status), (None, "unlocated"))
        self.assertIsNone(norm("chp_incidents", rows[2]))  # Los Angeles: filtered

    def test_categories_and_tokens(self):
        self.assertEqual(incident_category("1183-Trfc Collision-Unkn Inj"), "collision")
        self.assertEqual(incident_category("Traffic Stop"), "other")
        self.assertEqual(location_tokens("I280 N / Bunker Hill Dr Ofr"), frozenset({"280", "BUNKER", "HILL", "OFR"}))

    def test_parking_signs_are_not_incidents(self):
        self.assertNotIn("parking_signs", NORMALIZERS)

    def test_validation_rejects_naive_times(self):
        errs = validate(Record(kind="bogus", source="s", source_id="1", observed_at=datetime(2026, 1, 1)))
        self.assertTrue(any("unknown kind" in e for e in errs) and any("not UTC-aware" in e for e in errs))


def _inc(source, sid, lon, lat, minutes=0, cat="collision"):
    return Record(kind="incident", source=source, source_id=sid, observed_at=NOW + timedelta(minutes=minutes),
                  geometry={"type": "Point", "coordinates": [lon, lat]}, attributes={"category": cat})


class DedupeTests(unittest.TestCase):
    def test_cross_source_merges_only_when_everything_agrees(self):
        cases = {
            "match": (_inc("police_dispatch", "p", -122.4191, 37.7751, 10), 1),
            "too far": (_inc("police_dispatch", "p", -122.4300, 37.7750, 10), 0),
            "too late": (_inc("police_dispatch", "p", -122.4191, 37.7751, 45), 0),
            "other category": (_inc("police_dispatch", "p", -122.4191, 37.7751, 10, "hazard"), 0),
            "same source": (_inc("chp_incidents", "c2", -122.4191, 37.7751, 10), 0),
        }
        for label, (other, merged) in cases.items():
            a = _inc("chp_incidents", "c", -122.4190, 37.7750)
            kept, n = dedupe.cross_source([other, a])
            self.assertEqual(n, merged, label)
            if merged:
                self.assertEqual(kept, [a])  # CHP outranks police regardless of input order
                self.assertEqual(a.also_reported_by[0]["source"], "police_dispatch")

    def test_closures_need_overlap_and_matching_street_text(self):
        def closure(source, text, start_h, end_h):
            return Record(kind="closure", source=source, source_id="x",
                          geometry={"type": "Point", "coordinates": [-122.40, 37.73]},
                          valid_from=NOW + timedelta(hours=start_h), valid_to=NOW + timedelta(hours=end_h),
                          attributes={"location_text": text})
        state = closure("caltrans_lane_closures", "Alemany Blvd", 1, 3)
        self.assertEqual(dedupe.cross_source([closure("street_closures", "ALEMANY BLVD", 0, 4), state])[1], 1)
        self.assertEqual(dedupe.cross_source([closure("street_closures", "MISSION ST", 0, 4), state])[1], 0)
        self.assertEqual(dedupe.cross_source([closure("street_use_permits", "Alemany Blvd", 1, 3), state])[1], 0)


class GeocodeTests(unittest.TestCase):
    def test_opt_in(self):
        for env, name in (({}, None), ({"MAPBOX_TOKEN": "t"}, None), ({"GEOCODER": "mapbox"}, None),
                          ({"GEOCODER": "mapbox", "MAPBOX_TOKEN": "t"}, "mapbox")):
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(getattr(geocode.from_env()[0], "name", None), name, env)

    def test_cache_bbox_and_failures(self):
        class Provider:
            name, n = "p", 0

            def geocode(self, q):
                self.n += 1
                if q == "boom":
                    raise geocode.FetchError("503")
                return (-118.2, 34.0) if q == "LA" else (-122.41, 37.78)

        with tempfile.TemporaryDirectory() as tmp:
            prov, path = Provider(), Path(tmp) / "geo.json"
            g = geocode.CachedGeocoder(prov, path)
            self.assertEqual(g.geocode("Market St"), (-122.41, 37.78))
            self.assertEqual(g.geocode("market  st"), (-122.41, 37.78))  # cached, normalized key
            self.assertIsNone(g.geocode("LA"))  # outside the Bay Area
            self.assertIsNone(g.geocode("boom"))
            self.assertIsNone(g.geocode("boom"))  # failures aren't cached
            self.assertEqual((prov.n, g.failures), (4, 2))


class SegmentLinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.net = Network(read_graphml(write_graph(Path(self.tmp.name))))

    def tearDown(self):
        self.tmp.cleanup()

    def test_line_point_and_nothing(self):
        line = {"type": "LineString", "coordinates": [list(A), list(B)]}
        self.assertEqual(segment_ids_for(line, self.net), sorted([EAST, WEST]))  # both directions of the street
        self.assertEqual(segment_ids_for({"type": "Point", "coordinates": [C[0], 37.7805]}, self.net), [NORTH])
        self.assertEqual(segment_ids_for({"type": "Point", "coordinates": [-122.45, 37.75]}, self.net), [])
        self.assertEqual(segment_ids_for(None, self.net), [])


class JobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.raw = fx.write_raw_dir(self.root / "raw", fx.all_rows())

    def tearDown(self):
        self.tmp.cleanup()

    def run_job(self, **kw):
        sink = DryRunSink(samples=1000)
        report = IncidentJob(self.raw, sink, out_dir=self.root, now=NOW, **kw).run()
        return sink, report

    def test_end_to_end(self):
        sink, report = self.run_job()
        docs = {(d["source"], d["source_id"]): d for d in sink.samples["road_incidents"]}
        self.assertEqual(report["police_dispatch"]["filtered"], 2)  # Well Being Check + non-traffic
        self.assertIn(("street_closures", "10"), docs)
        self.assertTrue(docs[("street_closures", "10")]["is_closure"])
        exc = docs[("excavation_permits", "EX1|100")]
        self.assertEqual((exc["location_status"], exc["is_closure"]), ("from_cnn", False))  # geometry from cnn
        self.assertEqual(report["excavation_permits"]["duplicates"], 1)
        self.assertEqual(exc["schema_version"], 1)
        self.assertEqual(exc["provenance"]["pulled_at"], datetime(2026, 9, 26, 0, 30, tzinfo=UTC))

    def test_bad_rows_are_quarantined(self):
        sink, report = self.run_job()
        self.assertEqual(report["street_closures"]["rejected"], 1)  # inverted time span
        q = [json.loads(l) for l in (self.root / "quarantine" / "street_closures.jsonl").read_text().splitlines()]
        self.assertIn("valid_to before valid_from", q[0]["errors"])
        self.assertEqual(report["caltrans_lane_closures"]["rejected"], 1)  # no coordinates

    def test_missing_snapshot_and_no_network(self):
        (self.raw / "chp_incidents.json").unlink()
        sink, report = self.run_job()
        self.assertEqual(report["chp_incidents"]["status"], "missing")
        self.assertIn("no OSM graph: road_segment_ids not computed", report["_notes"])
        self.assertNotIn("road_segment_ids", sink.samples["road_incidents"][0])  # not blanked when not computed

    def test_doc_shape(self):
        r = norm("street_closures", fx.STREET_CLOSURES[0])
        f, d = road_incident_doc(r, NOW)
        self.assertEqual(f, {"source": "street_closures", "source_id": "10"})
        self.assertEqual((d["incident_type"], d["category"], d["is_closure"], d["start_time"]),
                         ("closure", "street_closure", True, datetime(2026, 9, 26, 10, tzinfo=UTC)))


if __name__ == "__main__":
    unittest.main()
