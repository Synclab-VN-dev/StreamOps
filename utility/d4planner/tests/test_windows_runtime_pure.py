import os
from pathlib import Path

import pytest
from datetime import datetime, timezone
import hashlib
import subprocess
import zipfile

from d4planner.runtime.model import ProcessInfo, TolkHealth
from d4planner.runtime.store import RuntimePaths, atomic_write_json
from d4planner.runtime.windows import RuntimeBlocked, WindowsRuntime


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


def test_nvda_process_prefers_no_ui_access_host(tmp_path, monkeypatch):
    runtime = WindowsRuntime(RuntimePaths(tmp_path / "home"))
    calls = []

    def fake_process_named(name):
        calls.append(name)
        if name == "nvda_noUIAccess":
            return ProcessInfo("nvda_noUIAccess", 42, session_id=1)
        return ProcessInfo("nvda", 99, session_id=1)

    monkeypatch.setattr(runtime, "_process_named", fake_process_named)

    selected = runtime.nvda_process()

    assert selected is not None
    assert selected.name == "nvda_noUIAccess"
    assert selected.pid == 42
    assert calls == ["nvda_noUIAccess"]


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
        "nvda-stop": tmp_path / "nvda-stop.ps1",
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

    assert len(commands) == 5
    assert all("-Priority 4" in command for command in commands)
    assert all("-Force" in command for command in commands)


def test_isolated_tasks_are_namespaced_and_ownership_guarded(tmp_path, monkeypatch):
    runtime = WindowsRuntime(RuntimePaths(tmp_path / "home"))
    scripts = {
        "nvda": tmp_path / "nvda.ps1",
        "nvda-restart": tmp_path / "nvda-restart.ps1",
        "nvda-stop": tmp_path / "nvda-stop.ps1",
        "d4": tmp_path / "d4.ps1",
        "tolk-probe": tmp_path / "tolk-probe.ps1",
    }
    monkeypatch.setattr(runtime, "require_windows", lambda: None)
    monkeypatch.setattr(runtime, "ensure_helper_scripts", lambda: scripts)
    runtime.task_isolated = True
    commands = []

    def fake_powershell(script, *, timeout=15.0):
        commands.append(script)
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(runtime, "_powershell", fake_powershell)
    runtime.prepare_interactive_tasks()

    assert len(commands) == 5
    assert all("D4Planner-Isolated-" in command for command in commands)
    assert all("D4Planner owner=" in command for command in commands)
    assert all("$actions.Count -eq 1" in command for command in commands)
    assert all("$principalSid -eq $currentSid" in command for command in commands)
    assert all("refusing to modify foreign scheduled task" in command for command in commands)
    # -Force is reachable only after the ownership/adoption guard succeeds.
    assert all(command.index("refusing to modify foreign scheduled task")
               < command.index("Register-ScheduledTask") for command in commands)


def test_isolated_supervisor_forwards_home_and_uses_owned_task_name(tmp_path, monkeypatch):
    runtime = WindowsRuntime(RuntimePaths(tmp_path / "pr95-home"))
    commands = []
    monkeypatch.setattr(runtime, "require_windows", lambda: None)
    monkeypatch.setattr(runtime, "prepare_interactive_tasks", lambda: None)
    monkeypatch.setattr(
        runtime,
        "_powershell",
        lambda script, **kw: (
            commands.append(script) or subprocess.CompletedProcess([], 0, "", "")
        ),
    )

    runtime.launch_supervisor_task(
        speech=False,
        isolated=True,
        block_marker=True,
        controller_profile="xbox16",
    )

    assert len(commands) == 1
    script = commands[0]
    assert "--isolated" in script
    assert "--home" in script
    assert str((tmp_path / "pr95-home").resolve()) in script
    assert "D4Planner-Isolated-" in script
    assert "family=supervisor" in script
    assert "$actions.Count -eq 1" in script
    assert script.index("refusing to modify foreign scheduled task") < script.index("-Force")


