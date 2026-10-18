from __future__ import annotations

from contextlib import contextmanager
import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import EquipmentObservation
from . import item_current


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
            item_current.schema(db)

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
            # New current-state writes go EXCLUSIVELY to item_current.
            # The old equipment_current table is migration/rollback history.
            if empty_slot_family:
                item_current.remove_where(
                    db, "location='equipment' AND slot=?",
                    (empty_slot_family,), when=updated_at, session=session_id)
            if remove_item_fingerprint:
                item_current.remove_where(
                    db, "item_key=?",
                    ("eq:" + remove_item_fingerprint,),
                    when=updated_at, session=session_id)
            if observation and observation.confidence == "HIGH":
                item_current.record_equipment(db, observation)
            db.execute(
                """INSERT INTO projector_checkpoint(consumer,session_id,last_event_seq,updated_at)
                   VALUES(?,?,?,?)
                   ON CONFLICT(consumer) DO UPDATE SET
                     session_id=excluded.session_id,
                     last_event_seq=excluded.last_event_seq,
                     updated_at=excluded.updated_at""",
                (self.CONSUMER, session_id, event_seq, updated_at),
            )

    def list_equipment(self) -> list[dict[str, Any]]:
        """Legacy CLI adapter over the ONE unified current-item projection."""
        snapshot = item_current.snapshot(self.path, locations={"equipment"})
        result = []
        for entry in snapshot["items"]:
            location = entry.get("location") or {}
            result.append({
                "slotFamily": location.get("slot"),
                "slotIndex": None,
                "name": entry["name"],
                "favorite": entry.get("favorite", False),
                "ancestral": entry.get("ancestral", False),
                "rarity": entry.get("rarity"),
                "itemType": entry.get("itemType"),
                "itemPower": entry.get("itemPower"),
                "baseStats": entry.get("baseStats") or [],
                "affixes": entry.get("affixes") or [],
                "effectsRaw": entry.get("effectsRaw") or [],
                "observedAt": entry.get("lastSeenAt"),
                "sourceSessionId": entry.get("sourceSessionId"),
                "sourceEventSeqStart": entry.get("sourceEventSeqStart"),
                "sourceEventSeqEnd": entry.get("sourceEventSeqEnd"),
                "confidence": entry.get("observationConfidence", "HIGH"),
            })
        order = {"helm": 1, "chest": 2, "gloves": 3, "pants": 4,
                 "boots": 5, "main_hand": 6, "off_hand": 7,
                 "ring": 8, "amulet": 9}
        return sorted(result, key=lambda entry: (
            order.get(entry["slotFamily"], 99),
            entry.get("observedAt") or ""))
