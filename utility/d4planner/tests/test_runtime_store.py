import json
from datetime import datetime, timezone
import time

from d4planner.runtime.events.store import EventStore
from d4planner.runtime.store import (
    RuntimePaths,
    atomic_write_json,
    read_json,
    write_capture_config,
)


def test_session_store_uses_sqlite_and_monotonic_event_stream(tmp_path):
    paths = RuntimePaths(tmp_path / "d4planner")
    instant = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)
    store = EventStore.create(
        paths,
        silent=True,
        clock=lambda: instant,
        session_id="session-one",
    )
    try:
        one = store.emit("runtime.start", {"detail": "start"})
        two = store.ingest_capture(
            {
                "sessionId": "session-one",
                "sequence": 1,
                "process": "diablo iv",
                "processId": 4321,
                "contextSource": "win32Foreground",
                "windowTitle": "Diablo IV",
                "text": "850 Item Power",
                "rawSpeech": ["850 Item Power"],
            }
        )

        assert one["eventSeq"] == 1
        assert two["eventSeq"] == 2
        metadata = read_json(store.session.metadata_path)
        assert metadata["sessionId"] == "session-one"
        assert metadata["captureBackend"] == "NVDA"
        assert metadata["eventBackend"] == "sqlite"
        assert metadata["eventsDb"] == str(paths.events_db)

        rows = store.read_after(0)
        assert [row["eventSeq"] for row in rows] == [1, 2]
        assert rows[1]["data"]["processId"] == 4321
        assert not store.session.legacy_events_path.exists()
    finally:
        store.close()


def test_two_sessions_share_db_without_truncating_each_other(tmp_path):
    paths = RuntimePaths(tmp_path / "d4planner")
    first = EventStore.create(paths, silent=True, session_id="first")
    first.emit("runtime.start")
    second = EventStore.create(paths, silent=True, session_id="second")
    second.emit("runtime.start")
    try:
        assert first.session.directory != second.session.directory
        assert [row["eventSeq"] for row in first.read_after(0)] == [1]
        assert [row["eventSeq"] for row in second.read_after(0)] == [1]
        assert paths.events_db.exists()
    finally:
        second.close()
        first.close()


def test_store_reopens_existing_session_without_reusing_sequence(tmp_path):
    paths = RuntimePaths(tmp_path / "d4planner")
    first = EventStore.create(paths, silent=True, session_id="same-session")
    first.emit("speech.raw", {"text": "one"})
    first.close()

    second = EventStore.create(paths, silent=True, session_id="same-session")
    try:
        event = second.emit("speech.raw", {"text": "two"})
        assert event["eventSeq"] == 2
        assert [row["eventSeq"] for row in second.read_after(0)] == [1, 2]
    finally:
        second.close()


def test_capture_config_points_addon_to_session_raw_file(tmp_path):
    paths = RuntimePaths(tmp_path / "d4planner")
    store = EventStore.create(paths, silent=False, session_id="s")
    try:
        write_capture_config(
            paths,
            enabled=True,
            session=store.session,
            silent=False,
            game_pid=4321,
        )

        config = read_json(paths.capture_state)
        assert config["enabled"] is True
        assert config["silent"] is False
        assert config["sessionId"] == "s"
        assert config["rawSpeechPath"] == str(store.session.raw_speech_path)
        assert config["diagnosticsPath"] == str(store.session.context_diagnostics_path)
        assert config["gamePid"] == 4321
        assert config["leaseUntilUnix"] > time.time()
    finally:
        store.close()


def test_atomic_write_json_retries_transient_access_denied(monkeypatch, tmp_path):
    import d4planner.runtime.store as store_module

    path = tmp_path / "state" / "capture.json"
    real_replace = store_module.os.replace
    calls = {"count": 0}

    def flaky_replace(source, destination):
        calls["count"] += 1
        if calls["count"] < 3:
            raise PermissionError(13, "access denied", str(destination))
        return real_replace(source, destination)

    monkeypatch.setattr(store_module.os, "replace", flaky_replace)
    monkeypatch.setattr(store_module.time, "sleep", lambda _seconds: None)

    atomic_write_json(path, {"enabled": True})

    assert calls["count"] == 3
    assert read_json(path) == {"enabled": True}
    assert list(path.parent.glob(".capture.json.*.tmp")) == []
