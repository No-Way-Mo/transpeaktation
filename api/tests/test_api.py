"""Offline checks: provider normalization, Mapbox→OSRM fallback, input validation, caching, segment matching, voice intent.

    cd api && .venv/bin/python -m unittest discover -s tests -t .
"""
import unittest
from unittest import mock

import httpx
import networkx as nx
from fastapi.testclient import TestClient

from app import main, providers, voice
from app.segments import Segments

MAPBOX_ROUTE = {
    "code": "Ok",
    "routes": [{
        "duration": 420.0, "duration_typical": 360.0, "distance": 2000.0,
        "geometry": {"coordinates": [[-122.41, 37.78], [-122.40, 37.78], [-122.40, 37.79]]},
        "legs": [{
            "summary": "Market Street", "annotation": {"congestion": ["heavy", "low"]},
            "steps": [{"distance": 900, "duration": 200, "name": "Market Street",
                       "maneuver": {"type": "depart", "modifier": "right", "location": [-122.41, 37.78], "bearing_after": 90}}],
        }],
    }],
}


class Normalize(unittest.TestCase):
    def test_mapbox_route_keeps_traffic_fields_and_flips_to_lat_lon(self):
        r = providers.normalize_routes(MAPBOX_ROUTE)[0]
        self.assertEqual(r["coords"][0], [37.78, -122.41])
        self.assertEqual((r["dur"], r["dur_typical"], r["summary"]), (420.0, 360.0, "Market Street"))
        self.assertEqual(r["congestion"], ["heavy", "low"])
        self.assertEqual(r["steps"][0]["maneuver"], {"type": "depart", "modifier": "right", "location": [-122.41, 37.78]})

    def test_osrm_route_has_no_traffic_fields(self):
        osrm = {"code": "Ok", "routes": [{**MAPBOX_ROUTE["routes"][0], "legs": [{"summary": "", "steps": []}]}]}
        del osrm["routes"][0]["duration_typical"]
        r = providers.normalize_routes(osrm)[0]
        self.assertIsNone(r["dur_typical"])
        self.assertIsNone(r["congestion"])

    def test_route_through_via_points_is_one_trip(self):
        step = lambda t, name: {"distance": 1, "duration": 1, "name": name, "maneuver": {"type": t, "location": [0, 0]}}  # noqa: E731
        leg = lambda a, b, c: {"summary": a, "annotation": {"congestion": c},  # noqa: E731
                                "steps": [step("depart", a), step("turn", b), step("arrive", b)]}
        data = {"code": "Ok", "routes": [{**MAPBOX_ROUTE["routes"][0],
                                          "legs": [leg("Post", "4th", ["low"]), leg("4th", "King", ["heavy"])]}]}
        r = providers.normalize_routes(data)[0]
        self.assertEqual([(s["maneuver"]["type"], s["name"]) for s in r["steps"]],
                         [("depart", "Post"), ("turn", "4th"), ("turn", "King"), ("arrive", "King")])
        self.assertEqual(r["congestion"], ["low", "heavy"])

    def test_no_route_is_its_own_error(self):
        with self.assertRaises(providers.NoRoute):
            providers.normalize_routes({"code": "NoRoute", "routes": []})

    def test_places(self):
        mb = {"features": [{"properties": {"name": "Oracle Park", "place_formatted": "San Francisco, CA"},
                            "geometry": {"coordinates": [-122.389, 37.778]}}]}
        self.assertEqual(providers.mapbox_places(mb), [{"label": "Oracle Park", "sub": "San Francisco, CA", "lat": 37.778, "lon": -122.389}])
        nom = [{"name": "", "display_name": "Ferry Building, 1, The Embarcadero, SF, CA", "lat": "37.7955", "lon": "-122.3937"}]
        self.assertEqual(providers.nominatim_places(nom)[0]["label"], "Ferry Building")


