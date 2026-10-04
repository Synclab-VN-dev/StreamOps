from datetime import datetime, timezone

from d4planner.capture.core import (
    CaptureSession,
    flatten_speech_sequence,
    is_diablo_context,
    validate_event_order,
)


class FakeCommand:
    def __repr__(self):
        return "<FakeCommand>"


def test_flatten_preserves_text_and_non_text_tokens():
    text, raw = flatten_speech_sequence(["EQUIPPED", FakeCommand(), "STAFF OF LAM ESEN"])
    assert text == "EQUIPPED STAFF OF LAM ESEN"
    assert raw == ["EQUIPPED", "<FakeCommand>", "STAFF OF LAM ESEN"]


def test_sequence_is_monotonic_even_when_timestamp_is_identical():
    instant = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
    session = CaptureSession(session_id="poc", clock=lambda: instant)

    first = session.make_event(
        speech_sequence=["one"], process="diablo iv", window_title="Diablo IV"
    )
    second = session.make_event(
        speech_sequence=["two"], process="diablo iv", window_title="Diablo IV"
    )

    assert first.sequence == 1
    assert second.sequence == 2
    assert first.timestamp == second.timestamp
    assert validate_event_order([first.as_json_dict(), second.as_json_dict()]) == []


def test_diablo_context_is_broad_but_not_generic():
    assert is_diablo_context("diablo iv", "Diablo IV")
    assert is_diablo_context("DiabloIV", None)
    assert not is_diablo_context("chrome", "GitHub")
    assert not is_diablo_context(None, None)
