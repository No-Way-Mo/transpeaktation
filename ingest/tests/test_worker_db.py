import unittest
from datetime import datetime, timezone

from worker.db import ETA_UPSERT, TRAFFIC_COLS, TRAFFIC_UPSERT, WORKER_SQL, TigerSink


class FakeCursor:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.log.append(("execute", sql))

    def executemany(self, sql, rows):
        self.log.append(("executemany", sql, list(rows)))


class FakeConn:
    def __init__(self):
        self.log = []
        self.commits = 0

    def cursor(self):
        return FakeCursor(self.log)

    def commit(self):
        self.commits += 1


class TigerSinkTests(unittest.TestCase):
    def test_upserts_are_idempotent_on_the_unique_key(self):
        self.assertIn("ON CONFLICT (road_segment_id, source, time) DO UPDATE", TRAFFIC_UPSERT)
        self.assertIn("ON CONFLICT (corridor_id, direction, provider, route_idx, departure_time, time)", ETA_UPSERT)
        self.assertNotIn("time = EXCLUDED.time", TRAFFIC_UPSERT)

    def test_rows_go_in_column_order(self):
        conn = FakeConn()
        row = {"time": datetime(2026, 9, 26, tzinfo=timezone.utc), "road_segment_id": "1-2-0", "source": "tomtom",
               "speed_mph": 12.4, "free_flow_speed_mph": 24.9, "travel_time_sec": 15.8, "congestion_ratio": 0.5}
        TigerSink(conn=conn).write_traffic([row])
        _, _, rows = conn.log[0]
        self.assertEqual(rows, [tuple(row[c] for c in TRAFFIC_COLS)])
        self.assertEqual(conn.commits, 1)

    def test_schema_applies_contract_then_worker_additions(self):
        conn = FakeConn()
        self.assertEqual(TigerSink(conn=conn).apply_schema(), ["tiger_schema.sql", "schema.sql"])
        self.assertIn("CREATE TABLE IF NOT EXISTS traffic_metrics", conn.log[0][1])

    def test_worker_schema_has_unique_indexes(self):
        sql = WORKER_SQL.read_text()
        self.assertIn("traffic_metrics_uq ON traffic_metrics (road_segment_id, source, time)", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS route_eta_metrics", sql)


if __name__ == "__main__":
    unittest.main()
