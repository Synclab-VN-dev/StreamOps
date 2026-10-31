from d4planner.capture.core import CaptureEvent, JsonlWriter, read_jsonl


def _event(sequence=1):
    return CaptureEvent(
        session_id="test",
        sequence=sequence,
        timestamp="2026-10-04T19:30:21.123+07:00",
        process="diablo iv",
        window_title="Diablo IV",
        text='Critical Strike "Chance"\n+12.5%',
        raw_speech=["Critical Strike Chance", "+12.5%"],
        process_id=1234,
        context_source="win32Foreground",
    )


def test_jsonl_round_trip_preserves_content(tmp_path):
    path = tmp_path / "capture" / "raw.jsonl"
    writer = JsonlWriter(path)
    assert writer.write(_event())

    events = read_jsonl(path)
    assert len(events) == 1
    assert events[0]["sequence"] == 1
    assert events[0]["text"] == 'Critical Strike "Chance"\n+12.5%'
    assert events[0]["rawSpeech"] == ["Critical Strike Chance", "+12.5%"]
    assert events[0]["processId"] == 1234
    assert events[0]["contextSource"] == "win32Foreground"


def test_legacy_capture_event_without_additive_context_fields_still_serializes():
    event = CaptureEvent(
        session_id="legacy",
        sequence=1,
        timestamp="2026-10-04T19:30:21.123+07:00",
        process="diablo iv",
        window_title="Diablo IV",
        text="Diablo IV",
        raw_speech=["Diablo IV"],
    )
    assert event.as_json_dict()["processId"] is None
    assert event.as_json_dict()["contextSource"] is None


def test_writer_appends_instead_of_truncating(tmp_path):
    path = tmp_path / "raw.jsonl"
    writer = JsonlWriter(path)
    assert writer.write(_event(1))
    assert writer.write(_event(2))
    assert [event["sequence"] for event in read_jsonl(path)] == [1, 2]


def test_writer_failure_is_isolated(tmp_path):
    directory = tmp_path / "directory"
    directory.mkdir()
    writer = JsonlWriter(directory)
    assert writer.write(_event()) is False
