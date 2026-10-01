"""FastAPI application factory for streamops-node."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.health import router as health_router
from .api.obs import router as obs_router
from .api.obs_process import router as obs_process_router
from .api.screen import router as screen_router
from .api.steam import router as steam_router
from .config import ServerConfig
from .errors import (
    CaptureStorageError,
    InvalidObsProcessRequestError,
    InvalidSteamRestartRequestError,
    NoCaptureError,
    ObsExecutableNotAllowedError,
    ObsOperationInProgressError,
    ObsReadinessTimeoutError,
    ObsShutdownError,
    ObsShutdownTimeoutError,
    ObsStartError,
    ObsStartTimeoutError,
    ObsStatusError,
    ObsUnsafeOperationError,
    ObsWebSocketConnectionError,
    ObsWebSocketRequestError,
    SceneOperationError,
    SceneProfileConflictError,
    SceneProfileNotFoundError,
    SceneProfileStorageError,
    SceneProfileValidationError,
    SceneReviewArtifactNotFoundError,
    SceneReviewNotFoundError,
    ScreenCaptureError,
    SteamLaunchError,
    SteamNotFoundError,
    SteamRestartInProgressError,
    SteamShutdownError,
    SteamShutdownTimeoutError,
    SteamStatusError,
    WrongDesktopSessionError,
)
from .scene_config import SceneConfigError
from .obs import ObsManager
from .platform.windows import WindowsScreenCaptureBackend, WindowsSteamBackend
from .services import ObsSceneService, ScreenCaptureService, SteamService
from .services.runtime import RuntimeLease


WEB_ROOT = Path(__file__).with_name("web")


def create_app(
    config: ServerConfig,
    *,
    capture_service: ScreenCaptureService | None = None,
    steam_service: SteamService | None = None,
    obs_manager: ObsManager | None = None,
    obs_scene_service: ObsSceneService | None = None,
    manage_runtime: bool = True,
) -> FastAPI:
    service = capture_service or ScreenCaptureService(
        WindowsScreenCaptureBackend(config.output_index),
        config.data_dir,
        config.capture_timeout,
    )
    steam = steam_service or SteamService(WindowsSteamBackend())
    obs = obs_manager or ObsManager()
    obs_scenes = obs_scene_service or ObsSceneService(data_dir=config.data_dir / "scene-profiles")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        lease = RuntimeLease.acquire(config) if manage_runtime else None
        try:
            service.start()
            yield
        finally:
            service.close()
            obs_scenes.close()
            if lease is not None:
                lease.release()

    app = FastAPI(title="StreamOps Node", version="0.1.0", lifespan=lifespan)
    app.state.config = config
    app.state.capture_service = service
    app.state.steam_service = steam
    app.state.obs_manager = obs
    app.state.obs_scene_service = obs_scenes
    app.include_router(health_router)
    app.include_router(obs_router)
    app.include_router(obs_process_router)
    app.include_router(screen_router)
    app.include_router(steam_router)

    @app.exception_handler(InvalidObsProcessRequestError)
    async def invalid_obs_request_handler(_request, exc: InvalidObsProcessRequestError) -> JSONResponse:
        return _error_response(400, "invalid_obs_process_request", str(exc))

    @app.exception_handler(ObsOperationInProgressError)
    async def obs_operation_in_progress_handler(_request, exc: ObsOperationInProgressError) -> JSONResponse:
        return _error_response(409, "obs_operation_in_progress", str(exc))

    @app.exception_handler(ObsUnsafeOperationError)
    async def obs_unsafe_operation_handler(_request, exc: ObsUnsafeOperationError) -> JSONResponse:
        return _error_response(409, "obs_unsafe_operation", str(exc))

    @app.exception_handler(ObsExecutableNotAllowedError)
    async def obs_executable_handler(_request, exc: ObsExecutableNotAllowedError) -> JSONResponse:
        return _error_response(503, "obs_executable_unavailable", str(exc))

    @app.exception_handler(ObsStartTimeoutError)
    async def obs_start_timeout_handler(_request, exc: ObsStartTimeoutError) -> JSONResponse:
        return _error_response(504, "obs_start_timeout", str(exc))

    @app.exception_handler(ObsReadinessTimeoutError)
    async def obs_readiness_timeout_handler(_request, exc: ObsReadinessTimeoutError) -> JSONResponse:
        return _error_response(504, "obs_readiness_timeout", str(exc))

    @app.exception_handler(ObsShutdownTimeoutError)
    async def obs_shutdown_timeout_handler(_request, exc: ObsShutdownTimeoutError) -> JSONResponse:
        return _error_response(504, "obs_shutdown_timeout", str(exc))

    @app.exception_handler(ObsShutdownError)
    async def obs_shutdown_handler(_request, exc: ObsShutdownError) -> JSONResponse:
        return _error_response(503, "obs_shutdown_failed", str(exc))

    @app.exception_handler(ObsStartError)
    async def obs_start_handler(_request, exc: ObsStartError) -> JSONResponse:
        return _error_response(503, "obs_start_failed", str(exc))

    @app.exception_handler(ObsStatusError)
    async def obs_status_handler(_request, exc: ObsStatusError) -> JSONResponse:
        return _error_response(503, "obs_status_failed", str(exc))

    @app.exception_handler(SceneConfigError)
    async def scene_config_handler(_request, exc: SceneConfigError) -> JSONResponse:
        return _error_response(400, "scene_config_invalid", str(exc))

    @app.exception_handler(SceneReviewNotFoundError)
    async def scene_review_not_found_handler(_request, exc: SceneReviewNotFoundError) -> JSONResponse:
        return _error_response(404, "scene_review_not_found", str(exc))

    @app.exception_handler(SceneReviewArtifactNotFoundError)
    async def scene_review_artifact_not_found_handler(
        _request, exc: SceneReviewArtifactNotFoundError
    ) -> JSONResponse:
        return _error_response(404, "scene_review_artifact_not_found", str(exc))

    @app.exception_handler(SceneProfileNotFoundError)
    async def scene_profile_not_found_handler(_request, exc: SceneProfileNotFoundError) -> JSONResponse:
        return _error_response(404, "scene_profile_not_found", str(exc))

    @app.exception_handler(SceneProfileValidationError)
    async def scene_profile_validation_handler(_request, exc: SceneProfileValidationError) -> JSONResponse:
        return _error_response(422, "scene_profile_invalid", str(exc))

    @app.exception_handler(SceneProfileConflictError)
    async def scene_profile_conflict_handler(_request, exc: SceneProfileConflictError) -> JSONResponse:
        return _error_response(409, "scene_profile_conflict", str(exc))

    @app.exception_handler(SceneProfileStorageError)
    async def scene_profile_storage_handler(_request, exc: SceneProfileStorageError) -> JSONResponse:
        return _error_response(500, "scene_profile_storage_failed", str(exc))

    @app.exception_handler(ObsWebSocketConnectionError)
    async def obs_connection_handler(_request, exc: ObsWebSocketConnectionError) -> JSONResponse:
        return _error_response(503, "obs_unavailable", str(exc))

    @app.exception_handler(ObsWebSocketRequestError)
    async def obs_request_handler(_request, exc: ObsWebSocketRequestError) -> JSONResponse:
        return _error_response(503, "obs_request_failed", str(exc))

    @app.exception_handler(SceneOperationError)
    async def scene_operation_handler(_request, exc: SceneOperationError) -> JSONResponse:
        return _error_response(409, "scene_operation_failed", str(exc))

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

    @app.get("/obs", include_in_schema=False)
    async def obs_page() -> FileResponse:
        return FileResponse(WEB_ROOT / "obs.html", headers={"Cache-Control": "no-store"})

    app.mount("/assets", StaticFiles(directory=WEB_ROOT), name="web-assets")
    return app


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
        headers={"Cache-Control": "no-store"},
    )
