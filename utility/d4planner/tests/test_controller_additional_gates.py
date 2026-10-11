"""Issue #87: deterministic corner-case coverage for controller inputs.

All tests are safe without Steam, Diablo IV, NVDA or Win32 hooks.
"""
from __future__ import annotations

import io
import threading

import pytest

from d4planner.controller import ProfileValidationError, load_profile
from d4planner.controller.contract import EXPECTED_DIGITAL
from d4planner.controller import profiles as packaged
from d4planner.runtime.input_marker import HookInputMarkerCapture
from d4planner.runtime.keyboard_hook import (
    BoundedSamples, F11Sample, WM_KEYDOWN, WM_KEYUP,
    WM_SYSKEYDOWN, WM_SYSKEYUP, capture_or_pass, EdgeFilter,
)


def test_malformed_packaged_json_is_a_typed_error(monkeypatch):
    class InvalidResource:
        def joinpath(self, _name):
            return self

        def open(self, *_args, **_kwargs):
            return io.StringIO('{"layoutId":"xbox-steaminput-18-v1",')

    monkeypatch.setattr(packaged, "files", lambda _pkg: InvalidResource())
    with pytest.raises(ProfileValidationError, match="cannot load packaged profile"):
        packaged.load_profile("xbox16")


def test_all_16_down_up_including_system_keys_and_us_punctuation():
    profile = load_profile("xbox16")
    assert profile.configured_count == 16
    assert {
        entry.control_id: (entry.key, entry.virtual_key)
        for entry in profile.digital
    } == EXPECTED_DIGITAL
    assert [
        (entry.control_id, entry.key, entry.virtual_key)
        for entry in profile.digital[-4:]
    ] == [
        ("DPAD_UP", "[", 0xDB),
        ("DPAD_DOWN", "]", 0xDD),
        ("DPAD_LEFT", "\\", 0xDC),
        ("DPAD_RIGHT", "`", 0xC0),
    ]
    keys = frozenset(entry.virtual_key for entry in profile.digital)
    queue = BoundedSamples(capacity=32)
    for i, entry in enumerate(profile.digital):
        down = WM_SYSKEYDOWN if i % 2 else WM_KEYDOWN
        up = WM_SYSKEYUP if i % 2 else WM_KEYUP
        for message in (down, up):
            suppressed = capture_or_pass(
                n_code=0, message=message,
                vk=entry.virtual_key, flags=0,
                foreground_pid=111, game_pid=111, block=True,
                samples=queue, timestamp_ms=i * 10 + (message in (WM_KEYUP, WM_SYSKEYUP)),
                virtual_keys=keys, scan_code=i,
            )
            assert suppressed is True
    rows = queue.drain()
    assert len(rows) == 32
    assert queue.dropped == 0
    assert [row.virtual_key for row in rows] == [
        entry.virtual_key for entry in profile.digital for _ in range(2)
    ]
    assert [row.state for row in rows] == ["down", "up"] * 16


def test_repeated_down_and_spurious_up_are_independent_by_control():
    keys = [entry.virtual_key for entry in load_profile("xbox16").digital]
    edges = EdgeFilter()
    for key in keys:
        assert not edges.accept(key, "up")
        assert edges.accept(key, "down")
        assert not edges.accept(key, "down")  # WM_KEYDOWN auto-repeat
    for key in reversed(keys):
        assert edges.accept(key, "up")
        assert not edges.accept(key, "up")
    for key in keys:
        assert edges.accept(key, "down")
    edges.reset()
    for key in keys:
        assert edges.accept(key, "down")


