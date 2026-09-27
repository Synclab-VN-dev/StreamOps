"""FastAPI application factory for streamops-node."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.health import router as health_router
from .api.screen import router as screen_router
from .api.steam import router as steam_router
from .config import ServerConfig
from .errors import (
    CaptureStorageError,
    InvalidSteamRestartRequestError,
    NoCaptureError,
    ScreenCaptureError,
    SteamLaunchError,
    SteamNotFoundError,
    SteamRestartInProgressError,
    SteamShutdownError,
    SteamShutdownTimeoutError,
    SteamStatusError,
    WrongDesktopSessionError,
)
from .platform.windows import WindowsScreenCaptureBackend, WindowsSteamBackend
from .services import ScreenCaptureService, SteamService
from .services.runtime import RuntimeLease


WEB_ROOT = Path(__file__).with_name("web")


def create_app(
    config: ServerConfig,
    *,
    capture_service: ScreenCaptureService | None = None,
    steam_service: SteamService | None = None,
    manage_runtime: bool = True,
) -> FastAPI:
    service = capture_service or ScreenCaptureService(
        WindowsScreenCaptureBackend(config.output_index),
        config.data_dir,
        config.capture_timeout,
    )
    steam = steam_service or SteamService(WindowsSteamBackend())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        lease = RuntimeLease.acquire(config) if manage_runtime else None
        try:
            service.start()
            yield
        finally:
            service.close()
            if lease is not None:
                lease.release()

    app = FastAPI(title="StreamOps Node", version="0.1.0", lifespan=lifespan)
    app.state.config = config
    app.state.capture_service = service
    app.state.steam_service = steam
    app.include_router(health_router)
    app.include_router(screen_router)
    app.include_router(steam_router)

    @app.exception_handler(NoCaptureError)
    async def no_capture_handler(_request, exc: NoCaptureError) -> JSONResponse:
        return _error_response(404, "no_capture", str(exc))

    @app.exception_handler(ScreenCaptureError)
    async def capture_error_handler(_request, exc: ScreenCaptureError) -> JSONResponse:
        return _error_response(503, "capture_failed", str(exc))

    @app.exception_handler(WrongDesktopSessionError)
    async def wrong_session_handler(_request, exc: WrongDesktopSessionError) -> JSONResponse:
        return _error_response(503, "wrong_desktop_session", str(exc))

    @app.exception_handler(CaptureStorageError)
    async def storage_error_handler(_request, exc: CaptureStorageError) -> JSONResponse:
        return _error_response(500, "capture_storage_failed", str(exc))

    @app.exception_handler(InvalidSteamRestartRequestError)
    async def invalid_restart_handler(
        _request, exc: InvalidSteamRestartRequestError
    ) -> JSONResponse:
        return _error_response(400, "invalid_restart_request", str(exc))

    @app.exception_handler(SteamNotFoundError)
    async def steam_not_found_handler(_request, exc: SteamNotFoundError) -> JSONResponse:
        return _error_response(404, "steam_not_found", str(exc))

    @app.exception_handler(SteamRestartInProgressError)
    async def restart_in_progress_handler(
        _request, exc: SteamRestartInProgressError
    ) -> JSONResponse:
        return _error_response(409, "restart_in_progress", str(exc))

    @app.exception_handler(SteamShutdownTimeoutError)
    async def shutdown_timeout_handler(
        _request, exc: SteamShutdownTimeoutError
    ) -> JSONResponse:
        return _error_response(504, "steam_shutdown_timeout", str(exc))

    @app.exception_handler(SteamShutdownError)
    async def shutdown_error_handler(_request, exc: SteamShutdownError) -> JSONResponse:
        return _error_response(503, "steam_shutdown_failed", str(exc))

    @app.exception_handler(SteamLaunchError)
    async def launch_error_handler(_request, exc: SteamLaunchError) -> JSONResponse:
        return _error_response(503, "steam_launch_failed", str(exc))

    @app.exception_handler(SteamStatusError)
    async def status_error_handler(_request, exc: SteamStatusError) -> JSONResponse:
        return _error_response(503, "steam_status_failed", str(exc))

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(WEB_ROOT / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/screen", include_in_schema=False)
    async def screen_page() -> FileResponse:
        return FileResponse(WEB_ROOT / "screen.html", headers={"Cache-Control": "no-store"})

    @app.get("/steam", include_in_schema=False)
    async def steam_page() -> FileResponse:
        return FileResponse(WEB_ROOT / "steam.html", headers={"Cache-Control": "no-store"})

    app.mount("/assets", StaticFiles(directory=WEB_ROOT), name="web-assets")
    return app


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
        headers={"Cache-Control": "no-store"},
    )
