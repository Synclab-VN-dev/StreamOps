"""Allowlisted OBS plugin lifecycle endpoints."""

from fastapi import APIRouter, Depends, Request, Response

from ..auth import require_access
from ..errors import ObsPluginError
from ..services.obs_plugin import ObsPluginService


router = APIRouter(prefix="/api/v1/obs/plugins", dependencies=[Depends(require_access)])


def _service(request: Request) -> ObsPluginService:
    return request.app.state.obs_plugin_service


async def _reject_input(request: Request) -> None:
    if request.query_params or await request.body():
        raise ObsPluginError(
            "invalid_plugin_request",
            "OBS plugin operations do not accept URLs, paths, commands, binaries, query parameters, or request bodies.",
            400,
        )


def _refresh(request: Request) -> None:
    request.app.state.obs_status_hub.trigger_refresh()
    request.app.state.live_status_hub.trigger_refresh()


@router.get("")
async def plugin_inventory(request: Request, response: Response) -> dict[str, object]:
    await _reject_input(request)
    response.headers["Cache-Control"] = "no-store"
    return {"plugins": [item.api_payload() for item in await _service(request).inventory()]}


@router.get("/{plugin_id}")
async def plugin_status(plugin_id: str, request: Request, response: Response) -> dict[str, object]:
    await _reject_input(request)
    response.headers["Cache-Control"] = "no-store"
    return (await _service(request).status(plugin_id)).api_payload()


@router.post("/{plugin_id}/install")
async def install_plugin(plugin_id: str, request: Request, response: Response) -> dict[str, object]:
    await _reject_input(request)
    response.headers["Cache-Control"] = "no-store"
    try:
        return (await _service(request).install(plugin_id)).api_payload()
    finally:
        _refresh(request)


@router.post("/{plugin_id}/update")
async def update_plugin(plugin_id: str, request: Request, response: Response) -> dict[str, object]:
    await _reject_input(request)
    response.headers["Cache-Control"] = "no-store"
    try:
        return (await _service(request).update(plugin_id)).api_payload()
    finally:
        _refresh(request)


@router.post("/{plugin_id}/verify")
async def verify_plugin(plugin_id: str, request: Request, response: Response) -> dict[str, object]:
    await _reject_input(request)
    response.headers["Cache-Control"] = "no-store"
    try:
        return (await _service(request).verify(plugin_id)).api_payload()
    finally:
        _refresh(request)


@router.post("/{plugin_id}/rollback")
async def rollback_plugin(plugin_id: str, request: Request, response: Response) -> dict[str, object]:
    await _reject_input(request)
    response.headers["Cache-Control"] = "no-store"
    try:
        return (await _service(request).rollback(plugin_id)).api_payload()
    finally:
        _refresh(request)