def test_legacy_supervisor_can_reconcile_mode_only_after_ownership_check(
    tmp_path, monkeypatch,
):
    runtime = WindowsRuntime(RuntimePaths(tmp_path / "home"))
    commands = []
    monkeypatch.setattr(runtime, "require_windows", lambda: None)
    monkeypatch.setattr(runtime, "prepare_interactive_tasks", lambda: None)
    monkeypatch.setattr(
        runtime,
        "_powershell",
        lambda script, **kw: (
            commands.append(script) or subprocess.CompletedProcess([], 0, "", "")
        ),
    )

    runtime.launch_supervisor_task(speech=False, isolated=False, block_marker=False)
    runtime.launch_supervisor_task(speech=False, isolated=False, block_marker=True)
    runtime.launch_supervisor_task(speech=False, isolated=False, block_marker=False)

    assert len(commands) == 3
    assert "-m d4planner.daemon'" in commands[0]
    assert "-m d4planner.daemon --block" in commands[1]
    assert "-m d4planner.daemon'" in commands[2]
    assert all("family=supervisor" in command for command in commands)
    assert all(".StartsWith($legacyPrefix" in command for command in commands)
    assert all("$principalSid -eq $currentSid" in command for command in commands)


def test_supervisor_foreign_task_collision_is_fail_closed_in_generated_script(
    tmp_path, monkeypatch,
):
    runtime = WindowsRuntime(RuntimePaths(tmp_path / "home"))
    commands = []
    monkeypatch.setattr(runtime, "require_windows", lambda: None)
    monkeypatch.setattr(runtime, "prepare_interactive_tasks", lambda: None)
    monkeypatch.setattr(
        runtime,
        "_powershell",
        lambda script, **kw: (
            commands.append(script) or subprocess.CompletedProcess([], 0, "", "")
        ),
    )

    runtime.launch_supervisor_task(speech=False, isolated=False)

    script = commands[0]
    assert "($actions.Count -eq 1)" in script
    assert "($principalSid -eq $currentSid)" in script
    assert "([string]$actions[0].Execute -eq $expectedExecute)" in script
    assert "refusing to modify foreign scheduled task" in script
    assert script.index("throw ('refusing") < script.index("Register-ScheduledTask")


def test_attach_only_is_forwarded_with_absolute_home(tmp_path, monkeypatch):
    runtime = WindowsRuntime(RuntimePaths(tmp_path / "pr95-home"))
    commands = []
    monkeypatch.setattr(runtime, "require_windows", lambda: None)
    monkeypatch.setattr(runtime, "prepare_interactive_tasks", lambda: None)
    monkeypatch.setattr(
        runtime,
        "_powershell",
        lambda script, **kw: (
            commands.append(script) or subprocess.CompletedProcess([], 0, "", "")
        ),
    )

    runtime.launch_supervisor_task(
        speech=False,
        isolated=True,
        block_marker=True,
        controller_profile="xbox16",
        uat_attach_only=True,
    )

    script = commands[0]
    assert "--uat-attach-only" in script
    assert "--home" in script
    assert str((tmp_path / "pr95-home").resolve()) in script


def test_attach_only_forwards_legacy_observe_without_dependency_mutation(
    tmp_path, monkeypatch,
):
    runtime = WindowsRuntime(RuntimePaths(tmp_path / "pr95-home"))
    commands = []
    monkeypatch.setattr(runtime, "require_windows", lambda: None)
    monkeypatch.setattr(runtime, "prepare_interactive_tasks", lambda: None)
    monkeypatch.setattr(
        runtime,
        "_powershell",
        lambda script, **kw: (
            commands.append(script) or subprocess.CompletedProcess([], 0, "", "")
        ),
    )

    runtime.launch_supervisor_task(
        speech=False,
        isolated=True,
        block_marker=False,
        controller_profile=None,
        uat_attach_only=True,
    )

    script = commands[0]
    assert "--uat-attach-only" in script
    assert "--isolated" in script
    assert "--block" not in script
    assert "--controller-profile" not in script


def test_isolated_run_task_maps_legacy_base_name_to_owned_task(tmp_path, monkeypatch):
    runtime = WindowsRuntime(RuntimePaths(tmp_path / "pr95-home"))
    runtime.task_isolated = True
    calls = []
    monkeypatch.setattr(runtime, "require_windows", lambda: None)
    monkeypatch.setattr(
        runtime,
        "_powershell",
        lambda script, **kw: (
            calls.append(script) or subprocess.CompletedProcess([], 0, "", "")
        ),
    )

    runtime.run_task("D4Planner-Tolk-Probe")

    assert len(calls) == 1
    assert "D4Planner-Isolated-" in calls[0]
    assert "D4Planner-Tolk-Probe'" not in calls[0]


