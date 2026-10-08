"""Unified SQLite-backed event store for one D4Planner runtime session."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Callable, Iterable
from uuid import uuid4

from ..store import RuntimePaths, SessionInfo, atomic_write_json, iso_now, utc_now
from .migration import MigrationReport, migrate_legacy_jsonl
from .model import EventDraft, EventEnvelope, validate_event_draft
from .repository import SQLiteEventRepository

Clock = Callable[[], datetime]


class EventStore:
    """Single-writer ordered event stream with SQLite as canonical storage."""

    def __init__(
        self,
        *,
        paths: RuntimePaths,
        session: SessionInfo,
        repository: SQLiteEventRepository,
        clock: Clock = utc_now,
        migration_report: MigrationReport | None = None,
    ):
        self.paths = paths
        self.session = session
        self.repository = repository
        self._clock = clock
        self.migration_report = migration_report or MigrationReport()
        self._next_seq = repository.max_sequence(session.session_id) + 1

    @classmethod
    def create(
        cls,
        paths: RuntimePaths,
        *,
        silent: bool,
        metadata: dict[str, Any] | None = None,
        clock: Clock = utc_now,
        session_id: str | None = None,
    ) -> "EventStore":
        paths.ensure()
        repository = SQLiteEventRepository(paths.events_db)
        migrated_at = iso_now(clock)
        malformed_diagnostics: list[dict[str, Any]] = []

        def on_malformed(path: Path, line_no: int, error: str) -> None:
            malformed_diagnostics.append(
                {
                    "timestamp": migrated_at,
                    "source": str(path),
                    "line": line_no,
                    "error": error,
                }
            )

        migration_report = migrate_legacy_jsonl(
            paths.sessions,
            repository,
            migrated_at=migrated_at,
            on_malformed=on_malformed,
        )
        if malformed_diagnostics:
            migration_log = paths.logs / "event-migration.jsonl"
            with migration_log.open("a", encoding="utf-8", newline="\n") as handle:
                for diagnostic in malformed_diagnostics:
                    handle.write(
                        json.dumps(
                            diagnostic,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                    )
                    handle.write("\n")

        sid = session_id or uuid4().hex
        started = iso_now(clock)
        stamp = clock().astimezone().strftime("%Y%m%d-%H%M%S")
        directory = paths.sessions / f"{stamp}-{sid[:8]}"
        suffix = 0
        candidate = directory
        while candidate.exists():
            suffix += 1
            candidate = paths.sessions / f"{stamp}-{sid[:8]}-{suffix}"
        directory = candidate
        directory.mkdir(parents=True)

        session = SessionInfo(
            session_id=sid,
            started_at=started,
            directory=directory,
            metadata_path=directory / "metadata.json",
            raw_speech_path=directory / "raw-speech.jsonl",
            context_diagnostics_path=directory / "capture-context.jsonl",
            legacy_events_path=directory / "events.jsonl",
            runtime_log_path=directory / "runtime.log",
        )
        payload = {
            "sessionId": sid,
            "startedAt": started,
            "game": "Diablo IV",
            "captureBackend": "NVDA",
            "eventBackend": "sqlite",
            "eventsDb": str(paths.events_db),
            "legacyMigration": {
                "filesScanned": migration_report.files_scanned,
                "filesSkipped": migration_report.files_skipped,
                "rowsImported": migration_report.rows_imported,
                "duplicateRows": migration_report.duplicate_rows,
                "malformedRows": migration_report.malformed_rows,
            },
            "silent": silent,
            **(metadata or {}),
        }
        atomic_write_json(session.metadata_path, payload)
        return cls(
            paths=paths,
            session=session,
            repository=repository,
            clock=clock,
            migration_report=migration_report,
        )

    def emit(self, event_type: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.emit_batch([EventDraft(event_type, data or {})])[0]

    def emit_batch(self, drafts: Iterable[EventDraft]) -> list[dict[str, Any]]:
        events: list[EventEnvelope] = []
        for draft in drafts:
            validate_event_draft(draft)
            timestamp = draft.timestamp or iso_now(self._clock)
            events.append(
                EventEnvelope(
                    event_seq=self._next_seq,
                    type=draft.type,
                    timestamp=timestamp,
                    session_id=self.session.session_id,
                    data=dict(draft.data),
                )
            )
            self._next_seq += 1
        if not events:
            return []
        try:
            self.repository.append_batch(events)
        except Exception:
            self._next_seq -= len(events)
            raise

        for event in events:
            if event.type.startswith("runtime."):
                detail = str(event.data.get("detail") or "")
                with self.session.runtime_log_path.open(
                    "a", encoding="utf-8", newline="\n"
                ) as log:
                    log.write(
                        f"[{event.timestamp}] {event.type} {detail}".rstrip() + "\n"
                    )
        return [event.as_dict() for event in events]

    @staticmethod
    def capture_draft(capture: dict[str, Any]) -> EventDraft:
        timestamp = str(capture.get("timestamp") or "") or None
        return EventDraft(
            "speech.raw",
            {
                "captureSessionId": capture.get("sessionId"),
                "captureSequence": capture.get("sequence"),
                "process": capture.get("process"),
                "processId": capture.get("processId"),
                "contextSource": capture.get("contextSource"),
                "windowTitle": capture.get("windowTitle"),
                "text": capture.get("text"),
                "rawSpeech": capture.get("rawSpeech") or [],
            },
            timestamp=timestamp,
        )

    def ingest_capture(self, capture: dict[str, Any]) -> dict[str, Any]:
        return self.emit_batch([self.capture_draft(capture)])[0]

    def read_after(self, after_seq: int, *, limit: int = 1000) -> list[dict[str, Any]]:
        return [
            event.as_dict()
            for event in self.repository.read_after(
                self.session.session_id,
                after_seq,
                limit=limit,
            )
        ]

    def close(self) -> None:
        self.repository.close()
