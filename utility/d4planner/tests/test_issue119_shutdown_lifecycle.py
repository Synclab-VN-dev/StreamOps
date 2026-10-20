"""Issue #119 / PR #120 Real-A 2026-10-20: stale Supervisor after RESTART_REQUIRED.

Regression for (a) prompt exit during Steam PATH bootstrap gate; (b) CLI stop
of an already-exited daemon; (c) truthful read-only status and safe live stop.
Steam/NVDA/game must never be stopped or otherwise modified by these tests.
"""
import json

from d4planner import cli
from d4planner.runtime.model import ProcessInfo, RuntimeState
from d4planner.runtime.store import RuntimePaths, atomic_write_json, read_json
from d4planner.runtime.pathing import MemoryPathBackend, UserPathManager
from d4planner.runtime.supervisor import Supervisor


def _seed_restart(paths):
    paths.ensure()
    atomic_write_json(paths.runtime_state, {
        "state": RuntimeState.RESTART_REQUIRED.value,
        "detail": "Steam predates D4Planner User PATH update; exit Steam normally",
        "lastError": None,
        "supervisorPid": 4764,
        "captureActive": False,
        "silent": True,
        "extras": {"runtime": {"isolated": False}, "inputMarker": {"state": "STARTING"}},
    })


def test_exited_restart_required_status_is_truthful_but_does_not_mutate_disk(
    monkeypatch, capsys, tmp_path,
):
    paths = RuntimePaths(tmp_path / "d4-home")
    _seed_restart(paths)
    monkeypatch.setattr(cli, "_pid_alive", lambda pid: False)

    assert cli.command_status(paths, raw_json=True) == 2
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["state"] == "STOPPED"
    assert rendered["lastPersistedState"] == "RESTART_REQUIRED"
    assert rendered["supervisorAlive"] is False
    assert rendered["supervisorPid"] is None
    # Read-only status must not rewrite bootstrap's diagnostic, so start can
    # still see the terminal reason / correct 3=RESTART_REQUIRED outcome.
    assert read_json(paths.runtime_state)["state"] == "RESTART_REQUIRED"


def test_stop_exited_restart_required_reconciles_durable_stopped(
    monkeypatch, capsys, tmp_path,
):
    paths = RuntimePaths(tmp_path / "d4-home")
    _seed_restart(paths)
    monkeypatch.setattr(cli, "_pid_alive", lambda pid: False)
    assert cli.command_stop(paths, timeout=0) == 0
    durable = read_json(paths.runtime_state)
    assert durable["state"] == "STOPPED"
    assert durable["supervisorPid"] is None
    assert durable["captureActive"] is False
    assert "Steam predates" in durable["lastExitDetail"]
    assert "Steam predates" in durable["lastExitDetail"]
    assert read_json(paths.capture_state)["enabled"] is False
    assert not paths.stop_request.exists()

    assert cli.command_status(paths, raw_json=True) == 0
    after = json.loads(capsys.readouterr().out.split("D4Planner already stopped.\n")[-1])
    assert after["state"] == "STOPPED"
    assert after["supervisorPid"] is None


def test_stop_live_restart_required_does_not_fake_stop_or_kill(
    monkeypatch, tmp_path,
):
    paths = RuntimePaths(tmp_path / "d4-home")
    _seed_restart(paths)
    monkeypatch.setattr(cli, "_pid_alive", lambda pid: True)
    assert cli.command_stop(paths, timeout=0) == 1
    assert read_json(paths.runtime_state)["state"] == "RESTART_REQUIRED"
    assert paths.stop_request.read_text(encoding="utf-8") == "stop\n"


class _PathStaleRuntime:
    """Focused Steam PATH guard: don't launch or stop external processes."""
    def __init__(self, paths):
        self.paths = paths
        self.launches = 0

    def require_windows(self): pass
    def nvda_version(self): return "2026.2"
    def nvda_version_compatible(self, version): return True
    def ensure_controller_runtime(self):
        self.paths.controller.mkdir(parents=True, exist_ok=True)
        out = self.paths.controller / "nvdaControllerClient64.dll"
        out.write_bytes(b"fixture")
        return out
    def ensure_addon_runtime(self): return False
    def addon_installed(self): return True
    def active_console_session_id(self): return 1
    def nvda_process(self): return ProcessInfo("nvda_noUIAccess", 3328, session_id=1)
    def ensure_nvda_running(self): return self.nvda_process()
    def probe_tolk(self):
        from d4planner.runtime.model import TolkHealth
        return TolkHealth("NVDA", True, True)
    def steam_process(self): return ProcessInfo("steam", 12332, session_id=1)
    def process_started_before(self, *_args): return True
    def game_process(self): return None
    def launch_game(self): self.launches += 1


def test_early_bootstrap_restart_required_closes_ingress_and_marker(tmp_path):
    paths = RuntimePaths(tmp_path / "d4-home")
    runtime = _PathStaleRuntime(paths)
    supervisor = Supervisor(
        paths=paths, runtime=runtime,
        path_manager=UserPathManager(
            paths, MemoryPathBackend(user_path="", machine_path="M")),
        tolk_ready_timeout=0.01,
    )
    assert supervisor.run() == 3
    status = read_json(paths.runtime_state)
    assert status["state"] == "RESTART_REQUIRED"  # preserve startup exit code
    assert status["captureActive"] is False
    assert status["extras"]["inputMarker"]["state"] == "STOPPED"
    assert read_json(paths.capture_state)["enabled"] is False
    assert runtime.launches == 0
    assert not paths.stop_request.exists()
