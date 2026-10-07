from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import logging
from io import BytesIO
from pathlib import Path
import socket
import threading
import time
from typing import Any, Callable

from PIL import Image
import pytest
import uvicorn

from streamops.server.app import create_app
from streamops.server.config import ServerConfig
from streamops.server.errors import ScreenCaptureError, SteamLaunchError
from streamops.server.services import ScreenCaptureService, SteamService
from streamops.server.services.live import LiveService
from streamops.server.services.live_status import LiveStatusHub
from streamops.server.services.multistream import MultistreamService
from streamops.server.services.steam import SteamStatus
from streamops.server.services.obs_scene import ObsSceneService
from streamops.server.multistream.repository import MultistreamRepository
from streamops.server.multistream.secrets import MultistreamSecretStore
from streamops.server.scene_profiles import source_catalog
from streamops.server.tests.browser_obs import BrowserObs
from streamops.server.tests.browser_obs_process import ControllableObsManager
from streamops.server.streaming import DestinationStore, SecretStore


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


class ControllableMultistreamAdapter:
    """In-memory plugin boundary used through the real public REST/WS routes."""

    def __init__(self) -> None:
        self.targets: list[dict[str, Any]] = []
        self.runtime: dict[str, dict[str, Any]] = {}
        self.next_id = 1

    def list_targets(self):
        return [dict(target) for target in self.targets]

    def add_target(self, name):
        target = {"id": str(self.next_id), "name": name}
        self.next_id += 1
        self.targets.append(target)
        self.runtime[target["id"]] = {"runtimeState": "IDLE", "status": "stopped"}
        return {"status": "target_added"}

    def delete_target(self, target_id):
        self.targets = [target for target in self.targets if target["id"] != target_id]
        self.runtime.pop(target_id, None)
        return {}

    def update_name(self, target_id, name):
        next(target for target in self.targets if target["id"] == target_id)["name"] = name
        return {}

    def update_server(self, _target_id, _server_url):
        return {}

    def update_stream_key(self, _target_id, _key):
        return {"status": "updated"}

    def start(self, target_id):
        self.set_state(target_id, "STARTING")
        return {"status": "start_requested"}

    def stop(self, target_id):
        self.set_state(target_id, "STOPPING")
        return {"status": "stop_requested"}

    def state(self, target_id):
        return dict(self.runtime[target_id])

    def stats(self, target_id):
        return {
            **self.runtime[target_id],
            "totalBytes": 12_345_678,
            "totalFrames": 7_890,
            "bitrateValue": 6_000_000,
            "fpsValue": 60,
        }

    def set_state(self, target_id: str, state: str) -> None:
        self.runtime[target_id] = {
            "runtimeState": state,
            "status": state.casefold(),
            "isRunning": state in {"LIVE", "RECONNECTING"},
        }


@dataclass(frozen=True)
class BrowserTestServer:
    base_url: str
    steam: ControllableSteamBackend
    capture: ControllableCaptureBackend
    obs: ObsSceneService
    transport: BrowserObs
    obs_process: ControllableObsManager
    live: LiveService
    multistream: MultistreamService
    multistream_adapter: ControllableMultistreamAdapter
    source_catalog: list[dict[str, Any]]


@pytest.fixture
def live_server(tmp_path: Path) -> BrowserTestServer:
    steam_backend = ControllableSteamBackend()
    obs_executable = tmp_path / "obs-studio" / "bin" / "64bit" / "obs64.exe"
    obs_executable.parent.mkdir(parents=True)
    obs_executable.write_bytes(b"test")
    obs_manager = ControllableObsManager(obs_executable)
    capture_backend = ControllableCaptureBackend()
    transport = BrowserObs(tmp_path)
    catalog = source_catalog()
    obs_service = ObsSceneService(data_dir=tmp_path / "profiles", artifact_root=tmp_path / "artifacts", client_factory=lambda: transport, inventory_provider=lambda: {"windows": [], "capture": [], "render": [], "cameras": [], "errors": []}, catalog_provider=lambda: catalog)
    config = ServerConfig(
        host="127.0.0.1",
        port=0,
        output_index=0,
        data_dir=tmp_path,
        capture_timeout=0.5,
        log_level="warning",
    )
    live_service = LiveService(
        obs_manager,
        obs_service,
        DestinationStore(tmp_path / "stream-destinations"),
        SecretStore(tmp_path / "stream-secrets"),
        client_factory=lambda: transport,
        poll_interval=0.001,
    )
    live_hub = LiveStatusHub(live_service, reconcile_interval=0.05, heartbeat_interval=1.0)
    multistream_adapter = ControllableMultistreamAdapter()
    multistream_service = MultistreamService(
        MultistreamRepository(tmp_path / "multistream-destinations"),
        multistream_adapter,
        MultistreamSecretStore(tmp_path / "multistream-secrets"),
        poll_interval=0.01,
    )
    app = create_app(
        config,
        capture_service=ScreenCaptureService(capture_backend, tmp_path, config.capture_timeout),
        steam_service=SteamService(steam_backend),
        obs_manager=obs_manager,
        obs_scene_service=obs_service,
        live_service=live_service,
        live_status_hub=live_hub,
        multistream_service=multistream_service,
        manage_runtime=False,
    )

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(
        app,
        log_level="warning",
        lifespan="on",
        timeout_graceful_shutdown=5,
    ))
    thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [listener]},
        name="streamops-browser-test-server",
        daemon=True,
    )
    thread.start()
    wait_until(lambda: server.started, message="The browser test server did not start.")

    try:
        yield BrowserTestServer(
            base_url=f"http://127.0.0.1:{port}",
            steam=steam_backend,
            capture=capture_backend,
            obs=obs_service,
            transport=transport,
            obs_process=obs_manager,
            live=live_service,
            multistream=multistream_service,
            multistream_adapter=multistream_adapter,
            source_catalog=catalog,
        )
    finally:
        obs_service.close()
        steam_backend.release_restart()
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
