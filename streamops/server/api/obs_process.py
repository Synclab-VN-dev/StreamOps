"""OBS process lifecycle endpoints."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request, Response

from ..auth import require_access
from ..errors import InvalidObsProcessRequestError
from ..obs import ObsManager


router = APIRouter(prefix="/api/v1/obs/process", dependencies=[Depends(require_access)])


def _manager(request: Request) -> ObsManager:
    return request.app.state.obs_manager


@router.get("/status")
async def obs_process_status(request: Request, response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    status = await asyncio.to_thread(_manager(request).status)
    return status.api_payload()


async def _reject_body(request: Request) -> None:
    if await request.body():
        raise InvalidObsProcessRequestError(
            "OBS lifecycle operations do not accept executable paths, arguments, commands, or request bodies."
        )


@router.post("/start")
async def start_obs(request: Request) -> dict[str, object]:
    await _reject_body(request)
    try:
        status = await asyncio.to_thread(_manager(request).start)
        return status.api_payload()
    finally:
        request.app.state.obs_status_hub.trigger_refresh()


@router.post("/stop")
async def stop_obs(request: Request) -> dict[str, object]:
    await _reject_body(request)
    try:
        status = await asyncio.to_thread(_manager(request).stop)
        return status.api_payload()
    finally:
        request.app.state.obs_status_hub.trigger_refresh()


@router.post("/restart")
async def restart_obs(request: Request) -> dict[str, object]:
    await _reject_body(request)
    try:
        status = await asyncio.to_thread(_manager(request).restart)
        return status.api_payload()
    finally:
        request.app.state.obs_status_hub.trigger_refresh()
