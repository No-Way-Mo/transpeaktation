import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from datetime import timedelta
from unittest import mock

from worker import service
from worker.db import DryRunSink, MONGO_INDEXES, _update
from worker.events import SOURCE, EventJob, complete_window, event_id, load_seeds, match_seed, normalize

SEEDS = load_seeds()


def phq(**kw):
    """A /v1/events result, trimmed to the fields the worker reads."""
    row = {"id": "Abc123", "title": "Giants vs Dodgers", "category": "sports", "labels": ["baseball", "sport"],
           "rank": 85, "local_rank": 92, "phq_attendance": 38000, "state": "active", "scope": "venue",
           "start": "2026-09-27T02:15:00Z", "end": "2026-09-27T02:15:00Z", "predicted_end": "2026-09-27T05:15:00Z",
           "timezone": "America/Los_Angeles", "updated": "2026-09-20T10:00:00Z", "location": [-122.3892, 37.7785],
           "geo": {"geometry": {"type": "Point", "coordinates": [-122.3892, 37.7785]}},
           "entities": [{"entity_id": "V1", "name": "Oracle Park", "type": "venue",
                         "formatted_address": "24 Willie Mays Plaza"}]}
    row.update(kw)
    return row


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


class NormalizeTests(unittest.TestCase):
    def test_event_doc_matches_design_and_api_reads(self):
        ev, venue = normalize(phq(), SEEDS)
        d = ev["set"]
        self.assertEqual(ev["_id"], event_id("predicthq", "Abc123"))
        self.assertTrue(ev["_id"].startswith("evt_") and len(ev["_id"]) == 20)
        self.assertEqual((d["title"], d["category"], d["status"]), ("Giants vs Dodgers", "sports", "active"))
        self.assertEqual(d["location"], {"type": "Point", "coordinates": [-122.3892, 37.7785]})
        self.assertEqual((d["attendance"], d["rank"], d["local_rank"]), (38000, 85, 92))
        self.assertEqual(ev["add"], {"source_names": "predicthq"})
        self.assertEqual(d["sources.predicthq"]["id"], "Abc123")

    def test_seeded_venue_supplies_capacity(self):
        ev, venue = normalize(phq(), SEEDS)
        self.assertEqual((ev["set"]["venue_id"], ev["set"]["capacity"]), ("seed:oracle-park", 41265))
        self.assertEqual(venue["entity_id"], "V1")

    def test_unknown_venue_is_phq_entity(self):
        ev, _ = normalize(phq(location=[-122.42, 37.76], entities=[{"entity_id": "V9", "name": "Bottom of the Hill",
                                                                     "type": "venue"}]), SEEDS)
        self.assertEqual((ev["set"]["venue_id"], ev["set"]["capacity"]), ("phq:V9", None))

    def test_neighbouring_halls_match_by_name(self):
        davies = next(s for s in SEEDS if s["slug"] == "davies-symphony-hall")
        opera = next(s for s in SEEDS if s["slug"] == "war-memorial-opera-house")
        self.assertIs(match_seed("Davies Symphony Hall", opera["lon"], opera["lat"], SEEDS), davies)

    def test_zero_length_end_uses_predicted_end(self):
        d = normalize(phq(), SEEDS)[0]["set"]
        self.assertEqual((d["start_time"], d["end_time"], d["end_is_predicted"]),
                         (utc(2026, 9, 27, 2, 15), utc(2026, 9, 27, 5, 15), True))
        d = normalize(phq(predicted_end=None), SEEDS)[0]["set"]
        self.assertIsNone(d["end_time"])

    def test_no_timezone_means_sf_wall_clock(self):
        d = normalize(phq(timezone=None, start="2026-10-12T00:00:00Z", end="2026-10-12T23:59:59Z"), SEEDS)[0]["set"]
        self.assertEqual(d["start_time"], utc(2026, 10, 12, 7))  # PDT midnight
        self.assertTrue(d["all_day"])

    def test_categories_and_parade_label(self):
        self.assertEqual(normalize(phq(category="concerts"), SEEDS)[0]["set"]["category"], "concert")
        self.assertEqual(normalize(phq(category="performing-arts"), SEEDS)[0]["set"]["category"], "performing_arts")
        self.assertEqual(normalize(phq(category="community", labels=["parade"]), SEEDS)[0]["set"]["category"],
                         "parade")

    def test_deleted_events_keep_their_reason(self):
        self.assertEqual(normalize(phq(state="deleted", deleted_reason="cancelled"), SEEDS)[0]["set"]["status"],
                         "cancelled")
        self.assertEqual(normalize(phq(state="deleted", deleted_reason="duplicate"), SEEDS)[0]["set"]["status"],
                         "archived")
        self.assertEqual(normalize(phq(state="predicted"), SEEDS)[0]["set"]["status"], "active")

    def test_skips(self):
        self.assertEqual(normalize(phq(location=[-122.27, 37.80]), SEEDS), "outside_sf")  # Oakland
        self.assertEqual(normalize(phq(location=[]), SEEDS), "no_location")

    def test_hash_changes_with_content(self):
        a = normalize(phq(), SEEDS)[0]["set"]["sources.predicthq"]["hash"]
        self.assertEqual(a, normalize(phq(), SEEDS)[0]["set"]["sources.predicthq"]["hash"])
        self.assertNotEqual(a, normalize(phq(phq_attendance=40000), SEEDS)[0]["set"]["sources.predicthq"]["hash"])