def test_native_adapter_unhooks_before_draining_release_tail():
    """A release queued during __exit__ must survive stop/unhook and drain."""
    profile = load_profile("xbox16")
    key = profile.digital[0].virtual_key
    pumped = threading.Event()

    class UnhookTailBackend:
        hook_errors = 0

        def __init__(self, **kw):
            self.samples = BoundedSamples(10)
            self.game_pid = kw["game_pid"]
            self.block = kw["block"]
            self.keys = kw["virtual_keys"]
            self.closed = False
            self.emitted = False

        def set_target_pid(self, pid):
            self.game_pid = pid

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            self.closed = True
            self.samples.append(F11Sample(
                timestamp_ms=1800000000001, message=WM_KEYUP, state="up",
                flags=0, foreground_pid=9001, suppressed=True, virtual_key=key,
            ))

        def pump(self):
            if not self.emitted:
                self.emitted = True
                self.samples.append(F11Sample(
                    timestamp_ms=1800000000000, message=WM_KEYDOWN, state="down",
                    flags=0, foreground_pid=9001, suppressed=True, virtual_key=key,
                ))
                pumped.set()
            return True

    hook = UnhookTailBackend(
        game_pid=9001, block=True,
        virtual_keys=frozenset(item.virtual_key for item in profile.digital),
    )
    capture = HookInputMarkerCapture(
        profile=profile, block=True,
        backend_factory=lambda **_kw: hook, poll_interval=0.005,
    )
    capture.set_target_pid(9001)
    capture.start()
    assert pumped.wait(1.0)
    capture.stop()
    assert hook.closed
    tail = capture.drain()
    assert [row.state for row in tail] == ["down", "up"]
    assert [row.control_id for row in tail] == ["A", "A"]
    assert capture.drain() == []
    assert capture.dropped_count == 0


def test_vk_punctuation_scan_code_diagnostics_not_claimed_steam_origin():
    profile = load_profile("xbox16")
    from d4planner.runtime.keyboard_hook import F11Sample
    for control, vk, scan in [
        ("DPAD_UP", 0xDB, 0x1A),
        ("DPAD_DOWN", 0xDD, 0x1B),
        ("DPAD_LEFT", 0xDC, 0x2B),
        ("DPAD_RIGHT", 0xC0, 0x29),
    ]:
        capture = HookInputMarkerCapture(profile=profile, block=True)
        sample = F11Sample(
            timestamp_ms=1800000000000, message=WM_KEYDOWN,
            state="down", flags=0x10, foreground_pid=9001,
            suppressed=True, virtual_key=vk, scan_code=scan,
        )
        result = capture._convert_sample(sample)
        assert result is not None and result.control_id == control
        draft = result.as_draft()
        assert draft.data["scanCode"] == scan
        assert draft.data["virtualKey"] == vk
        assert draft.data["mappingSource"] == "configuredLayout"
        assert draft.data.get("physicalSteamVerified") is None



def test_capture_restart_is_fresh_and_never_replays_prior_key_edges():
    profile = load_profile("xbox16")
    a_vk = profile.digital[0].virtual_key
    hooks = []

    class OneShot:
        hook_errors = 0

        def __init__(self, **kw):
            self.samples = BoundedSamples(capacity=8)
            self.closed = False
            self.sent = threading.Event()
            self.target_pid = kw["game_pid"]
            hooks.append(self)

        def set_target_pid(self, pid):
            self.target_pid = pid

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            self.closed = True

        def pump(self):
            if not self.sent.is_set():
                for msg, direction in ((WM_KEYDOWN, "down"), (WM_KEYUP, "up")):
                    self.samples.append(F11Sample(
                        timestamp_ms=1800000000000, message=msg,
                        state=direction, flags=0, foreground_pid=self.target_pid,
                        suppressed=True, virtual_key=a_vk,
                    ))
                self.sent.set()
            return True

    capture = HookInputMarkerCapture(
        profile=profile, block=True, poll_interval=0.002,
        backend_factory=lambda **kwargs: OneShot(**kwargs),
    )
    capture.set_target_pid(9001)
    for index in range(2):
        capture.start()
        assert hooks[-1].sent.wait(1.0)
        capture.stop()
        assert hooks[-1].closed
        assert len(hooks) == index + 1
        assert [row.state for row in capture.drain()] == ["down", "up"]
        assert capture.drain() == []
    assert capture.dropped_count == 0
