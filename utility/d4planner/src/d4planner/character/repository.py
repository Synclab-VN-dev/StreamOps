from __future__ import annotations

from contextlib import contextmanager
import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import EquipmentObservation


class EquipmentRepository:
    CONSUMER = "equipment-v1"

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            # sqlite3.Connection.__exit__ commits/rolls back but does not close
            # the OS handle. Nest it here and always close explicitly so the
            # high-frequency projector path cannot accumulate Windows handles.
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_schema(self):
        with self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS equipment_current(
              id INTEGER PRIMARY KEY, slot_family TEXT NOT NULL, slot_index INTEGER,
              item_name TEXT NOT NULL, item_type TEXT NOT NULL, item_power INTEGER NOT NULL,
              item_json TEXT NOT NULL, observed_at TEXT NOT NULL, source_session_id TEXT NOT NULL,
              source_event_seq_start INTEGER NOT NULL, source_event_seq_end INTEGER NOT NULL,
              confidence TEXT NOT NULL, item_fingerprint TEXT NOT NULL UNIQUE);
            CREATE INDEX IF NOT EXISTS ix_equipment_slot ON equipment_current(slot_family, slot_index);
            CREATE TABLE IF NOT EXISTS projector_checkpoint(
              consumer TEXT PRIMARY KEY, session_id TEXT NOT NULL, last_event_seq INTEGER NOT NULL,
              updated_at TEXT NOT NULL);
            """)

    def checkpoint(self) -> tuple[str, int] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT session_id,last_event_seq FROM projector_checkpoint WHERE consumer=?",
                (self.CONSUMER,),
            ).fetchone()
            return (str(row[0]), int(row[1])) if row else None

    def commit_event(
        self,
        *,
        session_id: str,
        event_seq: int,
        updated_at: str,
        observation: EquipmentObservation | None,
        empty_slot_family: str | None = None,
        remove_item_fingerprint: str | None = None,
    ):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")

            # Materialize equipped -> empty in the same transaction as the
            # projector checkpoint so a restart cannot resurrect stale state.
            if empty_slot_family:
                db.execute(
                    "DELETE FROM equipment_current WHERE slot_family=?",
                    (empty_slot_family,),
                )

            # Ring removal is item-specific because two physical ring slots
            # share slot_family='ring' and slot_index=None.
            if remove_item_fingerprint:
                db.execute(
                    "DELETE FROM equipment_current "
                    "WHERE slot_family='ring' AND item_fingerprint=?",
                    (remove_item_fingerprint,),
                )

            if observation and observation.confidence == "HIGH":
                item = observation.item
                if observation.slot_family != "ring":
                    db.execute(
                        "DELETE FROM equipment_current "
                        "WHERE slot_family=? AND item_fingerprint<>?",
                        (observation.slot_family, observation.fingerprint),
                    )
                db.execute(
                    """INSERT INTO equipment_current(slot_family,slot_index,item_name,item_type,item_power,item_json,observed_at,source_session_id,source_event_seq_start,source_event_seq_end,confidence,item_fingerprint)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(item_fingerprint) DO UPDATE SET item_json=excluded.item_json,observed_at=excluded.observed_at,source_session_id=excluded.source_session_id,source_event_seq_start=excluded.source_event_seq_start,source_event_seq_end=excluded.source_event_seq_end,confidence=excluded.confidence""",
                    (
                        observation.slot_family,
                        observation.slot_index,
                        item.name,
                        item.item_type,
                        item.item_power,
                        json.dumps(item.as_dict(), ensure_ascii=False),
                        observation.observed_at,
                        observation.session_id,
                        observation.seq_start,
                        observation.seq_end,
                        observation.confidence,
                        observation.fingerprint,
                    ),
                )
                if observation.slot_family == "ring":
                    rows = db.execute(
                        "SELECT id FROM equipment_current WHERE slot_family='ring' "
                        "ORDER BY observed_at DESC,id DESC"
                    ).fetchall()
                    for row in rows[2:]:
                        db.execute(
                            "DELETE FROM equipment_current WHERE id=?",
                            (row[0],),
                        )

            db.execute(
                """INSERT INTO projector_checkpoint(consumer,session_id,last_event_seq,updated_at) VALUES(?,?,?,?)
              ON CONFLICT(consumer) DO UPDATE SET session_id=excluded.session_id,last_event_seq=excluded.last_event_seq,updated_at=excluded.updated_at""",
                (self.CONSUMER, session_id, event_seq, updated_at),
            )

    def list_equipment(self) -> list[dict[str, Any]]:
        order = "CASE slot_family WHEN 'helm' THEN 1 WHEN 'chest' THEN 2 WHEN 'gloves' THEN 3 WHEN 'pants' THEN 4 WHEN 'boots' THEN 5 WHEN 'main_hand' THEN 6 WHEN 'off_hand' THEN 7 WHEN 'ring' THEN 8 WHEN 'amulet' THEN 9 ELSE 99 END"
        with self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM equipment_current ORDER BY {order}, observed_at"
            ).fetchall()
            result = []
            for r in rows:
                item = json.loads(r["item_json"])
                result.append(
                    {
                        "slotFamily": r["slot_family"],
                        "slotIndex": r["slot_index"],
                        "name": r["item_name"],
                        "favorite": item.get("favorite", False),
                        "ancestral": item.get("ancestral", False),
                        "rarity": item.get("rarity"),
                        "itemType": r["item_type"],
                        "itemPower": r["item_power"],
                        "baseStats": item.get("base_stats", []),
                        "affixes": item.get("affixes", []),
                        "effectsRaw": item.get("effects_raw", []),
                        "observedAt": r["observed_at"],
                        "sourceSessionId": r["source_session_id"],
                        "sourceEventSeqStart": r["source_event_seq_start"],
                        "sourceEventSeqEnd": r["source_event_seq_end"],
                        "confidence": r["confidence"],
                    }
                )
            return result