class Fallback(unittest.IsolatedAsyncioTestCase):
    async def test_mapbox_quota_falls_back_to_osrm_and_backs_off(self):
        calls = []

        def handler(req: httpx.Request):
            calls.append(req.url.host)
            if req.url.host == "api.mapbox.com":
                return httpx.Response(429, json={"message": "rate limited"})
            return httpx.Response(200, json=MAPBOX_ROUTE)

        providers._mapbox_off_until = 0.0
        with mock.patch.dict("os.environ", {"MAPBOX_TOKEN": "pk.test"}):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
                _, source = await providers.find_routes(c, (-122.41, 37.78), (-122.40, 37.79))
                self.assertEqual(source, "osrm")
                _, source = await providers.find_routes(c, (-122.41, 37.78), (-122.40, 37.79))
        self.assertEqual(calls, ["api.mapbox.com", "router.project-osrm.org", "router.project-osrm.org"])  # no 2nd Mapbox hit
        providers._mapbox_off_until = 0.0

    async def test_depart_at_keeps_traffic_profile_arrive_by_switches_to_driving(self):
        seen = []

        def handler(req: httpx.Request):
            seen.append((req.url.path.split("/")[4], dict(req.url.params)))
            return httpx.Response(200, json=MAPBOX_ROUTE)

        providers._mapbox_off_until = 0.0
        with mock.patch.dict("os.environ", {"MAPBOX_TOKEN": "pk.test"}):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
                await providers.find_routes(c, (-122.41, 37.78), (-122.40, 37.79), depart_at="2026-09-27T02:00:00Z")
                await providers.find_routes(c, (-122.41, 37.78), (-122.40, 37.79), arrive_by="2026-09-27T02:00:00Z")
        (p1, q1), (p2, q2) = seen
        self.assertEqual((p1, q1["depart_at"], q1["annotations"]), ("driving-traffic", "2026-09-27T02:00:00Z", "congestion"))
        self.assertEqual((p2, q2["arrive_by"]), ("driving", "2026-09-27T02:00:00Z"))
        self.assertNotIn("annotations", q2)  # congestion is driving-traffic only


