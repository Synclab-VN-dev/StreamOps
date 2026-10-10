"""Steam WS adapter to existing SteamService (no new Steam engine)."""
from __future__ import annotations
import asyncio
import json
from fastapi import APIRouter,Depends,WebSocket,WebSocketDisconnect
from ..auth import require_access
from ..services.games.access import GameAccessDenied, require_mutation
from ..services.games.lifecycle import GameServiceError

router=APIRouter()

@router.websocket("/api/v1/steam/ws")
async def steam_ws(websocket: WebSocket, _access: None = Depends(require_access)):
    protocols=[x.strip() for x in websocket.headers.get("sec-websocket-protocol","").split(",")]
    await websocket.accept(subprotocol="streamops-games-v1" if "streamops-games-v1" in protocols else None)
    service=websocket.app.state.steam_service
    hub=websocket.app.state.steam_status_hub
    q=await hub.subscribe()
    lock=asyncio.Lock()
    async def send(msg):
        async with lock: await websocket.send_json(msg)
    async def events():
        while True: await send(await q.get())
    task=asyncio.create_task(events())
    try:
        while True:
            raw=await websocket.receive_text()
            rid=None
            try:
                obj=json.loads(raw)
                if not isinstance(obj,dict) or set(obj)-{"type","request_id","operation","payload"}:
                    raise GameServiceError("invalid_request","Invalid request.")
                rid=obj.get("request_id")
                op=obj.get("operation")
                payload=obj.get("payload",{})
                if obj.get("type")!="request" or not isinstance(rid,str) or not rid or not isinstance(payload,dict) or payload:
                    raise GameServiceError("invalid_request","Invalid request fields.")
                if op=="steam.status":
                    result=(await service.status()).api_payload()
                elif op=="steam.lifecycle.restart":
                    require_mutation(websocket.headers)
                    result=(await service.restart()).api_payload()
                    hub.trigger_refresh()
                    await hub.snapshot()
                else:
                    raise GameServiceError("unknown_operation","Unsupported Steam operation.")
                await send({"type":"response","request_id":rid,"ok":True,"data":result})
            except (GameServiceError,GameAccessDenied) as exc:
                await send({"type":"response","request_id":rid,"ok":False,"error":{"code":exc.code,"message":str(exc)}})
            except Exception:
                await send({"type":"response","request_id":rid,"ok":False,"error":{"code":"steam_operation_failed","message":"Steam operation failed."}})
    except WebSocketDisconnect: pass
    finally:
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        hub.unsubscribe(q)
