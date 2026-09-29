from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import threading
import time

import pytest

from streamops.server.errors import (
    ObsOperationInProgressError,
    ObsReadinessTimeoutError,
    ObsShutdownTimeoutError,
    ObsUnsafeOperationError,
    ObsWebSocketConnectionError,
    WrongDesktopSessionError,
)
from streamops.server.obs.manager import ObsManager, ObsProcess
from streamops.server.platform.windows.session import NO_ACTIVE_CONSOLE_SESSION, DesktopSessionInfo


class FakeObsClient:
    host = "127.0.0.1"
    port = 4455

    def __init__(self, *, connected: bool = True, streaming: bool = False, recording: bool = False) -> None:
        self.connected = connected
        self.streaming = streaming
        self.recording = recording

    def connect(self) -> None:
        if not self.connected:
            raise ObsWebSocketConnectionError("test websocket unavailable")

    def close(self) -> None:
        pass

    def get_version(self):
        return {"obsVersion": "32.0.0", "obsWebSocketVersion": "5.6.0"}

    def get_stream_status(self):
        return {"outputActive": self.streaming}

    def get_record_status(self):
        return {"outputActive": self.recording}


def _manager(tmp_path: Path, client_factory=lambda: FakeObsClient()) -> tuple[ObsManager, Path]:
    executable = tmp_path / "obs-studio" / "bin" / "64bit" / "obs64.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"test")
    manager = ObsManager(
        executable=executable,
        client_factory=client_factory,
        start_timeout=0.05,
        shutdown_timeout=0.05,
        readiness_timeout=0.05,
        poll_interval=0,
    )
    manager._session_info = lambda: DesktopSessionInfo(7, 7)  # type: ignore[method-assign]
    return manager, executable


def _process(executable: Path, pid: int = 100, session_id: int = 7) -> ObsProcess:
    return ObsProcess(pid, executable, time.time() - 60, session_id)


def test_status_stopped(tmp_path: Path) -> None:
    manager, _ = _manager(tmp_path)
    manager._obs_processes = lambda: []  # type: ignore[method-assign]
    status = manager.status()
    assert status.state == "STOPPED"
    assert status.process["running"] is False
    assert status.websocket["connected"] is False


def test_status_ready_requires_process_session_and_websocket(tmp_path: Path) -> None:
    manager, executable = _manager(tmp_path)
    manager._obs_processes = lambda: [_process(executable)]  # type: ignore[method-assign]
    status = manager.status()
    assert status.state == "READY"
    assert status.process["pid"] == 100
    assert status.process["session_id"] == 7
    assert status.process["active_console_session_id"] == 7
    assert status.process["interactive"] is True
    assert status.websocket["obs_version"] == "32.0.0"
    assert status.websocket["obs_websocket_version"] == "5.6.0"
    assert status.output == {"streaming": False, "recording": False}


def test_running_without_websocket_is_not_ready(tmp_path: Path) -> None:
    manager, executable = _manager(tmp_path, lambda: FakeObsClient(connected=False))
    manager._obs_processes = lambda: [_process(executable)]  # type: ignore[method-assign]
    status = manager.status()
    assert status.state == "RUNNING_NO_WEBSOCKET"
    assert status.websocket["connected"] is False
    assert status.output == {"streaming": None, "recording": None}


def test_wrong_process_session_is_error(tmp_path: Path) -> None:
    manager, executable = _manager(tmp_path)
    manager._obs_processes = lambda: [_process(executable, session_id=8)]  # type: ignore[method-assign]
    status = manager.status()
    assert status.state == "ERROR"
    assert "does not match active console session" in (status.error or "")


def test_process_outside_allowlist_is_error(tmp_path: Path) -> None:
    manager, _ = _manager(tmp_path)
    other = tmp_path / "other" / "obs64.exe"
    other.parent.mkdir()
    other.write_bytes(b"test")
    manager._obs_processes = lambda: [_process(other)]  # type: ignore[method-assign]
    status = manager.status()
    assert status.state == "ERROR"
    assert "allowed executable path" in (status.error or "")


def test_start_stopped_launches_one_process_and_waits_until_ready(tmp_path: Path) -> None:
    manager, executable = _manager(tmp_path)
    processes: list[ObsProcess] = []
    launches = 0
    manager._obs_processes = lambda: list(processes)  # type: ignore[method-assign]

    def launch(_executable: Path):
        nonlocal launches
        launches += 1
        processes.append(_process(executable, pid=200))
        return SimpleNamespace(pid=200)

    manager._launch = launch  # type: ignore[method-assign]
    status = manager.start()
    assert launches == 1
    assert status.state == "READY"
    assert status.process["pid"] == 200
    assert status.last_operation["action"] == "start"
    assert status.last_operation["result"] == "success"


