from pathlib import Path

from d4planner.runtime.model import ProcessInfo, RuntimeState, TolkHealth
from d4planner.runtime.pathing import MemoryPathBackend, UserPathManager
from d4planner.runtime.store import RuntimePaths, read_json
from d4planner.runtime.supervisor import Supervisor


class FakeRuntime:
    def __init__(self, paths, *, game=None, steam=None, stale=False):
        self.paths = paths
        self._game = game
        self._steam = steam
        self.stale = stale
        self.launch_calls = 0
        self._nvda = ProcessInfo("nvda_noUIAccess", 10, session_id=1)

    def require_windows(self):
        return None

    def ensure_controller_runtime(self):
        self.paths.controller.mkdir(parents=True, exist_ok=True)
        path = self.paths.controller / "nvdaControllerClient64.dll"
        path.write_bytes(b"dll")
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
        if self._nvda is None:
            self._nvda = ProcessInfo("nvda_noUIAccess", 11, session_id=1)
        return self._nvda

    def nvda_process(self):
        return self._nvda

    def restart_nvda(self, *, timeout=15.0):
        self._nvda = ProcessInfo("nvda_noUIAccess", self._nvda.pid + 1, session_id=1)
        return self._nvda

    def steam_process(self):
        return self._steam

    def game_process(self):
        return self._game

    def probe_tolk(self):
        return TolkHealth("NVDA", True, True)

    def process_started_before(self, process, timestamp):
        return bool(process and self.stale)

    def launch_game(self):
        self.launch_calls += 1

    def wait_for_game(self, *, timeout=90.0):
        if self._game is None:
            self._steam = self._steam or ProcessInfo("steam", 20, session_id=1)
            self._game = ProcessInfo("Diablo IV", 30, session_id=1)
        return self._game


def build_supervisor(tmp_path, runtime):
    paths = runtime.paths
    manager = UserPathManager(paths, MemoryPathBackend(user_path="", machine_path="MACHINE"))
    return Supervisor(
        paths=paths,
        runtime=runtime,
        path_manager=manager,
        silent=True,
        poll_interval=0.001,
        game_start_timeout=0.01,
        tolk_ready_timeout=0.01,
        tolk_retry_interval=0.001,
    )


