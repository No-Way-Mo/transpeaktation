"""Offline checks for the event-aware trip plan: the model (pure) and GET /plan / /events with a fake store."""
import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient

import httpx

from app import advice, main, ml, model, providers, store as store_mod

SF = model.SF_TZ
DAY = datetime(2026, 9, 26, tzinfo=SF)
at = lambda h, m=0: DAY.replace(hour=h, minute=m)  # noqa: E731
ORACLE = model.demo_events(DAY)[0]


def line(lon: float, n: int = 11) -> list[list[float]]:
    return [[37.774 + i * 0.001, lon] for i in range(n)]  # northbound, clear of Chase Center


def route(lon: float, dur: float = 600, sids=None, typical=360.0) -> dict:
    coords = line(lon)
    return {"dur": dur, "dur_typical": typical, "dist": 2000, "summary": "", "coords": coords, "steps": [],
            "road_segment_ids": sids if sids is not None else [f"{i}-{i + 1}-0" for i in range(10)]}


PAST, AROUND = route(-122.3893), route(-122.401, 660)  # straight past Oracle Park / ~1 km west of it
CTX = {"events": [ORACLE], "incidents": [], "traffic": [], "predictions": [], "lengths": {}}


class EventImpact(unittest.TestCase):
    def test_delay_only_near_the_venue_while_the_crowd_is_there(self):
        now = at(9)
        self.assertEqual(model.predict_route(PAST, at(12), CTX, now=now)["delay"], 0)       # noon: no crowd
        self.assertEqual(model.predict_route(PAST, at(18, 30), CTX, now=now)["delay"], 600)  # arrival window: high tier
        edge = model.predict_route(PAST, at(17, 25), CTX, now=now)["delay"]                  # passes ~17:30: ramping in
        self.assertTrue(0 < edge < 600, edge)
        self.assertEqual(model.predict_route(AROUND, at(18, 30), CTX, now=now)["delay"], 0)  # ~1 km away
        self.assertGreater(model.predict_route(PAST, at(22, 20), CTX, now=now)["delay"], 0)  # crowd leaving

    def test_size_and_type_pick_the_tier(self):
        tier = lambda **kw: model.event_tier({**ORACLE, **kw})  # noqa: E731
        self.assertEqual((tier(), tier(capacity=8000, category="community"), tier(capacity=1300, category="conference"),
                          tier(capacity=None, category=None)), ("high", "medium", "low", "low"))
        self.assertEqual([model.event_max_delay_s({**ORACLE, "capacity": c}) for c in (41265, 6000, 100)], [600, 300, 120])

    def test_a_route_gets_its_worst_event_not_the_sum(self):
        small = [{**ORACLE, "id": f"c{i}", "title": f"Conf {i}", "capacity": 500, "category": "conference"} for i in range(9)]
        p = model.predict_route(PAST, at(18, 30), {**CTX, "events": [*small, ORACLE]}, now=at(9))
        self.assertEqual((p["delay"], p["events"][0], len(p["events"])), (600, "Giants vs. Dodgers at Oracle Park", 10))

    def test_without_ml_the_card_is_the_fastest_route_unchanged(self):
        now = at(9)
        p = model.plan([PAST, AROUND], [at(18, 30)] * 2, "depart", CTX, now=now)  # Giants crowd on PAST
        self.assertEqual((p["best"], p["preds"][0]["dur"], p["advice"]), (0, PAST["dur"], None))  # no re-pick/re-time
        est = p["preds"][0]["estimate"]                          # api/'s estimate: shown on the normal route only
        self.assertEqual((round(est["dur"]), est["delay"]), (PAST["dur"] + 600, 600))
        self.assertEqual(est["why"], ["Giants vs. Dodgers at Oracle Park"])
        self.assertEqual(p["tag"], "Events on the way")
        # the pick's note: what's on it; no "faster"/"avoids", since api/'s estimate for AROUND (11) beats PAST's (20)
        self.assertEqual(p["note"], "Passes Giants vs. Dodgers at Oracle Park.")
        self.assertEqual(p["preds"][0]["note"], "10 min slower: Giants vs. Dodgers at Oracle Park.")
        self.assertEqual(p["preds"][1]["note"], "1 min slower: longer or busier roads.")
        tie = model.plan([AROUND, AROUND], [at(12)] * 2, "depart", CTX, now=now)  # same time: nothing slows them
        self.assertEqual(([x["note"] for x in tie["preds"]], tie["note"]),
                         (["No events or closures on it."] * 2, "No events or closures on it."))
        self.assertEqual(model.plan([PAST, AROUND], [at(12)] * 2, "depart", CTX, now=now)["tag"], "Clear")

    def test_normal_route_note_sums_up_its_congestion(self):
        def note(*why, slower=3, slow=0, coverage=1.0, blocked=False):
            return model.route_note({"blocked": blocked, "estimate": {"why": list(why)},
                                     "traffic": {"slow_segments": slow, "coverage": coverage}}, slower)
        self.assertEqual(note("LIVE Spinal Manual Therapy Course", "Catawba and Cherokee American Revolution Symposium",
                              "Other"), "3 min slower: LIVE Spinal Manual Therapy Course +2 more.")
        self.assertEqual(note("Catawba and Cherokee American Revolution Symposium at Moscone West"),
                         "3 min slower: Catawba and Cherokee American Revolution…")  # whole words only
        self.assertEqual(note("Giants vs. Dodgers", slow=4), "3 min slower: Giants vs. Dodgers, 4 slow stretches.")
        self.assertEqual(note(slow=1, slower=0), "1 slow stretch of traffic.")
        self.assertEqual(note(slow=4, coverage=0.0), "3 min slower: longer or busier roads.")  # no traffic data: no claim
        self.assertEqual(note("Giants vs. Dodgers", slower=0), "Giants vs. Dodgers.")
        self.assertEqual(note("Road closure on King St", slower=25, blocked=True),  # the minutes are the penalty
                         "Crosses a road closure when you'd get there.")
        self.assertLessEqual(len(note("x" * 200, "y", slow=12, slower=99)), model.NOTE_MAX)

    def test_special_event_closure_counts_like_any_event(self):
        # shaped like store.find_closure_events (what /events shows): a multi-day event right on the route
        amzn = model.from_map_event({"id": "street_closures:X@2026-09-23T13:00:00+00:00", "name": "AMZN Unboxed",
                                     "category": "special_event", "venue": None, "lat": 37.779, "lon": -122.3893,
                                     "start_time": "2026-09-23T13:00:00+00:00", "end_time": "2026-10-03T01:00:00+00:00",
                                     "source": "street_closures"})
        p = model.plan([PAST], [at(12)], "depart", {**CTX, "events": [amzn]}, now=at(9))
        self.assertNotEqual(p["tag"], "Clear")
        self.assertIn("AMZN Unboxed", p["preds"][0]["note"])