class Api(unittest.TestCase):
    def setUp(self):
        main._cache.clear()
        self.load = mock.patch.object(main.segments, "load")  # don't download SF during tests
        self.load.start()
        self.client = TestClient(main.app).__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.load.stop()

    def test_rejects_bad_or_out_of_area_coordinates(self):
        for bad in ("abc", "1,2,3", "nan,nan", "-73.98,40.75"):  # last one is Manhattan
            self.assertEqual(self.client.get("/routes", params={"from": bad, "to": "-122.39,37.77"}).status_code, 400, bad)
        self.assertEqual(self.client.get("/places", params={"q": "x" * 121}).status_code, 422)

    def test_routes_are_cached_and_carry_source(self):
        fake = mock.AsyncMock(return_value=(providers.normalize_routes(MAPBOX_ROUTE), "mapbox"))
        with mock.patch.object(providers, "find_routes", fake):
            for _ in range(2):
                body = self.client.get("/routes", params={"from": "-122.41,37.78", "to": "-122.40,37.79"}).json()
        self.assertEqual(fake.await_count, 1)
        self.assertEqual(body["source"], "mapbox")
        self.assertIn("road_segment_ids", body["routes"][0])

    def test_time_is_validated_and_sent_as_utc(self):
        from datetime import datetime, timedelta, timezone
        soon = (datetime.now(timezone.utc) + timedelta(hours=2)).astimezone(timezone(timedelta(hours=-7)))
        fake = mock.AsyncMock(return_value=(providers.normalize_routes(MAPBOX_ROUTE), "mapbox"))
        ab = {"from": "-122.41,37.78", "to": "-122.40,37.79"}
        with mock.patch.object(providers, "find_routes", fake):
            self.assertEqual(self.client.get("/routes", params={**ab, "depart_at": soon.isoformat()}).status_code, 200)
            for bad in ({"depart_at": "tonight"}, {"depart_at": "2026-09-26T19:00"},             # no offset
                        {"depart_at": "2020-01-01T00:00:00Z"}, {"arrive_by": "2099-01-01T00:00:00Z"},
                        {"depart_at": soon.isoformat(), "arrive_by": soon.isoformat()}):
                self.assertEqual(self.client.get("/routes", params={**ab, **bad}).status_code, 400, bad)
        dep = fake.await_args.args[3]
        self.assertEqual(dep, soon.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def test_no_route_is_404(self):
        with mock.patch.object(providers, "find_routes", mock.AsyncMock(side_effect=providers.NoRoute())):
            self.assertEqual(self.client.get("/routes", params={"from": "-122.41,37.78", "to": "-122.40,37.79"}).status_code, 404)


class VoiceIntent(unittest.TestCase):
    def test_parses_trip_requests(self):
        cases = {
            "Plan and book my ride to Chase Center at 6:30": ("plan_and_book", "Chase Center", None, "6:30", "depart"),
            "I want to go to Oracle Park.": ("plan", "Oracle Park", None, None, None),
            "Take me from the Ferry Building to Oracle Park by 7 pm please": ("plan", "Oracle Park", "Ferry Building", "7 pm", "arrive"),
            "Navigate to the Chase Center from here": ("plan", "Chase Center", None, None, None),
            "What's the weather like?": ("unknown", None, None, None, None),
        }
        for text, want in cases.items():
            got = voice.parse_intent(text)
            self.assertEqual((got["action"], got["destination"], got["origin"], got["time"], got["time_mode"]), want, text)


class VoiceEndpoint(unittest.TestCase):
    def setUp(self):
        main._cache.clear()
        self.load = mock.patch.object(main.segments, "load")
        self.load.start()
        self.client = TestClient(main.app).__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.load.stop()

    def post(self, audio=b"RIFF....WAVE"):
        return self.client.post("/voice", files={"audio": ("clip.wav", audio, "audio/wav")})

    def test_transcribes_parses_and_resolves_the_destination(self):
        chase = {"label": "Chase Center", "sub": "1 Warriors Way", "lat": 37.768, "lon": -122.3877}
        stt = mock.AsyncMock(return_value="Plan and book my ride to Chase Center at 6:30")
        search = mock.AsyncMock(return_value=([chase], "mapbox"))
        with mock.patch.dict("os.environ", {"ELEVENLABS_API_KEY": "sk_test"}), \
                mock.patch.object(voice, "transcribe", stt), mock.patch.object(providers, "search_places", search):
            body = self.post().json()
        self.assertEqual(body["action"], "plan_and_book")
        self.assertEqual(body["destination"], {"query": "Chase Center", "place": chase})
        self.assertIsNone(body["origin"])
        self.assertEqual(stt.await_args.args[1], b"RIFF....WAVE")

    def test_errors(self):
        with mock.patch.dict("os.environ", {"ELEVENLABS_API_KEY": ""}):
            self.assertEqual(self.post().status_code, 503)
        with mock.patch.dict("os.environ", {"ELEVENLABS_API_KEY": "sk_test"}):
            self.assertEqual(self.post(b"").status_code, 400)
            self.assertEqual(self.post(b"x" * (voice.MAX_AUDIO_BYTES + 1)).status_code, 413)
            with mock.patch.object(voice, "transcribe", mock.AsyncMock(side_effect=providers.ProviderError())):
                self.assertEqual(self.post().status_code, 502)


class Transcribe(unittest.IsolatedAsyncioTestCase):
    async def test_sends_key_model_and_file(self):
        seen = {}

        def handler(req: httpx.Request):
            seen["key"], seen["body"] = req.headers["xi-api-key"], req.content
            return httpx.Response(200, json={"text": " Take me to Oracle Park. "})

        with mock.patch.dict("os.environ", {"ELEVENLABS_API_KEY": "sk_test"}):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
                text = await voice.transcribe(c, b"AUDIO", "clip.webm", "audio/webm")
        self.assertEqual(text, "Take me to Oracle Park.")
        self.assertEqual(seen["key"], "sk_test")
        self.assertIn(b"scribe_v1", seen["body"])
        self.assertIn(b"AUDIO", seen["body"])


class SegmentMatching(unittest.TestCase):
    """Tiny grid: A <-> B (two-way), B -> C (one-way north)."""

    def setUp(self):
        g = nx.MultiDiGraph(crs="epsg:4326")
        g.add_node("A", x=-122.41, y=37.78)
        g.add_node("B", x=-122.40, y=37.78)
        g.add_node("C", x=-122.40, y=37.79)
        for u, v in (("A", "B"), ("B", "A"), ("B", "C")):
            g.add_edge(u, v, key=0)
        self.s = Segments()
        self.s.use(g)

    def test_follows_driving_direction(self):
        east_then_north = [[37.78, -122.41], [37.78, -122.405], [37.78, -122.40], [37.785, -122.40], [37.79, -122.40]]
        self.assertEqual(self.s.match(east_then_north), ["A-B-0", "B-C-0"])
        self.assertEqual(self.s.match([[37.78, -122.40], [37.78, -122.41]]), ["B-A-0"])  # westbound picks B->A

    def test_no_graph_means_no_ids(self):
        self.assertIsNone(Segments().match([[37.78, -122.41], [37.78, -122.40]]))


if __name__ == "__main__":
    unittest.main()
