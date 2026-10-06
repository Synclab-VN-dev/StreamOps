import os

import pytest
from datetime import datetime, timezone
import hashlib
import subprocess
import zipfile

from d4planner.runtime.model import ProcessInfo, TolkHealth
from d4planner.runtime.store import RuntimePaths, atomic_write_json
from d4planner.runtime.windows import WindowsRuntime


def fake_pe(machine: int, marker: bytes = b"controller-client") -> bytes:
    payload = bytearray(0xA0)
    payload[0:2] = b"MZ"
    payload[0x3C:0x40] = (0x80).to_bytes(4, "little")
    payload[0x80:0x84] = b"PE\x00\x00"
    payload[0x84:0x86] = int(machine).to_bytes(2, "little")
    payload[0x90:0x90 + len(marker)] = marker
    return bytes(payload)


def test_controller_checksum_validation_is_deterministic(tmp_path, monkeypatch):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    dll = paths.controller / "nvdaControllerClient64.dll"
    content = fake_pe(0x8664)
    dll.write_bytes(content)
    expected = hashlib.sha256(content).hexdigest()
    runtime = WindowsRuntime(paths)
    monkeypatch.setattr(runtime, "EXPECTED_CONTROLLER_SHA256", expected)
    assert runtime.controller_machine() == 0x8664
    assert runtime.controller_ready() is True

    dll.write_bytes(fake_pe(0x8664, b"tampered"))
    assert runtime.controller_ready() is False


def test_controller_rejects_wrong_arch_even_when_checksum_matches(tmp_path, monkeypatch):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    dll = paths.controller / "nvdaControllerClient64.dll"
    x86 = fake_pe(0x014C)
    dll.write_bytes(x86)

    runtime = WindowsRuntime(paths)
    monkeypatch.setattr(
        runtime,
        "EXPECTED_CONTROLLER_SHA256",
        hashlib.sha256(x86).hexdigest(),
    )
    assert runtime.controller_machine() == 0x014C
    assert runtime.controller_ready() is False


def test_process_started_before_path_update():
    process = ProcessInfo(
        "steam",
        10,
        session_id=1,
        started_at="2026-10-05T19:00:00+07:00",
    )
    assert WindowsRuntime.process_started_before(
        process,
        "2026-10-05T19:01:00+07:00",
    )
    assert not WindowsRuntime.process_started_before(
        process,
        "2026-10-05T18:59:00+07:00",
    )


def test_addon_runtime_sync_is_idempotent(tmp_path, monkeypatch):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    runtime = WindowsRuntime(paths)

    first = runtime.ensure_addon_runtime()
    second = runtime.ensure_addon_runtime()

    assert first is True
    assert second is False
    assert runtime.addon_installed() is True
    assert runtime.addon_version() == "0.2.0"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell runtime probe is Windows-only")
def test_windows_process_probe_script_is_valid(tmp_path):
    runtime = WindowsRuntime(RuntimePaths(tmp_path / "home"))
    assert runtime._process(("d4planner-process-that-does-not-exist",)) is None


def test_extract_official_controller_archive_validates_x64_and_checksum(tmp_path, monkeypatch):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    runtime = WindowsRuntime(paths)

    content = fake_pe(0x8664, b"official")
    monkeypatch.setattr(
        runtime,
        "EXPECTED_CONTROLLER_SHA256",
        hashlib.sha256(content).hexdigest(),
    )

    archive = tmp_path / "controller.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("x64/nvdaControllerClient.dll", content)

    extracted = runtime._extract_controller_archive(archive)

    assert extracted.is_file()
    assert runtime.controller_machine(extracted) == 0x8664
    assert runtime.controller_sha256(extracted) == hashlib.sha256(content).hexdigest().upper()


def test_nvda_version_gate_accepts_only_verified_major_minor(tmp_path, monkeypatch):
    runtime = WindowsRuntime(RuntimePaths(tmp_path / "home"))
    assert runtime.nvda_version_compatible("2026.2") is True
    assert runtime.nvda_version_compatible("2026.2.1.0") is True
    assert runtime.nvda_version_compatible("2026.1") is False
    assert runtime.nvda_version_compatible("2027.1") is False
    monkeypatch.setattr(runtime, "nvda_version", lambda: None)
    assert runtime.nvda_version_compatible(None) is False


def test_tolk_probe_runs_locally_in_active_console_session(tmp_path, monkeypatch):
    runtime = WindowsRuntime(RuntimePaths(tmp_path / "home"))
    expected = TolkHealth("NVDA", True, False)
    monkeypatch.setattr(runtime, "require_windows", lambda: None)
    monkeypatch.setattr(runtime, "active_console_session_id", lambda: 1)
    monkeypatch.setattr(runtime, "current_process_session_id", lambda: 1)
    monkeypatch.setattr(runtime, "_probe_tolk_local", lambda: expected)

    assert runtime.probe_tolk() is expected


