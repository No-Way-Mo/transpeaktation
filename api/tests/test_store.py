"""Ingested-data endpoints: /events, /road-conditions, /traffic against in-memory Mongo (mongomock) and a fake
Tiger cursor. Documents are shaped like ingest/worker's road_incident_doc output and ingest/DESIGN.md §4 events.

    cd api && .venv/bin/pip install -e .[test] && .venv/bin/python -m unittest discover -s tests -t .
"""
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import mongomock
from fastapi.testclient import TestClient

from app import main, store

CONTRACT = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "map_context.schema.json").read_text())
T0 = datetime(2026, 9, 30, 20, 0, tzinfo=timezone.utc)  # 1 PM PDT


def closure(source_id, *, case="260001", name="Castro Farmers' Market 2026", status="Permitted", special=True,
            coords=((-122.4351, 37.7625), (-122.4349, 37.7610)), start=T0, end=T0 + timedelta(hours=7), **kw):
    return {
        "source": "street_closures", "source_id": source_id, "incident_type": "closure",
        "category": "street_closure", "is_closure": True,
        "location": {"type": "LineString", "coordinates": [list(c) for c in coords]},
        "location_status": "exact", "start_time": start, "end_time": end,
        "road_segment_ids": ["1-2-0"], "last_ingested_at": T0 - timedelta(days=1),
        "details": {"closure_type": "street_closure", "category": "Special Event" if special else "Roadway Shared Spaces",
                    "is_closure": True, "is_special_event": special, "name": name, "street": "NOE ST",
                    "from_street": "MARKET ST", "to_street": "BEAVER ST", "status": status},
        "source_fields": {"case_num": case, "loc_desc": "NOE ST between MARKET ST and BEAVER ST", "info": "raw text"},
        "provenance": {"source": "street_closures", "source_id": source_id}, **kw,
    }


def incident(source, source_id, *, start, end=None, status="exact", point=(-122.40, 37.78)):
    return {
        "source": source, "source_id": source_id, "incident_type": "incident", "category": "collision",
        "is_closure": False, "location": {"type": "Point", "coordinates": list(point)}, "location_status": status,
        "start_time": start, "end_time": end, "road_segment_ids": [],
        "details": {"call_type": "1183 - Trfc Collision", "category": "collision", "location_text": "OAK ST / FELL ST"},
        "source_fields": {"secret_raw": "x"}, "provenance": {},
    }


class StoreBase(unittest.TestCase):
    def setUp(self):
        main._cache.clear()
        self.db = mongomock.MongoClient(tz_aware=True).db
        self.db.road_incidents.insert_many([
            closure("a"), closure("b", coords=((-122.4340, 37.7600), (-122.4338, 37.7590))),  # one event, 2 blocks
            closure("c", case="260002", name="Pending fair", status="Application In Review"),  # not approved
            closure("d", case="260003", name="Parklet", special=False),                        # shared space
            closure("e", case="260004", name="Tomorrow fair", start=T0 + timedelta(days=1),
                    end=T0 + timedelta(days=1, hours=5)),
            incident("chp_incidents", "live", start=T0 - timedelta(hours=1)),                 # open-ended, recent
            incident("chp_incidents", "stale", start=T0 - timedelta(days=2)),                 # open-ended, old
            incident("police_dispatch", "hidden", start=T0, status="withheld"),
            incident("chp_incidents", "oakland", start=T0, point=(-122.27, 37.80)),           # outside SF
        ])
        self.db.venues.insert_one({"_id": "seed:oracle-park", "name": "Oracle Park"})
        self.db.events.insert_many([
            {"_id": "evt_giants", "title": "Giants vs. Dodgers", "category": "sports", "venue_id": "seed:oracle-park",
             "location": {"type": "Point", "coordinates": [-122.3893, 37.7786]}, "status": "active",
             "start_time": T0 + timedelta(hours=6), "end_time": None, "source_names": ["predicthq"]},
            {"_id": "evt_cancelled", "title": "Called off", "status": "cancelled",
             "location": {"type": "Point", "coordinates": [-122.39, 37.77]}, "start_time": T0},
            {"_id": "evt_nowhere", "title": "No location", "status": "active", "location": None, "start_time": T0},
        ])


