from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import logging
from pathlib import Path
from types import SimpleNamespace
import socket
import threading
import time
from typing import Any, Callable

from PIL import Image
import pytest
import uvicorn

from streamops.errors import ObsConnectionError
from streamops.server.app import create_app
from streamops.server.config import ServerConfig
from streamops.server.errors import ScreenCaptureError, SteamLaunchError
from streamops.server.obs import ObsManager, ObsProcess
from streamops.server.platform.windows.session import DesktopSessionInfo
from streamops.server.services import ScreenCaptureService, SteamService
from streamops.server.services.steam import SteamStatus


INTERNAL_LOG_SENTINEL = r"C:\internal\streamops\steam-test.log test-secret"


def running_status(pid: int = 2100) -> SteamStatus:
    return SteamStatus(
        state="running",
        running=True,
        pid=pid,
        started_at="2026-09-28T00:00:00Z",
        uptime_seconds=3723,
        session_id=7,
        interactive=True,
        installation_detected=True,
    )


def stopped_status() -> SteamStatus:
    return SteamStatus(
        state="stopped",
        running=False,
        pid=None,
        started_at=None,
        uptime_seconds=None,
        session_id=None,
        interactive=False,
        installation_detected=True,
    )


class ControllableSteamBackend:
    """Thread-safe Steam backend controlled by browser tests."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status = running_status()
        self._restart_result: SteamStatus | Exception = running_status(3100)
        self.status_calls = 0
        self.restart_calls = 0
        self.restart_started = threading.Event()
        self.restart_release = threading.Event()

    def status(self) -> SteamStatus:
        with self._lock:
            self.status_calls += 1
            return self._status

    def restart(self) -> SteamStatus:
        with self._lock:
            self.restart_calls += 1
        self.restart_started.set()
        if not self.restart_release.wait(timeout=10):
            raise SteamLaunchError("Timed out waiting for the test restart controller.")
        logging.getLogger(__name__).info(INTERNAL_LOG_SENTINEL)
        with self._lock:
            result = self._restart_result
            if isinstance(result, Exception):
                raise result
            self._status = result
            return result

    def set_running(self, pid: int) -> None:
        with self._lock:
            self._status = running_status(pid)

    def set_stopped(self) -> None:
        with self._lock:
            self._status = stopped_status()

    def prepare_restart_success(self, pid: int) -> None:
        with self._lock:
            self._restart_result = running_status(pid)
        self.restart_started.clear()
        self.restart_release.clear()

    def prepare_restart_failure(self, message: str = "Test Steam launch failed.") -> None:
        with self._lock:
            self._restart_result = SteamLaunchError(message)
        self.restart_started.clear()
        self.restart_release.clear()

    def release_restart(self) -> None:
        self.restart_release.set()


class FakeObsClient:
    host = "127.0.0.1"
    port = 4455

    def __init__(self, manager: "ControllableObsManager") -> None:
        self.manager = manager

    def connect(self) -> None:
        if not self.manager.ws_ready:
            raise ObsConnectionError("Test OBS WebSocket unavailable.")

    def close(self) -> None:
        pass

    def get_version(self):
        return {"obsVersion": "32.0.0-test", "obsWebSocketVersion": "5.6.0-test"}

    def get_stream_status(self):
        return {"outputActive": self.manager.streaming}

    def get_record_status(self):
        return {"outputActive": self.manager.recording}


class ControllableObsManager(ObsManager):
    """Real lifecycle manager with fake Windows process and fake WebSocket adapters."""

    def __init__(self, executable: Path) -> None:
        super().__init__(
            executable=executable,
            client_factory=lambda: FakeObsClient(self),
            start_timeout=2,
            shutdown_timeout=2,
            readiness_timeout=2,
            poll_interval=0.01,
        )
        self._process: ObsProcess | None = ObsProcess(5100, executable, time.time() - 120, 7)
        self.ws_ready = True
        self.streaming = False
        self.recording = False
        self.target_pid = 6100
        self.status_calls = 0
        self.launch_calls = 0
        self.launch_started = threading.Event()
        self.launch_release = threading.Event()
        self.launch_release.set()
        self._test_lock = threading.Lock()

    def status(self):
        with self._test_lock:
            self.status_calls += 1
        return super().status()

    def _session_info(self) -> DesktopSessionInfo:
        return DesktopSessionInfo(7, 7)

    def _obs_processes(self) -> list[ObsProcess]:
        with self._test_lock:
            return [self._process] if self._process is not None else []

    def _launch(self, _executable: Path):
        with self._test_lock:
            self.launch_calls += 1
            pid = self.target_pid
        self.launch_started.set()
        if not self.launch_release.wait(timeout=10):
            raise RuntimeError("Timed out waiting for OBS browser test launch release.")
        with self._test_lock:
            self._process = ObsProcess(pid, self.expected_executable, time.time(), 7)
        return SimpleNamespace(pid=pid)

    def _request_graceful_close(self, _pid: int) -> None:
        with self._test_lock:
            self._process = None

    def set_stopped(self) -> None:
        with self._test_lock:
            self._process = None
            self.streaming = False
            self.recording = False
            self.ws_ready = True

    def set_ready(self, pid: int, *, streaming: bool = False, recording: bool = False) -> None:
        with self._test_lock:
            self._process = ObsProcess(pid, self.expected_executable, time.time() - 30, 7)
            self.streaming = streaming
            self.recording = recording
            self.ws_ready = True

    def set_websocket_unavailable(self) -> None:
        with self._test_lock:
            self.ws_ready = False

    def prepare_launch(self, pid: int) -> None:
        with self._test_lock:
            self.target_pid = pid
        self.launch_started.clear()
        self.launch_release.clear()

    def release_launch(self) -> None:
        self.launch_release.set()


class ControllableCaptureBackend:
    backend_name = "fake-browser"

    def __init__(self) -> None:
        self._frames: deque[Any] = deque(
            [
                Image.new("RGB", (12, 8), "#2da486"),
                ScreenCaptureError("Test capture failed."),
            ]
        )
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def capture(self, _timeout: float) -> Any:
        value = self._frames.popleft()
        if isinstance(value, Exception):
            raise value
        return value.copy()

    def close(self) -> None:
        self.closed = True


@dataclass(frozen=True)
class BrowserTestServer:
    base_url: str
    steam: ControllableSteamBackend
    obs: ControllableObsManager
    capture: ControllableCaptureBackend


@pytest.fixture
def live_server(tmp_path: Path) -> BrowserTestServer:
    steam_backend = ControllableSteamBackend()
    obs_executable = tmp_path / "obs-studio" / "bin" / "64bit" / "obs64.exe"
    obs_executable.parent.mkdir(parents=True)
    obs_executable.write_bytes(b"test")
    obs_manager = ControllableObsManager(obs_executable)
    capture_backend = ControllableCaptureBackend()
    config = ServerConfig(
        host="127.0.0.1",
        port=0,
        output_index=0,
        data_dir=tmp_path,
        capture_timeout=0.5,
        log_level="warning",
    )
    app = create_app(
        config,
        capture_service=ScreenCaptureService(capture_backend, tmp_path, config.capture_timeout),
        steam_service=SteamService(steam_backend),
        obs_manager=obs_manager,
        manage_runtime=False,
    )

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="on"))
    thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [listener]},
        name="streamops-browser-test-server",
        daemon=True,
    )
    thread.start()
    wait_until(lambda: server.started, message="The browser test server did not start.")

    try:
        yield BrowserTestServer(f"http://127.0.0.1:{port}", steam_backend, obs_manager, capture_backend)
    finally:
        steam_backend.release_restart()
        obs_manager.release_launch()
        server.should_exit = True
        thread.join(timeout=10)
        if thread.is_alive():
            raise RuntimeError("The browser test server did not stop.")


def wait_until(
    predicate: Callable[[], bool],
    *,
    timeout: float = 5,
    message: str = "Condition was not met before timeout.",
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(message)