def test_cleanup_removes_only_owned_isolated_tasks(tmp_path, monkeypatch):
    runtime = WindowsRuntime(RuntimePaths(tmp_path / "pr95-home"))
    runtime.task_isolated = True
    scripts = []
    helper_scripts = {
        "nvda": tmp_path / "start-nvda.ps1",
        "nvda-restart": tmp_path / "restart-nvda.ps1",
        "nvda-stop": tmp_path / "stop-nvda.ps1",
        "d4": tmp_path / "start-d4.ps1",
        "tolk-probe": tmp_path / "probe-tolk.ps1",
    }
    monkeypatch.setattr(runtime, "require_windows", lambda: None)
    monkeypatch.setattr(runtime, "ensure_helper_scripts", lambda: helper_scripts)
    monkeypatch.setattr(
        runtime,
        "_powershell",
        lambda script, **kw: (
            scripts.append(script) or subprocess.CompletedProcess([], 0, "removed\n", "")
        ),
    )

    removed = runtime.cleanup_owned_tasks()

    assert len(removed) == 7
    assert len(scripts) == 7
    assert all("D4Planner-Isolated-" in script for script in scripts)
    assert all("$principalSid -ne $currentSid" in script for script in scripts)
    assert all("$actions[0].Execute -ne $expectedExecute" in script for script in scripts)
    assert all("StartsWith($expectedPrefix" in script for script in scripts)
    assert all("refusing to remove unowned scheduled task" in script for script in scripts)
    assert all(script.index("refusing to remove") < script.index("Unregister-ScheduledTask")
               for script in scripts)


def test_cleanup_fails_closed_when_isolated_task_is_not_owned(tmp_path, monkeypatch):
    runtime = WindowsRuntime(RuntimePaths(tmp_path / "pr95-home"))
    runtime.task_isolated = True
    helper_scripts = {
        "nvda": tmp_path / "start-nvda.ps1",
        "nvda-restart": tmp_path / "restart-nvda.ps1",
        "nvda-stop": tmp_path / "stop-nvda.ps1",
        "d4": tmp_path / "start-d4.ps1",
        "tolk-probe": tmp_path / "probe-tolk.ps1",
    }
    monkeypatch.setattr(runtime, "require_windows", lambda: None)
    monkeypatch.setattr(runtime, "ensure_helper_scripts", lambda: helper_scripts)
    monkeypatch.setattr(
        runtime,
        "_powershell",
        lambda script, **kw: subprocess.CompletedProcess([], 1, "", "foreign collision"),
    )

    with pytest.raises(RuntimeBlocked, match="failed to clean isolated task"):
        runtime.cleanup_owned_tasks()


def test_cleanup_is_noop_for_legacy_task_namespace(tmp_path, monkeypatch):
    runtime = WindowsRuntime(RuntimePaths(tmp_path / "home"))
    monkeypatch.setattr(runtime, "require_windows", lambda: None)
    monkeypatch.setattr(
        runtime,
        "_powershell",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not mutate")),
    )

    assert runtime.cleanup_owned_tasks() == []


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


def test_supervisor_task_uses_active_module_source_root_not_inherited_pythonpath(
    tmp_path, monkeypatch,
):
    from d4planner.runtime import windows
    runtime = WindowsRuntime(RuntimePaths(tmp_path / "home"))
    monkeypatch.setattr(runtime, "require_windows", lambda: None)
    monkeypatch.setattr(runtime, "prepare_interactive_tasks", lambda: None)
    scripts = []
    monkeypatch.setattr(
        runtime, "_powershell",
        lambda script, **kwargs: (
            scripts.append(script) or subprocess.CompletedProcess([], 0, "", "")
        ),
    )

    runtime.launch_supervisor_task(
        speech=False, isolated=False, controller_profile="xbox16",
        block_marker=True,
    )
    assert len(scripts) == 1
    script = scripts[0]
    source_root = str(Path(windows.__file__).resolve().parents[2])
    assert ("$expectedWorkDir='" + source_root.replace("'", "''") + "'") in script
    assert "New-ScheduledTaskAction -Execute $expectedExecute" in script
    assert "-WorkingDirectory $expectedWorkDir" in script
    assert "[string]$actions[0].WorkingDirectory -ne $expectedWorkDir" in script
    if os.name == "nt":
        # Parse the exact generated task update command, not just fragments.
        parsed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "$inputScript=[Console]::In.ReadToEnd();"
             "$tokens=$null;$errors=$null;"
             "[void][System.Management.Automation.Language.Parser]::ParseInput("
             "$inputScript,[ref]$tokens,[ref]$errors);"
             "if(@($errors).Count){$errors|Out-String|Write-Error;exit 1}"],
            input=script, text=True, capture_output=True, timeout=20,
        )
        assert parsed.returncode == 0, parsed.stderr

    assert script.index("refusing to modify foreign scheduled task") < script.index(
        "Register-ScheduledTask"
    )
    assert "$expectedArguments='-m d4planner.daemon --block --controller-profile xbox16'" in script

    # Helper tasks do not depend on source checkout and retain old invocation.
    helper = runtime._task_reconcile_script(
        task_name="test-helper", executable="powershell.exe",
        arguments="-NoProfile -File start-nvda.ps1",
        family="helper:start-nvda", legacy_argument_prefix="-NoProfile",
    )
    assert "$expectedWorkDir=''" in helper
    assert "if($expectedWorkDir -ne '')" in helper


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



