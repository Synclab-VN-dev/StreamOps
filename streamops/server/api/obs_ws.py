"""Single WebSocket transport for the OBS dashboard."""

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from ..auth import require_access
from ..services.obs_ws_operations import ObsWsOperations, WsOperationError, public_ws_error


router = APIRouter()
logger = logging.getLogger(__name__)


def _parse_request(raw: str) -> tuple[str | None, str, dict[str, Any]]:
    try:
        message = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WsOperationError("invalid_request", "Message must be valid JSON.") from exc
    if not isinstance(message, dict):
        raise WsOperationError("invalid_request", "Message must be a JSON object.")
    extras = sorted(set(message) - {"type", "request_id", "operation", "payload"})
    if extras:
        raise WsOperationError("invalid_request", f"Unexpected request field(s): {', '.join(extras)}")
    request_id = message.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        raise WsOperationError("invalid_request", "request_id must be a non-empty string.")
    if message.get("type") != "request":
        raise WsOperationError("invalid_request", "type must be 'request'.")
    operation = message.get("operation")
    if not isinstance(operation, str) or not operation:
        raise WsOperationError("invalid_request", "operation must be a non-empty string.")
    payload = message.get("payload", {})
    if not isinstance(payload, dict):
        raise WsOperationError("invalid_request", "payload must be an object.")
    return request_id, operation, payload


async def _send_events(websocket: WebSocket, queue: asyncio.Queue[dict], lock: asyncio.Lock) -> None:
    while True:
        event = await queue.get()
        async with lock:
            await websocket.send_json(event)


@router.websocket("/api/v1/obs/ws")
async def obs_status_websocket(websocket: WebSocket, _access: None = Depends(require_access)) -> None:
    await websocket.accept()
    hub = websocket.app.state.obs_status_hub
    # A new dashboard must resolve its initial profile against the scene that is
    # current at connection time, not a monitor snapshot from before navigation.
    queue = await hub.subscribe(fresh=True)
    operations = ObsWsOperations(
        websocket.app.state.obs_manager,
        websocket.app.state.obs_scene_service,
        hub,
    )
    send_lock = asyncio.Lock()
    event_task = asyncio.create_task(_send_events(websocket, queue, send_lock))
    try:
        while True:
            raw = await websocket.receive_text()
            request_id: str | None = None
            try:
                try:
                    candidate = json.loads(raw)
                    if isinstance(candidate, dict) and isinstance(candidate.get("request_id"), str):
                        request_id = candidate["request_id"]
                except json.JSONDecodeError:
                    pass
                request_id, operation, payload = _parse_request(raw)
                data = await operations.execute(operation, payload)
                response = {"type": "response", "request_id": request_id, "ok": True, "data": data}
            except Exception as exc:
                code, message = public_ws_error(exc)
                if code == "internal_error":
                    logger.exception("Unhandled OBS WebSocket operation error")
                response = {
                    "type": "response",
                    "request_id": request_id,
                    "ok": False,
                    "error": {"code": code, "message": message},
                }
            async with send_lock:
                await websocket.send_json(response)
    except WebSocketDisconnect:
        pass
    finally:
        event_task.cancel()
        await asyncio.gather(event_task, return_exceptions=True)
        hub.unsubscribe(queue)
