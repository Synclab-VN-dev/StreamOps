import sqlite3

import pytest

from d4planner.runtime.events.model import EventEnvelope
from d4planner.runtime.events.repository import EventLogReader, SQLiteEventRepository


def event(seq: int, *, session: str = "s", kind: str = "speech.raw") -> EventEnvelope:
    return EventEnvelope(
        event_seq=seq,
        type=kind,
        timestamp=f"2026-10-09T03:00:00.{seq:03}+07:00",
        session_id=session,
        data={"seq": seq},
    )


def test_repository_uses_wal_and_round_trips_ordered_events(tmp_path):
    path = tmp_path / "events.db"
    repo = SQLiteEventRepository(path)
    try:
        assert repo.journal_mode() == "wal"
        assert repo.append_batch([event(1), event(2), event(3)]) == 3
        rows = repo.read_after("s", 0)
        assert [row.event_seq for row in rows] == [1, 2, 3]
        assert [row.data["seq"] for row in rows] == [1, 2, 3]
    finally:
        repo.close()


def test_unique_session_sequence_rejects_duplicate_without_ignore(tmp_path):
    repo = SQLiteEventRepository(tmp_path / "events.db")
    try:
        repo.append_batch([event(1)])
        with pytest.raises(sqlite3.IntegrityError):
            repo.append_batch([event(1)])
        assert repo.append_batch([event(1)], ignore_duplicates=True) == 0
    finally:
        repo.close()


def test_reader_observes_committed_writes_while_writer_stays_open(tmp_path):
    path = tmp_path / "events.db"
    writer = SQLiteEventRepository(path)
    reader = EventLogReader(path)
    try:
        writer.append_batch([event(1)])
        assert [row.event_seq for row in reader.read_after("s", 0)] == [1]

        writer.append_batch([event(2), event(3)])
        assert [row.event_seq for row in reader.read_after("s", 1)] == [2, 3]
        assert reader.max_sequence("s") == 3
    finally:
        reader.close()
        writer.close()


def test_large_batch_preserves_sequence_without_missing_rows(tmp_path):
    repo = SQLiteEventRepository(tmp_path / "events.db")
    try:
        events = [event(seq) for seq in range(1, 501)]
        assert repo.append_batch(events) == 500
        rows = repo.read_after("s", 0, limit=1000)
        assert [row.event_seq for row in rows] == list(range(1, 501))
    finally:
        repo.close()


def test_schema_initialization_is_idempotent(tmp_path):
    path = tmp_path / "events.db"
    first = SQLiteEventRepository(path)
    first.append_batch([event(1)])
    first.close()

    second = SQLiteEventRepository(path)
    try:
        assert second.journal_mode() == "wal"
        second.append_batch([event(2)])
        assert [row.event_seq for row in second.read_after("s", 0)] == [1, 2]
    finally:
        second.close()


def test_event_envelope_round_trip_preserves_all_fields(tmp_path):
    repo = SQLiteEventRepository(tmp_path / "events.db")
    original = EventEnvelope(
        event_seq=7,
        type="input.marker.raw",
        timestamp="2026-10-09T03:10:00.123+07:00",
        session_id="session-x",
        data={
            "source": "steamInput",
            "device": "keyboard",
            "key": "F11",
            "virtualKey": 122,
            "state": "down",
            "process": "diablo iv",
            "processId": 1280,
            "contextSource": "win32Foreground",
            "windowTitle": "Diablo IV",
            "nested": {"unicode": "đúng"},
        },
    )
    try:
        repo.append_batch([original])
        loaded = repo.read_after("session-x", 0)[0]
        assert loaded.as_dict() == original.as_dict()
    finally:
        repo.close()
