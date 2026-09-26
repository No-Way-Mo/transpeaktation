import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from worker import dedupe, geocode
from worker.pipeline import Pipeline, load_snapshot, load_timeseries, open_writers, select
from worker.records import Record, dumps
from worker.storage import MONGO, TIGER, destination, mongo_doc, tiger_row
from worker.writers import WriteResult

from tests import worker_fixtures as fx

NOW = datetime(2026, 9, 26, 1, tzinfo=timezone.utc)
ALL = list(fx.rows()) + ["sf511_traffic_events", "sf511_muni_vehicles", "mapbox_corridors"]


class FakeMongo:
    def __init__(self):
        self.calls = []

    def write(self, collection, items, now):
        items = list(items)
        self.calls.append((collection, items))
        return WriteResult(written=len(items))


class FakeTiger:
    def __init__(self):
        self.calls = []

    def write(self, table, rows):
        rows = list(rows)
        self.calls.append((table, rows))
        return WriteResult(written=len(rows))


class FakeGeocoder:
    name = "fake"

    def __init__(self, answer=(-122.41, 37.78)):
        self.queries = []
        self.answer = answer

    def geocode(self, q):
        self.queries.append(q)
        return self.answer


class PipelineCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.raw = fx.write_raw_dir(self.root / "raw")
        self.ts = fx.write_timeseries(self.root / "ts")
        self.out = self.root / "out"

    def tearDown(self):
        self.tmp.cleanup()

    def run_pipeline(self, names=ALL, **kw):
        kw.setdefault("dry_run", True)
        kw.setdefault("timeseries_dirs", {"mapbox_corridors": self.ts})
        return Pipeline(self.raw, out_dir=self.out, now=NOW, **kw).run(names)

    def written(self, fake):
        out = {}
        for target, items in fake.calls:
            out.setdefault(target, []).extend(items)
        return out


