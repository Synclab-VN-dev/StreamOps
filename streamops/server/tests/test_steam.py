from __future__ import annotations

import asyncio
import threading

import pytest
from fastapi.testclient import TestClient

from streamops.server.app import create_app
from streamops.server.auth import require_access
from streamops.server.errors import (
    SteamLaunchError,
    SteamNotFoundError,
    SteamRestartInProgressError,
    SteamShutdownError,
    SteamShutdownTimeoutError,
    SteamStatusError,
    WrongDesktopSessionError,
)
from streamops.server.services import SteamService, SteamStatus


RUNNING = SteamStatus(
    state="running",
    running=True,
    pid=23456,
    started_at="2026-09-27T06:32:10+07:00",
    uptime_seconds=2412,
    session_id=2,
    interactive=True,
    installation_detected=True,
)

STOPPED = SteamStatus(
    state="stopped",
    running=False,
    pid=None,
    started_at=None,
    uptime_seconds=None,
    session_id=None,
    interactive=False,
    installation_detected=True,
)


class FakeSteamBackend:
    def __init__(self, status=RUNNING, restart=RUNNING) -> None:
        self.status_result = status
        self.restart_result = restart
        self.restart_calls = 0

    def status(self) -> SteamStatus:
        if isinstance(self.status_result, Exception):
            raise self.status_result
        return self.status_result

    def restart(self) -> SteamStatus:
        self.restart_calls += 1
        if isinstance(self.restart_result, Exception):
            raise self.restart_result
        return self.restart_result


def _client(server_config, capture_service, backend: FakeSteamBackend) -> TestClient:
    return TestClient(
        create_app(
            server_config,
            capture_service=capture_service,
            steam_service=SteamService(backend),
            manage_runtime=False,
        )
    )


@pytest.mark.parametrize("expected", [RUNNING, STOPPED])
def test_status_contract(server_config, capture_service, expected: SteamStatus) -> None:
    with _client(server_config, capture_service, FakeSteamBackend(status=expected)) as client:
        response = client.get("/api/v1/steam/status")

    assert response.status_code == 200
    assert response.json() == expected.api_payload()
    assert response.headers["cache-control"] == "no-store"


def test_restart_success_contract(server_config, capture_service) -> None:
    backend = FakeSteamBackend(restart=RUNNING)
    with _client(server_config, capture_service, backend) as client:
        response = client.post("/api/v1/steam/restart")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "action": "restart",
        "running": True,
        "pid": 23456,
        "big_picture_requested": True,
    }
    assert backend.restart_calls == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"executable": r"C:\\other\\steam.exe"},
        {"command": "Stop-Process steam"},
        {"arguments": ["-silent"]},
        {"script": "steam-restart.ps1"},
    ],
)
def test_restart_rejects_all_client_input(server_config, capture_service, payload) -> None:
    backend = FakeSteamBackend()
    with _client(server_config, capture_service, backend) as client:
        response = client.post("/api/v1/steam/restart", json=payload)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_restart_request"
    assert backend.restart_calls == 0


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (SteamNotFoundError("missing"), 404, "steam_not_found"),
        (SteamRestartInProgressError("busy"), 409, "restart_in_progress"),
        (SteamShutdownTimeoutError("timeout"), 504, "steam_shutdown_timeout"),
        (SteamShutdownError("shutdown"), 503, "steam_shutdown_failed"),
        (SteamLaunchError("launch"), 503, "steam_launch_failed"),
        (WrongDesktopSessionError(0, 1, operation="Steam restart"), 503, "wrong_desktop_session"),
    ],
)
def test_restart_error_contracts(
    server_config, capture_service, error, status_code: int, code: str
) -> None:
    backend = FakeSteamBackend(restart=error)
    with _client(server_config, capture_service, backend) as client:
        response = client.post("/api/v1/steam/restart")

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code


def test_status_error_contract(server_config, capture_service) -> None:
    backend = FakeSteamBackend(status=SteamStatusError("unavailable"))
    with _client(server_config, capture_service, backend) as client:
        response = client.get("/api/v1/steam/status")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "steam_status_failed"


def test_steam_router_uses_access_policy(server_config, capture_service) -> None:
    backend = FakeSteamBackend()
    app = create_app(
        server_config,
        capture_service=capture_service,
        steam_service=SteamService(backend),
        manage_runtime=False,
    )
    calls = 0

    async def track_access() -> None:
        nonlocal calls
        calls += 1

    app.dependency_overrides[require_access] = track_access
    with TestClient(app) as client:
        client.get("/api/v1/steam/status")
        client.post("/api/v1/steam/restart")

    assert calls == 2


def test_concurrent_restart_is_rejected_without_double_launch() -> None:
    class BlockingBackend(FakeSteamBackend):
        def __init__(self) -> None:
            super().__init__()
            self.started = threading.Event()
            self.release = threading.Event()

        def restart(self) -> SteamStatus:
            self.restart_calls += 1
            self.started.set()
            assert self.release.wait(timeout=2)
            return RUNNING

    async def exercise() -> None:
        backend = BlockingBackend()
        service = SteamService(backend)
        first = asyncio.create_task(service.restart())
        assert await asyncio.to_thread(backend.started.wait, 1)
        with pytest.raises(SteamRestartInProgressError):
            await service.restart()
        backend.release.set()
        result = await first
        assert result.pid == RUNNING.pid
        assert backend.restart_calls == 1

    asyncio.run(exercise())


def test_management_pages_are_served(server_config, capture_service) -> None:
    with _client(server_config, capture_service, FakeSteamBackend()) as client:
        dashboard = client.get("/")
        screen = client.get("/screen")
        steam = client.get("/steam")

    assert "Dashboard" in dashboard.text
    assert "Screen Capture" in screen.text
    assert "Steam Process Status" in steam.text
    assert dashboard.headers["cache-control"] == "no-store"
    assert screen.headers["cache-control"] == "no-store"
    assert steam.headers["cache-control"] == "no-store"
