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


class _Payload:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def to_dict(self) -> dict[str, Any]:
        return self.payload


class ControllableObsSceneService:
    def __init__(self) -> None:
        self.apply_calls = 0
        self.verify_calls = 0
        self.activate_calls = 0
        self.review_calls = 0
        self.review_status_calls = 0

    def close(self) -> None:
        pass

    def status(self) -> dict[str, Any]:
        return {
            "connected": True,
            "obs_version": "32.0.2",
            "websocket_version": "5.7.0",
            "current_scene": "livestream-d4",
            "streaming": False,
            "recording": False,
        }

    def list_scenes(self) -> list[dict[str, Any]]:
        return [{"name": "livestream-d4"}]

    def scene(self, scene_name: str, *, runtime_audio: bool = False) -> dict[str, Any]:
        assert scene_name == "livestream-d4"
        return {
            "name": scene_name,
            "video": {
                "base_width": 1920,
                "base_height": 1080,
                "output_width": 1920,
                "output_height": 1080,
                "fps": 60,
            },
            "sources": [
                {"role": "main", "source_name": "StreamOps D4 Video", "media": "video", "managed": False, "signal_required": False},
                {"role": "camera", "source_name": "StreamOps Camera", "media": "video", "managed": False, "signal_required": False},
                {"role": "game_audio", "source_name": "StreamOps D4 Audio", "media": "audio", "managed": False, "signal_required": True},
                {"role": "voice", "source_name": "StreamOps Voice", "media": "audio", "managed": False, "signal_required": True},
            ],
            "verify": self._verify_payload(),
        }

    def apply(self, scene_name: str) -> _Payload:
        self.apply_calls += 1
        return _Payload({"scene": scene_name, "changed": self.apply_calls == 1, "changes": []})

    def verify(self, scene_name: str, *, runtime_audio: bool = True) -> _Payload:
        self.verify_calls += 1
        return _Payload(self._verify_payload())

    def activate(self, scene_name: str) -> dict[str, Any]:
        self.activate_calls += 1
        return {"scene": scene_name, "active": True}

    def preview(self, scene_name: str) -> bytes:
        assert scene_name == "livestream-d4"
        buffer = BytesIO()
        Image.new("RGB", (16, 9), "#2da486").save(buffer, format="PNG")
        return buffer.getvalue()

    def start_review(self, scene_name: str, *, seconds: int = 30) -> _Payload:
        self.review_calls += 1
        return _Payload({
            "job_id": "browser-review-1",
            "scene": scene_name,
            "state": "queued",
            "created_at": "2026-09-28T12:00:00Z",
            "updated_at": "2026-09-28T12:00:00Z",
            "seconds": seconds,
            "result": None,
            "error": None,
        })

    def review_job(self, job_id: str) -> _Payload:
        assert job_id == "browser-review-1"
        self.review_status_calls += 1
        return _Payload({
            "job_id": job_id,
            "scene": "livestream-d4",
            "state": "completed",
            "created_at": "2026-09-28T12:00:00Z",
            "updated_at": "2026-09-28T12:00:01Z",
            "seconds": 30,
            "result": self._verify_payload(),
            "error": None,
        })

    @staticmethod
    def _verify_payload() -> dict[str, Any]:
        return {
            "scene": "livestream-d4",
            "status": "PASS",
            "generated_at": "2026-09-28T12:00:00Z",
            "obs_version": "32.0.2",
            "checks": [
                {"id": "source.main.exists", "status": "PASS", "message": "D4 exists", "expected": True, "actual": True},
                {"id": "source.camera.exists", "status": "PASS", "message": "Camera exists", "expected": True, "actual": True},
                {"id": "audio.game_audio.signal", "status": "PASS", "message": "Game audio signal", "expected": {}, "actual": {"peak_db": -12}},
                {"id": "audio.voice.signal", "status": "PASS", "message": "Voice signal", "expected": {}, "actual": {"peak_db": -18}},
            ],
            "artifacts": {},
        }


@dataclass(frozen=True)
class BrowserTestServer:
    base_url: str
    steam: ControllableSteamBackend
    capture: ControllableCaptureBackend
    obs: ControllableObsSceneService


@pytest.fixture
def live_server(tmp_path: Path) -> BrowserTestServer:
    steam_backend = ControllableSteamBackend()
    capture_backend = ControllableCaptureBackend()
    obs_service = ControllableObsSceneService()
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
        obs_scene_service=obs_service,
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
        yield BrowserTestServer(f"http://127.0.0.1:{port}", steam_backend, capture_backend, obs_service)
    finally:
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