def test_tolk_probe_delegates_to_active_console_session(tmp_path, monkeypatch):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    runtime = WindowsRuntime(paths)
    monkeypatch.setattr(runtime, "require_windows", lambda: None)
    monkeypatch.setattr(runtime, "active_console_session_id", lambda: 1)
    monkeypatch.setattr(runtime, "current_process_session_id", lambda: 0)
    monkeypatch.setattr(runtime, "ensure_interactive_tasks", lambda: None)

    def fake_run_task(name):
        assert name == "D4Planner-Tolk-Probe"
        request = __import__("json").loads(
            (paths.state / "tolk-probe-request.json").read_text(encoding="utf-8")
        )
        atomic_write_json(
            paths.state / "tolk-probe-result.json",
            {
                "requestId": request["requestId"],
                "sessionId": 1,
                "reader": "NVDA",
                "speech": True,
                "braille": False,
                "error": None,
            },
        )

    monkeypatch.setattr(runtime, "run_task", fake_run_task)

    assert runtime.probe_tolk(timeout=0.5).ready is True


def test_tolk_probe_rejects_result_from_wrong_session(tmp_path, monkeypatch):
    paths = RuntimePaths(tmp_path / "home")
    paths.ensure()
    runtime = WindowsRuntime(paths)
    monkeypatch.setattr(runtime, "require_windows", lambda: None)
    monkeypatch.setattr(runtime, "active_console_session_id", lambda: 1)
    monkeypatch.setattr(runtime, "current_process_session_id", lambda: 0)
    monkeypatch.setattr(runtime, "ensure_interactive_tasks", lambda: None)

    def fake_run_task(_name):
        request = __import__("json").loads(
            (paths.state / "tolk-probe-request.json").read_text(encoding="utf-8")
        )
        atomic_write_json(
            paths.state / "tolk-probe-result.json",
            {
                "requestId": request["requestId"],
                "sessionId": 0,
                "reader": "NVDA",
                "speech": True,
                "braille": False,
                "error": None,
            },
        )

    monkeypatch.setattr(runtime, "run_task", fake_run_task)

    health = runtime.probe_tolk(timeout=0.5)
    assert health.ready is False
    assert health.error == "Tolk probe ran outside active console session: actual=0 expected=1"


def test_control_plane_reconciles_interactive_tasks_at_normal_priority(tmp_path, monkeypatch):
    runtime = WindowsRuntime(RuntimePaths(tmp_path / "home"))
    scripts = {
        "nvda": tmp_path / "nvda.ps1",
        "nvda-restart": tmp_path / "nvda-restart.ps1",
        "d4": tmp_path / "d4.ps1",
        "tolk-probe": tmp_path / "tolk-probe.ps1",
    }
    monkeypatch.setattr(runtime, "require_windows", lambda: None)
    monkeypatch.setattr(runtime, "ensure_helper_scripts", lambda: scripts)
    commands = []

    def fake_powershell(script, *, timeout=15.0):
        commands.append(script)
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(runtime, "_powershell", fake_powershell)

    runtime.prepare_interactive_tasks()

    assert len(commands) == 4
    assert all("-Priority 4" in command for command in commands)
    assert all("-Force" in command for command in commands)


def test_limited_supervisor_only_verifies_interactive_tasks(tmp_path, monkeypatch):
    runtime = WindowsRuntime(RuntimePaths(tmp_path / "home"))
    monkeypatch.setattr(runtime, "require_windows", lambda: None)
    commands = []

    def fake_powershell(script, *, timeout=15.0):
        commands.append(script)
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(runtime, "_powershell", fake_powershell)

    runtime.ensure_interactive_tasks()

    assert len(commands) == 1
    assert "Get-ScheduledTask" in commands[0]
    assert "Register-ScheduledTask" not in commands[0]


def test_supervisor_task_is_normal_priority_and_prepares_helpers_first(tmp_path, monkeypatch):
    runtime = WindowsRuntime(RuntimePaths(tmp_path / "home"))
    monkeypatch.setattr(runtime, "require_windows", lambda: None)
    calls = []
    monkeypatch.setattr(runtime, "prepare_interactive_tasks", lambda: calls.append("prepare"))

    def fake_powershell(script, *, timeout=15.0):
        calls.append(script)
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(runtime, "_powershell", fake_powershell)

    runtime.launch_supervisor_task(speech=True, isolated=False)

    assert calls[0] == "prepare"
    assert "-Priority 4" in calls[1]
    assert "Register-ScheduledTask" in calls[1]
