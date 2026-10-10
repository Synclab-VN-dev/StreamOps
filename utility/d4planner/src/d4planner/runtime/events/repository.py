"""SQLite persistence for the canonical D4Planner event stream."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Iterable

from .model import EventEnvelope


SCHEMA_VERSION = 1


class SQLiteEventRepository:
    """Single-writer repository. Keep one connection open for the runtime."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, timeout=5.0)
        self._db.row_factory = sqlite3.Row
        self._configure()
        self._init_schema()

    def _configure(self) -> None:
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.execute("PRAGMA busy_timeout=5000")

    def _init_schema(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS event_log(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id TEXT NOT NULL,
              event_seq INTEGER NOT NULL,
              timestamp TEXT NOT NULL,
              type TEXT NOT NULL,
              data_json TEXT NOT NULL,
              UNIQUE(session_id, event_seq)
            );
            CREATE INDEX IF NOT EXISTS ix_event_log_session_seq
              ON event_log(session_id, event_seq);
            CREATE TABLE IF NOT EXISTS legacy_jsonl_migration(
              source_path TEXT PRIMARY KEY,
              size_bytes INTEGER NOT NULL,
              mtime_ns INTEGER NOT NULL,
              imported_rows INTEGER NOT NULL,
              malformed_rows INTEGER NOT NULL,
              migrated_at TEXT NOT NULL
            );
            """
        )
        self._db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self._db.commit()

    def journal_mode(self) -> str:
        row = self._db.execute("PRAGMA journal_mode").fetchone()
        return str(row[0]).casefold() if row else ""

    def max_sequence(self, session_id: str) -> int:
        row = self._db.execute(
            "SELECT COALESCE(MAX(event_seq), 0) FROM event_log WHERE session_id=?",
            (session_id,),
        ).fetchone()
        return int(row[0]) if row else 0

    def append_batch(
        self,
        events: Iterable[EventEnvelope],
        *,
        ignore_duplicates: bool = False,
    ) -> int:
        rows = [
            (
                event.session_id,
                event.event_seq,
                event.timestamp,
                event.type,
                json.dumps(event.data, ensure_ascii=False, separators=(",", ":")),
            )
            for event in events
        ]
        if not rows:
            return 0
        verb = "INSERT OR IGNORE" if ignore_duplicates else "INSERT"
        before = self._db.total_changes
        with self._db:
            self._db.executemany(
                f"""{verb} INTO event_log(
                    session_id,event_seq,timestamp,type,data_json
                ) VALUES(?,?,?,?,?)""",
                rows,
            )
        return int(self._db.total_changes - before)

    def read_after(
        self,
        session_id: str,
        after_seq: int,
        *,
        limit: int = 1000,
    ) -> list[EventEnvelope]:
        rows = self._db.execute(
            """SELECT session_id,event_seq,timestamp,type,data_json
               FROM event_log
               WHERE session_id=? AND event_seq>?
               ORDER BY event_seq ASC
               LIMIT ?""",
            (session_id, int(after_seq), int(limit)),
        ).fetchall()
        return [_row_to_event(row) for row in rows]

    def migration_state(self, source_path: str) -> sqlite3.Row | None:
        return self._db.execute(
            """SELECT source_path,size_bytes,mtime_ns,imported_rows,malformed_rows,migrated_at
               FROM legacy_jsonl_migration WHERE source_path=?""",
            (source_path,),
        ).fetchone()

    def record_migration(
        self,
        *,
        source_path: str,
        size_bytes: int,
        mtime_ns: int,
        imported_rows: int,
        malformed_rows: int,
        migrated_at: str,
    ) -> None:
        with self._db:
            self._db.execute(
                """INSERT INTO legacy_jsonl_migration(
                     source_path,size_bytes,mtime_ns,imported_rows,malformed_rows,migrated_at
                   ) VALUES(?,?,?,?,?,?)
                   ON CONFLICT(source_path) DO UPDATE SET
                     size_bytes=excluded.size_bytes,
                     mtime_ns=excluded.mtime_ns,
                     imported_rows=excluded.imported_rows,
                     malformed_rows=excluded.malformed_rows,
                     migrated_at=excluded.migrated_at""",
                (
                    source_path,
                    int(size_bytes),
                    int(mtime_ns),
                    int(imported_rows),
                    int(malformed_rows),
                    migrated_at,
                ),
            )

    def close(self) -> None:
        self._db.close()


class EventLogReader:
    """Independent reader connection used by CLI/log followers."""

    def __init__(self, path: Path):
        self.path = path
        self._db: sqlite3.Connection | None = None
        if path.exists():
            self._db = sqlite3.connect(path, timeout=2.0)
            self._db.row_factory = sqlite3.Row
            self._db.execute("PRAGMA query_only=ON")
            self._db.execute("PRAGMA busy_timeout=2000")

    def max_sequence(self, session_id: str) -> int:
        if self._db is None:
            return 0
        row = self._db.execute(
            "SELECT COALESCE(MAX(event_seq),0) FROM event_log WHERE session_id=?",
            (session_id,),
        ).fetchone()
        return int(row[0]) if row else 0

    def read_after(
        self,
        session_id: str,
        after_seq: int,
        *,
        limit: int = 1000,
    ) -> list[EventEnvelope]:
        if self._db is None:
            return []
        rows = self._db.execute(
            """SELECT session_id,event_seq,timestamp,type,data_json
               FROM event_log
               WHERE session_id=? AND event_seq>?
               ORDER BY event_seq ASC
               LIMIT ?""",
            (session_id, int(after_seq), int(limit)),
        ).fetchall()
        return [_row_to_event(row) for row in rows]

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None


def _row_to_event(row: sqlite3.Row) -> EventEnvelope:
    try:
        data = json.loads(str(row["data_json"]))
    except (TypeError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return EventEnvelope(
        event_seq=int(row["event_seq"]),
        type=str(row["type"]),
        timestamp=str(row["timestamp"]),
        session_id=str(row["session_id"]),
        data=data,
    )