class JobTests(unittest.TestCase):
    def run_job(self, records, meta=None):
        tmp = Path(tempfile.mkdtemp())
        (tmp / f"{SOURCE}.json").write_text(json.dumps({"source": SOURCE, "pulled_at": "2026-09-26T12:00:00+00:00",
                                                       "meta": meta or {"count": len(records)}, "records": records}))
        sink = DryRunSink(samples=100)
        return EventJob(tmp, sink, out_dir=tmp).run(), sink, tmp

    def test_writes_events_and_all_seed_venues(self):
        report, sink, _ = self.run_job([phq(), phq(id="X2", location=[-122.27, 37.80])])
        self.assertEqual((report["status"], report["events"], report["outside_sf"]), ("ok", 1, 1))
        self.assertEqual(sink.counts["events"], 1)
        self.assertEqual(sink.counts["venues"], len(SEEDS))
        oracle = next(v for v in sink.samples["venues"] if v["_id"] == "seed:oracle-park")
        self.assertEqual((oracle["capacity"], oracle["phq_entity_ids"]), (41265, ["V1"]))

    def test_bad_row_is_quarantined(self):
        report, sink, tmp = self.run_job([phq(), phq(id="bad", start="not a time")])
        self.assertEqual((report["events"], report["rejected"]), (1, 1))
        self.assertTrue((tmp / "quarantine" / f"{SOURCE}.jsonl").exists())

    def test_complete_pull_archives_vanished_events(self):
        report, sink, _ = self.run_job([phq()], {"truncated": False, "active.lte": "2026-10-26"})
        call = sink.samples["archive_missing_events"][0]
        self.assertEqual((call["source"], call["keep"]), ("predicthq", 1))
        self.assertEqual((call["start"], call["end"]), (utc(2026, 9, 26, 12), utc(2026, 10, 26, 7)))  # SF midnight
        self.assertIn("archived_missing", report)

    def test_truncated_or_old_pull_archives_nothing(self):
        for meta in ({"truncated": True, "active.lte": "2026-10-26"}, {"count": 1}):
            _, sink, _ = self.run_job([phq()], meta)
            self.assertNotIn("archive_missing_events", sink.samples)
        self.assertIsNone(complete_window({"pulled_at": "2026-09-26T12:00:00+00:00", "meta": {"truncated": True}}))

    def test_deleted_events_say_why(self):
        d = normalize(phq(state="deleted", deleted_reason="duplicate"), SEEDS)[0]["set"]
        self.assertEqual(d["archived_reason"], "predicthq_duplicate")
        self.assertIsNone(normalize(phq(), SEEDS)[0]["set"]["archived_reason"])

    def test_missing_snapshot_still_writes_seeds(self):
        sink = DryRunSink()
        report = EventJob(Path(tempfile.mkdtemp()), sink).run()
        self.assertEqual(report["status"], "missing")
        self.assertEqual(sink.counts["venues"], len(SEEDS))


class ScheduleTests(unittest.TestCase):
    def manifest(self, entry):
        tmp = Path(tempfile.mkdtemp()) / "_manifest.json"
        tmp.write_text(json.dumps({SOURCE: entry} if entry else {}))
        return mock.patch.object(service, "MANIFEST", tmp)

    def test_events_due_reads_last_pull_from_disk(self):
        now, six_h = utc(2026, 9, 26, 18), timedelta(hours=6)
        with self.manifest(None):
            self.assertTrue(service.events_due(six_h, now))
        with self.manifest({"status": "ok", "pulled_at": "2026-09-26T13:00:00+00:00"}):
            self.assertFalse(service.events_due(six_h, now))  # a restart 5 h later doesn't pull again
        with self.manifest({"status": "skip", "pulled_at": "2026-09-26T11:00:00+00:00"}):
            self.assertTrue(service.events_due(six_h, now))

    def test_failed_pull_leaves_mongo_alone(self):
        pulled = {SOURCE: {"status": "fail", "error": "FetchError: 401"}}
        with mock.patch.object(service, "refresh_snapshots", return_value=pulled), \
                mock.patch.object(service, "run_events") as run:
            out = service.refresh(("events",))
        run.assert_not_called()
        self.assertEqual(out["jobs"]["events"]["report"]["status"], "not_run")
        self.assertEqual(out["failures"][0]["stage"], "pull")

    def test_no_token_is_not_a_failure(self):
        with mock.patch.object(service, "refresh_snapshots", return_value={SOURCE: {"status": "skip"}}), \
                mock.patch.object(service, "run_events") as run:
            out = service.refresh(("events",))
        run.assert_not_called()
        self.assertEqual((out["ok"], out["failures"]), (True, []))

    def test_truncated_pull_is_reported(self):
        with mock.patch.object(service, "refresh_snapshots", return_value={SOURCE: {"status": "ok"}}), \
                mock.patch.object(service, "run_events", return_value={"status": "ok", "meta": {"truncated": True}}):
            out = service.refresh(("events",))
        self.assertIn("truncated", out["failures"][0]["error"])


class MongoTests(unittest.TestCase):
    def test_update_adds_to_sets_without_replacing(self):
        now = utc(2026, 9, 26)
        u = _update({"name": "x"}, {"source_names": "predicthq", "phq_entity_ids": ["b", "a", "a"]}, now)
        self.assertEqual(u["$addToSet"], {"source_names": "predicthq", "phq_entity_ids": {"$each": ["a", "b"]}})
        self.assertNotIn("$addToSet", _update({"name": "x"}, None, now))

    def test_events_have_design_indexes(self):
        keys = [k for k, _ in MONGO_INDEXES["events"]]
        self.assertIn([("location", "2dsphere")], keys)
        self.assertIn([("sources.predicthq.id", 1)], keys)


if __name__ == "__main__":
    unittest.main()
