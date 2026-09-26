import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from worker.storage import MONGO_INDEXES
from worker.writers import ConfigError, MongoWriter, TigerWriter

try:
    import pymongo  # noqa: F401
    HAVE_PYMONGO = True
except ImportError:
    HAVE_PYMONGO = False

NOW = datetime(2026, 9, 26, 1, tzinfo=timezone.utc)


@unittest.skipUnless(HAVE_PYMONGO, "pymongo not installed (pip install -e .[db])")
class MongoWriterTests(unittest.TestCase):
    def setUp(self):
        self.client = mock.MagicMock()
        self.db = self.client.get_default_database.return_value
        self.coll = self.db["road_incidents"]
        self.coll.bulk_write.return_value = mock.Mock(upserted_count=1, matched_count=1)
        self.w = MongoWriter(client=self.client, batch_size=2)

    def item(self, sid):
        f = {"source": "chp_incidents", "source_id": sid}
        return f, {**f, "incident_type": "incident"}

    def test_upserts_on_contract_key_and_sets_first_seen_only_on_insert(self):
        res = self.w.write("road_incidents", [self.item("1"), self.item("2"), self.item("3")], NOW)
        self.assertEqual(self.coll.bulk_write.call_count, 2)  # batched
        self.assertEqual(self.coll.bulk_write.call_args_list[0].kwargs, {"ordered": False})
        op = self.coll.bulk_write.call_args_list[0].args[0][0]
        self.assertEqual(op._filter, {"source": "chp_incidents", "source_id": "1"})
        self.assertTrue(op._upsert)
        self.assertEqual(op._doc, {"$set": {"source": "chp_incidents", "source_id": "1", "incident_type": "incident"},
                                   "$setOnInsert": {"first_seen_at": NOW}})
        self.assertEqual((res.written, res.updated, res.errors), (2, 2, []))

    def test_database_from_uri_default_transpeaktation(self):
        self.client.get_default_database.assert_called_once_with(default="transpeaktation")

    def test_bulk_errors_are_reported_not_raised(self):
        from pymongo.errors import BulkWriteError
        self.coll.bulk_write.side_effect = BulkWriteError({
            "nUpserted": 1, "nMatched": 0,
            "writeErrors": [{"op": {"q": {"source": "s", "source_id": "2"}}, "errmsg": "Can't extract geo keys"}]})
        res = self.w.write("road_incidents", [self.item("1"), self.item("2")], NOW)
        self.assertEqual(res.written, 1)
        self.assertIn("Can't extract geo keys", res.errors[0])
        self.assertIn("'source_id': '2'", res.errors[0])

    def test_connection_errors_are_reported(self):
        from pymongo.errors import ServerSelectionTimeoutError
        self.coll.bulk_write.side_effect = ServerSelectionTimeoutError("no servers")
        res = self.w.write("road_incidents", [self.item("1")], NOW)
        self.assertIn("ServerSelectionTimeoutError", res.errors[0])

    def test_ensure_indexes_matches_contract(self):
        self.w.ensure_indexes(MONGO_INDEXES)
        seg = self.db["road_segments"].create_index.call_args_list
        inc = self.db["road_incidents"].create_index.call_args_list
        self.assertIn(mock.call([("segment_id", 1)], unique=True), seg)
        self.assertIn(mock.call([("cnn", 1)]), seg)
        self.assertIn(mock.call([("geometry", "2dsphere")]), seg)
        self.assertIn(mock.call([("source", 1), ("source_id", 1)], unique=True), inc)
        self.assertIn(mock.call([("location", "2dsphere")]), inc)
        self.assertIn(mock.call([("start_time", 1), ("end_time", 1)]), inc)
        self.assertIn(mock.call([("road_segment_ids", 1)]), inc)


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.last = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))
        self.last = sql

    def fetchall(self):
        if "information_schema" in self.last:
            return [(c,) for c in self.conn.columns]
        return list(self.conn.existing)

    def executemany(self, sql, rows):
        if self.conn.fail:
            raise RuntimeError("insert failed")
        self.conn.inserted.append((sql, list(rows)))