def test_start_running_without_websocket_never_spawns_duplicate(tmp_path: Path) -> None:
    attempts = 0

    def client_factory():
        nonlocal attempts
        attempts += 1
        return FakeObsClient(connected=attempts >= 3)

    manager, executable = _manager(tmp_path, client_factory)
    manager._obs_processes = lambda: [_process(executable)]  # type: ignore[method-assign]
    manager._launch = lambda _executable: pytest.fail("must not launch duplicate OBS")  # type: ignore[method-assign]
    status = manager.start()
    assert status.state == "READY"
    assert attempts >= 3


@pytest.mark.parametrize("client", [FakeObsClient(streaming=True), FakeObsClient(recording=True)])
def test_stop_is_blocked_when_output_active(tmp_path: Path, client: FakeObsClient) -> None:
    manager, executable = _manager(tmp_path, lambda: client)
    manager._obs_processes = lambda: [_process(executable)]  # type: ignore[method-assign]
    manager._request_graceful_close = lambda _pid: pytest.fail("must not close OBS")  # type: ignore[method-assign]
    with pytest.raises(ObsUnsafeOperationError):
        manager.stop()


def test_stop_uses_graceful_close_and_never_force_kills(tmp_path: Path) -> None:
    manager, executable = _manager(tmp_path)
    processes = [_process(executable)]
    closed: list[int] = []
    manager._obs_processes = lambda: list(processes)  # type: ignore[method-assign]

    def close(pid: int) -> None:
        closed.append(pid)
        processes.clear()

    manager._request_graceful_close = close  # type: ignore[method-assign]
    status = manager.stop()
    assert closed == [100]
    assert status.state == "STOPPED"
    assert status.last_operation["action"] == "stop"


