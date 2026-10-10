"""Authenticated game command channel and revisioned observer events."""
from __future__ import annotations
import asyncio
import json
import logging
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from ..auth import require_access
from ..services.games.access import require_mutation, GameAccessDenied
from ..services.games.lifecycle import GameServiceError

router = APIRouter()
logger = logging.getLogger(__name__)

def _request(raw: str):
    try: msg = json.loads(raw)
    except (TypeError, ValueError) as exc: raise GameServiceError("invalid_request","Invalid JSON.") from exc
    if not isinstance(msg, dict) or set(msg) - {"type","request_id","operation","payload"}:
        raise GameServiceError("invalid_request","Unexpected request fields.")
    rid, op, payload = msg.get("request_id"), msg.get("operation"), msg.get("payload",{})
    if msg.get("type") != "request" or not isinstance(rid,str) or not rid or not isinstance(op,str) or not op or not isinstance(payload,dict):
        raise GameServiceError("invalid_request","Malformed request envelope.")
    return rid,op,payload

def _fields(payload, required=(), optional=()):
    if any(k not in payload for k in required) or set(payload) - set(required) - set(optional):
        raise GameServiceError("invalid_request","Payload fields do not match contract.")
    for key in required:
        if not isinstance(payload[key],str) or not payload[key]:
            raise GameServiceError("invalid_request",f"{key} must be a nonempty string.")

async def _execute(service, op, data, headers):
    if op == "games.list":
        _fields(data, optional=("provider",))
        return await service.list(data.get("provider"))
    if op == "games.get":
        _fields(data,("game_id",))
        return await service.get(data["game_id"])
    if op in ("games.lifecycle.start","games.lifecycle.stop","games.lifecycle.restart"):
        _fields(data,("game_id","idempotency_key"))
        require_mutation(headers)
        return await service.action(data["game_id"], op.rsplit(".",1)[-1],data["idempotency_key"])
    if op == "games.operations.get":
        _fields(data,("operation_id",))
        return service.operation(data["operation_id"])
    if op == "games.reconcile":
        _fields(data,("game_id",))
        return await service.reconcile(data["game_id"])
    if op == "games.catalog.refresh":
        _fields(data)
        return await service.refresh_catalog()
    if op == "games.lifecycle.force_stop":
        raise GameServiceError("capability_disabled","Force stop is disabled in V1.")
    raise GameServiceError("unknown_operation","Unknown games operation.")

@router.websocket("/api/v1/games/ws")
async def games_ws(websocket: WebSocket, _access: None = Depends(require_access)):
    # Authenticated mutation requires token in Sec-WebSocket-Protocol, not URL.
    supported = "streamops-games-v1"
    protocols = [x.strip() for x in websocket.headers.get("sec-websocket-protocol","").split(",")]
    await websocket.accept(subprotocol=supported if supported in protocols else None)
    hub = websocket.app.state.game_status_hub
    service = websocket.app.state.game_service
    q = await hub.subscribe()
    send_lock = asyncio.Lock()
    async def send(message):
        async with send_lock: await websocket.send_json(message)
    async def sender():
        while True: await send(await q.get())
    task = asyncio.create_task(sender())
    try:
        while True:
            raw = await websocket.receive_text()
            rid = None
            try:
                candidate = json.loads(raw)
                if isinstance(candidate,dict) and isinstance(candidate.get("request_id"),str):
                    rid = candidate["request_id"]
            except ValueError: pass
            try:
                rid,op,data = _request(raw)
                result = await _execute(service,op,data,websocket.headers)
                response = {"type":"response","request_id":rid,"ok":True,"data":result}
            except (GameServiceError,GameAccessDenied) as exc:
                response = {"type":"response","request_id":rid,"ok":False,
                    "error":{"code":exc.code,"message":str(exc)}}
            except Exception:
                logger.exception("Unhandled Game WebSocket error")
                response = {"type":"response","request_id":rid,"ok":False,
                    "error":{"code":"internal_error","message":"Game operation failed."}}
            await send(response)
    except WebSocketDisconnect: pass
    finally:
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        hub.unsubscribe(q)
