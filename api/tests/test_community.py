"""Community events: create / My Events / edit over HTTP against in-memory Mongo (mongomock), ownership by host key,
the /events map path, and that the planner never sees them.

    cd api && .venv/bin/python -m unittest tests.test_community
"""
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import mongomock
from fastapi.testclient import TestClient

from app import community, main, store

CONTRACT = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "map_context.schema.json").read_text())
START = (datetime.now(timezone.utc) + timedelta(days=2)).replace(minute=0, second=0, microsecond=0)


def body(**kw):
    return {"title": "Dolores Park Jazz Picnic", "venue": "Dolores Park", "lat": 37.7596, "lon": -122.4269,
            "start_time": START.isoformat(), "end_time": (START + timedelta(hours=3)).isoformat(),
            "category": "concert", "admission": "free", "description": "Bring a blanket.", **kw}


class Community(unittest.TestCase):
    def setUp(self):
        main._cache.clear()
        self.db = mongomock.MongoClient(tz_aware=True).db
        self.patches = [mock.patch.object(main.segments, "load"), mock.patch.object(store, "mongo_db", return_value=self.db)]
        for p in self.patches:
            p.start()
        self.client = TestClient(main.app).__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        for p in reversed(self.patches):
            p.stop()

    def create(self, **kw):
        r = self.client.post("/community/events", json=body(**kw))
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def window(self):
        q = {"start": (START - timedelta(hours=1)).isoformat(), "end": (START + timedelta(hours=1)).isoformat()}
        return self.client.get("/events", params=q).json()["events"]

    def test_create_stores_the_canonical_doc_with_only_a_key_hash(self):
        got = self.create()
        ev, key = got["event"], got["host_key"]
        self.assertTrue(ev["id"].startswith("evt_") and len(key) >= 24)
        self.assertEqual((ev["name"], ev["venue"], ev["source"], ev["category"]),
                         ("Dolores Park Jazz Picnic", "Dolores Park", "community", "concert"))
        self.assertEqual(ev["community"], {"admission": "free", "ticket_url": None, "ticket_price": None,
                                           "description": "Bring a blanket.", "image_url": None,
                                           "promotion": {"status": "none"}})
        doc = self.db.events.find_one({"_id": ev["id"]})
        self.assertEqual((doc["source_names"], doc["status"], doc["location"]["coordinates"]),
                         (["community"], "active", [-122.4269, 37.7596]))
        self.assertEqual(doc["sources"]["community"]["host_key_hash"], community.key_hash(key))
        self.assertNotIn(key, json.dumps(doc, default=str))

    def test_appears_on_the_existing_events_map_path_right_away(self):
        self.assertEqual(self.window(), [])  # cached empty answer...
        ev = self.create()["event"]
        shown = self.window()                # ...dropped on create
        self.assertEqual([e["id"] for e in shown], [ev["id"]])
        defs = CONTRACT["$defs"]
        self.assertEqual(set(shown[0]), set(defs["MapEvent"]["properties"]))
        self.assertEqual(set(shown[0]["community"]), set(defs["CommunityInfo"]["properties"]))
        self.assertNotIn("host_key_hash", json.dumps(shown))

    def test_ticketed_needs_a_link_and_free_drops_ticket_fields(self):
        r = self.client.post("/community/events", json=body(admission="ticketed"))
        self.assertEqual(r.status_code, 422)
        ev = self.create(admission="ticketed", ticket_url="https://tickets.example/jazz", ticket_price=15)["event"]
        self.assertEqual((ev["community"]["ticket_url"], ev["community"]["ticket_price"]), ("https://tickets.example/jazz", 15))
        ev = self.create(admission="free", ticket_url="https://tickets.example/x", ticket_price=9)["event"]
        self.assertEqual((ev["community"]["ticket_url"], ev["community"]["ticket_price"]), (None, None))

    def test_bad_input_is_rejected(self):
        past = datetime.now(timezone.utc) - timedelta(days=1)
        for kw, code in (({"title": ""}, 422), ({"category": "rave"}, 422), ({"admission": "maybe"}, 422),
                         ({"end_time": (START - timedelta(hours=1)).isoformat()}, 422),
                         ({"end_time": (START + timedelta(days=8)).isoformat()}, 422),
                         ({"start_time": START.replace(tzinfo=None).isoformat()}, 422),
                         ({"admission": "ticketed", "ticket_url": "javascript:alert(1)"}, 422),
                         ({"image_url": "ftp://x/y.png"}, 422),
                         ({"title": "x" * 121}, 422), ({"description": "x" * 501}, 422),
                         ({"admission": "ticketed", "ticket_url": "https://t.example/a", "ticket_price": -1}, 422),
                         ({"lat": 91}, 400),
                         ({"lat": 37.80, "lon": -122.27}, 400),  # Oakland
                         ({"start_time": (past - timedelta(hours=3)).isoformat(), "end_time": past.isoformat()}, 400)):
            self.assertEqual(self.client.post("/community/events", json=body(**kw)).status_code, code, kw)
        self.assertEqual(self.db.events.count_documents({}), 0)

    def test_my_events_are_only_the_ones_the_keys_own(self):
        a, b = self.create(), self.create(title="Someone else's fair")
        other = {"_id": "evt_giants", "title": "Giants", "source_names": ["predicthq"], "start_time": START,
                 "location": {"type": "Point", "coordinates": [-122.39, 37.77]}, "status": "active"}
        self.db.events.insert_one(other)
        mine = self.client.post("/community/events/mine", json={"keys": {
            a["event"]["id"]: a["host_key"], b["event"]["id"]: "wrong-key-wrong-key", "evt_giants": "x" * 20}}).json()
        self.assertEqual([e["id"] for e in mine["events"]], [a["event"]["id"]])
        self.assertEqual(self.client.post("/community/events/mine", json={"keys": {}}).json(), {"events": []})

    def test_edit_needs_the_host_key_and_cannot_touch_promotion(self):
        got = self.create()
        eid, key = got["event"]["id"], got["host_key"]
        url = f"/community/events/{eid}"
        self.assertEqual(self.client.put(url, json={**body(title="Renamed"), "host_key": "nope" * 5}).status_code, 403)
        self.assertEqual(self.client.put("/community/events/evt_0000000000000000",
                                         json={**body(), "host_key": key}).status_code, 404)
        r = self.client.put(url, json={**body(title="Renamed", promotion={"status": "active"}), "host_key": key})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["event"]["name"], r.json()["event"]["community"]["promotion"]), ("Renamed", {"status": "none"}))
        self.assertEqual([e["name"] for e in self.window()], ["Renamed"])

    def test_reports_are_stored_for_review_and_never_hide_or_delete_the_event(self):
        eid = self.create()["event"]["id"]
        for i in range(5):
            r = self.client.post(f"/events/{eid}/report", json={"reason": "spam", "details": f"  report  {i} "})
            self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual([e["id"] for e in self.window()], [eid])            # still on the map
        self.assertEqual(self.db.events.find_one({"_id": eid})["status"], "active")
        reps = list(self.db.event_reports.find({}, {"_id": 0}))
        self.assertEqual(len(reps), 5)
        self.assertEqual(set(reps[0]), {"event_id", "reason", "details", "created_at"})  # no identity of any kind
        self.assertEqual(reps[0]["details"], "report 0")
        # any event can be reported (ingested ones too, e.g. a DataSF-derived id); reasons are a fixed list
        ext = "street_closures:260001@2026-09-30T20:00:00Z"
        self.assertEqual(self.client.post(f"/events/{ext}/report", json={"reason": "doesnt_exist"}).status_code, 201)
        self.assertEqual(self.client.post(f"/events/{eid}/report", json={"reason": "meh"}).status_code, 422)
        self.assertEqual(self.client.post(f"/events/{eid}/report", json={"reason": "other", "details": "x" * 501}).status_code, 422)

    def test_delete_needs_the_host_key_and_takes_it_off_the_map_and_my_events(self):
        got = self.create()
        eid, key = got["event"]["id"], got["host_key"]
        url = f"/community/events/{eid}/delete"
        self.assertEqual(self.client.post(url, json={"host_key": "not-the-key-at-all"}).status_code, 403)
        self.assertEqual([e["id"] for e in self.window()], [eid])
        self.assertEqual(self.client.post(url, json={"host_key": key}).status_code, 200)
        self.assertEqual(self.window(), [])
        self.assertEqual(self.client.post("/community/events/mine", json={"keys": {eid: key}}).json()["events"], [])
        self.assertEqual(self.client.post(url, json={"host_key": key}).status_code, 404)             # once
        self.assertEqual(self.client.put(f"/community/events/{eid}", json={**body(), "host_key": key}).status_code, 404)
        self.assertEqual(self.db.events.find_one({"_id": eid})["status"], "deleted")                  # kept for review

    def test_external_events_cannot_be_edited_deleted_or_promoted_by_anyone(self):
        self.db.events.insert_one({"_id": "evt_0123456789abcdef", "title": "Giants", "source_names": ["predicthq"],
                                   "status": "active", "sources": {"community": {"host_key_hash": community.key_hash("k" * 20)}}})
        k = {"host_key": "k" * 20}  # even a forged community block with a matching hash doesn't make it a community event
        self.assertEqual(self.client.put("/community/events/evt_0123456789abcdef", json={**body(), **k}).status_code, 404)
        self.assertEqual(self.client.post("/community/events/evt_0123456789abcdef/delete", json=k).status_code, 404)
        self.assertEqual(self.client.post("/community/events/mine", json={"keys": {"evt_0123456789abcdef": "k" * 20}}).json(),
                         {"events": []})

    def test_lookup_returns_listed_events_by_id_without_host_secrets(self):
        a, b = self.create(), self.create(title="Gone soon")
        self.client.post(f"/community/events/{b['event']['id']}/delete", json={"host_key": b["host_key"]})
        got = self.client.post("/events/lookup", json={"ids": [a["event"]["id"], b["event"]["id"], "evt_nope"]}).json()
        self.assertEqual([e["id"] for e in got["events"]], [a["event"]["id"]])
        self.assertNotIn("host_key", json.dumps(got))
        self.assertEqual(self.client.post("/events/lookup", json={"ids": ["x"] * 101}).status_code, 422)

    def test_an_ended_event_leaves_the_map_but_stays_in_my_events(self):
        got = self.create()
        eid = got["event"]["id"]
        self.db.events.update_one({"_id": eid}, {"$set": {"start_time": datetime.now(timezone.utc) - timedelta(hours=5),
                                                          "end_time": datetime.now(timezone.utc) - timedelta(hours=1)}})
        now = datetime.now(timezone.utc)
        q = {"start": now.isoformat(), "end": (now + timedelta(hours=2)).isoformat()}
        self.assertEqual(self.client.get("/events", params=q).json()["events"], [])
        mine = self.client.post("/community/events/mine", json={"keys": {eid: got["host_key"]}}).json()["events"]
        self.assertEqual([e["id"] for e in mine], [eid])
        # ending is time filtering, not deletion: still in Mongo, still active, still found for Saved Events
        self.assertEqual(self.db.events.find_one({"_id": eid})["status"], "active")
        self.assertEqual([e["id"] for e in self.client.post("/events/lookup", json={"ids": [eid]}).json()["events"]], [eid])
        # and nothing about promotion was ever written
        self.assertEqual(self.db.events.find_one({"_id": eid})["sources"]["community"]["promotion"], {"status": "none"})

    def test_no_database_is_503(self):
        with mock.patch.object(store, "mongo_db", side_effect=store.StoreUnavailable("MONGODB_URI is not configured")):
            self.assertEqual(self.client.post("/community/events", json=body()).status_code, 503)

    def test_no_payment_or_promotion_endpoint_exists_yet(self):
        paths = [getattr(r, "path", "") for r in main.app.routes]
        self.assertFalse([p for p in paths if "boost" in p or "promot" in p or "pay" in p], paths)