class RoadData(unittest.TestCase):
    def test_closure_counts_only_if_active_when_you_get_there(self):
        now, depart = at(9), at(10)
        sids = PAST["road_segment_ids"]
        closed_later = {"source": "street_closures", "category": "street_closure", "is_closure": True,
                        "road_segment_ids": [sids[8]], "start_time": at(10, 9), "end_time": at(12),
                        "details": {"name": "Fleet Week", "street": "KING ST"}}
        ctx = {**CTX, "incidents": [closed_later]}
        p = model.predict_route(PAST, depart, ctx, now=now)       # reaches segment 8 at ~10:08, before it closes
        self.assertEqual((p["blocked"], p["incidents"]), (False, []))
        p = model.predict_route(PAST, at(10, 5), ctx, now=now)    # now it's closed when we get there
        self.assertTrue(p["blocked"])
        self.assertEqual(p["breakdown"]["incidents_sec"], model.CLOSURE_PENALTY_S)
        self.assertEqual(p["incidents"][0]["label"], "Road closure on Fleet Week")

    def test_duplicate_closure_rows_count_once(self):
        sids = PAST["road_segment_ids"]
        rows = [{"source": "street_closures", "category": "street_closure", "is_closure": True, "road_segment_ids": [s],
                 "start_time": None, "end_time": None, "details": {"name": "NIBBI BROS"}} for s in sids[:2]]
        other = {**rows[0], "details": {"name": "Parade"}, "road_segment_ids": [sids[5]]}
        p = model.predict_route(PAST, at(10), {**CTX, "incidents": [*rows, other]}, now=at(9))
        self.assertEqual(p["breakdown"]["incidents_sec"], model.CLOSURE_PENALTY_S)  # blocked once, not per closure
        self.assertEqual([i["label"] for i in p["incidents"]], ["Road closure on NIBBI BROS", "Road closure on Parade"])

    def test_incident_without_end_time_clears_after_a_few_hours(self):
        crash = {"source": "chp_incidents", "category": "collision", "is_closure": False, "road_segment_ids": ["3-4-0"],
                 "start_time": at(9), "end_time": None, "details": {"call_type": "Crash"}}
        ctx = {**CTX, "events": [], "incidents": [crash]}
        self.assertEqual(model.predict_route(PAST, at(10), ctx, now=at(9))["breakdown"]["incidents_sec"], 90)
        self.assertEqual(model.predict_route(PAST, at(13), ctx, now=at(9))["breakdown"]["incidents_sec"], 0)  # not forever

    def test_store_asks_only_for_recent_open_ended_incidents(self):
        s, seen = store_mod.Store(), []
        s._mongo_call = lambda fn: seen.append(fn) or []
        s.incidents_on(["1-2-0"], at(18), at(19))

        class DB:
            class road_incidents:
                @staticmethod
                def find(q, proj):
                    DB.q = q
                    return type("C", (), {"limit": lambda self, n: []})()
        seen[0](DB)
        self.assertIn({"end_time": None, "start_time": {"$gte": at(18) - model.OPEN_ENDED}}, DB.q["$and"][1]["$or"])

    def test_permits_are_ignored_and_minor_incidents_are_capped(self):
        sids = PAST["road_segment_ids"]
        permit = {"category": "excavation", "is_closure": False, "road_segment_ids": sids, "start_time": None, "end_time": None}
        crashes = [{"category": "collision", "is_closure": False, "road_segment_ids": [s], "start_time": None,
                    "end_time": None, "details": {"call_type": "Traffic Collision", "location_text": f"block {s}"}} for s in sids]
        p = model.predict_route(PAST, at(10), {**CTX, "incidents": [permit, *crashes]}, now=at(9))
        self.assertEqual(p["breakdown"]["incidents_sec"], model.INCIDENT_CAP_S)
        self.assertEqual(len(p["incidents"]), len(sids))

    def test_live_traffic_is_added_only_to_routes_without_it(self):
        sids = PAST["road_segment_ids"]
        rows = [{"road_segment_id": s, "source": "tomtom", "time": at(9), "speed_mph": 10.0,
                 "free_flow_speed_mph": 25.0, "congestion_ratio": 0.6} for s in sids]
        ctx = {**CTX, "traffic": rows, "lengths": {s: 100.0 for s in sids}}
        osrm = {**PAST, "dur_typical": None}
        now = at(9)
        p = model.predict_route(osrm, now, ctx, now=now)
        self.assertEqual(p["traffic"]["slow_segments"], 10)
        self.assertEqual(p["traffic"]["coverage"], 1.0)
        self.assertEqual(p["breakdown"]["traffic_sec"], round(10 * (100 / (10 * 0.44704) - 100 / (25 * 0.44704))))
        self.assertEqual(model.predict_route(PAST, now, ctx, now=now)["breakdown"]["traffic_sec"], 0)  # Mapbox has it
        self.assertEqual(model.predict_route(osrm, at(12), ctx, now=now)["breakdown"]["traffic_sec"], 0)  # not "now"

    def test_best_traffic_source_wins_and_tiles_convert_ratio(self):
        rows = [{"road_segment_id": "a", "source": "mapbox_tiles", "time": at(9), "speed_mph": None,
                 "free_flow_speed_mph": 20.0, "congestion_ratio": 0.5},
                {"road_segment_id": "b", "source": "mapbox_tiles", "time": at(9), "speed_mph": None,
                 "free_flow_speed_mph": 20.0, "congestion_ratio": 0.5},
                {"road_segment_id": "b", "source": "tomtom", "time": at(9), "speed_mph": 20.0,
                 "free_flow_speed_mph": 20.0, "congestion_ratio": 0.0}]
        t = model.traffic_effect(rows, ["a", "b"], [100.0, 100.0])
        self.assertEqual(t["slow_segments"], 1)  # b uses TomTom (free flow), a uses the tile ratio (slow)
        self.assertEqual(t["delay_sec"], round(100 / (10 * 0.44704) - 100 / (20 * 0.44704)))

    def test_ml_forecasts_replace_the_heuristic(self):
        sids = PAST["road_segment_ids"]
        preds = [{"road_segment_id": s, "time": at(18, 30), "predicted_delay_sec": 30.0, "model_version": "gbm-1"} for s in sids]
        p = model.predict_route(PAST, at(18, 30), {**CTX, "predictions": preds}, now=at(9))
        self.assertEqual((p["breakdown"]["events_sec"], p["model"], p["events"]), (300, "ml:gbm-1", []))


