"""Read-only Issue #119 diagnostic: why the CLI item snapshot is empty.

No runtime calls, no D4Planner Engine start/stop, no SQLite writes.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
from contextlib import closing


def get_rows(file: Path, sql: str, args: tuple = ()) -> list[dict]:
    if not file.is_file():
        return []
    with closing(sqlite3.connect(file.resolve().as_uri() + "?mode=ro",
                                 uri=True, timeout=3)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        return [dict(row) for row in db.execute(sql, args)]


def table_exists(file: Path, table: str) -> bool:
    return bool(get_rows(file,
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,)))


def report(home: Path) -> dict:
    state = home / "state"
    events = state / "events.db"
    character = state / "character.db"
    runtime = state / "runtime.json"
    try:
        active = json.loads(runtime.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        active = {}
    sid = active.get("sessionId") or active.get("session_id")
    result = {
        "home": str(home),
        "eventsDbPresent": events.is_file(),
        "characterDbPresent": character.is_file(),
        "pythonModulePath": (
            str(spec.origin) if (spec := importlib.util.find_spec("d4planner"))
            else None),
        "runtime": {
            "sessionId": sid,
            "state": active.get("state"),
            "supervisorPid": active.get("supervisorPid"),
            "lastError": active.get("lastError"),
            "lastEventAt": active.get("lastEventAt"),
        },
        "recentEventSessions": [],
        "eventCountForRuntimeSession": None,
        "ownedCheckpoint": None,
        "itemProjectionState": None,
        "currentItems": [],
        "latestObservations": [],
    }
    if table_exists(events, "event_log"):
        result["recentEventSessions"] = get_rows(events,
            """SELECT session_id, COUNT(*) AS eventCount,
                      MAX(id) AS latestRowId,
                      SUM(CASE WHEN type='speech.raw' THEN 1 ELSE 0 END) AS speechCount,
                      SUM(CASE WHEN type='input.marker.raw' THEN 1 ELSE 0 END) AS markerCount
               FROM event_log GROUP BY session_id ORDER BY latestRowId DESC LIMIT 3""")
        if sid:
            rows = get_rows(events,
                "SELECT COUNT(*) AS count, MAX(id) AS lastRowId FROM event_log WHERE session_id=?",
                (sid,))
            result["eventCountForRuntimeSession"] = rows[0] if rows else None
    if table_exists(character, "owned_item_checkpoint"):
        rows = get_rows(character,
            "SELECT last_event_rowid,state_json FROM owned_item_checkpoint WHERE id=1")
        if rows:
            row = rows[0]
            try:
                payload = json.loads(row["state_json"])
            except (TypeError, ValueError):
                payload = {}
            result["ownedCheckpoint"] = {
                "lastEventRowId": row["last_event_rowid"],
                "sessionId": payload.get("session"),
                "context": payload.get("context"),
                "characterInput": payload.get("characterInput"),
                "bagVisible": payload.get("bagVisible"),
                "lastSeenAt": payload.get("lastSeenAt"),
            }
    if table_exists(character, "item_projection_state"):
        result["itemProjectionState"] = next(iter(get_rows(character,
            """SELECT last_engine_session_id,last_event_rowid,revision,
                      projection_version,committed_at
               FROM item_projection_state WHERE id=1""")), None)
    if table_exists(character, "item_current"):
        result["currentItems"] = get_rows(character,
            """SELECT name,location,slot,ownership_status,presence_status,
                      source_session_id,revision FROM item_current
               ORDER BY revision DESC LIMIT 30""")
    if table_exists(character, "owned_item_observation"):
        rows = get_rows(character,
            """SELECT source_session_id,source_seq_start,item_name,observation_json
               FROM owned_item_observation ORDER BY observation_id DESC LIMIT 8""")
        for row in rows:
            try:
                data = json.loads(row.pop("observation_json"))
            except (ValueError, TypeError):
                data = {}
            row.update({
                "ownershipStatus": data.get("ownershipStatus"),
                "ownershipEvidence": data.get("ownershipEvidence"),
                "location": (data.get("location") or {}).get("type"),
            })
        result["latestObservations"] = rows
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--home-dir", type=Path, default=Path(
        os.environ.get("D4PLANNER_HOME") or
        str(Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "d4planner")))
    args = p.parse_args()
    print(json.dumps(report(args.home_dir), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
