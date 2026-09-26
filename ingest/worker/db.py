"""Sinks: where finished rows/documents go. No normalization happens here.

TigerSink / MongoSink write for real (drivers imported lazily: pip install -e .[db]);
DryRunSink counts and keeps a few samples so `--dry-run` shows exactly what would be written.
"""
from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pull import INGEST_DIR

CONTRACT_SQL = INGEST_DIR.parent / "contracts" / "tiger_schema.sql"
WORKER_SQL = Path(__file__).with_name("schema.sql")

TRAFFIC_COLS = ("time", "road_segment_id", "source", "speed_mph", "free_flow_speed_mph", "travel_time_sec",
                "congestion_ratio")
ETA_COLS = ("time", "corridor_id", "direction", "provider", "route_idx", "departure_time", "duration_sec",
            "typical_duration_sec", "static_duration_sec", "distance_m", "route_plan_id", "event_id")
BATCH = 5000

# AGENTS.md road_segments indexes, plus route_plans lookups.
MONGO_INDEXES: dict[str, list[tuple[list, dict]]] = {
    "road_segments": [([("segment_id", 1)], {"unique": True}), ([("cnn", 1)], {}), ([("geometry", "2dsphere")], {})],
    "road_incidents": [([("source", 1), ("source_id", 1)], {"unique": True}), ([("location", "2dsphere")], {}),
                       ([("start_time", 1), ("end_time", 1)], {}), ([("road_segment_ids", 1)], {}),
                       ([("is_closure", 1), ("end_time", 1)], {})],
    "route_plans": [([("corridor_id", 1), ("direction", 1)], {}), ([("segment_ids", 1)], {})],
}


class ConfigError(RuntimeError):
    pass


def env_url(name: str) -> str:
    url = (os.environ.get(name) or "").strip()
    if not url or "<password>" in url:
        raise ConfigError(f"set {name} in ingest/.env (currently {'a placeholder' if url else 'empty'})")
    return url


def _upsert_sql(table: str, cols: tuple[str, ...], key: tuple[str, ...]) -> str:
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c not in key)
    return (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
            f"ON CONFLICT ({', '.join(key)}) DO UPDATE SET {updates}")


TRAFFIC_UPSERT = _upsert_sql("traffic_metrics", TRAFFIC_COLS, ("road_segment_id", "source", "time"))
ETA_UPSERT = _upsert_sql("route_eta_metrics", ETA_COLS,
                         ("corridor_id", "direction", "provider", "route_idx", "departure_time", "time"))


class TigerSink:
    def __init__(self, dsn: str | None = None, *, conn: Any = None):
        if conn is None:
            try:
                import psycopg
            except ImportError as e:
                raise ConfigError("psycopg is not installed (pip install -e .[db])") from e
            conn = psycopg.connect(dsn or env_url("TIGER_DATABASE_URL"), connect_timeout=10,
                                   application_name="transpeaktation-worker")
        self.conn = conn
        self.counts: Counter = Counter()

    def apply_schema(self) -> list[str]:
        """Contract tables first, then the worker's additions. Both files are idempotent."""
        applied = []
        for path in (CONTRACT_SQL, WORKER_SQL):
            with self.conn.cursor() as cur:
                cur.execute(path.read_text(encoding="utf-8"))
            self.conn.commit()
            applied.append(path.name)
        return applied

    def _write(self, sql: str, cols: tuple[str, ...], rows: list[dict], what: str) -> None:
        with self.conn.cursor() as cur:
            for i in range(0, len(rows), BATCH):
                cur.executemany(sql, [tuple(r[c] for c in cols) for r in rows[i:i + BATCH]])
        self.conn.commit()
        self.counts[what] += len(rows)

    def write_traffic(self, rows: list[dict]) -> None:
        self._write(TRAFFIC_UPSERT, TRAFFIC_COLS, rows, "traffic_metrics")

    def write_route_eta(self, rows: list[dict]) -> None:
        self._write(ETA_UPSERT, ETA_COLS, rows, "route_eta_metrics")

    def close(self) -> None:
        self.conn.close()


class MongoSink:
    DB_NAME = "transpeaktation"

    def __init__(self, uri: str | None = None, *, db: Any = None):
        if db is None:
            try:
                from pymongo import MongoClient
            except ImportError as e:
                raise ConfigError("pymongo is not installed (pip install -e .[db])") from e
            client = MongoClient(uri or env_url("MONGODB_URI"), serverSelectionTimeoutMS=10_000,
                                 tz_aware=True, appname="transpeaktation-worker")
            db = client.get_default_database(default=self.DB_NAME)
        self.db = db
        self.counts: Counter = Counter()

    def ensure_indexes(self) -> None:
        for coll, indexes in MONGO_INDEXES.items():
            for keys, opts in indexes:
                self.db[coll].create_index(keys, **opts)

    def _upsert(self, coll: str, items: list[tuple[dict, dict]]) -> None:
        """(filter, document) pairs. `first_seen_at` is set on insert only; `last_ingested_at` every write."""
        from pymongo import UpdateOne

        now = datetime.now(timezone.utc)
        for i in range(0, len(items), 1000):
            ops = [UpdateOne(f, {"$set": {**d, "last_ingested_at": d.get("last_ingested_at", now)},
                                 "$setOnInsert": {"first_seen_at": now}}, upsert=True)
                   for f, d in items[i:i + 1000]]
            self.db[coll].bulk_write(ops, ordered=False)
        self.counts[coll] += len(items)

    def write_road_segments(self, docs: list[dict]) -> None:
        self._upsert("road_segments", [({"segment_id": d["segment_id"]}, d) for d in docs])

    def write_route_plans(self, docs: list[dict]) -> None:
        self._upsert("route_plans", [({"_id": d["_id"]}, {k: v for k, v in d.items() if k != "_id"}) for d in docs])

    def write_road_incidents(self, items: list[tuple[dict, dict]]) -> None:
        self._upsert("road_incidents", items)


class CombinedSink:
    """Traffic rows and ETAs to Tiger, route plans to Mongo."""

    def __init__(self, tiger: TigerSink, mongo: MongoSink | None):
        self.tiger, self.mongo = tiger, mongo

    def write_traffic(self, rows: list[dict]) -> None:
        self.tiger.write_traffic(rows)

    def write_route_eta(self, rows: list[dict]) -> None:
        self.tiger.write_route_eta(rows)

    def write_route_plans(self, docs: list[dict]) -> None:
        if self.mongo is not None:
            self.mongo.write_route_plans(docs)


class DryRunSink:
    def __init__(self, samples: int = 3):
        self.counts: Counter = Counter()
        self.samples: dict[str, list] = {}
        self.n = samples

    def _keep(self, what: str, items: list) -> None:
        self.counts[what] += len(items)
        s = self.samples.setdefault(what, [])
        s.extend(items[: max(0, self.n - len(s))])

    def write_traffic(self, rows: list[dict]) -> None:
        self._keep("traffic_metrics", rows)

    def write_route_eta(self, rows: list[dict]) -> None:
        self._keep("route_eta_metrics", rows)

    def write_route_plans(self, docs: list[dict]) -> None:
        self._keep("route_plans", docs)

    def write_road_segments(self, docs: list[dict]) -> None:
        self._keep("road_segments", docs)

    def write_road_incidents(self, items: list[tuple[dict, dict]]) -> None:
        self._keep("road_incidents", [{**f, **d} for f, d in items])