class Events(unittest.TestCase):
    def test_views_match_the_web_shape(self):
        o, c, f = (model.event_view(e) for e in model.demo_events(DAY))
        self.assertEqual((o["time"], o["start"], o["crowd"]), ("7:15 PM", [19, 15], {"from": [17, 45], "to": [19, 30], "delay": 10}))
        self.assertEqual(o["drop"]["badge"], "Saves ~10 min")
        self.assertEqual((c["crowd"]["from"], c["crowd"]["to"]), ([18, 30], [20, 15]))
        self.assertEqual((f["start"], f["time"]), (None, "until 2:00 PM"))  # market: no fixed start

    def test_mongo_event_with_venue(self):
        doc = {"_id": "evt_1", "title": "Warriors vs. Lakers", "category": "sports", "start_time": at(19, 30),
               "end_time": at(22), "location": {"type": "Point", "coordinates": [-122.3877, 37.768]}, "attendance": 18000,
               "venue": {"name": "Chase Center", "keys": ["chase"], "drop_off": {"label": "x", "lat": 1, "lon": 2, "why": "y"}}}
        e = model.from_mongo(doc)
        self.assertEqual((e["venue"], e["lat"], e["source"]), ("Chase Center", 37.768, "mongo"))
        self.assertIsNone(model.from_mongo({"_id": "x", "title": "no place", "start_time": at(1)}))


