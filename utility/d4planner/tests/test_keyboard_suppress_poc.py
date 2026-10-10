"""Offline CI coverage for the isolated F11 suppression POC (#82)."""
from __future__ import annotations

from dataclasses import replace

import pytest

from d4planner.poc_keyboard_suppress import (
    BoundedSamples,
    F11Sample,
    HC_ACTION,
    VK_F11,
    WM_KEYDOWN,
    WM_KEYUP,
    WM_SYSKEYDOWN,
    WM_SYSKEYUP,
    capture_or_pass,
    decide_f11,
    safe_capture_or_pass,
)


@pytest.mark.parametrize("message,expected", [
    (WM_KEYDOWN, "down"),
    (WM_KEYUP, "up"),
    (WM_SYSKEYDOWN, "down"),
    (WM_SYSKEYUP, "up"),
])
@pytest.mark.parametrize("block", [False, True])
def test_f11_action_down_up_syskey_are_captured_and_maybe_blocked(message, expected, block):
    decision = decide_f11(
        n_code=HC_ACTION, message=message, vk=VK_F11,
        foreground_pid=1444, game_pid=1444, block=block,
    )
    assert decision.capture
    assert decision.state == expected
    assert decision.suppress is block


@pytest.mark.parametrize("changes", [
    {"n_code": -1},
    {"n_code": 1},
    {"message": 0x1001},
    {"vk": 0x41},
    {"foreground_pid": 1445},
    {"foreground_pid": None},
    {"game_pid": 0},
])
def test_scope_guard_fails_open(changes):
    args = dict(
        n_code=HC_ACTION, message=WM_KEYDOWN, vk=VK_F11,
        foreground_pid=1444, game_pid=1444, block=True,
    )
    args.update(changes)
    assert decide_f11(**args).capture is False
    assert decide_f11(**args).suppress is False


def test_observe_captures_without_suppressing_event_and_preserves_flags():
    samples = BoundedSamples()
    blocked = capture_or_pass(
        n_code=HC_ACTION, message=WM_KEYDOWN, vk=VK_F11,
        flags=0x10, foreground_pid=1444, game_pid=1444,
        block=False, samples=samples, timestamp_ms=1_800_000_000_000,
    )
    assert blocked is False
    events = samples.drain()
    assert len(events) == 1
    assert events[0].state == "down"
    assert events[0].suppressed is False
    assert events[0].as_dict()["injected"] is True
    assert events[0].as_dict()["flags"] == "0x10"
    assert samples.drain() == []


def test_block_captures_both_edges_without_swallowing_gamepad_events():
    samples = BoundedSamples()
    for message in [WM_KEYDOWN, WM_KEYDOWN, WM_KEYUP]:
        assert capture_or_pass(
            n_code=HC_ACTION, message=message, vk=VK_F11,
            flags=0, foreground_pid=1444, game_pid=1444,
            block=True, samples=samples, timestamp_ms=1_800_000_000_000,
        )
    events = samples.drain()
    assert [event.state for event in events] == ["down", "down", "up"]
    assert all(event.suppressed for event in events)
    # Gamepad is neither decoded nor intercepted by this keyboard-only API.


def test_other_foreground_and_other_keyboard_vk_not_recorded_even_block_mode():
    samples = BoundedSamples()
    assert not capture_or_pass(
        n_code=HC_ACTION, message=WM_KEYUP, vk=VK_F11, flags=0,
        foreground_pid=933, game_pid=1444,
        block=True, samples=samples, timestamp_ms=1234,
    )
    assert not capture_or_pass(
        n_code=HC_ACTION, message=WM_KEYUP, vk=0x41, flags=0,
        foreground_pid=1444, game_pid=1444,
        block=True, samples=samples, timestamp_ms=1234,
    )
    assert samples.drain() == []


def test_bounded_fifo_queue_counts_drops_on_burst():
    q = BoundedSamples(capacity=2)
    sample = F11Sample(1_800_000_000_000, WM_KEYDOWN, "down", 0, 1444, True)
    q.append(sample)
    q.append(replace(sample, timestamp_ms=1_800_000_000_001))
    q.append(replace(sample, timestamp_ms=1_800_000_000_002))
    assert q.dropped == 1
    assert [s.timestamp_ms for s in q.drain()] == [
        1_800_000_000_001, 1_800_000_000_002,
    ]
    with pytest.raises(ValueError):
        BoundedSamples(capacity=0)


def test_failure_to_queue_is_fail_open():
    class FailingSink:
        def append(self, sample):
            raise RuntimeError("synthetic queue failure")

    assert safe_capture_or_pass(
        n_code=HC_ACTION, message=WM_KEYDOWN, vk=VK_F11,
        flags=0, foreground_pid=1444, game_pid=1444, block=True,
        samples=FailingSink(), timestamp_ms=1234,
    ) is False


def test_default_policy_is_pass_through_even_targeted():
    # These assertions form a CI gate to stop accidental default suppression.
    assert decide_f11(
        n_code=0, message=WM_KEYDOWN, vk=VK_F11,
        foreground_pid=1444, game_pid=1444, block=False,
    ).suppress is False
