"""REST contract for stream destination setup and livestream lifecycle."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Request

from ..auth import require_access
from ..services.live import LiveService


router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_access)])


def _service(request: Request) -> LiveService:
    return request.app.state.live_service


def _refresh(request: Request, result: Any) -> Any:
    request.app.state.live_status_hub.trigger_refresh()
    return result


def _live_args(payload: dict[str, Any]) -> tuple[str, str]:
    if set(payload) - {"profile_id", "destination_id"}:
        from ..errors import StreamingError
        raise StreamingError("invalid_request", "Only profile_id and destination_id are accepted.", 422)
    profile_id = payload.get("profile_id")
    destination_id = payload.get("destination_id")
    if not isinstance(profile_id, str) or not profile_id.strip() or not isinstance(destination_id, str) or not destination_id.strip():
        from ..errors import StreamingError
        raise StreamingError("invalid_request", "profile_id and destination_id are required.", 422)
    return profile_id, destination_id


@router.get("/stream-destinations")
def list_destinations(request: Request) -> dict[str, Any]:
    return _service(request).list_destinations()


@router.post("/stream-destinations", status_code=201)
def create_destination(request: Request, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return _refresh(request, _service(request).create_destination(payload))


@router.get("/stream-destinations/{destination_id}")
def get_destination(destination_id: str, request: Request) -> dict[str, Any]:
    return _service(request).get_destination(destination_id)


@router.put("/stream-destinations/{destination_id}")
def update_destination(destination_id: str, request: Request, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return _refresh(request, _service(request).update_destination(destination_id, payload))


@router.delete("/stream-destinations/{destination_id}")
def delete_destination(destination_id: str, request: Request) -> dict[str, bool]:
    _service(request).delete_destination(destination_id)
    return _refresh(request, {"deleted": True})


@router.put("/stream-destinations/{destination_id}/credential")
def set_credential(destination_id: str, request: Request, payload: dict[str, Any] = Body(...)) -> dict[str, bool]:
    if set(payload) != {"credential"} or not isinstance(payload.get("credential"), str):
        from ..errors import StreamingError
        raise StreamingError("invalid_request", "Body must contain only string field credential.", 422)
    return _refresh(request, _service(request).set_credential(destination_id, payload["credential"]))


@router.delete("/stream-destinations/{destination_id}/credential")
def delete_credential(destination_id: str, request: Request) -> dict[str, bool]:
    return _refresh(request, _service(request).delete_credential(destination_id))


@router.post("/live/preflight")
def preflight(request: Request, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    profile_id, destination_id = _live_args(payload)
    return _service(request).preflight(profile_id, destination_id)


@router.post("/live/start")
def start_live(request: Request, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    profile_id, destination_id = _live_args(payload)
    try:
        return _service(request).start(profile_id, destination_id)
    finally:
        request.app.state.live_status_hub.trigger_refresh()


@router.get("/live/status")
def live_status(request: Request) -> dict[str, Any]:
    return _service(request).status()


@router.post("/live/stop")
def stop_live(request: Request) -> dict[str, Any]:
    try:
        return _service(request).stop()
    finally:
        request.app.state.live_status_hub.trigger_refresh()