def test_concurrent_lifecycle_operations_are_serialized(tmp_path: Path) -> None:
    manager, _ = _manager(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    def blocking_start():
        entered.set()
        assert release.wait(timeout=2)
        return manager._status_impl(include_operation=False)

    manager._start_locked = blocking_start  # type: ignore[method-assign]
    manager._obs_processes = lambda: []  # type: ignore[method-assign]
    result: list[object] = []
    thread = threading.Thread(target=lambda: result.append(manager.start()))
    thread.start()
    assert entered.wait(timeout=1)
    with pytest.raises(ObsOperationInProgressError):
        manager.stop()
    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert len(result) == 1

def test_status_reports_starting_while_start_waits_for_process(tmp_path: Path) -> None:
    manager, _ = _manager(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    manager._obs_processes = lambda: []  # type: ignore[method-assign]

    def blocking_start():
        entered.set()
        assert release.wait(timeout=2)
        return manager._status_impl(include_operation=False)

    manager._start_locked = blocking_start  # type: ignore[method-assign]
    result: list[object] = []
    thread = threading.Thread(target=lambda: result.append(manager.start()))
    thread.start()
    assert entered.wait(timeout=1)

    status = manager.status()
    assert status.state == "STARTING"

    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()

def test_start_ready_is_idempotent_and_does_not_launch(tmp_path: Path) -> None:
    manager, executable = _manager(tmp_path)
    manager._obs_processes = lambda: [_process(executable)]  # type: ignore[method-assign]
    manager._launch = lambda _executable: pytest.fail("READY start must be a no-op")  # type: ignore[method-assign]

    status = manager.start()

    assert status.state == "READY"
    assert status.process["pid"] == 100
    assert status.last_operation["action"] == "start"
    assert status.last_operation["result"] == "success"


def test_stop_stopped_is_idempotent_and_does_not_close(tmp_path: Path) -> None:
    manager, _ = _manager(tmp_path)
    manager._obs_processes = lambda: []  # type: ignore[method-assign]
    manager._request_graceful_close = lambda _pid: pytest.fail("STOPPED stop must be a no-op")  # type: ignore[method-assign]

    status = manager.stop()

    assert status.state == "STOPPED"
    assert status.last_operation["action"] == "stop"
    assert status.last_operation["result"] == "success"


def test_start_wrong_interactive_session_fails_before_launch(tmp_path: Path) -> None:
    manager, _ = _manager(tmp_path)
    manager._obs_processes = lambda: []  # type: ignore[method-assign]
    manager._session_info = lambda: DesktopSessionInfo(0, 7)  # type: ignore[method-assign]
    manager._launch = lambda _executable: pytest.fail("wrong-session start must not launch")  # type: ignore[method-assign]

    with pytest.raises(WrongDesktopSessionError, match="OBS start"):
        manager.start()


def test_running_without_websocket_times_out_without_duplicate_launch(tmp_path: Path) -> None:
    manager, executable = _manager(tmp_path, lambda: FakeObsClient(connected=False))
    manager._obs_processes = lambda: [_process(executable)]  # type: ignore[method-assign]
    manager._launch = lambda _executable: pytest.fail("must not launch duplicate OBS")  # type: ignore[method-assign]

    with pytest.raises(ObsReadinessTimeoutError, match="did not become ready"):
        manager.start()


def test_shutdown_timeout_never_force_kills(tmp_path: Path) -> None:
    manager, executable = _manager(tmp_path)
    manager._obs_processes = lambda: [_process(executable)]  # type: ignore[method-assign]
    graceful: list[int] = []
    manager._request_graceful_close = lambda pid: graceful.append(pid)  # type: ignore[method-assign]
    manager._wait_until_stopped = lambda _pids: False  # type: ignore[method-assign]

    with pytest.raises(ObsShutdownTimeoutError, match="not force-killed"):
        manager.stop()

    assert graceful == [100]


def test_restart_is_blocked_when_recording_is_active(tmp_path: Path) -> None:
    manager, executable = _manager(tmp_path, lambda: FakeObsClient(recording=True))
    manager._obs_processes = lambda: [_process(executable)]  # type: ignore[method-assign]
    manager._request_graceful_close = lambda _pid: pytest.fail("restart must not close while recording")  # type: ignore[method-assign]

    with pytest.raises(ObsUnsafeOperationError, match="recording"):
        manager.restart()


def test_status_never_exposes_websocket_password(tmp_path: Path) -> None:
    class ClientWithSecret(FakeObsClient):
        password = "super-secret-password"

    manager, executable = _manager(tmp_path, lambda: ClientWithSecret())
    manager._obs_processes = lambda: [_process(executable)]  # type: ignore[method-assign]

    payload = manager.status().api_payload()

    assert "super-secret-password" not in repr(payload)
    assert "password" not in payload["websocket"]

def test_start_without_active_console_session_fails_safely(tmp_path: Path) -> None:
    manager, _ = _manager(tmp_path)
    manager._obs_processes = lambda: []  # type: ignore[method-assign]
    manager._session_info = lambda: DesktopSessionInfo(0, NO_ACTIVE_CONSOLE_SESSION)  # type: ignore[method-assign]
    manager._launch = lambda _executable: pytest.fail("start must not launch without an active desktop")  # type: ignore[method-assign]

    with pytest.raises(WrongDesktopSessionError):
        manager.start()


@pytest.mark.parametrize(
    "client",
    [FakeObsClient(streaming=True), FakeObsClient(recording=True)],
)
def test_restart_is_blocked_for_any_active_output(tmp_path: Path, client: FakeObsClient) -> None:
    manager, executable = _manager(tmp_path, lambda: client)
    manager._obs_processes = lambda: [_process(executable)]  # type: ignore[method-assign]
    manager._request_graceful_close = lambda _pid: pytest.fail("restart must not close with active output")  # type: ignore[method-assign]

    with pytest.raises(ObsUnsafeOperationError):
        manager.restart()

def test_restart_fails_if_websocket_does_not_return_before_timeout(tmp_path: Path) -> None:
    processes: list[ObsProcess] = []
    manager, executable = _manager(
        tmp_path,
        lambda: FakeObsClient(
            connected=not processes or processes[0].pid == 100,
        ),
    )
    processes.append(_process(executable, pid=100))
    manager._obs_processes = lambda: list(processes)  # type: ignore[method-assign]

    def close(_pid: int) -> None:
        processes.clear()

    def launch(_executable: Path):
        processes.append(_process(executable, pid=200))
        return SimpleNamespace(pid=200)

    manager._request_graceful_close = close  # type: ignore[method-assign]
    manager._launch = launch  # type: ignore[method-assign]

    with pytest.raises(ObsReadinessTimeoutError, match="did not become ready"):
        manager.restart()

    assert [process.pid for process in processes] == [200]