def test_bootstrap_waits_for_tolk_nvda_readiness(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    runtime = FakeRuntime(paths)
    probes = iter(
        [
            TolkHealth(None, False, False),
            TolkHealth(None, False, False),
            TolkHealth("NVDA", True, True),
        ]
    )
    calls = {"count": 0}

    def probe():
        calls["count"] += 1
        return next(probes, TolkHealth("NVDA", True, True))

    runtime.probe_tolk = probe
    manager = UserPathManager(
        paths,
        MemoryPathBackend(user_path="", machine_path="MACHINE"),
    )
    supervisor = Supervisor(
        paths=paths,
        runtime=runtime,
        path_manager=manager,
        silent=True,
        poll_interval=0.001,
        game_start_timeout=0.01,
        tolk_ready_timeout=0.05,
        tolk_retry_interval=0.001,
    )

    assert supervisor.bootstrap() == RuntimeState.RUNNING
    assert calls["count"] >= 3
    assert supervisor.status.tolk.ready is True


def test_bootstrap_launches_game_and_reaches_running(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    runtime = FakeRuntime(paths)
    supervisor = build_supervisor(tmp_path, runtime)

    state = supervisor.bootstrap()

    assert state == RuntimeState.RUNNING
    assert runtime.launch_calls == 1
    status = read_json(paths.runtime_state)
    assert status["captureActive"] is True
    assert status["state"] == "RUNNING"
    capture = read_json(paths.capture_state)
    assert capture["enabled"] is True
    assert capture["silent"] is True
    assert capture["gamePid"] == 30


def test_existing_healthy_game_attaches_without_restart(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    runtime = FakeRuntime(
        paths,
        game=ProcessInfo("Diablo IV", 31, session_id=1),
        steam=ProcessInfo("steam", 21, session_id=1),
    )
    supervisor = build_supervisor(tmp_path, runtime)

    state = supervisor.bootstrap()

    assert state == RuntimeState.RUNNING
    assert runtime.launch_calls == 0
    assert supervisor.status.game.pid == 31


def test_stale_steam_requires_restart_and_never_launches_or_kills_game(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    runtime = FakeRuntime(
        paths,
        game=ProcessInfo("Diablo IV", 31, session_id=1),
        steam=ProcessInfo("steam", 21, session_id=1),
        stale=True,
    )
    supervisor = build_supervisor(tmp_path, runtime)

    state = supervisor.bootstrap()

    assert state == RuntimeState.RESTART_REQUIRED
    assert runtime.launch_calls == 0
    assert read_json(paths.capture_state)["enabled"] is False


def test_session_mismatch_blocks_before_capture(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    runtime = FakeRuntime(
        paths,
        game=ProcessInfo("Diablo IV", 31, session_id=2),
        steam=ProcessInfo("steam", 21, session_id=1),
    )
    supervisor = build_supervisor(tmp_path, runtime)

    state = supervisor.bootstrap()

    assert state == RuntimeState.BLOCKED
    assert read_json(paths.capture_state)["enabled"] is False


def test_game_exit_and_return_reaches_running_again(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    runtime = FakeRuntime(
        paths,
        game=ProcessInfo("Diablo IV", 31, session_id=1),
        steam=ProcessInfo("steam", 21, session_id=1),
    )
    supervisor = build_supervisor(tmp_path, runtime)
    assert supervisor.bootstrap() == RuntimeState.RUNNING

    runtime._game = None
    supervisor._watch_game()
    assert supervisor.status.state == RuntimeState.WAITING_FOR_GAME
    assert supervisor.status.game is None
    assert read_json(paths.capture_state)["gamePid"] is None

    runtime._game = ProcessInfo("Diablo IV", 32, session_id=1)
    supervisor._watch_game()
    assert supervisor.status.state == RuntimeState.RUNNING
    assert supervisor.status.game.pid == 32
    assert read_json(paths.capture_state)["gamePid"] == 32


def test_game_pid_replacement_without_poll_gap_refreshes_capture_identity(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    runtime = FakeRuntime(
        paths,
        game=ProcessInfo("Diablo IV", 31, session_id=1),
        steam=ProcessInfo("steam", 21, session_id=1),
    )
    supervisor = build_supervisor(tmp_path, runtime)
    assert supervisor.bootstrap() == RuntimeState.RUNNING

    runtime._game = ProcessInfo("Diablo IV", 33, session_id=1)
    supervisor._watch_game()

    assert supervisor.status.state == RuntimeState.RUNNING
    assert supervisor.status.game.pid == 33
    assert read_json(paths.capture_state)["gamePid"] == 33


def test_below_normal_steam_blocks_automated_launch_but_not_attach(tmp_path):
    launch_paths = RuntimePaths(tmp_path / "launch")
    low_steam = ProcessInfo("steam", 21, session_id=1, priority_class="BelowNormal")
    launch_runtime = FakeRuntime(launch_paths, steam=low_steam)
    launch_supervisor = build_supervisor(tmp_path, launch_runtime)

    assert launch_supervisor.bootstrap() == RuntimeState.RESTART_REQUIRED
    assert launch_runtime.launch_calls == 0
    assert "priority" in launch_supervisor.status.detail.casefold()

    attach_paths = RuntimePaths(tmp_path / "attach")
    attach_runtime = FakeRuntime(
        attach_paths,
        steam=low_steam,
        game=ProcessInfo("Diablo IV", 31, session_id=1),
    )
    attach_supervisor = build_supervisor(tmp_path, attach_runtime)

    assert attach_supervisor.bootstrap() == RuntimeState.RUNNING
    assert attach_runtime.launch_calls == 0


def test_existing_game_with_non_nvda_backend_requires_restart_without_kill(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    runtime = FakeRuntime(
        paths,
        game=ProcessInfo("Diablo IV", 31, session_id=1),
        steam=ProcessInfo("steam", 21, session_id=1),
    )
    runtime.probe_tolk = lambda: TolkHealth("SAPI", True, False)
    supervisor = build_supervisor(tmp_path, runtime)

    state = supervisor.bootstrap()

    assert state == RuntimeState.RESTART_REQUIRED
    assert runtime.launch_calls == 0
    assert runtime._game.pid == 31
    assert read_json(paths.capture_state)["enabled"] is False
    assert "not NVDA" in supervisor.status.detail


def test_nvda_recovery_reprobes_tolk_before_returning_running(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    runtime = FakeRuntime(
        paths,
        game=ProcessInfo("Diablo IV", 31, session_id=1),
        steam=ProcessInfo("steam", 21, session_id=1),
    )
    supervisor = build_supervisor(tmp_path, runtime)
    assert supervisor.bootstrap() == RuntimeState.RUNNING

    runtime._nvda = None
    runtime.probe_tolk = lambda: TolkHealth("SAPI", True, False)
    supervisor._recover_nvda()

    assert supervisor.status.state == RuntimeState.DEGRADED
    assert supervisor.status.capture_active is False
    assert read_json(paths.capture_state)["enabled"] is False
    assert runtime._game.pid == 31

    runtime.probe_tolk = lambda: TolkHealth("NVDA", True, True)
    supervisor._recover_nvda()

    assert supervisor.status.state == RuntimeState.RUNNING
    assert supervisor.status.capture_active is True
    assert read_json(paths.capture_state)["enabled"] is True
    assert read_json(paths.capture_state)["gamePid"] == 31


def test_returning_game_reprobes_tolk_before_reattach(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    runtime = FakeRuntime(
        paths,
        game=ProcessInfo("Diablo IV", 31, session_id=1),
        steam=ProcessInfo("steam", 21, session_id=1),
    )
    supervisor = build_supervisor(tmp_path, runtime)
    assert supervisor.bootstrap() == RuntimeState.RUNNING

    runtime._game = None
    supervisor._watch_game()
    assert supervisor.status.state == RuntimeState.WAITING_FOR_GAME

    runtime._game = ProcessInfo("Diablo IV", 32, session_id=1)
    runtime.probe_tolk = lambda: TolkHealth(None, False, False)
    supervisor._watch_game()

    assert supervisor.status.state == RuntimeState.RESTART_REQUIRED
    assert supervisor.status.capture_active is False
    assert read_json(paths.capture_state)["enabled"] is False
    assert supervisor.status.game.pid == 32


def test_nvda_crash_recovers_without_touching_game(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    runtime = FakeRuntime(
        paths,
        game=ProcessInfo("Diablo IV", 31, session_id=1),
        steam=ProcessInfo("steam", 21, session_id=1),
    )
    supervisor = build_supervisor(tmp_path, runtime)
    assert supervisor.bootstrap() == RuntimeState.RUNNING

    runtime._nvda = None
    supervisor._recover_nvda()

    assert supervisor.status.state == RuntimeState.RUNNING
    assert runtime.launch_calls == 0
    assert runtime._game.pid == 31


def test_raw_capture_is_promoted_to_unified_monotonic_stream(tmp_path):
    import json

    paths = RuntimePaths(tmp_path / "home")
    runtime = FakeRuntime(
        paths,
        game=ProcessInfo("Diablo IV", 31, session_id=1),
        steam=ProcessInfo("steam", 21, session_id=1),
    )
    supervisor = build_supervisor(tmp_path, runtime)
    assert supervisor.bootstrap() == RuntimeState.RUNNING
    raw = supervisor.store.session.raw_speech_path
    raw.write_text(
        json.dumps(
            {
                "sessionId": supervisor.store.session.session_id,
                "sequence": 1,
                "timestamp": "2026-10-05T19:00:00+07:00",
                "process": "diablo iv",
                "windowTitle": "Diablo IV",
                "text": "850 Item Power",
                "rawSpeech": ["850 Item Power"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert supervisor._read_new_capture() == 1
    rows = [
        json.loads(line)
        for line in supervisor.store.session.events_path.read_text(encoding="utf-8").splitlines()
    ]
    speech = [row for row in rows if row["type"] == "speech.raw"]
    assert len(speech) == 1
    assert speech[0]["data"]["text"] == "850 Item Power"
    assert [row["eventSeq"] for row in rows] == list(range(1, len(rows) + 1))


def test_runtime_event_sink_failure_is_isolated(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    runtime = FakeRuntime(
        paths,
        game=ProcessInfo("Diablo IV", 31, session_id=1),
        steam=ProcessInfo("steam", 21, session_id=1),
    )
    supervisor = build_supervisor(tmp_path, runtime)
    assert supervisor.bootstrap() == RuntimeState.RUNNING

    def fail(*_args, **_kwargs):
        raise OSError("disk full")

    supervisor.store.emit = fail
    assert supervisor._safe_emit("runtime.test", {"detail": "x"}) is None
    assert "event sink failure" in supervisor.status.last_error
    assert supervisor.status.state == RuntimeState.RUNNING


def test_isolated_mode_requires_existing_steam_to_be_restarted(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    runtime = FakeRuntime(
        paths,
        game=None,
        steam=ProcessInfo("steam", 21, session_id=1),
    )
    manager = UserPathManager(paths, MemoryPathBackend(user_path="", machine_path="M"))
    supervisor = Supervisor(
        paths=paths,
        runtime=runtime,
        path_manager=manager,
        silent=True,
        isolated=True,
        poll_interval=0.001,
        game_start_timeout=0.01,
    )

    state = supervisor.bootstrap()

    assert state == RuntimeState.RESTART_REQUIRED
    assert runtime.launch_calls == 0
    assert "isolated mode" in supervisor.status.detail


def test_capture_lease_renewal_failure_backs_off(monkeypatch, tmp_path):
    import d4planner.runtime.supervisor as supervisor_module

    paths = RuntimePaths(tmp_path / "home")
    runtime = FakeRuntime(
        paths,
        game=ProcessInfo("Diablo IV", 31, session_id=1),
        steam=ProcessInfo("steam", 21, session_id=1),
    )
    supervisor = build_supervisor(tmp_path, runtime)
    assert supervisor.bootstrap() == RuntimeState.RUNNING

    def fail_write(*_args, **_kwargs):
        raise PermissionError("busy")

    monkeypatch.setattr(supervisor_module, "write_capture_config", fail_write)
    supervisor._next_lease_refresh = 0.0
    supervisor._renew_capture_lease(force=True)

    assert supervisor._next_lease_refresh > 0.0
    assert "capture lease renewal failed" in supervisor.status.last_error


def test_shutdown_state_write_failure_remains_fail_open(monkeypatch, tmp_path):
    import d4planner.runtime.supervisor as supervisor_module

    paths = RuntimePaths(tmp_path / "home")
    runtime = FakeRuntime(
        paths,
        game=ProcessInfo("Diablo IV", 31, session_id=1),
        steam=ProcessInfo("steam", 21, session_id=1),
    )
    supervisor = build_supervisor(tmp_path, runtime)
    supervisor.status.state = RuntimeState.RUNNING
    supervisor.status.capture_active = True
    paths.ensure()
    paths.stop_request.write_text("stop\n", encoding="utf-8")

    monkeypatch.setattr(supervisor, "bootstrap", lambda: RuntimeState.RUNNING)

    def fail_disable(*_args, **_kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(supervisor_module, "write_capture_config", fail_disable)

    assert supervisor.run() == 0
    assert supervisor.status.state == RuntimeState.STOPPED
    assert supervisor.status.capture_active is False
    assert "failed to disable capture during shutdown" in supervisor.status.last_error
