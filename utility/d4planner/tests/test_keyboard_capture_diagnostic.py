"""Offline CI coverage for the isolated F11 suppression diagnostic (#82)."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import d4planner.keyboard_capture_diagnostic as diag

import pytest

from d4planner.keyboard_capture_diagnostic import (
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


def test_diagnostic_event_identifies_off_target_without_suppression():
    sample = F11Sample(
        timestamp_ms=1_800_000_000_000,
        message=WM_KEYUP,
        state="up",
        flags=0x10,
        foreground_pid=4242,
        suppressed=False,
        target_match=False,
    )
    obj = sample.as_dict()
    assert obj["foregroundPid"] == 4242
    assert obj["targetMatch"] is False
    assert obj["suppressed"] is False
    assert obj["injected"] is True


def test_diagnostic_event_allows_unknown_foreground():
    obj = F11Sample(
        timestamp_ms=1_800_000_000_000,
        message=WM_SYSKEYDOWN,
        state="down",
        flags=0,
        foreground_pid=None,
        suppressed=False,
        target_match=False,
    ).as_dict()
    assert obj["foregroundPid"] is None
    assert obj["targetMatch"] is False


def test_scheduled_task_command_contains_interactive_user_and_reliable_worker():
    script = diag.scheduled_task_script(
        task_name="D4Planner-F11-Diagnostic-abcd",
        python_exe=r"C:\Program Files\Python312\python.exe",
        script_path=r"C:\Users\Bob's PC\StreamOps-82\keyboard_capture_diagnostic.py",
        game_pid=14872, seconds=60.0, block=True,
        jsonl=True, diagnose=True,
        log_path=Path(r"C:\Users\Bob's PC\AppData\Local\d4planner\keyboard-diagnostic\log.txt"),
    )
    assert "New-ScheduledTaskPrincipal -UserId $u -LogonType Interactive" in script
    assert "Start-ScheduledTask" in script
    assert "Register-ScheduledTask" in script
    assert "--interactive-worker" in script
    assert "--block" in script
    assert "--diagnose" in script
    assert "Bob''s PC" in script  # correctly escaped in PowerShell string
    assert "D4Planner-F11-Diagnostic-abcd" in script


def test_scheduled_task_nonblocking_does_not_enable_suppression():
    script = diag.scheduled_task_script(
        task_name="DIAGNOSTIC", python_exe="python.exe", script_path="probe.py",
        game_pid=14872, seconds=10, block=False, jsonl=False,
        diagnose=False, log_path=Path("diag.log"),
    )
    assert "--block" not in script
    assert "--diagnose" not in script
    assert "--interactive-worker" in script


def test_interactive_worker_rejects_wrong_session_without_hook(tmp_path, monkeypatch):
    monkeypatch.setattr(diag, "process_session_id",
                        lambda pid: 1 if pid == 14872 else 0)
    monkeypatch.setattr(diag, "active_console_session_id", lambda: 1)
    monkeypatch.setattr(diag, "run_diagnostic",
                        lambda **kwargs: pytest.fail("hook should not be called"))
    output = tmp_path / "worker.log"
    rc = diag._run_interactive_worker(
        pid=14872, seconds=5, block=True, jsonl=False,
        diagnose=False, output=output,
    )
    assert rc == 2
    content = output.read_text(encoding="utf-8")
    assert "DIAGNOSTIC_SESSION worker=0 game=1 active=1" in content
    assert "DIAGNOSTIC ERROR:" in content
    assert "F11_DIAGNOSTIC_COMPLETE status=2" in content


def test_interactive_worker_writes_terminal_marker_after_diagnostic(tmp_path, monkeypatch):
    monkeypatch.setattr(diag, "process_session_id", lambda pid: 1)
    monkeypatch.setattr(diag, "active_console_session_id", lambda: 1)
    monkeypatch.setattr(diag, "run_diagnostic",
                        lambda **kwargs: print("F11 DOWN") or 0)
    output = tmp_path / "worker.log"
    assert diag._run_interactive_worker(
        pid=14872, seconds=5, block=False, jsonl=False,
        diagnose=False, output=output,
    ) == 0
    lines = output.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "DIAGNOSTIC_SESSION worker=1 game=1 active=1"
    assert lines[-2:] == ["F11 DOWN", "F11_DIAGNOSTIC_COMPLETE status=0"]


def test_remote_ssh_relay_echoes_worker_and_cleans_up(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(diag, "process_session_id",
                        lambda pid: 1 if pid == 14872 else 0)
    monkeypatch.setattr(diag, "active_console_session_id", lambda: 1)
    monkeypatch.setattr(
        diag, "remote_log_path",
        lambda request_id: tmp_path / f"{request_id}.log",
    )
    executed = []

    def fake_powershell(code, **kwargs):
        executed.append(code)
        if "Register-ScheduledTask" in code:
            files = list(tmp_path.glob("*.log"))
            if not files:
                # Build the path from the assigned task name (request UUID).
                import re
                request_id = re.search(
                    r"D4Planner-F11-Diagnostic-([a-f0-9]{16})", code
                ).group(1)
                path = tmp_path / f"{request_id}.log"
                path.write_text(
                    "DIAGNOSTIC_SESSION worker=1 game=1 active=1\n"
                    "F11 DOWN suppressed=False\n"
                    "F11_DIAGNOSTIC_COMPLETE status=0\n",
                    encoding="utf-8",
                )

    monkeypatch.setattr(diag, "_run_powershell", fake_powershell)
    result = diag._relay_ssh_to_interactive(
        pid=14872, seconds=30, block=False, jsonl=False, diagnose=True,
    )
    assert result == 0
    out = capsys.readouterr().out
    assert "control_session=0 game_session=1" in out
    assert "F11 DOWN suppressed=False" in out
    assert "LOG_PATH:" in out
    assert len(executed) == 2
    assert "Stop-ScheduledTask" in executed[1]
    assert "Unregister-ScheduledTask" in executed[1]


def test_remote_relay_rejects_inactive_game_session_before_registering(monkeypatch):
    monkeypatch.setattr(diag, "process_session_id",
                        lambda pid: 1 if pid == 14872 else 0)
    monkeypatch.setattr(diag, "active_console_session_id", lambda: 3)
    monkeypatch.setattr(diag, "_run_powershell",
                        lambda *a, **kw: pytest.fail("cannot start task"))
    with pytest.raises(RuntimeError, match="not active"):
        diag._relay_ssh_to_interactive(
            pid=14872, seconds=30, block=True, jsonl=False, diagnose=False,
        )


def test_remote_ssh_main_auto_relays_instead_of_hooking_session_zero(monkeypatch):
    monkeypatch.setattr(diag, "require_game_pid", lambda pid: None)
    monkeypatch.setattr(diag, "process_session_id",
                        lambda pid: 1 if pid == 14872 else 0)
    monkeypatch.setattr(diag, "_relay_ssh_to_interactive",
                        lambda **kwargs: 0 if kwargs["block"] else 1)
    monkeypatch.setattr(diag, "run_diagnostic",
                        lambda **kwargs: pytest.fail("do not hook session 0"))
    assert diag.main(["--pid", "14872", "--seconds", "30", "--block"]) == 0