class LoadingAndDispatchTests(PipelineCase):
    def test_load_snapshot(self):
        snap = load_snapshot(self.raw, "streets")
        self.assertEqual(len(snap["records"]), 2)
        self.assertIsNone(load_snapshot(self.raw, "nope"))
        (self.raw / "bad.json").write_text('{"records": 5}')
        with self.assertRaises(ValueError):
            load_snapshot(self.raw, "bad")

    def test_load_timeseries(self):
        with open(self.ts / "2026-09-26.jsonl", "a", encoding="utf-8") as f:
            f.write("{truncated\n")
        snap = load_timeseries(self.ts, "mapbox_corridors")
        self.assertEqual(len(snap["records"]), 6)
        self.assertEqual(snap["records"][-1], "{truncated")  # kept for quarantine
        self.assertIsNone(load_timeseries(self.root / "none", "mapbox_corridors"))

    def test_select_mirrors_pull(self):
        self.assertEqual(select(["live"]), ["police_dispatch", "sf511_traffic_events", "sf511_muni_vehicles",
                                            "chp_incidents", "mapbox_corridors"])
        self.assertIn("streets", select([]))
        self.assertEqual(select(["streets", "mapbox_corridors"]), ["streets", "mapbox_corridors"])
        with self.assertRaises(ValueError):
            select(["nope"])

    def test_full_dry_run_stats(self):
        res = self.run_pipeline()
        s = res.stats
        expect = {  # source: (raw, normalized, filtered, rejected, duplicates, unrouted)
            "streets": (2, 2, 0, 0, 0, 2), "speed_limits": (4, 3, 0, 1, 0, 3), "clearance_heights": (1, 1, 0, 0, 0, 1),
            "street_closures": (2, 1, 0, 1, 0, 0), "excavation_permits": (3, 2, 0, 0, 1, 0),
            "parking_signs": (3, 2, 0, 1, 0, 0), "police_dispatch": (4, 3, 0, 1, 0, 0),
            "chp_incidents": (3, 2, 1, 0, 0, 0), "caltrans_lane_closures": (3, 1, 1, 1, 0, 0),
            "osm_drive_graph": (4, 4, 0, 0, 0, 0), "osm_turn_restrictions": (2, 1, 0, 1, 0, 1),
            "mapbox_corridors": (5, 2, 2, 1, 0, 0),
        }
        for name, (raw, n, filt, rej, dup, unrouted) in expect.items():
            st = s[name]
            self.assertEqual((st.status, st.raw, st.normalized, st.filtered, st.rejected, st.duplicates, st.unrouted),
                             ("ok", raw, n, filt, rej, dup, unrouted), name)
        self.assertEqual((s["excavation_permits"].from_cnn, s["excavation_permits"].linked), (2, 2))
        self.assertEqual((s["parking_signs"].from_cnn, s["parking_signs"].linked), (1, 2))
        self.assertEqual((s["street_closures"].linked, s["osm_drive_graph"].linked), (1, 4))
        self.assertEqual(s["clearance_heights"].snapped, 1)
        self.assertEqual((s["police_dispatch"].withheld, s["police_dispatch"].unlocated), (1, 1))
        self.assertEqual(s["police_dispatch"].merged, 1)  # p1 == CHP collision
        self.assertEqual(s["sf511_traffic_events"].status, "unsupported")
        self.assertIn("SF511_API_KEY", s["sf511_traffic_events"].note)
        self.assertIn("no store in the contract", s["streets"].note)
        self.assertEqual(len(res.records), sum(st.normalized for st in s.values()) - 1)
        self.assertEqual(sum(st.stored + st.unrouted for st in s.values()), len(res.records))
        self.assertEqual(res.exit_code, 0)

    def test_links_and_provenance(self):
        recs = {r.id: r for r in self.run_pipeline().records}
        node = recs["excavation_permits:EX1|901"]
        self.assertEqual((node.road_ref["match"], node.location_status, node.geometry["type"]),
                         ("intersection", "from_cnn", "Point"))
        self.assertEqual(node.road_segment_ids, ["1-2-0", "2-1-0", "2-3-0", "3-2-0"])
        self.assertEqual(recs["street_closures:10"].road_segment_ids, ["1-2-0", "2-1-0"])
        self.assertEqual(recs["speed_limits:3"].road_ref["match"], "unknown")  # cnn 300 not in network
        self.assertEqual(recs["clearance_heights:1"].road_ref["match"], "nearest_segment")
        seg = recs["osm_drive_graph:1-2-0"]
        self.assertEqual((seg.road_ref["cnn"], seg.attributes["speed_limit"]["posted_mph"]), ("100", 25))
        self.assertEqual(recs["osm_drive_graph:2-3-0"].attributes["speed_limit"]["status"], "unposted")
        chp = recs["chp_incidents:260925GG0001"]
        self.assertEqual(chp.also_reported_by, [{"id": "police_dispatch:p1", "source": "police_dispatch",
                                                  "source_id": "p1"}])
        _, doc = mongo_doc(recs["street_closures:10"], NOW)
        self.assertEqual(doc["provenance"]["pulled_at"], datetime(2026, 9, 26, 0, 30, tzinfo=timezone.utc))
        self.assertEqual(recs["street_closures:10"].layer, "planned")


