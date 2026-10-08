"""WebSocket entry point for OBS Plugin Manager operations."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from ..auth import require_access
from ..services.obs_ws_operations import WsOperationError, public_ws_error


router = APIRouter()
logger = logging.getLogger(__name__)

_OPERATIONS = {
    "obs_plugin.status": "status",
    "obs_plugin.install": "install",
    "obs_plugin.update": "update",
    "obs_plugin.verify": "verify",
    "obs_plugin.rollback": "rollback",
}


def _parse_request(raw: str) -> tuple[str, str, str]:
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
    if operation not in _OPERATIONS:
        raise WsOperationError("unknown_operation", f"Unsupported operation: {operation}")
    payload = message.get("payload", {})
    if not isinstance(payload, dict):
        raise WsOperationError("invalid_request", "payload must be an object.")
    if set(payload) != {"plugin_id"}:
        raise WsOperationError("invalid_request", "payload must contain only plugin_id.")
    plugin_id = payload.get("plugin_id")
    if not isinstance(plugin_id, str) or not plugin_id:
        raise WsOperationError("invalid_request", "plugin_id must be a non-empty string.")
    return request_id, operation, plugin_id


@router.websocket("/api/v1/obs/plugins/ws")
async def obs_plugin_websocket(websocket: WebSocket, _access: None = Depends(require_access)) -> None:
    await websocket.accept()
    service = websocket.app.state.obs_plugin_service
    try:
        while True:
            raw = await websocket.receive_text()
            request_id: str | None = None
            try:
                try:
                    candidate: Any = json.loads(raw)
                    if isinstance(candidate, dict) and isinstance(candidate.get("request_id"), str):
                        request_id = candidate["request_id"]
                except json.JSONDecodeError:
                    pass
                request_id, operation, plugin_id = _parse_request(raw)
                result = await getattr(service, _OPERATIONS[operation])(plugin_id)
                response = {
                    "type": "response",
                    "request_id": request_id,
                    "ok": True,
                    "data": result.api_payload(),
                }
            except Exception as exc:
                code, message = public_ws_error(exc)
                if code == "internal_error":
                    # Never log exception details/tracebacks: providers and OBS drivers
                    # can embed secrets, paths and stream keys in raw exceptions.
                    logger.error("Unhandled OBS Plugin Manager WebSocket operation error")
                response = {
                    "type": "response",
                    "request_id": request_id,
                    "ok": False,
                    "error": {"code": code, "message": message},
                }
            await websocket.send_json(response)
    except WebSocketDisconnect:
        pass
