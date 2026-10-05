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
    )


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

    runtime._game = ProcessInfo("Diablo IV", 32, session_id=1)
    supervisor._watch_game()
    assert supervisor.status.state == RuntimeState.RUNNING
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