class Shapes(StoreBase):
    def test_events_group_blocks_filter_status_time_and_resolve_venue(self):
        evs = store.find_events(self.db, T0, T0 + timedelta(hours=8), main.SERVICE_AREA)
        self.assertEqual([e["name"] for e in evs], ["Castro Farmers' Market 2026", "Giants vs. Dodgers"])
        fair, game = evs
        self.assertEqual(fair["road_closure_ids"], ["street_closures:a", "street_closures:b"])
        self.assertEqual(fair["venue"], "Noe St between Market St and Beaver St (+1 more blocks)")
        self.assertEqual((fair["category"], fair["start_time"]), ("special_event", "2026-09-30T20:00:00Z"))
        self.assertAlmostEqual(fair["lat"], (37.7625 + 37.7610 + 37.7600 + 37.7590) / 4)
        self.assertEqual((game["venue"], game["source"], game["end_time"]), ("Oracle Park", "predicthq", None))

    def test_event_without_end_counts_for_the_default_duration(self):
        later = T0 + timedelta(hours=6) + store.DEFAULT_EVENT_DURATION - timedelta(minutes=1)
        self.assertIn("evt_giants", [e["id"] for e in store.find_events(self.db, later, later, main.SERVICE_AREA)])
        after = later + timedelta(minutes=2)
        self.assertNotIn("evt_giants", [e["id"] for e in store.find_events(self.db, after, after, main.SERVICE_AREA)])

    def test_event_window_is_interval_overlap(self):
        """event.start <= window.end and event.end >= window.start; multi-day events count only inside their span."""
        self.db.road_incidents.insert_many([
            closure("m1", case="M", name="Multi-day", start=T0 - timedelta(days=5), end=T0 + timedelta(days=4)),
            closure("x1", case="X", name="Ended", start=T0 - timedelta(hours=6), end=T0 - timedelta(minutes=1)),
            closure("y1", case="Y", name="Later", start=T0 + timedelta(hours=2, minutes=1), end=T0 + timedelta(hours=5)),
        ])
        names = {e["name"] for e in store.find_events(self.db, T0, T0 + timedelta(hours=2), main.SERVICE_AREA)}
        self.assertIn("Multi-day", names)
        self.assertNotIn("Ended", names)
        self.assertNotIn("Later", names)
        after = T0 + timedelta(days=4, minutes=1)
        self.assertNotIn("Multi-day", {e["name"] for e in store.find_events(self.db, after, after, main.SERVICE_AREA)})

    def test_road_conditions_skip_events_hidden_unlocated_stale_and_out_of_area(self):
        cs = store.find_road_conditions(self.db, T0, T0 + timedelta(hours=1), main.SERVICE_AREA)
        self.assertEqual([c["id"] for c in cs], ["street_closures:d", "chp_incidents:live"])  # closures first
        live = cs[1]
        self.assertEqual((live["description"], live["street"]), ("1183 - Trfc Collision", "Oak St / Fell St"))
        self.assertEqual((live["lat"], live["lon"]), (37.78, -122.40))

    def test_outputs_match_the_contract_and_leak_no_raw_fields(self):
        defs = CONTRACT["$defs"]
        evs = store.find_events(self.db, T0, T0 + timedelta(hours=8), main.SERVICE_AREA)
        cs = store.find_road_conditions(self.db, T0, T0 + timedelta(hours=1), main.SERVICE_AREA)
        for items, name in ((evs, "MapEvent"), (cs, "RoadCondition")):
            for it in items:
                self.assertEqual(set(it), set(defs[name]["properties"]), name)
                self.assertTrue(set(defs[name]["required"]) <= {k for k, v in it.items() if v is not None})
        self.assertNotIn("secret_raw", json.dumps(cs) + json.dumps(evs))

    def test_permits_are_opt_in(self):
        permit = {**closure("p1", special=False), "source": "street_use_permits", "is_closure": False}
        self.db.road_incidents.insert_one(permit)
        ids = lambda **kw: [c["id"] for c in store.find_road_conditions(self.db, T0, T0 + timedelta(hours=1),
                                                                         main.SERVICE_AREA, **kw)]
        self.assertNotIn("street_use_permits:p1", ids())
        self.assertIn("street_use_permits:p1", ids(include_permits=True))

    def test_bad_geometry_is_dropped_not_raised(self):
        self.assertIsNone(store.rep_point({"type": "Point", "coordinates": ["x", 1]}))
        self.assertIsNone(store.rep_point({"type": "Polygon", "coordinates": []}))
        self.assertIsNone(store.condition_from_doc({"source": "s", "source_id": "1", "location": None}))


