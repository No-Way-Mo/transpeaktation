"""Offline checks for the event-aware trip plan: the model (pure) and GET /plan / /events with a fake store."""
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
        self.assertEqual(model.predict_route(PAST, at(18, 30), CTX, now=now)["delay"], 482)  # arrival window: ~8 min
        edge = model.predict_route(PAST, at(17, 25), CTX, now=now)["delay"]                  # passes ~17:30: ramping in
        self.assertTrue(0 < edge < 482, edge)
        self.assertEqual(model.predict_route(AROUND, at(18, 30), CTX, now=now)["delay"], 0)  # ~1 km away
        self.assertGreater(model.predict_route(PAST, at(22, 20), CTX, now=now)["delay"], 0)  # crowd leaving

    def test_size_and_type_scale_the_delay(self):
        small = {**ORACLE, "capacity": 1300, "category": "conference"}
        self.assertEqual(round(model.event_max_delay_s(ORACLE)), 482)
        self.assertEqual(round(model.event_max_delay_s(small)), 72)  # 2 min floor x 0.6

    def test_without_ml_the_card_is_the_fastest_route_unchanged(self):
        now = at(9)
        p = model.plan([PAST, AROUND], [at(18, 30)] * 2, "depart", CTX, now=now)  # Giants crowd on PAST
        self.assertEqual((p["best"], p["preds"][0]["dur"], p["advice"]), (0, PAST["dur"], None))  # no re-pick/re-time
        est = p["preds"][0]["estimate"]                          # api/'s estimate: shown on the normal route only
        self.assertEqual((round(est["dur"]), est["delay"]), (PAST["dur"] + 482, 482))
        self.assertEqual(est["why"], ["Giants vs. Dodgers at Oracle Park"])
        self.assertEqual(p["tag"], "Events on the way")
        self.assertIn("Giants vs. Dodgers at Oracle Park", p["note"])
        self.assertEqual(model.plan([PAST, AROUND], [at(12)] * 2, "depart", CTX, now=now)["tag"], "Clear")

    def test_special_event_closure_counts_like_any_event(self):
        # shaped like store.find_closure_events (what /events shows): a multi-day event right on the route
        amzn = model.from_map_event({"id": "street_closures:X@2026-09-23T13:00:00+00:00", "name": "AMZN Unboxed",
                                     "category": "special_event", "venue": None, "lat": 37.779, "lon": -122.3893,
                                     "start_time": "2026-09-23T13:00:00+00:00", "end_time": "2026-10-03T01:00:00+00:00",
                                     "source": "street_closures"})
        p = model.plan([PAST], [at(12)], "depart", {**CTX, "events": [amzn]}, now=at(9))
        self.assertNotEqual(p["tag"], "Clear")
        self.assertIn("AMZN Unboxed", p["note"])


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
        self.assertEqual((o["time"], o["start"], o["crowd"]), ("7:15 PM", [19, 15], {"from": [17, 45], "to": [19, 30], "delay": 8}))
        self.assertEqual(o["drop"]["badge"], "Saves ~8 min")
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

    def test_gemini_words_the_note_from_the_facts_only(self):
        depart = (datetime.now(SF) + timedelta(hours=1)).replace(second=0, microsecond=0)
        self.assertEqual(self.plan(FakeStore(), depart).json()["data"]["note"], "template (no GEMINI_API_KEY)")
        sent = []

        def run(reply):
            def handler(req: httpx.Request):
                sent.append(req)
                return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": reply}]}}]})
            advice._cache.clear()
            with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "k"}), \
                    mock.patch.dict(main.state, {"http": httpx.AsyncClient(transport=httpx.MockTransport(handler))}):
                return self.plan(FakeStore(), depart).json()

        body = run("Roads look clear; about 10 min.")
        self.assertEqual((body["plan"]["note"], body["data"]["note"]), ("Roads look clear; about 10 min.", "gemini:gemini-flash-lite-latest"))
        self.assertEqual(sent[0].headers["x-goog-api-key"], "k")
        self.assertNotIn("37.7", sent[0].content.decode())  # facts only: no coordinates leave the api
        for made_up in ("Saves 987 min by taking the ferry.", "Saves eleven minutes."):  # not in the facts
            body = run(made_up)
            self.assertEqual(body["data"]["note"], "template (gemini reply rejected)")
            self.assertNotEqual(body["plan"]["note"], made_up)

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
        self.assertTrue(plan["note"].startswith("Fewer riders heading there"))
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
