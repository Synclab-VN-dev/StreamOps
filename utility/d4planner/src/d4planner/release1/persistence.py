from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable


class StaleAssessment(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AssessmentBinding:
    runtime_instance_id: str
    character_id: str
    current_revision: int
    target_id: str
    target_sha256: str
    selection_revision: int
    policy_version: str

    def key(self) -> str:
        return "|".join((
            self.runtime_instance_id, self.character_id, str(self.current_revision),
            self.target_id, self.target_sha256, str(self.selection_revision),
            self.policy_version,
        ))

    def as_dict(self) -> dict[str, Any]:
        return {
            "runtimeInstanceId": self.runtime_instance_id,
            "characterId": self.character_id,
            "currentRevision": self.current_revision,
            "targetId": self.target_id,
            "targetSha256": self.target_sha256,
            "selectionRevision": self.selection_revision,
            "policyVersion": self.policy_version,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AssessmentBinding":
        return cls(
            str(value["runtimeInstanceId"]), str(value["characterId"]),
            int(value["currentRevision"]), str(value["targetId"]),
            str(value["targetSha256"]), int(value["selectionRevision"]),
            str(value["policyVersion"]),
        )


class DurableHudStore:
    """SQLite commit boundary for binding + HUD snapshot + publish recovery."""

    SCHEMA_VERSION = 1

    def __init__(self, path: Path, *, timeout_seconds: float = 5.0):
        self.path = path
        self.timeout_seconds = timeout_seconds
        path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=self.timeout_seconds)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        try:
            yield db
        finally:
            db.close()

    def _migrate(self) -> None:
        with self._connect() as db, db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS schema_meta(
              component TEXT PRIMARY KEY, version INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS assessment_binding(
              singleton INTEGER PRIMARY KEY CHECK(singleton=1), binding_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS hud_snapshot(
              hud_revision INTEGER PRIMARY KEY, binding_key TEXT NOT NULL UNIQUE,
              payload_json TEXT NOT NULL, published INTEGER NOT NULL DEFAULT 0,
              committed_at TEXT NOT NULL);
            """)
            row = db.execute(
                "SELECT version FROM schema_meta WHERE component='release1-hud'"
            ).fetchone()
            if row is not None and int(row[0]) > self.SCHEMA_VERSION:
                raise RuntimeError("HUD_STORE_SCHEMA_NEWER_THAN_RUNTIME")
            db.execute(
                "INSERT INTO schema_meta(component,version) VALUES('release1-hud',?) "
                "ON CONFLICT(component) DO UPDATE SET version=excluded.version",
                (self.SCHEMA_VERSION,),
            )

    def set_binding(self, binding: AssessmentBinding) -> None:
        encoded = json.dumps(binding.as_dict(), separators=(",", ":"), sort_keys=True)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO assessment_binding(singleton,binding_json) VALUES(1,?) "
                "ON CONFLICT(singleton) DO UPDATE SET binding_json=excluded.binding_json",
                (encoded,),
            )
            db.commit()

    def current_binding(self) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT binding_json FROM assessment_binding WHERE singleton=1"
            ).fetchone()
            return json.loads(row[0]) if row else None

    def commit_if_current(
        self,
        binding: AssessmentBinding,
        payload_factory: Callable[[int], dict[str, Any]],
        committed_at: str,
    ) -> dict[str, Any]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            state = db.execute(
                "SELECT binding_json FROM assessment_binding WHERE singleton=1"
            ).fetchone()
            if state is None or json.loads(state[0]) != binding.as_dict():
                db.rollback()
                raise StaleAssessment("ASSESSMENT_BINDING_CHANGED")
            existing = db.execute(
                "SELECT payload_json FROM hud_snapshot WHERE binding_key=?",
                (binding.key(),),
            ).fetchone()
            if existing:
                db.commit()
                return json.loads(existing[0])
            revision = int(db.execute(
                "SELECT COALESCE(MAX(hud_revision),-1)+1 FROM hud_snapshot"
            ).fetchone()[0])
            payload = payload_factory(revision)
            db.execute(
                "INSERT INTO hud_snapshot(hud_revision,binding_key,payload_json,published,committed_at) "
                "VALUES(?,?,?,?,?)",
                (revision, binding.key(), json.dumps(payload, separators=(",", ":"), sort_keys=True), 0, committed_at),
            )
            db.commit()
            return payload

    def mark_published(self, hud_revision: int) -> None:
        with self._connect() as db, db:
            db.execute(
                "UPDATE hud_snapshot SET published=1 WHERE hud_revision=?",
                (hud_revision,),
            )

    def is_pending(self, hud_revision: int) -> bool:
        with self._connect() as db:
            row = db.execute(
                "SELECT published FROM hud_snapshot WHERE hud_revision=?",
                (hud_revision,),
            ).fetchone()
            return row is not None and int(row[0]) == 0

    def latest(self) -> dict[str, Any] | None:
        with self._connect() as db:
            binding = db.execute(
                "SELECT binding_json FROM assessment_binding WHERE singleton=1"
            ).fetchone()
            if binding is None:
                return None
            binding_key = AssessmentBinding.from_dict(json.loads(binding[0])).key()
            row = db.execute(
                "SELECT payload_json FROM hud_snapshot WHERE binding_key=? "
                "ORDER BY hud_revision DESC LIMIT 1",
                (binding_key,),
            ).fetchone()
            return json.loads(row[0]) if row else None

    def pending_publish(self) -> tuple[dict[str, Any], ...]:
        with self._connect() as db:
            binding = db.execute(
                "SELECT binding_json FROM assessment_binding WHERE singleton=1"
            ).fetchone()
            if binding is None:
                return ()
            binding_key = AssessmentBinding.from_dict(json.loads(binding[0])).key()
            rows = db.execute(
                "SELECT payload_json FROM hud_snapshot "
                "WHERE published=0 AND binding_key=? ORDER BY hud_revision",
                (binding_key,),
            ).fetchall()
            return tuple(json.loads(row[0]) for row in rows)