class Endpoints(StoreBase):
    def setUp(self):
        super().setUp()
        self.patches = [mock.patch.object(main.segments, "load"), mock.patch.object(store, "mongo_db", return_value=self.db)]
        for p in self.patches:
            p.start()
        self.client = TestClient(main.app).__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        for p in reversed(self.patches):
            p.stop()

    def test_events_and_conditions_over_http(self):
        q = {"start": "2026-09-30T13:00:00-07:00", "end": "2026-09-30T14:00:00-07:00"}
        evs = self.client.get("/events", params=q).json()["events"]
        self.assertEqual([e["name"] for e in evs], ["Castro Farmers' Market 2026"])
        cs = self.client.get("/road-conditions", params=q).json()["road_conditions"]
        self.assertEqual(len(cs), 2)
        box = self.client.get("/events", params={**q, "bbox": "-122.39,37.77,-122.38,37.78"}).json()["events"]
        self.assertEqual(box, [])

    def test_window_and_bbox_are_validated(self):
        for q in ({"start": "x", "end": "y"}, {"start": "2026-09-30T13:00:00", "end": "2026-09-30T14:00:00"},
                  {"start": "2026-09-30T14:00:00Z", "end": "2026-09-30T13:00:00Z"},
                  {"start": "2026-09-01T00:00:00Z", "end": "2026-09-30T00:00:00Z"},
                  {"start": "2026-09-30T13:00:00Z", "end": "2026-09-30T14:00:00Z", "bbox": "1,2,3"}):
            self.assertEqual(self.client.get("/events", params=q).status_code, 400, q)

    def test_unconfigured_or_failing_database_is_503_without_details(self):
        q = {"start": "2026-09-30T13:00:00Z", "end": "2026-09-30T14:00:00Z"}
        with mock.patch.object(store, "mongo_db", side_effect=store.StoreUnavailable("MONGODB_URI is not configured")):
            r = self.client.get("/events", params=q)
        self.assertEqual(r.status_code, 503)
        self.assertIn("not configured", r.json()["detail"])
        with mock.patch.object(store, "mongo_db", side_effect=RuntimeError("mongodb+srv://user:pw@host")):
            r = self.client.get("/road-conditions", params=q)
        self.assertEqual(r.status_code, 503)
        self.assertNotIn("pw@", r.text)
        # Failures aren't cached: the next call reaches the database again.
        self.assertEqual(self.client.get("/events", params=q).status_code, 200)

    def test_traffic_latest_per_segment_from_tiger(self):
        cur = mock.MagicMock()
        cur.fetchall.return_value = [("1-2-0", T0, "tomtom", 12.5, 25.0, 0.5)]
        conn = mock.MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        with mock.patch.object(store, "tiger_conn", return_value=conn):
            r = self.client.get("/traffic", params={"segments": "1-2-0,3-4-0"})
        self.assertEqual(r.json()["traffic"], [{"road_segment_id": "1-2-0", "time": "2026-09-30T20:00:00Z",
                                                "source": "tomtom", "speed_mph": 12.5, "free_flow_speed_mph": 25.0,
                                                "congestion_ratio": 0.5}])
        self.assertEqual(set(r.json()["traffic"][0]), set(CONTRACT["$defs"]["SegmentTraffic"]["properties"]))
        sql, (ids, _since) = cur.execute.call_args.args
        self.assertIn("source <> 'muni'", sql)
        self.assertEqual(ids, ["1-2-0", "3-4-0"])
        conn.close.assert_called_once()
        self.assertEqual(self.client.get("/traffic", params={"segments": ","}).status_code, 400)

    def test_health_reports_db_config_without_secrets(self):
        with mock.patch.dict("os.environ", {"MONGODB_URI": "mongodb+srv://u:secretpw@h", "TIGER_DATABASE_URL": ""}),                 mock.patch.object(store, "_INGEST_ENV", Path("no-such-dir") / ".env"):  # ignore this machine's ingest/.env
            h = self.client.get("/health").json()
        self.assertEqual((h["mongo"], h["tiger"]), ("ready", "not configured"))
        self.assertNotIn("secretpw", json.dumps(h))


if __name__ == "__main__":
    unittest.main()
