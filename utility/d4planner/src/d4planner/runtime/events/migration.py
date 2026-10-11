"""Idempotent migration of legacy per-session events.jsonl files."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable

from .model import EventEnvelope
from .repository import SQLiteEventRepository


@dataclass(frozen=True, slots=True)
class MigrationReport:
    files_scanned: int = 0
    files_skipped: int = 0
    rows_imported: int = 0
    duplicate_rows: int = 0
    malformed_rows: int = 0


def migrate_legacy_jsonl(
    sessions_root: Path,
    repository: SQLiteEventRepository,
    *,
    migrated_at: str,
    on_malformed: Callable[[Path, int, str], None] | None = None,
) -> MigrationReport:
    scanned = skipped = imported = duplicates = malformed = 0
    if not sessions_root.exists():
        return MigrationReport()

    for path in sorted(sessions_root.glob("*/events.jsonl")):
        try:
            stat = path.stat()
        except OSError:
            continue
        source = str(path.resolve())
        state = repository.migration_state(source)
        if (
            state is not None
            and int(state["size_bytes"]) == int(stat.st_size)
            and int(state["mtime_ns"]) == int(stat.st_mtime_ns)
        ):
            skipped += 1
            continue

        scanned += 1
        valid: list[EventEnvelope] = []
        bad = 0
        try:
            handle = path.open("r", encoding="utf-8")
        except OSError:
            continue
        with handle:
            for line_no, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                    if not isinstance(raw, dict):
                        raise ValueError("event is not an object")
                    event = EventEnvelope.from_dict(raw)
                    if event.event_seq <= 0 or not event.session_id or not event.type:
                        raise ValueError("missing required event identity")
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                    bad += 1
                    if on_malformed is not None:
                        on_malformed(path, line_no, str(exc))
                    continue
                valid.append(event)

        inserted = repository.append_batch(valid, ignore_duplicates=True)
        imported += inserted
        duplicates += max(0, len(valid) - inserted)
        malformed += bad
        repository.record_migration(
            source_path=source,
            size_bytes=int(stat.st_size),
            mtime_ns=int(stat.st_mtime_ns),
            imported_rows=inserted,
            malformed_rows=bad,
            migrated_at=migrated_at,
        )

    return MigrationReport(
        files_scanned=scanned,
        files_skipped=skipped,
        rows_imported=imported,
        duplicate_rows=duplicates,
        malformed_rows=malformed,
    )
