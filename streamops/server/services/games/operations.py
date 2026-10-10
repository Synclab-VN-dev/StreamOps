"""SQLite backed idempotent game operations, resilient to browser/node reconnect."""
from __future__ import annotations
import json
from pathlib import Path
import sqlite3
import threading
import uuid
from .models import utc_now

TERMINAL = frozenset({"SUCCEEDED", "FAILED", "UNKNOWN"})

class GameOperationStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        with self._connect() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS game_operations
                (id TEXT PRIMARY KEY, game_id TEXT NOT NULL, action TEXT NOT NULL,
                 idempotency_key TEXT NOT NULL UNIQUE, status TEXT NOT NULL,
                 phase TEXT NOT NULL, code TEXT, created_at TEXT NOT NULL,
                 updated_at TEXT NOT NULL)""")
            # Operation process died or node restarted: do not re-execute.
            con.execute("UPDATE game_operations SET status='UNKNOWN', phase='INTERRUPTED', "
                        "code='node_restarted', updated_at=? WHERE status IN ('PENDING','RUNNING')", (utc_now(),))

    def _connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def get(self, operation_id: str):
        with self._lock, self._connect() as con:
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT * FROM game_operations WHERE id=?", (operation_id,)).fetchone()
            return dict(row) if row else None

    def begin(self, game_id: str, action: str, key: str):
        with self._lock, self._connect() as con:
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT * FROM game_operations WHERE idempotency_key=?", (key,)).fetchone()
            if row:
                previous = dict(row)
                if previous["game_id"] != game_id or previous["action"] != action:
                    raise ValueError("idempotency_conflict")
                return previous, False
            now = utc_now()
            item = {"id": f"op-{uuid.uuid4().hex}", "game_id":game_id, "action":action,
                    "idempotency_key":key, "status":"PENDING","phase":"QUEUED",
                    "code":None, "created_at":now, "updated_at":now}
            con.execute("INSERT INTO game_operations VALUES (:id,:game_id,:action,:idempotency_key,"
                        ":status,:phase,:code,:created_at,:updated_at)", item)
            con.execute("DELETE FROM game_operations WHERE id IN "
                        "(SELECT id FROM game_operations WHERE status IN ('SUCCEEDED','FAILED','UNKNOWN') "
                        "ORDER BY updated_at DESC LIMIT -1 OFFSET 512)")
            return item, True

    def update(self, operation_id: str, status: str, phase: str, code: str | None = None):
        with self._lock, self._connect() as con:
            con.execute("UPDATE game_operations SET status=?,phase=?,code=?,updated_at=? WHERE id=?",
                        (status, phase, code, utc_now(), operation_id))
        return self.get(operation_id)