def test_stop_nvda_targets_active_console_and_uses_graceful_task(tmp_path, monkeypatch):
    runtime = WindowsRuntime(RuntimePaths(tmp_path / "home"))
    current = [ProcessInfo("nvda_noUIAccess", 42, session_id=1)]
    calls = []
    monkeypatch.setattr(runtime, "require_windows", lambda: None)
    monkeypatch.setattr(runtime, "active_console_session_id", lambda: 1)
    monkeypatch.setattr(runtime, "nvda_process", lambda: current[0] if current else None)
    monkeypatch.setattr(runtime, "prepare_nvda_stop_task", lambda: calls.append("prepare-stop"))

    def run_task(name):
        calls.append(name)
        current.clear()

    monkeypatch.setattr(runtime, "run_task", run_task)

    assert runtime.stop_nvda(timeout=0.1) is True
    assert calls == ["prepare-stop", "D4Planner-NVDA-Stop"]


def test_stop_nvda_is_idempotent_when_nvda_absent(tmp_path, monkeypatch):
    runtime = WindowsRuntime(RuntimePaths(tmp_path / "home"))
    monkeypatch.setattr(runtime, "require_windows", lambda: None)
    monkeypatch.setattr(runtime, "nvda_process", lambda: None)
    monkeypatch.setattr(
        runtime,
        "run_task",
        lambda _name: (_ for _ in ()).throw(AssertionError("task must not run")),
    )

    assert runtime.stop_nvda(timeout=0.1) is False


def test_stop_nvda_refuses_other_windows_session(tmp_path, monkeypatch):
    runtime = WindowsRuntime(RuntimePaths(tmp_path / "home"))
    monkeypatch.setattr(runtime, "require_windows", lambda: None)
    monkeypatch.setattr(runtime, "active_console_session_id", lambda: 1)
    monkeypatch.setattr(
        runtime,
        "nvda_process",
        lambda: ProcessInfo("nvda_noUIAccess", 42, session_id=2),
    )
    monkeypatch.setattr(
        runtime,
        "run_task",
        lambda _name: (_ for _ in ()).throw(AssertionError("task must not run")),
    )

    with pytest.raises(Exception, match="outside active console session"):
        runtime.stop_nvda(timeout=0.1)


def test_stop_helper_uses_nvda_quit_without_force_kill(tmp_path, monkeypatch):
    paths = RuntimePaths(tmp_path / "home")
    runtime = WindowsRuntime(paths)
    nvda = tmp_path / "NVDA" / "nvda_noUIAccess.exe"
    steam = tmp_path / "Steam" / "steam.exe"
    nvda.parent.mkdir(parents=True)
    steam.parent.mkdir(parents=True)
    nvda.write_bytes(b"")
    steam.write_bytes(b"")
    monkeypatch.setattr(runtime, "locate_nvda_executable", lambda: nvda)
    monkeypatch.setattr(runtime, "locate_steam_executable", lambda: steam)

    scripts = runtime.ensure_helper_scripts()
    stop_script = scripts["nvda-stop"].read_text(encoding="utf-8")

    assert "nvda.exe" in stop_script
    assert "-q" in stop_script
    assert "taskkill" not in stop_script.casefold()
    assert "stop-process" not in stop_script.casefold()
    assert "-force" not in stop_script.casefold()
    assert ("D4Planner-NVDA-Stop", scripts["nvda-stop"]) in runtime._interactive_task_specs()



