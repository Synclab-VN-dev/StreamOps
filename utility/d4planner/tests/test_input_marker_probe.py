import pytest

from d4planner.runtime.input_marker import (
    InputMarkerCapture,
    MarkerSample,
    edge_transition,
    virtual_key_code,
)


def test_virtual_key_code_accepts_scroll_lock_aliases():
    assert virtual_key_code("scroll-lock") == 0x91
    assert virtual_key_code("SCROLL_LOCK") == 0x91


def test_virtual_key_code_accepts_function_keys():
    assert virtual_key_code("f1") == 0x70
    assert virtual_key_code("F11") == 0x7A
    assert virtual_key_code("f12") == 0x7B


def test_virtual_key_code_rejects_unknown_key():
    with pytest.raises(ValueError):
        virtual_key_code("f24")


def test_edge_transition_only_emits_on_change():
    assert edge_transition(False, False) is None
    assert edge_transition(False, True) == "DOWN"
    assert edge_transition(True, True) is None
    assert edge_transition(True, False) == "UP"


class FakeBackend:
    def __init__(self, *, down: bool, pid: int | None, title: str = "Diablo IV"):
        self.down = down
        self.pid = pid
        self.title = title

    def is_down(self, _virtual_key: int) -> bool:
        return self.down

    def foreground_context(self):
        return self.pid, self.title


def test_marker_capture_queues_only_edges_for_target_game_pid():
    backend = FakeBackend(down=True, pid=1280)
    capture = InputMarkerCapture(key="f11", backend=backend)
    capture.set_target_pid(1280)

    current = capture._observe(False)
    assert current is True
    samples = capture.drain()
    assert len(samples) == 1
    draft = samples[0].as_draft()
    assert draft.type == "input.marker.raw"
    assert draft.data == {
        "source": "steamInput",
        "device": "keyboard",
        "key": "F11",
        "virtualKey": 122,
        "state": "down",
        "process": "diablo iv",
        "processId": 1280,
        "contextSource": "win32Foreground",
        "windowTitle": "Diablo IV",
    }


def test_marker_capture_ignores_edge_when_diablo_is_not_foreground():
    backend = FakeBackend(down=True, pid=999)
    capture = InputMarkerCapture(key="f11", backend=backend)
    capture.set_target_pid(1280)

    assert capture._observe(False) is True
    assert capture.drain() == []


def test_marker_sample_up_serializes_lowercase_state():
    sample = MarkerSample(
        timestamp="2026-10-09T03:00:00.000+07:00",
        key="f11",
        virtual_key=122,
        state="UP",
        process_id=1280,
        window_title="Diablo IV",
    )
    draft = sample.as_draft()
    assert draft.data["state"] == "up"
    assert draft.data["key"] == "F11"