TRAFFIC_COLS = ("time", "road_segment_id", "source", "speed_mph", "free_flow_speed_mph", "travel_time_sec",
                "congestion_ratio")


class FakeConn:
    def __init__(self, columns=TRAFFIC_COLS, existing=(), fail=False):
        self.columns, self.existing, self.fail = columns, existing, fail
        self.executed, self.inserted = [], []
        self.commits = self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def row(t=NOW, seg="1-2-0"):
    return {"time": t, "road_segment_id": seg, "source": "mapbox", "speed_mph": 9.9, "free_flow_speed_mph": None,
            "travel_time_sec": 20.0, "congestion_ratio": None}


class TigerWriterTests(unittest.TestCase):
    def test_appends_rows_in_contract_column_order(self):
        conn = FakeConn()
        res = TigerWriter(connect=lambda: conn).write("traffic_metrics", [row(), row(seg="2-1-0")])
        sql, rows = conn.inserted[0]
        self.assertIn("INSERT INTO traffic_metrics (time, road_segment_id, source, speed_mph, free_flow_speed_mph, "
                      "travel_time_sec, congestion_ratio)", sql)
        self.assertEqual(rows[1], (NOW, "2-1-0", "mapbox", 9.9, None, 20.0, None))
        self.assertEqual((res.written, res.skipped, conn.commits, res.errors), (2, 0, 1, []))

    def test_rerun_skips_poll_times_already_stored(self):
        later = NOW + timedelta(minutes=10)
        conn = FakeConn(existing=[("mapbox", NOW)])
        res = TigerWriter(connect=lambda: conn).write("traffic_metrics", [row(), row(seg="2-1-0"), row(later)])
        check_sql, params = conn.executed[1]
        self.assertIn("SELECT DISTINCT source, time FROM traffic_metrics", check_sql)
        self.assertEqual(params, (["mapbox"], [NOW, later]))
        self.assertEqual([r[0] for r in conn.inserted[0][1]], [later])
        self.assertEqual((res.written, res.skipped), (1, 2))

    def test_all_already_stored_inserts_nothing(self):
        conn = FakeConn(existing=[("mapbox", NOW)])
        res = TigerWriter(connect=lambda: conn).write("traffic_metrics", [row()])
        self.assertEqual((conn.inserted, res.written, res.skipped), ([], 0, 1))

    def test_missing_table_is_not_created(self):
        conn = FakeConn(columns=())
        res = TigerWriter(connect=lambda: conn).write("traffic_metrics", [row()])
        self.assertIn("contracts/tiger_schema.sql", res.errors[0])
        self.assertEqual(conn.inserted, [])
        self.assertFalse(any("CREATE" in sql for sql, _ in conn.executed))

    def test_schema_mismatch_is_reported(self):
        conn = FakeConn(columns=("time", "source"))
        res = TigerWriter(connect=lambda: conn).write("traffic_metrics", [row()])
        self.assertIn("missing columns", res.errors[0])

    def test_insert_failure_rolls_back(self):
        conn = FakeConn(fail=True)
        res = TigerWriter(connect=lambda: conn).write("traffic_metrics", [row()])
        self.assertEqual((res.written, conn.rollbacks), (0, 1))
        self.assertIn("insert failed", res.errors[0])

    def test_unknown_table_and_empty_batch(self):
        conn = FakeConn()
        w = TigerWriter(connect=lambda: conn)
        self.assertEqual(w.write("traffic_metrics", []).written, 0)
        self.assertIn("not in storage.TIGER_TABLES", w.write("vehicle_positions", [row()]).errors[0])


class ConfigTests(unittest.TestCase):
    def test_missing_env(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ConfigError, "MONGODB_URI"):
                MongoWriter.from_env()
            with self.assertRaisesRegex(ConfigError, "TIGER_DATABASE_URL"):
                TigerWriter.from_env()

    def test_placeholder_env(self):
        with mock.patch.dict(os.environ, {"TIGER_DATABASE_URL": "postgres://u:<password>@h/db"}, clear=True):
            with self.assertRaisesRegex(ConfigError, "placeholder"):
                TigerWriter.from_env()


if __name__ == "__main__":
    unittest.main()
