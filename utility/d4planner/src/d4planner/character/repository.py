from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import EquipmentObservation


class EquipmentRepositoryReadError(RuntimeError):
    """Base failure exposed by the read-only projection boundary."""


class EquipmentRepositoryUnavailable(EquipmentRepositoryReadError):
    pass


class EquipmentRepositoryTransient(EquipmentRepositoryReadError):
    pass


class EquipmentRepositoryIncompatible(EquipmentRepositoryReadError):
    pass


@dataclass(frozen=True)
class EquipmentProjectionView:
    revision: tuple[int, str, int, str] | None
    rows: tuple[dict[str, Any], ...]


def _equipment_rows(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        item = json.loads(row["item_json"])
        result.append({
            "slotFamily": row["slot_family"], "slotIndex": row["slot_index"],
            "name": row["item_name"], "favorite": item.get("favorite", False),
            "ancestral": item.get("ancestral", False), "rarity": item.get("rarity"),
            "itemType": row["item_type"], "itemPower": row["item_power"],
            "baseStats": item.get("base_stats", []), "affixes": item.get("affixes", []),
            "effectsRaw": item.get("effects_raw", []), "observedAt": row["observed_at"],
            "sourceSessionId": row["source_session_id"],
            "sourceEventSeqStart": row["source_event_seq_start"],
            "sourceEventSeqEnd": row["source_event_seq_end"],
            "confidence": row["confidence"], "itemFingerprint": row["item_fingerprint"],
        })
    return result


class ReadOnlyEquipmentRepository:
    """Read an existing producer projection without initializing or mutating it."""

    REQUIRED_COLUMNS = {
        "equipment_current": {
            "slot_family", "slot_index", "item_name", "item_type", "item_power",
            "item_json", "observed_at", "source_session_id", "source_event_seq_start",
            "source_event_seq_end", "confidence", "item_fingerprint",
        },
        "equipment_projection_revision": {
            "singleton", "revision", "session_id", "event_seq", "updated_at",
        },
    }

    def __init__(self, path: Path, *, timeout_seconds: float = 1.0):
        self.path = path
        self.timeout_seconds = timeout_seconds
        if not path.is_file():
            raise EquipmentRepositoryUnavailable("EQUIPMENT_DB_MISSING")

    @contextmanager
    def _connect(self):
        try:
            connection = sqlite3.connect(
                self.path.resolve().as_uri() + "?mode=ro", uri=True,
                timeout=self.timeout_seconds, isolation_level=None,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
        except sqlite3.OperationalError as error:
            raise self._classify(error) from error
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _classify(error: sqlite3.OperationalError) -> EquipmentRepositoryReadError:
        message = str(error).lower()
        if "locked" in message or "busy" in message:
            return EquipmentRepositoryTransient("EQUIPMENT_DB_BUSY")
        if "unable to open" in message or "not a database" in message:
            return EquipmentRepositoryUnavailable("EQUIPMENT_DB_UNAVAILABLE")
        return EquipmentRepositoryReadError(f"EQUIPMENT_DB_READ_FAILED:{error}")

    def _validate_schema(self, db: sqlite3.Connection) -> None:
        for table, required in self.REQUIRED_COLUMNS.items():
            try:
                columns = {str(row["name"]) for row in db.execute(f"PRAGMA table_info({table})")}
            except sqlite3.OperationalError as error:
                raise self._classify(error) from error
            except sqlite3.DatabaseError as error:
                raise EquipmentRepositoryIncompatible("EQUIPMENT_DB_SCHEMA_INVALID") from error
            if not required.issubset(columns):
                raise EquipmentRepositoryIncompatible(
                    f"EQUIPMENT_DB_SCHEMA_INCOMPATIBLE:{table}"
                )

    def projection_snapshot(self) -> EquipmentProjectionView:
        order = "CASE slot_family WHEN 'helm' THEN 1 WHEN 'chest' THEN 2 WHEN 'gloves' THEN 3 WHEN 'pants' THEN 4 WHEN 'boots' THEN 5 WHEN 'main_hand' THEN 6 WHEN 'off_hand' THEN 7 WHEN 'ring' THEN 8 WHEN 'amulet' THEN 9 ELSE 99 END"
        try:
            with self._connect() as db:
                db.execute("BEGIN")
                self._validate_schema(db)
                revision_row = db.execute(
                    "SELECT revision,session_id,event_seq,updated_at "
                    "FROM equipment_projection_revision WHERE singleton=1"
                ).fetchone()
                rows = db.execute(
                    f"SELECT * FROM equipment_current ORDER BY {order},slot_index,observed_at,item_fingerprint"
                ).fetchall()
                db.execute("ROLLBACK")
        except EquipmentRepositoryReadError:
            raise
        except (sqlite3.DatabaseError, json.JSONDecodeError) as error:
            if isinstance(error, sqlite3.OperationalError):
                raise self._classify(error) from error
            raise EquipmentRepositoryIncompatible("EQUIPMENT_DB_PROJECTION_INVALID") from error
        revision = (
            (int(revision_row[0]), str(revision_row[1]), int(revision_row[2]), str(revision_row[3]))
            if revision_row else None
        )
        try:
            projected = tuple(_equipment_rows(rows))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise EquipmentRepositoryIncompatible("EQUIPMENT_DB_PROJECTION_INVALID") from error
        return EquipmentProjectionView(revision, projected)

    def projection_revision(self) -> tuple[int, str, int, str] | None:
        return self.projection_snapshot().revision

    def list_equipment(self) -> list[dict[str, Any]]:
        return list(self.projection_snapshot().rows)


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
            CREATE TABLE IF NOT EXISTS equipment_projection_revision(
              singleton INTEGER PRIMARY KEY CHECK(singleton=1), revision INTEGER NOT NULL,
              session_id TEXT NOT NULL, event_seq INTEGER NOT NULL, updated_at TEXT NOT NULL);
            """)

    def checkpoint(self) -> tuple[str, int] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT session_id,last_event_seq FROM projector_checkpoint WHERE consumer=?",
                (self.CONSUMER,),
            ).fetchone()
            return (str(row[0]), int(row[1])) if row else None

    def projection_revision(self) -> tuple[int, str, int, str] | None:
        """Return the durable producer cursor for current Equipment state."""
        with self._connect() as db:
            row = db.execute(
                "SELECT revision,session_id,event_seq,updated_at "
                "FROM equipment_projection_revision WHERE singleton=1"
            ).fetchone()
            return (int(row[0]), str(row[1]), int(row[2]), str(row[3])) if row else None

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

            equipment_changed = bool(observation or empty_slot_family or remove_item_fingerprint)

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
            if equipment_changed:
                db.execute(
                    """INSERT INTO equipment_projection_revision(singleton,revision,session_id,event_seq,updated_at)
                    VALUES(1,1,?,?,?) ON CONFLICT(singleton) DO UPDATE SET
                    revision=equipment_projection_revision.revision+1,
                    session_id=excluded.session_id,event_seq=excluded.event_seq,updated_at=excluded.updated_at""",
                    (session_id, event_seq, updated_at),
                )

    def list_equipment(self) -> list[dict[str, Any]]:
        order = "CASE slot_family WHEN 'helm' THEN 1 WHEN 'chest' THEN 2 WHEN 'gloves' THEN 3 WHEN 'pants' THEN 4 WHEN 'boots' THEN 5 WHEN 'main_hand' THEN 6 WHEN 'off_hand' THEN 7 WHEN 'ring' THEN 8 WHEN 'amulet' THEN 9 ELSE 99 END"
        with self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM equipment_current ORDER BY {order}, observed_at"
            ).fetchall()
            return _equipment_rows(rows)
