import json

from d4planner.runtime.events.migration import migrate_legacy_jsonl
from d4planner.runtime.events.repository import SQLiteEventRepository
from d4planner.runtime.store import RuntimePaths


def envelope(seq: int) -> dict:
    return {
        "eventSeq": seq,
        "type": "speech.raw",
        "timestamp": f"2026-10-08T22:00:00.{seq:03}+07:00",
        "sessionId": "legacy-session",
        "data": {"text": f"line-{seq}"},
    }


def test_legacy_jsonl_migration_is_idempotent_and_preserves_file(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    session = paths.sessions / "legacy"
    session.mkdir()
    source = session / "events.jsonl"
    source.write_text(
        json.dumps(envelope(1)) + "\n"
        + "{not-json}\n"
        + json.dumps(envelope(2)) + "\n",
        encoding="utf-8",
    )

    diagnostics = []
    repo = SQLiteEventRepository(paths.events_db)
    try:
        first = migrate_legacy_jsonl(
            paths.sessions,
            repo,
            migrated_at="2026-10-09T03:00:00.000+07:00",
            on_malformed=lambda path, line, error: diagnostics.append((path, line, error)),
        )
        assert first.files_scanned == 1
        assert first.rows_imported == 2
        assert first.malformed_rows == 1
        assert len(diagnostics) == 1
        assert source.exists()

        second = migrate_legacy_jsonl(
            paths.sessions,
            repo,
            migrated_at="2026-10-09T03:01:00.000+07:00",
        )
        assert second.files_skipped == 1
        assert second.rows_imported == 0

        rows = repo.read_after("legacy-session", 0)
        assert [row.event_seq for row in rows] == [1, 2]
    finally:
        repo.close()


def test_changed_legacy_file_rescans_without_duplicate_rows(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    session = paths.sessions / "legacy"
    session.mkdir()
    source = session / "events.jsonl"
    source.write_text(
        json.dumps(envelope(1)) + "\n" + json.dumps(envelope(2)) + "\n",
        encoding="utf-8",
    )

    repo = SQLiteEventRepository(paths.events_db)
    try:
        migrate_legacy_jsonl(
            paths.sessions,
            repo,
            migrated_at="2026-10-09T03:00:00.000+07:00",
        )
        with source.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(envelope(3)) + "\n")

        report = migrate_legacy_jsonl(
            paths.sessions,
            repo,
            migrated_at="2026-10-09T03:01:00.000+07:00",
        )
        assert report.files_scanned == 1
        assert report.rows_imported == 1
        assert report.duplicate_rows == 2
        assert [row.event_seq for row in repo.read_after("legacy-session", 0)] == [1, 2, 3]
    finally:
        repo.close()
