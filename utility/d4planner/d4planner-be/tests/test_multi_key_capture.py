"""Issue #87: one multi-key hook produces configured marker evidence."""
from d4planner.controller import load_profile
from d4planner.runtime.input_marker import HookInputMarkerCapture
from d4planner.runtime.keyboard_hook import BoundedSamples, F11Sample, WM_KEYDOWN, WM_KEYUP
import time


class FakeMultiHook:
    def __init__(self, game_pid, block, virtual_keys):
        self.game_pid, self.block, self.virtual_keys = game_pid, block, virtual_keys
        self.samples = BoundedSamples()
        self.hook_errors = 0
        self.pending = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def set_target_pid(self, pid):
        self.game_pid = int(pid or 0)

    def pump(self):
        for vk, direction in self.pending:
            self.samples.append(F11Sample(
                timestamp_ms=1_800_000_000_000,
                message=WM_KEYDOWN if direction == "down" else WM_KEYUP,
                state=direction, flags=0, foreground_pid=self.game_pid,
                suppressed=self.block, virtual_key=vk,
            ))
        self.pending.clear()
        return True


def test_one_hook_captures_16_keys_observe_and_block():
    profile = load_profile("xbox16")
    for block in (True, False):
        hook = FakeMultiHook(0, block, frozenset(x.virtual_key for x in profile.digital))
        capture = HookInputMarkerCapture(profile=profile, block=block,
                                         poll_interval=.001,
                                         backend_factory=lambda **kw: hook)
        capture.set_target_pid(5555)
        capture.start()
        hook.pending.extend((d.virtual_key, edge)
                            for d in profile.digital for edge in ("down", "up"))
        events = []
        deadline = time.monotonic() + 2
        while len(events) < 32 and time.monotonic() < deadline:
            events.extend(capture.drain())
            time.sleep(.003)
        capture.stop()
        assert hook.closed
        assert len(events) == 32
        assert {e.control_id for e in events} == {b.control_id for b in profile.digital}
        assert all(e.layout_id == profile.layout_id for e in events)
        assert all(e.mapping_source == "configuredLayout" for e in events)
        assert all(e.suppressed == block for e in events)
        assert [e.state for e in events] == ["down","up"] * 16


def test_unknown_key_never_attributed_to_controller():
    capture = HookInputMarkerCapture(profile=load_profile("xbox16"))
    sample = F11Sample(0, WM_KEYDOWN, "down", 0, 1, True, virtual_key=0x41)
    assert capture._convert_sample(sample) is None



def test_supervisor_ingress_queue_overflow_never_silent():
    profile = load_profile("xbox16")
    backend = FakeMultiHook(
        0, True, frozenset(x.virtual_key for x in profile.digital)
    )
    capture = HookInputMarkerCapture(
        profile=profile, block=True, poll_interval=.001,
        sample_capacity=2, backend_factory=lambda **kw: backend,
    )
    capture.set_target_pid(5555)
    capture.start()
    backend.pending.extend((d.virtual_key, "down") for d in profile.digital[:3])
    deadline = time.monotonic() + 2
    while capture._running and time.monotonic() < deadline:
        time.sleep(.002)
    assert not capture._running
    assert capture.dropped_count >= 1
    assert capture.overflowed
    assert "adapter queue overflow" in (capture.consume_error() or "")
    assert len(capture.drain()) == 2
    assert backend.closed
    capture.stop()
