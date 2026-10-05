import json
import threading
import time

from d4planner import cli
from d4planner.runtime.model import ProcessInfo, RuntimeState, TolkHealth
from d4planner.runtime.pathing import MemoryPathBackend, UserPathManager
from d4planner.runtime.store import RuntimePaths, read_json
from d4planner.runtime.supervisor import Supervisor


class E2ERuntime:
    def __init__(self, paths):
        self.paths = paths
        self._nvda = ProcessInfo("nvda_noUIAccess", 100, session_id=1)
        self._steam = ProcessInfo("steam", 200, session_id=1)
        self._game = ProcessInfo("Diablo IV", 300, session_id=1)
        self.launch_calls = 0

    def require_windows(self):
        return None

    def ensure_controller_runtime(self):
        self.paths.controller.mkdir(parents=True, exist_ok=True)
        path = self.paths.controller / "nvdaControllerClient64.dll"
        path.write_bytes(b"e2e-controller")
        return path

    def controller_ready(self):
        return True

    def addon_installed(self):
        return True

    def ensure_addon_runtime(self):
        return False

    def nvda_version(self):
        return "2026.2"

    def nvda_version_compatible(self, version=None):
        return (version or self.nvda_version()).startswith("2026.2")

    def active_console_session_id(self):
        return 1

    def ensure_nvda_running(self, *, timeout=15.0):
        return self._nvda

    def restart_nvda(self, *, timeout=15.0):
        self._nvda = ProcessInfo("nvda_noUIAccess", self._nvda.pid + 1, session_id=1)
        return self._nvda

    def nvda_process(self):
        return self._nvda

    def steam_process(self):
        return self._steam

    def game_process(self):
        return self._game

    def probe_tolk(self):
        return TolkHealth("NVDA", True, True)

    def process_started_before(self, process, timestamp):
        return False

    def launch_game(self):
        self.launch_calls += 1

    def wait_for_game(self, *, timeout=90.0):
        return self._game


def wait_until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_e2e_supervisor_status_logs_and_stop(monkeypatch, tmp_path, capsys):
    paths = RuntimePaths(tmp_path / "home")
    runtime = E2ERuntime(paths)
    manager = UserPathManager(
        paths,
        MemoryPathBackend(user_path="", machine_path="MACHINE"),
    )
    supervisor = Supervisor(
        paths=paths,
        runtime=runtime,
        path_manager=manager,
        silent=True,
        poll_interval=0.02,
        health_poll_interval=0.10,
        game_start_timeout=0.01,
    )

    thread = threading.Thread(target=supervisor.run, daemon=True)
    thread.start()

    assert wait_until(
        lambda: (read_json(paths.runtime_state) or {}).get("state") == RuntimeState.RUNNING.value
    )
    status = read_json(paths.runtime_state)
    session_dir = status["sessionDir"]
    raw_path = supervisor.store.session.raw_speech_path
    raw_path.write_text(
        json.dumps(
            {
                "sessionId": supervisor.store.session.session_id,
                "sequence": 1,
                "timestamp": "2026-10-06T04:00:00+07:00",
                "process": "diablo iv",
                "windowTitle": "Diablo IV",
                "text": "900 Item Power",
                "rawSpeech": ["900 Item Power"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    events_path = supervisor.store.session.events_path

    def speech_arrived():
        try:
            rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
        except OSError:
            return False
        return any(row.get("type") == "speech.raw" for row in rows)

    assert wait_until(speech_arrived)

    # This is an in-process fake supervisor; use its real pytest process PID as
    # alive evidence so CLI status/stop exercise the same persisted contract.
    monkeypatch.setattr(cli, "_pid_alive", lambda pid: int(pid) == supervisor.status.supervisor_pid)

    assert cli.command_status(paths, raw_json=False) == 0
    status_output = capsys.readouterr().out
    assert "RUNNING" in status_output
    assert "ACTIVE" in status_output

    assert cli.command_logs(paths, follow=False, raw=False) == 0
    assert "900 Item Power" in capsys.readouterr().out

    assert cli.command_logs(paths, follow=False, raw=True) == 0
    raw_lines = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.strip()
    ]
    assert any(row["type"] == "speech.raw" for row in raw_lines)

    assert cli.command_stop(paths, timeout=2.0) == 0
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    final = read_json(paths.runtime_state)
    assert final["state"] == RuntimeState.STOPPED.value
    assert runtime.launch_calls == 0
    assert runtime._game.pid == 300
    assert runtime._steam.pid == 200