class TrafficByTime(unittest.TestCase):
    def test_typical_buckets_step_back_whole_weeks_in_sf_time(self):
        t = datetime(2026, 11, 5, 18, 7, tzinfo=SF)  # PST; 1 and 2 weeks back straddle the Nov 1 DST change
        b = store_mod.typical_buckets(t, t)
        self.assertEqual(len(b), store_mod.TYPICAL_WEEKS)
        self.assertEqual([x.astimezone(SF).strftime("%m-%d %a %H:%M") for x in b[:2]],
                         ["10-29 Thu 18:00", "10-22 Thu 18:00"])
        self.assertTrue(all(x.tzinfo == timezone.utc for x in b))
        now = datetime(2026, 9, 26, 12, tzinfo=SF)  # a trip on Thu Oct 22: its last 4 Thursdays before *now*
        self.assertEqual([x.astimezone(SF).strftime("%m-%d %H:%M") for x in store_mod.typical_buckets(datetime(2026, 10, 22, 8, 30, tzinfo=SF), now)],
                         ["09-24 08:30", "09-17 08:30", "09-10 08:30", "09-03 08:30"])

    def test_live_observed_or_typical_by_trip_time(self):
        s, calls = store_mod.Store(), []
        s._tiger_call = lambda sql, params: calls.append((sql, params)) or []
        now = datetime(2026, 9, 26, 20, tzinfo=timezone.utc)
        self.assertEqual(s.traffic_at(["1-2-0"], now + timedelta(minutes=20), now)[1], "live")
        self.assertIn("now() -", calls[-1][0])
        then = now - timedelta(days=2)
        self.assertEqual(s.traffic_at(["1-2-0"], then, now), ([], "observed"))
        self.assertEqual(calls[-1][1][2:], (then - store_mod.TRAFFIC_MAX_AGE, then))  # what we saw up to then
        self.assertEqual(s.traffic_at(["1-2-0"], now + timedelta(days=3), now), ([], "typical"))
        self.assertIn("avg(", calls[-1][0])
        s._tiger_call = lambda sql, params: None  # Tiger down: None, the planner reports "unavailable"
        self.assertEqual(s.traffic_at(["1-2-0"], then, now), (None, "observed"))


class MLAnswer(unittest.TestCase):
    def test_parse_rejects_off_contract_answers(self):
        area = main.in_area
        ok = {"model": "m", "predicted_sec": 600, "choice": {"candidate": 0}}
        self.assertEqual(ml.parse(ok, 2, area)["best"], 0)
        self.assertEqual(ml.parse({**ok, "choice": {"waypoints": [[-122.4, 37.78]]}}, 2, area)["waypoints"], [(-122.4, 37.78)])
        for bad in [{**ok, "model": ""}, {**ok, "predicted_sec": -1}, {**ok, "predicted_sec": True},
                    {**ok, "predicted_sec": float("nan")}, {**ok, "choice": {"candidate": 2}}, {**ok, "choice": {}},
                    {**ok, "choice": {"waypoints": [[-73.9, 40.7]]}},   # New York: outside the service area
                    {**ok, "choice": {"waypoints": [[-122.4, 37.78]] * 30}}, {**ok, "reasons": "text"}, []]:
            with self.assertRaises(ValueError, msg=bad):
                ml.parse(bad, 2, area)


class FakeStore:
    def __init__(self, events=None, incidents=None, traffic=None):
        self._events, self._incidents, self._traffic = events, incidents, traffic
        self.trips = []

    def events_between(self, t0, t1):
        return self._events

    def incidents_on(self, sids, t0, t1):
        return self._incidents

    def traffic_at(self, sids, t, now):
        self.traffic_asked = (t, now)
        return self._traffic, "observed" if t < now - model.LIVE_WINDOW else "live"

    def closure_events(self, t0, t1):
        return []

    def predictions(self, sids, t0, t1):
        return None

    def trips_to(self, lon, lat, t0, t1):
        return 3

    def save_trip(self, doc):
        self.trips.append(doc)
        return True

    def mark_arrived(self, trip_id, at):
        hit = [t for t in self.trips if t["trip_id"] == trip_id and t["arrived_at"] is None]
        for t in hit:
            t["arrived_at"] = at
        return len(hit)

    def status(self):
        return {"mongo": "not configured", "tiger": "not configured"}