class Planner(unittest.TestCase):
    """Community events are map-only: the planner keeps its demo fallback and never routes around them."""
    def test_planner_ignores_community_events(self):
        db = mongomock.MongoClient(tz_aware=True).db
        db.events.insert_one(community.new_doc(community.EventIn(**body()), "k" * 20, datetime.now(timezone.utc)))
        s = store.Store()
        with mock.patch.object(s, "db", return_value=db):
            self.assertIsNone(s.events_between(START - timedelta(hours=1), START + timedelta(hours=1)))  # -> demo events
            db.events.insert_one({"_id": "evt_giants", "title": "Giants", "source_names": ["predicthq"], "status": "active",
                                  "start_time": START, "end_time": START + timedelta(hours=3),
                                  "location": {"type": "Point", "coordinates": [-122.39, 37.77]}})
            got = s.events_between(START - timedelta(hours=1), START + timedelta(hours=1))
            self.assertEqual([e["_id"] for e in got], ["evt_giants"])
            # promotion is not routing trust: even a (future) promoted community event stays out of the planner
            db.events.update_many({"source_names": "community"}, {"$set": {"sources.community.promotion.status": "active"}})
            got = s.events_between(START - timedelta(hours=1), START + timedelta(hours=1))
        self.assertEqual([e["_id"] for e in got], ["evt_giants"])


if __name__ == "__main__":
    unittest.main()
