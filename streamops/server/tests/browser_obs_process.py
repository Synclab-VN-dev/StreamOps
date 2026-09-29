"""Browser-test OBS adapters using the real ObsManager state machine."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import threading
import time

from streamops.server.errors import ObsWebSocketConnectionError
from streamops.server.obs import ObsManager, ObsProcess
from streamops.server.platform.windows.session import DesktopSessionInfo


class FakeObsClient:
    host = "127.0.0.1"
    port = 4455

    def __init__(self, manager: "ControllableObsManager") -> None:
        self.manager = manager

    def connect(self) -> None:
        if not self.manager.ws_ready:
            raise ObsWebSocketConnectionError("Test OBS WebSocket unavailable.")

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
