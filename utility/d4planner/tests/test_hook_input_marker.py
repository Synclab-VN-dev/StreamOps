"""Production hook backend gates: POC behavior, queue, lifecycle, no polling."""
from __future__ import annotations

from collections import deque
import time

from d4planner.runtime.input_marker import HookInputMarkerCapture, MarkerSample
from d4planner.runtime.keyboard_hook import (
    BoundedSamples, F11Sample, WM_KEYDOWN, WM_KEYUP,
)


class FakeHook:
    def __init__(self, *, game_pid: int, block: bool):
        self.game_pid = game_pid
        self.block = block
        self.hook_errors = 0
        self.samples = BoundedSamples()
        self.requests = deque()
        self.closed = False
        self.started = False
        self.targets = []

    def __enter__(self):
        self.started = True
        return self

    def __exit__(self, *_):
        self.closed = True

    def set_target_pid(self, pid):
        self.game_pid = int(pid or 0)
        self.targets.append(self.game_pid)

    def pump(self):
        while self.requests:
            pid, msg = self.requests.popleft()
            if self.game_pid and pid == self.game_pid:
                self.samples.append(F11Sample(
                    timestamp_ms=1_800_000_000_000,
                    message=msg, state="down" if msg == WM_KEYDOWN else "up",
                    flags=0x10, foreground_pid=pid,
                    suppressed=True, target_match=True,
                ))
        return True


def wait_until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(.005)
    return False


def test_hook_capture_uses_same_poc_core_and_preserves_contract():
    fake = FakeHook(game_pid=0, block=True)
    capture = HookInputMarkerCapture(
        poll_interval=.001, backend_factory=lambda **kw: fake,
    )
    capture.set_target_pid(14872)
    capture.start()
    assert fake.started
    fake.requests.extend([
        (99999, WM_KEYDOWN),
        (14872, WM_KEYDOWN), (14872, WM_KEYUP),
    ])
    observed = []
    assert wait_until(lambda: (observed.extend(capture.drain()) or len(observed) == 2))
    capture.stop()
    assert fake.closed
    assert [x.state for x in observed] == ["down", "up"]
    for sample in observed:
        draft = sample.as_draft()
        assert draft.type == "input.marker.raw"
        assert draft.data["source"] == "steamInput"
        assert draft.data["virtualKey"] == 122
        assert draft.data["suppressed"] is True
        assert draft.data["captureMethod"] == "keyboardHook"
        assert draft.data["processId"] == 14872
        assert draft.timestamp
    assert capture.consume_error() is None


def test_hook_updates_pid_without_reinstall_and_ignores_unknown_target():
    fake = FakeHook(game_pid=0, block=True)
    capture = HookInputMarkerCapture(
        poll_interval=.001, backend_factory=lambda **kw: fake,
    )
    capture.start()
    fake.requests.append((14872, WM_KEYDOWN))
    time.sleep(.02)
    assert capture.drain() == []
    capture.set_target_pid(14872)
    assert wait_until(lambda: fake.game_pid == 14872)
    fake.requests.append((14872, WM_KEYDOWN))
    first = []
    assert wait_until(lambda: (first.extend(capture.drain()) or bool(first)))
    capture.set_target_pid(22222)
    assert wait_until(lambda: fake.game_pid == 22222)
    fake.requests.extend([(14872, WM_KEYUP), (22222, WM_KEYUP)])
    second = []
    assert wait_until(lambda: (second.extend(capture.drain()) or bool(second)))
    capture.stop()
    assert len(first) == 1
    assert len(second) == 1
    assert second[0].process_id == 22222
    assert fake.closed


def test_hook_start_failure_does_not_silently_fall_back_to_polling():
    class FailingHook:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            raise OSError("SetWindowsHookExW denied")

        def __exit__(self, *_):
            pass

    capture = HookInputMarkerCapture(
        poll_interval=.001, backend_factory=FailingHook,
    )
    try:
        capture.start()
        assert False, "a failing hook must not be marked ACTIVE"
    except RuntimeError as exc:
        assert "SetWindowsHookExW denied" in str(exc)
    assert "SetWindowsHookExW denied" in (capture.consume_error() or "")
    capture.stop()


def test_hook_runtime_failure_is_reported_after_start():
    fake = FakeHook(game_pid=14872, block=True)
    capture = HookInputMarkerCapture(
        poll_interval=.001, backend_factory=lambda **kw: fake,
    )
    capture.start()
    fake.hook_errors = 1
    assert wait_until(lambda: not capture._running)
    assert "callback errors" in (capture.consume_error() or "")
    assert fake.closed
    capture.stop()


def test_marker_sample_legacy_payload_unchanged_without_block():
    legacy = MarkerSample(
        timestamp="2026-10-10T08:30:00+07:00", key="f11",
        virtual_key=122, state="DOWN", process_id=14872,
        window_title="Diablo IV",
    ).as_draft().data
    assert "suppressed" not in legacy
    assert "captureMethod" not in legacy
