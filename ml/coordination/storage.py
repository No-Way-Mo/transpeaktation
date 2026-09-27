"""SQLite persistence for assignments. The coordinator writes here BEFORE applying a change in memory; a failed write
means no commitment is returned. On restart the live state is rebuilt from this table."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .schemas import LIVE, Assignment

SCHEMA = """
CREATE TABLE IF NOT EXISTS assignments (
    assignment_id TEXT PRIMARY KEY,
    request_id    TEXT NOT NULL UNIQUE,
    version       INTEGER NOT NULL,
    status        TEXT NOT NULL,
    expires_at    REAL NOT NULL,
    updated_at    REAL NOT NULL,
    data          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS assignments_status ON assignments(status);
"""


class Storage:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.execute("PRAGMA journal_mode=WAL" if self.path != ":memory:" else "PRAGMA journal_mode=MEMORY")
        self.conn.executescript(SCHEMA)

    def save_many(self, assigns: list[Assignment]) -> None:
        """All-or-nothing."""
        rows = [(a.assignment_id, a.request_id, a.version, a.status, a.expires_at, a.updated_at,
                 json.dumps(a.to_dict())) for a in assigns]
        cur = self.conn.cursor()
        cur.execute("BEGIN IMMEDIATE")
        try:
            cur.executemany("INSERT OR REPLACE INTO assignments VALUES (?,?,?,?,?,?,?)", rows)
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise

    def load_live(self) -> list[Assignment]:
        q = f"SELECT data FROM assignments WHERE status IN ({','.join('?' * len(LIVE))})"
        return [Assignment.from_dict(json.loads(r[0])) for r in self.conn.execute(q, LIVE)]

    def get(self, assignment_id: str) -> Assignment | None:
        r = self.conn.execute("SELECT data FROM assignments WHERE assignment_id=?", (assignment_id,)).fetchone()
        return Assignment.from_dict(json.loads(r[0])) if r else None

    def by_request(self, request_id: str) -> Assignment | None:
        r = self.conn.execute("SELECT data FROM assignments WHERE request_id=?", (request_id,)).fetchone()
        return Assignment.from_dict(json.loads(r[0])) if r else None

    def close(self) -> None:
        self.conn.close()
