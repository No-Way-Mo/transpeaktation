"""Database writers. No normalization here: they take finished documents/rows.

Drivers are imported lazily so dry runs and tests work without them installed:
    pip install -e .[db]     (pymongo, psycopg)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterable

from .storage import TIGER_TABLES, TigerTable

PLACEHOLDER_MARKERS = ("<password>", "<user>", "<db_password>")


class ConfigError(RuntimeError):
    """Missing/unusable DB configuration: the affected store is skipped, not the run."""


@dataclass
class WriteResult:
    written: int = 0      # inserted or upserted-new
    updated: int = 0      # matched an existing document
    skipped: int = 0      # time-series rows already stored by an earlier run
    errors: list[str] = field(default_factory=list)


def _env_url(name: str) -> str:
    url = (os.environ.get(name) or "").strip()
    if not url:
        raise ConfigError(f"{name} is not set in ingest/.env")
    if any(m in url for m in PLACEHOLDER_MARKERS):
        raise ConfigError(f"{name} still contains a placeholder (e.g. <password>)")
    return url


# --- MongoDB ------------------------------------------------------------------

class MongoWriter:
    """Idempotent upserts on the contract keys (road_segments.segment_id,
    road_incidents.source+source_id). `first_seen_at` is set only on insert."""

    DB_NAME = "transpeaktation"  # AGENTS.md; also the default database in MONGODB_URI

    def __init__(self, uri: str | None = None, *, client: Any = None, batch_size: int = 1000):
        if client is None:
            try:
                from pymongo import MongoClient
            except ImportError as e:
                raise ConfigError("pymongo is not installed (pip install -e .[db])") from e
            client = MongoClient(uri, serverSelectionTimeoutMS=10_000, appname="transpeaktation-ingest")
        self.client = client
        self.db = client.get_default_database(default=self.DB_NAME)
        self.batch_size = batch_size

    @classmethod
    def from_env(cls) -> "MongoWriter":
        return cls(_env_url("MONGODB_URI"))

    def ping(self) -> None:
        self.client.admin.command("ping")

    def write(self, collection: str, items: Iterable[tuple[dict, dict]], now: datetime) -> WriteResult:
        """items: (upsert filter, document) pairs."""
        from pymongo import UpdateOne
        from pymongo.errors import BulkWriteError, PyMongoError

        res = WriteResult()
        items = list(items)
        for i in range(0, len(items), self.batch_size):
            ops = [UpdateOne(f, {"$set": d, "$setOnInsert": {"first_seen_at": now}}, upsert=True)
                   for f, d in items[i:i + self.batch_size]]
            try:
                r = self.db[collection].bulk_write(ops, ordered=False)
                res.written += r.upserted_count
                res.updated += r.matched_count
            except BulkWriteError as e:  # unordered: the rest of the batch still went in
                det = e.details or {}
                res.written += det.get("nUpserted", 0)
                res.updated += det.get("nMatched", 0)
                res.errors += [f"{collection} {w.get('op', {}).get('q')}: {w.get('errmsg')}"
                               for w in det.get("writeErrors", [])]
            except PyMongoError as e:
                res.errors.append(f"{collection}: {type(e).__name__}: {e}")
        return res

    def ensure_indexes(self, spec: dict[str, list[tuple[list, dict]]]) -> None:
        """Opt-in (--ensure-indexes): the contract indexes from storage.MONGO_INDEXES."""
        for collection, indexes in spec.items():
            for keys, opts in indexes:
                self.db[collection].create_index(keys, **opts)

    def close(self) -> None:
        self.client.close()


# --- Tiger Data (TimescaleDB / Postgres) ---------------------------------------

class TigerWriter:
    """Appends to the hypertables in contracts/tiger_schema.sql. Never creates or alters
    tables. Rows whose (source, time) are already stored are skipped, so reruns don't
    duplicate history (the hypertables have no unique key)."""

    def __init__(self, dsn: str | None = None, *, connect: Callable[[], Any] | None = None):
        if connect is None:
            try:
                import psycopg
            except ImportError as e:
                raise ConfigError("psycopg is not installed (pip install -e .[db])") from e
            connect = lambda: psycopg.connect(dsn, connect_timeout=10, application_name="transpeaktation-ingest")  # noqa: E731
        self.conn = connect()

    @classmethod
    def from_env(cls) -> "TigerWriter":
        return cls(_env_url("TIGER_DATABASE_URL"))

    def missing_columns(self, table: TigerTable) -> list[str] | None:
        """None if the table doesn't exist, else the expected columns it lacks."""
        with self.conn.cursor() as cur:
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table.name,))
            have = {row[0] for row in cur.fetchall()}
        if not have:
            return None
        return [c for c in table.columns if c not in have]

    def write(self, table_name: str, rows: Iterable[dict[str, Any]]) -> WriteResult:
        res = WriteResult()
        rows = list(rows)
        if not rows:
            return res
        table = TIGER_TABLES.get(table_name)
        if table is None:
            res.errors.append(f"{table_name}: not in storage.TIGER_TABLES")
            return res
        missing = self.missing_columns(table)
        if missing is None:
            res.errors.append(f"{table.name}: table does not exist in Tiger Data "
                              "(apply contracts/tiger_schema.sql; the worker won't create it)")
            return res
        if missing:
            res.errors.append(f"{table.name}: missing columns {missing} (contracts/tiger_schema.sql changed?)")
            return res
        src_col, time_col = table.idempotency
        cols = ", ".join(table.columns)
        marks = ", ".join(["%s"] * len(table.columns))
        try:
            with self.conn.cursor() as cur:
                cur.execute(f"SELECT DISTINCT {src_col}, {time_col} FROM {table.name} "
                            f"WHERE {src_col} = ANY(%s) AND {time_col} = ANY(%s)",
                            (sorted({r[src_col] for r in rows}), sorted({r[time_col] for r in rows})))
                done = {(s, t) for s, t in cur.fetchall()}
                new = [r for r in rows if (r[src_col], r[time_col]) not in done]
                if new:
                    cur.executemany(f"INSERT INTO {table.name} ({cols}) VALUES ({marks})",
                                    [tuple(r[c] for c in table.columns) for r in new])
            self.conn.commit()
            res.written = len(new)
            res.skipped = len(rows) - len(new)
        except Exception as e:  # driver-specific errors; keep the rest of the run alive
            self.conn.rollback()
            res.errors.append(f"{table.name}: {type(e).__name__}: {e}")
        return res

    def close(self) -> None:
        self.conn.close()
