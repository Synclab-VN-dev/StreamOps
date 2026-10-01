from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from streamops.server.app import create_app
from streamops.server.auth import require_access
from streamops.server.errors import (
    ObsOperationInProgressError,
    ObsReadinessTimeoutError,
    ObsShutdownTimeoutError,
    ObsUnsafeOperationError,
)
from streamops.server.obs.manager import ObsRuntimeStatus


def runtime_status(state: str = "READY", *, pid: int | None = 5000) -> ObsRuntimeStatus:
    running = pid is not None
    return ObsRuntimeStatus(
        state=state,  # type: ignore[arg-type]
        process={
            "running": running,
            "pid": pid,
            "started_at": "2026-09-29T10:00:00+07:00" if running else None,
            "uptime_seconds": 60 if running else None,
            "session_id": 7 if running else None,
            "active_console_session_id": 7,
            "interactive": running,
            "executable_path": r"C:\Program Files\obs-studio\bin\64bit\obs64.exe" if running else None,
            "expected_executable_path": r"C:\Program Files\obs-studio\bin\64bit\obs64.exe",
        },
        websocket={
            "connected": state == "READY",
            "host": "127.0.0.1",
            "port": 4455,
            "obs_version": "32.0.0" if state == "READY" else None,
            "obs_websocket_version": "5.6.0" if state == "READY" else None,
        },
        output={"streaming": False, "recording": False},
        last_operation=None,
        error=None,
    )


class FakeObsManager:
    def __init__(self) -> None:
        self.status_result: ObsRuntimeStatus | Exception = runtime_status()
        self.calls: list[str] = []
        self.failures: dict[str, Exception] = {}

    def _result(self, action: str) -> ObsRuntimeStatus:
        self.calls.append(action)
        failure = self.failures.get(action)
        if failure:
            raise failure
        if action == "status" and isinstance(self.status_result, Exception):
            raise self.status_result
        assert isinstance(self.status_result, ObsRuntimeStatus)
        return self.status_result

    def status(self) -> ObsRuntimeStatus:
        return self._result("status")

    def start(self) -> ObsRuntimeStatus:
        return self._result("start")

    def stop(self) -> ObsRuntimeStatus:
        return self._result("stop")

    def restart(self) -> ObsRuntimeStatus:
        return self._result("restart")


def _client(server_config, capture_service, manager: FakeObsManager) -> TestClient:
    return TestClient(create_app(
        server_config,
        capture_service=capture_service,
        obs_manager=manager,  # type: ignore[arg-type]
        manage_runtime=False,
    ))


def test_obs_status_contract(server_config, capture_service) -> None:
    manager = FakeObsManager()
    with _client(server_config, capture_service, manager) as client:
        response = client.get("/api/v1/obs/process/status")
    assert response.status_code == 200
    assert response.json()["state"] == "READY"
    assert response.json()["process"]["pid"] == 5000
    assert response.json()["websocket"]["connected"] is True
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("action", ["start", "stop", "restart"])
def test_lifecycle_actions_have_stable_contract(server_config, capture_service, action: str) -> None:
    manager = FakeObsManager()
    with _client(server_config, capture_service, manager) as client:
        response = client.post(f"/api/v1/obs/process/{action}")
    assert response.status_code == 200
    assert response.json()["state"] == "READY"
    assert manager.calls.count(action) == 1


@pytest.mark.parametrize("payload", [
    {"executable": r"C:\other\obs64.exe"},
    {"arguments": ["--multi"]},
    {"command": "Stop-Process obs64"},
    {"script": "shutdown.ps1"},
])
@pytest.mark.parametrize("action", ["start", "stop", "restart"])
def test_lifecycle_rejects_all_client_input(server_config, capture_service, payload, action: str) -> None:
    manager = FakeObsManager()
    with _client(server_config, capture_service, manager) as client:
        response = client.post(f"/api/v1/obs/process/{action}", json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_obs_process_request"
    assert action not in manager.calls


@pytest.mark.parametrize(("action", "error", "status_code", "code"), [
    ("start", ObsOperationInProgressError("busy"), 409, "obs_operation_in_progress"),
    ("stop", ObsUnsafeOperationError("recording"), 409, "obs_unsafe_operation"),
    ("restart", ObsUnsafeOperationError("streaming"), 409, "obs_unsafe_operation"),
    ("start", ObsReadinessTimeoutError("timeout"), 504, "obs_readiness_timeout"),
    ("stop", ObsShutdownTimeoutError("timeout"), 504, "obs_shutdown_timeout"),
])
def test_lifecycle_error_contracts(server_config, capture_service, action: str, error: Exception, status_code: int, code: str) -> None:
    manager = FakeObsManager()
    manager.failures[action] = error
    with _client(server_config, capture_service, manager) as client:
        response = client.post(f"/api/v1/obs/process/{action}")
    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code


def test_obs_router_uses_access_policy(server_config, capture_service) -> None:
    manager = FakeObsManager()
    app = create_app(server_config, capture_service=capture_service, obs_manager=manager, manage_runtime=False)  # type: ignore[arg-type]
    calls = 0

    async def track_access() -> None:
        nonlocal calls
        calls += 1

    app.dependency_overrides[require_access] = track_access
    with TestClient(app) as client:
        client.get("/api/v1/obs/process/status")
        client.post("/api/v1/obs/process/start")
        client.post("/api/v1/obs/process/stop")
        client.post("/api/v1/obs/process/restart")
    assert calls == 4


def test_obs_management_page_is_served(server_config, capture_service) -> None:
    manager = FakeObsManager()
    with _client(server_config, capture_service, manager) as client:
        response = client.get("/obs")
    assert response.status_code == 200
    assert "OBS Runtime" in response.text
    assert "obs-process.js" in response.text
    assert response.headers["cache-control"] == "no-store"