def test_prepare_nvda_stop_task_reconciles_only_stop_task(tmp_path, monkeypatch):
    runtime = WindowsRuntime(RuntimePaths(tmp_path / "home"))
    stop_script = tmp_path / "stop-nvda.ps1"
    stop_script.write_text("& 'nvda.exe' -q\n", encoding="utf-8")
    monkeypatch.setattr(runtime, "require_windows", lambda: None)
    monkeypatch.setattr(
        runtime,
        "ensure_helper_scripts",
        lambda: {
            "nvda-stop": stop_script,
        },
    )
    calls = []
    monkeypatch.setattr(
        runtime,
        "_prepare_interactive_task",
        lambda name, path: calls.append((name, path)),
    )

    runtime.prepare_nvda_stop_task()

    assert calls == [("D4Planner-NVDA-Stop", stop_script)]


def test_input_marker_probe_task_uses_interactive_principal(tmp_path, monkeypatch):
    runtime = WindowsRuntime(RuntimePaths(tmp_path / "home"))
    monkeypatch.setattr(runtime, "require_windows", lambda: None)
    calls = []

    def fake_powershell(script, *, timeout=15.0):
        calls.append(script)
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(runtime, "_powershell", fake_powershell)

    output = tmp_path / "state" / "input-marker-probe.log"
    runtime.launch_input_marker_probe_task(
        key="scroll-lock",
        seconds=12,
        output_path=output,
    )

    script = calls[0]
    assert "D4Planner-Input-Marker-Probe" in script
    assert "-LogonType Interactive" in script
    assert "input-marker-probe --key" in script
    assert "scroll-lock" in script
    assert "--seconds 12" in script
    assert str(output) in script
    assert "family=input-marker-probe" in script
    assert "refusing to modify foreign scheduled task" in script
    assert ".StartsWith($legacyPrefix" in script



def test_supervisor_interactive_task_block_flag_preserves_session1_principal(
    tmp_path, monkeypatch,
):
    runtime = WindowsRuntime(RuntimePaths(tmp_path / "home"))
    commands = []
    monkeypatch.setattr(runtime, "require_windows", lambda: None)
    monkeypatch.setattr(runtime, "prepare_interactive_tasks", lambda: None)
    monkeypatch.setattr(
        runtime, "_powershell",
        lambda script, **kw: (
            commands.append(script) or subprocess.CompletedProcess([], 0, "", "")
        ),
    )
    runtime.launch_supervisor_task(speech=False, isolated=False, block_marker=True)
    assert len(commands) == 1
    assert "$expectedArguments='-m d4planner.daemon --block'" in commands[0]
    assert "LogonType Interactive" in commands[0]
    assert "Start-ScheduledTask" in commands[0]

    commands.clear()
    runtime.launch_supervisor_task(speech=False, isolated=False, block_marker=False)
    assert "--block" not in commands[0]



def test_supervisor_interactive_task_forwards_xbox16_profile_without_autoconfig(
    tmp_path, monkeypatch,
):
    """Session 0 must forward profile to Session 1, without writing Steam VDF."""
    runtime = WindowsRuntime(RuntimePaths(tmp_path / "home"))
    commands = []
    monkeypatch.setattr(runtime, "require_windows", lambda: None)
    monkeypatch.setattr(runtime, "prepare_interactive_tasks", lambda: None)
    monkeypatch.setattr(
        runtime, "_powershell",
        lambda script, **kw: (
            commands.append(script) or subprocess.CompletedProcess([], 0, "", "")
        ),
    )
    runtime.launch_supervisor_task(
        speech=False, isolated=False, block_marker=True,
        controller_profile="xbox16",
    )
    assert len(commands) == 1
    script = commands[0]
    assert "--controller-profile xbox16" in script
    assert "$expectedArguments='-m d4planner.daemon --block --controller-profile xbox16'" in script
    assert "LogonType Interactive" in script
    assert "-Priority 4" in script

    commands.clear()
    from d4planner.controller import ProfileValidationError
    import pytest
    with pytest.raises(ProfileValidationError):
        runtime.launch_supervisor_task(
            speech=False, isolated=False, controller_profile="unknown"
        )
    assert commands == []
