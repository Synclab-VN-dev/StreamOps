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
            # Fresh DEV schema: no second equipment_current authority.
            # Projector checkpoint is diagnostic compatibility only.
            db.executescript("""
            CREATE TABLE IF NOT EXISTS projector_checkpoint(
              consumer TEXT PRIMARY KEY, session_id TEXT NOT NULL,
              last_event_seq INTEGER NOT NULL, updated_at TEXT NOT NULL);
            """)
            item_current.schema(db)

    def checkpoint(self, connection: sqlite3.Connection | None = None) -> tuple[str, int] | None:
        """Read checkpoint inside the caller's transaction when supplied."""
        if connection is None:
            with self._connect() as db:
                return self.checkpoint(connection=db)
        row = connection.execute(
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
        connection: sqlite3.Connection | None = None,
    ):
        """One transaction with Bag + cursor when Engine passes a connection.

        Existing standalone equipment replay keeps its own transaction.
        The domain reducer remains the sole item_current write policy.
        """
        if connection is None:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                self.commit_event(
                    session_id=session_id, event_seq=event_seq,
                    updated_at=updated_at, observation=observation,
                    empty_slot_family=empty_slot_family,
                    remove_item_fingerprint=remove_item_fingerprint,
                    connection=db)
            return

        db = connection
        # Empty slot and ring decisions are separately attested by the
        # Equipment context state machine; only the reducer mutates current.
        if empty_slot_family:
            item_current.mark_location_unknown(
                db, "location='equipment' AND slot=?",
                (empty_slot_family,), when=updated_at, session=session_id)
        if remove_item_fingerprint:
            item_current.mark_location_unknown(
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
