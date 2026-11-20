"""Durable Talisman observations derived from the canonical event journal."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .talisman import TalismanTooltip


class TalismanProjection:
    def __init__(self, path: Path):
        self.path = path
        self.caught_up = None
        with closing(sqlite3.connect(path)) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS talisman_observation(
                    session_id TEXT NOT NULL, start_seq INTEGER NOT NULL, end_seq INTEGER NOT NULL,
                    observed_at TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('bag','equipped')),
                    kind TEXT NOT NULL CHECK(kind IN ('charm','seal')), slot_index INTEGER,
                    name TEXT NOT NULL, item_type TEXT NOT NULL, item_power INTEGER NOT NULL,
                    attributes_json TEXT NOT NULL, comparison_name TEXT,
                    PRIMARY KEY(session_id, start_seq)
                );
                CREATE TABLE IF NOT EXISTS talisman_checkpoint(
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    row_id INTEGER NOT NULL, session_id TEXT NOT NULL,
                    event_seq INTEGER NOT NULL, pending_json TEXT NOT NULL
                );
                CREATE VIEW IF NOT EXISTS talisman_equipped_observations AS
                    SELECT * FROM talisman_observation WHERE role='equipped';
                -- A seal has a single evidenced position. Within a capture session
                -- its latest confirmed observation supersedes an earlier one.
                -- Charm navigation does not identify physical charm positions.
                CREATE VIEW IF NOT EXISTS talisman_last_equipped_seal AS
                    SELECT obs.* FROM talisman_equipped_observations AS obs
                    JOIN (SELECT session_id, MAX(end_seq) AS end_seq
                          FROM talisman_equipped_observations WHERE kind='seal'
                          GROUP BY session_id) AS latest USING(session_id,end_seq)
                    WHERE obs.kind='seal';
            """)

    def advance(self, source):
        """Commit one bounded batch. Idle polls also recover after a failed write."""
        latest = source.last_row_id()
        if latest == self.caught_up:
            return
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            checkpoint = db.execute(
                "SELECT row_id,session_id,event_seq,pending_json FROM talisman_checkpoint"
            ).fetchone()
            parser = TalismanTooltip()
            row_id = 0
            if checkpoint and source.matches_row(*checkpoint[:3]):
                row_id, parser.session, _, pending = checkpoint
                parser.lines = json.loads(pending)
            batch = source.projection_batch(row_id)
            for row_id, event in batch:
                item = parser.consume(event)
                if item:
                    db.execute("""
                        INSERT INTO talisman_observation
                        (session_id,start_seq,end_seq,observed_at,role,kind,name,item_type,
                         item_power,attributes_json,comparison_name)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(session_id,start_seq) DO NOTHING
                    """, (event.session_id,item["start"],item["end"],event.timestamp,item["role"],
                          item["kind"],item["name"],item["type"],item["power"],
                          json.dumps(item["attributes"], ensure_ascii=False), item["comparison"]))
            if batch:
                db.execute("""
                    INSERT INTO talisman_checkpoint VALUES(1,?,?,?,?)
                    ON CONFLICT(singleton) DO UPDATE SET row_id=excluded.row_id,
                    session_id=excluded.session_id,event_seq=excluded.event_seq,
                    pending_json=excluded.pending_json
                """, (row_id, event.session_id, event.event_seq, json.dumps(parser.lines)))
        self.caught_up = row_id