class PlanEndpoint(unittest.TestCase):
    def setUp(self):
        main._cache.clear()
        self.load = mock.patch.object(main.segments, "load")
        self.load.start()
        self.env = mock.patch.dict("os.environ", {"GEMINI_API_KEY": ""})  # never call the real Gemini from tests
        self.env.start()
        self.client = TestClient(main.app).__enter__()
        main.segments.graph = None  # no road graph: routes keep the fake segment IDs, lengths are unknown

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.load.stop()
        self.env.stop()

    def plan(self, store, depart, **extra):
        self.find = mock.AsyncMock(return_value=([dict(PAST), dict(AROUND)], "mapbox"))
        with mock.patch.object(providers, "find_routes", self.find), mock.patch.object(main, "store", store), \
                mock.patch.object(main.segments, "match", return_value=PAST["road_segment_ids"]):
            return self.client.get("/plan", params={"from": "-122.4075,37.788", "to": "-122.3893,37.7786",
                                                    "depart_at": depart.isoformat(), **extra})

    def test_replay_plans_a_past_trip_with_that_days_data(self):
        depart = (datetime.now(SF) - timedelta(days=3)).replace(hour=18, minute=30, second=0, microsecond=0)
        self.assertEqual(self.plan(FakeStore(), depart).status_code, 400)  # the past needs replay
        store = FakeStore(traffic=[])
        body = self.plan(store, depart, replay="true").json()
        self.assertEqual((body["data"]["traffic"], body["data"]["replay"]), ("tiger:observed", True))
        self.assertEqual(datetime.fromisoformat(body["data"]["at"]), depart)
        self.assertEqual(store.traffic_asked[0], depart)  # Tiger is asked about that day, not now
        self.assertEqual(store.trips, [])                 # a simulation isn't logged as demand
        mapbox_at = datetime.strptime(self.find.call_args.args[3], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        self.assertEqual(mapbox_at.astimezone(SF).strftime("%a %H:%M"), depart.strftime("%a %H:%M"))  # same slot,
        self.assertGreater(mapbox_at, datetime.now(timezone.utc))                                     # next week

    def test_demo_events_without_a_database_and_trip_is_logged(self):
        store = FakeStore()
        depart = (datetime.now(SF) + timedelta(hours=1)).replace(second=0, microsecond=0)
        r = self.plan(store, depart)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["data"]["events"], "demo")
        self.assertEqual(len(body["plan"]["preds"]), 2)
        [trip] = store.trips
        self.assertEqual((trip["origin"], trip["mode"], trip["provider"]), ({"lon": -122.407, "lat": 37.788}, "depart", "mapbox"))
        self.assertNotIn("user", trip)
        self.assertEqual(trip["road_segment_ids"], PAST["road_segment_ids"][3:-3])  # the route, minus its ends
        self.assertEqual((body["data"]["trip_record"]["trip_id"], trip["arrived_at"]), (trip["trip_id"], None))
        with mock.patch.object(main, "store", store):
            arrived = lambda tid: self.client.post(f"/trips/{tid}/arrived").status_code  # noqa: E731
            self.assertEqual([arrived(trip["trip_id"]), arrived(trip["trip_id"]), arrived("nope")], [200, 404, 422])
        self.assertIsNotNone(trip["arrived_at"])

    def test_demand_counts_only_riders_still_on_the_way(self):
        s, seen = store_mod.Store(), []
        s._mongo_call = lambda fn: seen.append(fn)
        s.trips_to(-122.39, 37.78, at(18), at(19))

        class DB:
            class trips:
                @staticmethod
                def count_documents(q):
                    DB.q = q
        seen[0](DB)
        self.assertIsNone(DB.q["arrived_at"])

    def test_mongo_events_and_closures_flow_into_the_plan(self):
        depart = (datetime.now(SF) + timedelta(hours=2)).replace(second=0, microsecond=0)
        ev = {"_id": "evt_1", "title": "Big Game", "category": "sports", "start_time": depart + timedelta(minutes=45),
              "end_time": depart + timedelta(hours=3), "location": {"coordinates": [-122.3893, 37.7786]}, "attendance": 40000}
        closure = {"source": "street_closures", "category": "street_closure", "is_closure": True,
                   "road_segment_ids": PAST["road_segment_ids"][:1], "start_time": depart - timedelta(hours=1),
                   "end_time": depart + timedelta(hours=5), "details": {"name": "Parade"}}
        body = self.plan(FakeStore(events=[ev], incidents=[closure], traffic=[]), depart).json()
        self.assertEqual((body["data"]["events"], body["data"]["incidents"]), ("mongo", "mongo"))
        self.assertEqual(body["plan"]["tag"], "Closure ahead")  # the fake routes share segment IDs, so both are closed
        self.assertTrue(all(p["blocked"] for p in body["plan"]["preds"]))
        self.assertEqual([e["title"] for e in body["events"]], ["Big Game"])

    def test_up_to_30_days_ahead_mapbox_gets_the_same_slot_this_week(self):
        depart = (datetime.now(SF) + timedelta(days=24)).replace(hour=18, minute=0, second=0, microsecond=0)
        store = FakeStore()
        body = self.plan(store, depart).json()
        self.assertEqual(datetime.fromisoformat(body["data"]["at"]), depart)  # the databases are asked about that day
        mapbox_at = datetime.strptime(self.find.call_args.args[3], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        self.assertEqual(mapbox_at.astimezone(SF).strftime("%a %H:%M"), depart.strftime("%a %H:%M"))
        self.assertLessEqual(mapbox_at, datetime.now(timezone.utc) + main.MAPBOX_AHEAD)
        self.assertEqual(store.traffic_asked[0], depart)
        self.assertEqual(self.plan(FakeStore(), depart + timedelta(days=7)).status_code, 400)  # 31 days: too far

    def test_gemini_words_both_cards_from_the_facts_only(self):
        depart = at(12) + timedelta(days=(datetime.now(SF).date() - DAY.date()).days + 1)  # noon tomorrow: no crowds
        body = self.plan(FakeStore(), depart).json()
        self.assertEqual(body["data"]["note"], "template (no GEMINI_API_KEY)")
        # PAST (10 min) is the pick; AROUND (11 min) the other route: the template claims just that minute
        self.assertEqual(body["plan"]["note"], "1 min faster than the next best route.")
        sent = []

        def run(write, pick=lambda rec: f"{rec['minutes_faster']} min faster than the next best route."):
            def handler(req: httpx.Request):
                sent.append(req)
                trip = json.loads(json.loads(req.content)["contents"][0]["parts"][0]["text"])
                return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(
                    {"recommended": pick(trip["recommended_route"]), "routes": [write(r) for r in trip["routes"]]})}]}}]})
            advice._cache.clear()
            with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "k"}), \
                    mock.patch.dict(main.state, {"http": httpx.AsyncClient(transport=httpx.MockTransport(handler))}):
                return self.plan(FakeStore(), depart).json()

        good = lambda r: f"{r['minutes_slower']} min slower: a longer way round." if "minutes_slower" in r \
            else "Nothing slowing it."  # noqa: E731
        body = run(good, lambda rec: "1 min faster than the next best route, and nothing on the way")
        self.assertEqual([p["note"] for p in body["plan"]["preds"]], ["Nothing slowing it.", "1 min slower: a longer way round."])
        self.assertEqual(body["plan"]["note"], "1 min faster than the next best route, and nothing on the way.")  # tidied
        self.assertEqual(body["data"]["note"], "gemini:gemini-3.5-flash-lite")
        self.assertEqual(sent[0].headers["x-goog-api-key"], "k")
        facts = json.loads(json.loads(sent[0].content)["contents"][0]["parts"][0]["text"])
        self.assertEqual((facts["recommended_route"]["minutes_faster"], facts["recommended_route"]["avoids_on_other_routes"]),
                         (1, []))
        self.assertNotIn("37.7", sent[0].content.decode())  # facts only: no coordinates leave the api
        for made_up in (lambda r: "Saves 987 min by taking the ferry.", lambda r: "Saves eleven minutes.",
                        lambda r: "Slow. " * 45,
                        lambda r: "11 min slower: a longer way round.",  # a number in the facts, but not the delay
                        lambda r: "1 min slower." if "minutes_slower" not in r else good(r)):  # not slower at all
            with self.assertLogs("app.advice", "WARNING"):  # a rejected note is logged, not only in data.note
                body = run(made_up)
            self.assertEqual(body["plan"]["note"], "1 min faster than the next best route.")  # the pick's still Gemini's
            notes = [p["note"] for p in body["plan"]["preds"]]
            self.assertIn(notes[1], ("1 min slower: longer or busier roads.", "1 min slower: a longer way round."))
            self.assertNotEqual(notes, [made_up(r) for r in ({}, {"minutes_slower": 1})])  # each wrong one: template
        for wrong in ("Avoids the Giants crowd.",  # nothing to avoid on the other route
                      "5 min faster than the next best route."):  # not the minutes the facts give
            with self.assertLogs("app.advice", "WARNING"):
                body = run(good, lambda rec: wrong)
            self.assertEqual(body["plan"]["note"], "1 min faster than the next best route.")  # the template
            self.assertEqual(body["plan"]["preds"][1]["note"], "1 min slower: a longer way round.")  # notes still Gemini's

    def test_ml_reasons_stay_on_the_pick_and_gemini_only_words_the_normal_routes(self):
        depart = at(12) + timedelta(days=(datetime.now(SF).date() - DAY.date()).days + 1)
        sent = []

        def handler(req: httpx.Request):
            if "generativelanguage" not in str(req.url):
                return httpx.Response(200, json={"model": "m1", "choice": {"candidate": 1}, "predicted_sec": 700,
                                                 "reasons": ["Fewer riders here."]})
            sent.append(json.loads(json.loads(req.content)["contents"][0]["parts"][0]["text"]))
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(
                {"recommended": "Avoids nothing.", "routes": ["No events or closures on it."] * len(sent[-1]["routes"])})}]}}]})
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "k", "ML_URL": "http://ml.test/"}), \
                mock.patch.dict(main.state, {"http": httpx.AsyncClient(transport=httpx.MockTransport(handler))}):
            body = self.plan(FakeStore(), depart).json()
        self.assertEqual(body["plan"]["note"], "Fewer riders here.")
        self.assertNotIn("recommended_route", sent[0])

    def test_gemini_note_must_name_the_routes_worst_event_and_its_own_delay(self):
        route = {"events_on_it": [{"name": "Giants vs. Dodgers at Oracle Park", "when": "7:15 PM to 10:15 PM",
                                   "crowd_when_you_pass": "arriving", "adds_about_min": 10, "passes_within_m": 150}],
                 "closures_and_incidents_on_it": [{"name": "Road closure on King St", "until": "11:00 PM"}],
                 "crosses_a_closure": False, "slow_stretches": 3, "minutes_slower": 7}
        ok = ("7 min slower: Giants game, 3 slow stretches.", "7 minutes slower: Giants crowd until 10:15 PM.",
              "7 min slower: the Giants crowd will be arriving, 150 m off the route, adding about 10 min.")
        bad = ("7 min slower: Bay to Breakers race.",  # an event it made up
               "7 min slower: road closure on King St.",  # a real one, but not the worst
               "15 min slower: Giants game.",  # a number from the facts (10:15), not the delay
               "10 min slower: Giants game, adding about 7 min.",  # the two minutes swapped
               "7 min slower: Giants game, adding about 15 min.",  # an event delay that isn't there
               "7 min slower: Giants game ends 9 PM.")  # a time that isn't there
        self.assertEqual([advice.check(t, route) for t in ok], list(ok))
        self.assertEqual([advice.check(t, route) for t in bad], [None] * len(bad))
        clear = {"events_on_it": [], "closures_and_incidents_on_it": [], "crosses_a_closure": False, "slow_stretches": 0}
        self.assertEqual(advice.check("No events or closures on it.", clear), "No events or closures on it.")
        self.assertIsNone(advice.check("It is a busier way.", clear))  # not slower: Gemini once said this every time
        self.assertIsNone(advice.check("6 slow stretches on 4th St. Traffic flowing.", {**clear, "slow_stretches": 6}))
        self.assertIsNone(advice.check("No events or closures, traffic flowing.", clear))  # no traffic data: unknown
        self.assertIsNotNone(advice.check("No events or closures, traffic flowing.", {**clear, "have_traffic_data": True}))
        closed = {**route, "crosses_a_closure": True}
        self.assertEqual(advice.check("Crosses a road closure when you'd get there.", closed),
                         "Crosses a road closure when you'd get there.")

    def test_pick_note_claims_minutes_only_against_open_routes(self):
        est = lambda m, **kw: {"estimate": {"dur": m * 60, "why": kw.get("why", [])}, "blocked": kw.get("blocked", False),  # noqa: E731
                               "traffic": {"slow_segments": 0, "coverage": 1.0}}
        routes = [{}, {}, {}]
        f = model.pick_facts(routes, [est(10), est(32, blocked=True), est(13)], 0)  # 32 = 12 + the closure penalty
        self.assertEqual((f["minutes_faster"], f["avoids_a_closure"]), (3, True))
        self.assertEqual(model.pick_note(f), "3 min faster than the next best route. Avoids a road closure on another route.")
        f = model.pick_facts(routes[:2], [est(10), est(32, blocked=True)], 0)  # the only other route is closed
        self.assertEqual(model.pick_note(f), "Avoids a road closure on another route.")

    def test_gemini_pick_must_back_every_claim_with_the_facts(self):
        rec = {"events_on_it": [], "closures_and_incidents_on_it": [], "crosses_a_closure": False, "slow_stretches": 2,
               "avoids_a_closure_on_another_route": False, "minutes_faster": 4,
               "avoids_on_other_routes": ["Giants vs. Dodgers at Oracle Park", "Concert at Chase Center"]}
        self.assertEqual(advice.check_pick("4 min faster than the next best route. Avoids the Giants game crowd.", rec),
                         "4 min faster than the next best route. Avoids the Giants game crowd.")
        for bad in ("6 min faster than the next best route.",  # made-up minutes
                    "4 min faster. Avoids the Chase Center concert.",  # avoids the second, not the worst
                    "Fastest way, avoids the Bay to Breakers."):  # an event it made up
            self.assertIsNone(advice.check_pick(bad, rec), bad)
        plain = {**rec, "minutes_faster": None, "avoids_on_other_routes": []}
        self.assertIsNone(advice.check_pick("Quicker than the others.", plain))  # no minutes: no faster claim
        self.assertIsNone(advice.check_pick("Avoids the traffic.", plain))  # nothing to avoid
        self.assertEqual(advice.check_pick("2 slow stretches on the way", plain), "2 slow stretches on the way.")
        closure = {**plain, "avoids_a_closure_on_another_route": True}
        self.assertIsNotNone(advice.check_pick("Avoids a road closure on another route.", closure))

    def test_gemini_reply_that_is_not_an_object_is_rejected(self):
        for reply in ({"notes": "x", "more": "y"}, "ab", {"routes": ["Nothing slowing it."]}):  # no routes, a string, one too few
            advice._cache.clear()
            client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={
                "candidates": [{"content": {"parts": [{"text": json.dumps(reply)}]}}]})))
            with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "k"}), self.assertLogs("app.advice", "WARNING"):
                got = asyncio.run(advice.explain(client, {"routes": [{}, {}]}))
            self.assertEqual(got, (None, None, "template (gemini reply rejected)"))

    def test_rider_can_turn_off_saving_and_ai_text(self):
        depart = (datetime.now(SF) + timedelta(hours=1)).replace(second=0, microsecond=0)
        store = FakeStore()
        data = self.plan(store, depart).json()["data"]
        self.assertEqual(data["stored"], "trips")
        self.assertEqual(data["trip_record"]["origin"], store.trips[0]["origin"])  # the response shows what was logged
        sent = []
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "k"}), \
                mock.patch.dict(main.state, {"http": httpx.AsyncClient(transport=httpx.MockTransport(sent.append))}):
            store = FakeStore()
            data = self.plan(store, depart, save="false", ai_text="false").json()["data"]
        self.assertEqual((store.trips, sent), ([], []))  # nothing logged, nothing sent to Google
        self.assertEqual((data["stored"], data["trip_record"], data["note"]), ("off", None, "template (ai text off)"))

    def ml_plan(self, answer, status=200):
        """/plan with ML_URL set and ml/ answering `answer`; returns (body, what ml/ was sent)."""
        sent = []

        def handler(req: httpx.Request):
            sent.append(req)
            return httpx.Response(status, json=answer)

        depart = (datetime.now(SF) + timedelta(hours=1)).replace(second=0, microsecond=0)
        with mock.patch.dict("os.environ", {"ML_URL": "http://ml.test/"}), \
                mock.patch.dict(main.state, {"http": httpx.AsyncClient(transport=httpx.MockTransport(handler))}):
            r = self.plan(FakeStore(), depart)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json(), sent

    def test_ml_picks_a_candidate_and_explains(self):
        body, sent = self.ml_plan({"model": "congestion-v0", "choice": {"candidate": 1}, "predicted_sec": 700,
                                   "reasons": ["Fewer riders heading there on this street."]})
        self.assertEqual(str(sent[0].url), "http://ml.test/decide")
        req = json.loads(sent[0].content)
        self.assertEqual((req["version"], req["mode"], len(req["candidates"]), req["demand"]["trips_to_destination"]),
                         (1, "depart", 2, 3))
        self.assertEqual(set(req["context"]), {"events", "incidents", "traffic", "predictions", "segment_lengths_m"})
        self.assertIn("heuristic", req["candidates"][0])
        plan = body["plan"]
        self.assertEqual((plan["best"], plan["preds"][1]["dur"], plan["preds"][1]["model"]), (1, 700, "ml:congestion-v0"))
        self.assertTrue(plan["note"].startswith("Fewer riders heading there"))  # ml/'s reasons stay (contract)
        self.assertEqual(body["data"]["decision"], "ml:congestion-v0")

    def test_ml_own_route_becomes_the_transpeaktation_route(self):
        body, _ = self.ml_plan({"model": "m", "choice": {"waypoints": [[-122.40, 37.785], [-122.395, 37.78]]},
                                "predicted_sec": 640})
        self.assertEqual(len(body["routes"]), 3)
        self.assertEqual((body["routes"][2]["by"], body["plan"]["best"]), ("ml", 2))
        self.assertEqual(self.find.call_args.args[5], ((-122.40, 37.785), (-122.395, 37.78)))  # routed through them

    def test_ml_down_or_off_contract_keeps_the_heuristic(self):
        body, _ = self.ml_plan({"detail": "boom"}, status=500)
        self.assertTrue(body["data"]["decision"].startswith("heuristic (ml unavailable"))
        self.assertEqual(len(body["plan"]["preds"]), 2)
        body, _ = self.ml_plan({"model": "m", "choice": {"candidate": 7}, "predicted_sec": 600})
        self.assertIn("choice.candidate", body["data"]["decision"])

    def test_without_ml_url_nothing_is_sent(self):
        depart = (datetime.now(SF) + timedelta(hours=1)).replace(second=0, microsecond=0)
        with mock.patch.dict("os.environ", {"ML_URL": ""}):
            self.assertEqual(self.plan(FakeStore(), depart).json()["data"]["decision"], "heuristic")

    def test_events_endpoint_falls_back_to_demo(self):
        with mock.patch.object(main, "store", FakeStore()):
            body = self.client.get("/events", params={"date": "2026-09-26"}).json()
        self.assertEqual((body["source"], [e["venue"] for e in body["events"]]),
                         ("demo", ["Oracle Park", "Chase Center", "Ferry Building"]))
        self.assertEqual(self.client.get("/events", params={"date": "soon"}).status_code, 400)

    def test_health_reports_databases(self):
        self.assertIn("mongo", self.client.get("/health").json())


if __name__ == "__main__":
    unittest.main()