class FailureIsolationTests(PipelineCase):
    def test_malformed_rows_are_quarantined_not_fatal(self):
        snap = json.loads((self.raw / "chp_incidents.json").read_text())
        snap["records"] += ["not a dict", {"log_id": "X", "LogTime": "garbage"}, {"LogTime": "Sep 25 2026  5:00PM"}]
        (self.raw / "chp_incidents.json").write_text(json.dumps(snap))
        res = self.run_pipeline(["chp_incidents"])
        st = res.stats["chp_incidents"]
        self.assertEqual((st.status, st.normalized, st.rejected), ("ok", 2, 3))
        lines = (self.out / "quarantine" / "chp_incidents.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 3)
        q = json.loads(lines[1])
        self.assertEqual((q["source"], q["index"]), ("chp_incidents", 4))
        self.assertIn("ValueError", q["errors"][0])
        self.assertEqual(q["raw"]["log_id"], "X")

    def test_malformed_poll_quarantined(self):
        res = self.run_pipeline(["mapbox_corridors"])
        q = [json.loads(x) for x in (self.out / "quarantine" / "mapbox_corridors.jsonl").read_text().splitlines()]
        self.assertEqual(len(q), 1)
        self.assertIn("segment arrays disagree", q[0]["errors"][0])
        self.assertEqual(res.stats["mapbox_corridors"].normalized, 2)

    def test_unreadable_snapshot_fails_only_that_source(self):
        (self.raw / "police_dispatch.json").write_text("{broken")
        res = self.run_pipeline(["police_dispatch", "chp_incidents"])
        self.assertEqual(res.stats["police_dispatch"].status, "failed")
        self.assertEqual(res.stats["chp_incidents"].normalized, 2)
        self.assertEqual(res.exit_code, 1)

    def test_adapter_crash_on_every_row_is_contained(self):
        with mock.patch.dict("worker.pipeline.NORMALIZERS", {"streets": mock.Mock(side_effect=KeyError("boom"))}):
            res = self.run_pipeline(["streets", "chp_incidents"])
        self.assertEqual((res.stats["streets"].rejected, res.stats["chp_incidents"].normalized), (2, 2))

    def test_missing_snapshot_pull_skip_and_no_polls(self):
        (self.raw / "streets.json").unlink()
        res = self.run_pipeline(["streets", "sf511_muni_vehicles", "mapbox_corridors"],
                                timeseries_dirs={"mapbox_corridors": self.root / "empty"})
        self.assertEqual(res.stats["streets"].status, "missing")
        self.assertIn("python -m pull streets", res.stats["streets"].note)
        self.assertEqual(res.stats["sf511_muni_vehicles"].status, "unsupported")
        self.assertEqual(res.stats["mapbox_corridors"].status, "missing")
        self.assertIn("python -m pull.poll", res.stats["mapbox_corridors"].note)
        self.assertEqual(res.exit_code, 0)

    def test_mapbox_blocked_without_osm_graph(self):
        (self.raw / "osm_drive_graph.graphml").unlink()
        res = self.run_pipeline(["mapbox_corridors", "chp_incidents"])
        self.assertEqual(res.stats["mapbox_corridors"].status, "blocked")
        self.assertIn("road_segment_id", res.stats["mapbox_corridors"].note)
        self.assertEqual(res.stats["chp_incidents"].status, "ok")
        self.assertEqual(res.exit_code, 0)

    def test_stale_quarantine_removed(self):
        qdir = self.out / "quarantine"
        qdir.mkdir(parents=True)
        (qdir / "streets.jsonl").write_text("old\n")
        self.run_pipeline(["streets"])
        self.assertFalse((qdir / "streets.jsonl").exists())


class PersistenceTests(PipelineCase):
    def test_dry_run_never_touches_writers(self):
        mongo, tiger = mock.Mock(), mock.Mock()
        res = self.run_pipeline(mongo=mongo, tiger=tiger, dry_run=True)
        mongo.write.assert_not_called()
        tiger.write.assert_not_called()
        segs = json.loads((self.out / "normalized" / "osm_drive_graph.json").read_text())
        self.assertEqual(segs[0]["_store"], "mongo.road_segments")
        ts = json.loads((self.out / "normalized" / "mapbox_corridors.json").read_text())
        self.assertEqual(ts[0]["_store"], "tiger.traffic_metrics")
        summary = json.loads((self.out / "normalized" / "_run.json").read_text())
        self.assertTrue(summary["dry_run"])
        self.assertEqual(summary["sources"]["streets"]["normalized"], 2)
        self.assertGreater(sum(s.stored for s in res.stats.values()), 0)

    def test_records_routed_per_contract(self):
        mongo, tiger = FakeMongo(), FakeTiger()
        res = self.run_pipeline(mongo=mongo, tiger=tiger, dry_run=False)
        m, t = self.written(mongo), self.written(tiger)
        self.assertEqual(set(m), {"road_segments", "road_incidents"})
        self.assertEqual(set(t), {"traffic_metrics"})
        segs = {f["segment_id"]: d for f, d in m["road_segments"]}
        self.assertEqual(sorted(segs), ["1-2-0", "2-1-0", "2-3-0", "3-2-0"])
        self.assertEqual((segs["1-2-0"]["cnn"], segs["1-2-0"]["speed_limit"]["status"]), ("100", "posted"))
        self.assertEqual(segs["1-2-0"]["geometry"]["type"], "LineString")
        self.assertNotIn("_id", segs["1-2-0"])
        inc = {(f["source"], f["source_id"]): d for f, d in m["road_incidents"]}
        self.assertIn(("parking_signs", "5|100|N"), inc)
        self.assertIn(("chp_incidents", "260925GG0001"), inc)
        self.assertNotIn(("police_dispatch", "p1"), inc)  # merged into CHP
        closure = inc[("street_closures", "10")]
        self.assertEqual((closure["incident_type"], closure["category"], closure["road_segment_ids"]),
                         ("closure", "street_closure", ["1-2-0", "2-1-0"]))
        self.assertEqual((closure["start_time"], closure["end_time"]),
                         (datetime(2026, 9, 26, 10, tzinfo=timezone.utc), datetime(2026, 9, 27, 2, tzinfo=timezone.utc)))
        withheld = inc[("police_dispatch", "p2")]
        self.assertEqual((withheld["location"], withheld["location_status"]), (None, "withheld"))
        rows = t["traffic_metrics"]
        self.assertEqual({r["road_segment_id"] for r in rows}, {"1-2-0", "2-1-0"})
        self.assertEqual(set(rows[0]), {"time", "road_segment_id", "source", "speed_mph", "free_flow_speed_mph",
                                        "travel_time_sec", "congestion_ratio"})
        self.assertEqual(rows[0]["source"], "mapbox")
        self.assertFalse(any(tbl for tbl, _ in mongo.calls if tbl in ("road_rules", "closures", "incidents")))
        self.assertEqual(res.stats["osm_drive_graph"].mongo_new, 4)
        self.assertEqual(res.stats["mapbox_corridors"].tiger_rows, 2)
        self.assertEqual(res.exit_code, 0)
        self.assertFalse((self.out / "normalized").exists())  # no dump unless asked

    def test_joins_not_computed_are_not_overwritten(self):
        (self.raw / "streets.json").unlink()
        (self.raw / "osm_drive_graph.graphml").unlink()
        mongo = FakeMongo()
        self.run_pipeline(["osm_drive_graph", "street_closures"], mongo=mongo, dry_run=False)
        m = self.written(mongo)
        seg = m["road_segments"][0][1]
        self.assertNotIn("cnn", seg)          # no street index this run: don't blank stored cnn
        self.assertNotIn("speed_limit", seg)
        inc = m["road_incidents"][0][1]
        self.assertNotIn("road_segment_ids", inc)  # no OSM graph this run

    def test_rerun_is_idempotent(self):
        runs = []
        for _ in range(2):
            mongo, tiger = FakeMongo(), FakeTiger()
            self.run_pipeline(mongo=mongo, tiger=tiger, dry_run=False)
            runs.append(dumps([mongo.calls, tiger.calls], sort_keys=True))
        self.assertEqual(runs[0], runs[1])
        keys = [json.dumps(f, sort_keys=True) for _, items in mongo.calls for f, _ in items]
        self.assertEqual(len(keys), len(set(keys)))

    def test_missing_mongo_config_skips_store_and_exits_nonzero(self):
        res = self.run_pipeline(["street_closures"], mongo=None, dry_run=False,
                                store_errors={MONGO: "MONGODB_URI is not set in ingest/.env"})
        self.assertEqual(res.exit_code, 1)
        self.assertTrue(any("MONGODB_URI is not set" in n for n in res.notes))
        self.assertEqual(res.stats["street_closures"].mongo_new, 0)

    def test_missing_tiger_config_only_blocks_time_series(self):
        mongo = FakeMongo()
        res = self.run_pipeline(["chp_incidents", "mapbox_corridors"], mongo=mongo, tiger=None, dry_run=False,
                                store_errors={TIGER: "TIGER_DATABASE_URL is not set in ingest/.env"})
        self.assertEqual(res.stats["chp_incidents"].mongo_new, 2)
        self.assertEqual(res.stats["mapbox_corridors"].tiger_rows, 0)
        self.assertTrue(any("TIGER_DATABASE_URL" in n for n in res.notes))
        self.assertEqual(res.exit_code, 1)

    def test_unrouted_sources_need_no_store(self):
        res = self.run_pipeline(["streets", "speed_limits"], mongo=None, tiger=None, dry_run=False)
        self.assertEqual(res.exit_code, 0)
        self.assertEqual(res.stats["streets"].unrouted, 2)

    def test_write_errors_are_counted(self):
        mongo = mock.Mock()
        mongo.write.return_value = WriteResult(written=1, errors=["road_incidents x: bad geo"])
        res = self.run_pipeline(["street_closures"], mongo=mongo, dry_run=False)
        self.assertEqual(res.stats["street_closures"].write_errors, 1)
        self.assertEqual(res.exit_code, 1)

    def test_open_writers_without_env(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            mongo, tiger, errors = open_writers(dry_run=False)
        self.assertIsNone(mongo)
        self.assertIsNone(tiger)
        self.assertIn("MONGODB_URI", errors[MONGO])
        self.assertIn("TIGER_DATABASE_URL", errors[TIGER])
        self.assertEqual(open_writers(dry_run=True), (None, None, {}))

    def test_placeholder_uri_is_treated_as_missing(self):
        env = {"MONGODB_URI": "mongodb+srv://app:<password>@x.mongodb.net/transpeaktation"}
        with mock.patch.dict(os.environ, env, clear=True):
            _, _, errors = open_writers(dry_run=False)
        self.assertIn("placeholder", errors[MONGO])


class StorageTests(unittest.TestCase):
    def test_destination_by_kind_and_source(self):
        mk = lambda kind, source="s": Record(kind=kind, source=source, source_id="1")  # noqa: E731
        self.assertEqual(destination(mk("road_segment", "osm_drive_graph")), (MONGO, "road_segments"))
        self.assertIsNone(destination(mk("road_segment", "streets")))  # segment_id is the OSM edge
        self.assertIsNone(destination(mk("road_rule", "speed_limits")))  # embedded in road_segments
        self.assertEqual(destination(mk("closure")), (MONGO, "road_incidents"))
        self.assertEqual(destination(mk("incident")), (MONGO, "road_incidents"))
        self.assertEqual(destination(mk("traffic_metric")), (TIGER, "traffic_metrics"))
        self.assertIsNone(destination(mk("event")))

    def test_tiger_row(self):
        r = Record(kind="traffic_metric", source="mapbox_corridors", source_id="t|1-2-0", observed_at=NOW,
                   attributes={"road_segment_id": "1-2-0", "tiger_source": "mapbox", "speed_mph": 9.9,
                               "travel_time_sec": 20.0, "free_flow_speed_mph": None, "congestion_ratio": None,
                               "corridor": "market"})
        self.assertEqual(tiger_row(r), {"time": NOW, "road_segment_id": "1-2-0", "source": "mapbox",
                                        "speed_mph": 9.9, "free_flow_speed_mph": None, "travel_time_sec": 20.0,
                                        "congestion_ratio": None})

    def test_serialization(self):
        r = Record(kind="incident", source="s", source_id="1", observed_at=NOW, valid_from=NOW,
                   location_status="withheld")
        f, doc = mongo_doc(r, NOW)
        out = json.loads(dumps(doc))
        self.assertEqual(f, {"source": "s", "source_id": "1"})
        self.assertEqual((out["start_time"], out["reported_at"], out["last_ingested_at"]),
                         ("2026-09-26T01:00:00Z", "2026-09-26T01:00:00Z", "2026-09-26T01:00:00Z"))


def _inc(source, sid, lon, lat, minutes=0, cat="collision"):
    return Record(kind="incident", source=source, source_id=sid, observed_at=NOW + timedelta(minutes=minutes),
                  geometry={"type": "Point", "coordinates": [lon, lat]}, attributes={"category": cat})


class DedupeTests(unittest.TestCase):
    def test_within_source_keeps_first(self):
        a, b = _inc("chp_incidents", "1", -122.4, 37.7), _inc("chp_incidents", "1", -122.5, 37.7)
        kept, dupes = dedupe.within_source([a, b])
        self.assertEqual((kept, dupes), ([a], 1))

    def test_cross_source_merges_only_when_everything_agrees(self):
        cases = {
            "match": (_inc("police_dispatch", "p", -122.4191, 37.7751, 10), 1),
            "too far": (_inc("police_dispatch", "p", -122.4300, 37.7750, 10), 0),
            "too late": (_inc("police_dispatch", "p", -122.4191, 37.7751, 45), 0),
            "other category": (_inc("police_dispatch", "p", -122.4191, 37.7751, 10, "hazard"), 0),
            "uncategorized": (_inc("police_dispatch", "p", -122.4191, 37.7751, 10, "other"), 0),
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
        def closure(source, sid, text, start_h, end_h):
            return Record(kind="closure", source=source, source_id=sid,
                          geometry={"type": "Point", "coordinates": [-122.40, 37.73]},
                          valid_from=NOW + timedelta(hours=start_h), valid_to=NOW + timedelta(hours=end_h),
                          attributes={"location_text": text})
        city = lambda t, s=0, e=4: closure("street_closures", "s", t, s, e)  # noqa: E731
        state = lambda: closure("caltrans_lane_closures", "c", "Alemany Blvd", 1, 3)  # noqa: E731
        self.assertEqual(dedupe.cross_source([city("ALEMANY BLVD"), state()])[1], 1)
        self.assertEqual(dedupe.cross_source([city("MISSION ST"), state()])[1], 0)
        self.assertEqual(dedupe.cross_source([city("ALEMANY BLVD", 5, 6), state()])[1], 0)
        permit = closure("street_use_permits", "p", "Alemany Blvd", 1, 3)  # permits never merge
        self.assertEqual(dedupe.cross_source([permit, state()])[1], 0)

    def test_traffic_metrics_never_cross_merge(self):
        a = Record(kind="traffic_metric", source="mapbox_corridors", source_id="t|1", observed_at=NOW,
                   geometry={"type": "Point", "coordinates": [-122.4, 37.7]})
        b = Record(kind="traffic_metric", source="other", source_id="t|1", observed_at=NOW,
                   geometry={"type": "Point", "coordinates": [-122.4, 37.7]})
        self.assertEqual(dedupe.cross_source([a, b])[1], 0)


class GeocodingTests(PipelineCase):
    def test_only_unlocated_records_are_geocoded(self):
        g = FakeGeocoder()
        res = self.run_pipeline(["police_dispatch", "chp_incidents"], geocoder=g)
        self.assertEqual(len(g.queries), 2)  # CHP 0:0 + police p3; never the withheld call or located rows
        self.assertTrue(any("Alemany" in q for q in g.queries) and any("MISSION" in q for q in g.queries))
        recs = {r.id: r for r in res.records}
        self.assertEqual(recs["chp_incidents:260925GG0002"].location_status, "geocoded")
        self.assertEqual(recs["chp_incidents:260925GG0002"].attributes["geocode"]["provider"], "fake")
        self.assertEqual(recs["police_dispatch:p2"].location_status, "withheld")
        self.assertEqual(res.stats["chp_incidents"].geocoded, 1)

    def test_geocoder_miss_keeps_record_unlocated(self):
        res = self.run_pipeline(["chp_incidents"], geocoder=FakeGeocoder(answer=None))
        rec = next(r for r in res.records if r.source_id == "260925GG0002")
        self.assertEqual((rec.location_status, res.stats["chp_incidents"].geocode_missed), ("unlocated", 1))

    def test_geocoding_is_opt_in_and_uses_team_mapbox_token(self):
        cases = [({}, None, "GEOCODER=mapbox"),
                 ({"MAPBOX_TOKEN": "t"}, None, "GEOCODER=mapbox"),        # polling token alone doesn't enable it
                 ({"GEOCODER": "mapbox"}, None, "MAPBOX_TOKEN"),
                 ({"GEOCODER": "google", "MAPBOX_TOKEN": "t"}, None, "unknown GEOCODER"),
                 ({"GEOCODER": "mapbox", "MAPBOX_TOKEN": "t"}, "mapbox", "mapbox")]
        for env, name, why in cases:
            with mock.patch.dict(os.environ, env, clear=True):
                g, reason = geocode.from_env()
            self.assertEqual(getattr(g, "name", None), name, env)
            self.assertIn(why, reason, env)
        res = self.run_pipeline(["chp_incidents"], geocoder=None)
        self.assertEqual(res.stats["chp_incidents"].unlocated, 1)

    def test_mapbox_geocoder_requests_permanent_results(self):
        body = json.dumps({"features": [{"geometry": {"coordinates": [-122.41, 37.78]}}]}).encode()
        with mock.patch("worker.geocode.fetch", return_value=body) as fetch:
            self.assertEqual(geocode.MapboxGeocoder("tok").geocode("Market St"), (-122.41, 37.78))
        params = fetch.call_args.kwargs["params"]
        self.assertEqual((params["permanent"], params["access_token"]), ("true", "tok"))

    def test_cache_bbox_and_failures(self):
        class Provider:
            name = "p"
            n = 0

            def geocode(self, q):
                self.n += 1
                if q == "boom":
                    raise geocode.FetchError("503")
                return (-118.2, 34.0) if q == "LA" else (-122.41, 37.78)

        prov = Provider()
        path = self.root / "cache" / "geo.json"
        g = geocode.CachedGeocoder(prov, path)
        self.assertEqual(g.geocode("Market St"), (-122.41, 37.78))
        self.assertEqual(g.geocode("market  st"), (-122.41, 37.78))  # cached, normalized key
        self.assertIsNone(g.geocode("LA"))  # outside the Bay Area
        self.assertIsNone(g.geocode("boom"))
        self.assertIsNone(g.geocode("boom"))  # failures aren't cached
        self.assertEqual((prov.n, g.failures), (4, 2))
        g.save()
        self.assertEqual(geocode.CachedGeocoder(prov, path).geocode("Market St"), (-122.41, 37.78))
        self.assertEqual(prov.n, 4)


class CliTests(PipelineCase):
    def test_cli_dry_run_writes_nothing_to_dbs(self):
        import contextlib
        import io
        from worker.__main__ import main
        out = io.StringIO()
        with mock.patch("worker.pipeline.MongoWriter") as mw, mock.patch("worker.pipeline.TigerWriter") as tw, \
                mock.patch("worker.log.setup"), contextlib.redirect_stdout(out):
            code = main(["--dry-run", "--no-geocode", "--raw-dir", str(self.raw), "--out-dir", str(self.out),
                         "--timeseries-dir", str(self.ts), "live"])
        mw.from_env.assert_not_called()
        tw.from_env.assert_not_called()
        self.assertEqual(code, 0)
        self.assertIn("DRY RUN: nothing written", out.getvalue())
        self.assertIn("mapbox_corridors", out.getvalue())
        self.assertTrue((self.out / "normalized" / "mapbox_corridors.json").exists())

    def test_cli_rejects_unknown_target(self):
        import contextlib
        import io
        from worker.__main__ import main
        with mock.patch("worker.log.setup"), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--dry-run", "nope"]), 2)


if __name__ == "__main__":
    unittest.main()
