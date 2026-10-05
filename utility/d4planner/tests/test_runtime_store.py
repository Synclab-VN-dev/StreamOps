import json
from datetime import datetime, timezone

from d4planner.runtime.store import EventStore, RuntimePaths, read_json, write_capture_config


def test_session_store_creates_immutable_files_and_monotonic_event_stream(tmp_path):
    paths = RuntimePaths(tmp_path / "d4planner")
    instant = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)
    store = EventStore.create(
        paths,
        silent=True,
        clock=lambda: instant,
        session_id="session-one",
    )

    one = store.emit("runtime.start", {"detail": "start"})
    two = store.ingest_capture(
        {
            "sessionId": "session-one",
            "sequence": 1,
            "process": "diablo iv",
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
    rows = [json.loads(x) for x in store.session.events_path.read_text().splitlines()]
    assert [row["eventSeq"] for row in rows] == [1, 2]


def test_two_sessions_never_truncate_each_other(tmp_path):
    paths = RuntimePaths(tmp_path / "d4planner")
    first = EventStore.create(paths, silent=True, session_id="first")
    first.emit("runtime.start")
    second = EventStore.create(paths, silent=True, session_id="second")
    second.emit("runtime.start")

    assert first.session.directory != second.session.directory
    assert first.session.events_path.read_text()
    assert second.session.events_path.read_text()


def test_capture_config_points_addon_to_session_raw_file(tmp_path):
    paths = RuntimePaths(tmp_path / "d4planner")
    store = EventStore.create(paths, silent=False, session_id="s")
    write_capture_config(paths, enabled=True, session=store.session, silent=False)

    config = read_json(paths.capture_state)
    assert config["enabled"] is True
    assert config["silent"] is False
    assert config["sessionId"] == "s"
    assert config["rawSpeechPath"] == str(store.session.raw_speech_path)
    assert config["leaseUntilUnix"] > time.time()
