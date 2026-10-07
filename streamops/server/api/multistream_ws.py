"""WebSocket entry point for the same multistream core used by HTTP."""
from __future__ import annotations
import asyncio, json
from typing import Any
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from ..auth import require_access
from ..errors import StreamingError
router=APIRouter()

def _parse(raw:str)->tuple[str,str,dict[str,Any]]:
    try: m=json.loads(raw)
    except json.JSONDecodeError: raise StreamingError("invalid_request","Message must be valid JSON.",422)
    if not isinstance(m,dict) or m.get("type")!="request" or not isinstance(m.get("request_id"),str): raise StreamingError("invalid_request","type=request and request_id are required.",422)
    op=m.get("operation"); payload=m.get("payload",{})
    if not isinstance(op,str) or not isinstance(payload,dict): raise StreamingError("invalid_request","operation and object payload are required.",422)
    return m["request_id"],op,payload

def _execute(service:Any,op:str,p:dict[str,Any])->Any:
    did=p.get("destination_id")
    table={"destinations.list":lambda:service.list_destinations(),"destinations.get":lambda:service.get_destination(did),"destinations.create":lambda:service.create_destination(p.get("destination",{})),"destinations.update":lambda:service.update_destination(did,p.get("destination",{})),"destinations.delete":lambda:service.delete_destination(did),"destination.start":lambda:service.start_destination(did),"destination.stop":lambda:service.stop_destination(did),"destination.status":lambda:service.status(did),"destination.stats":lambda:service.stats(did)}
    if op not in table: raise StreamingError("unknown_operation",f"Unsupported operation: {op}",422)
    return table[op]()

@router.websocket("/api/v1/multistream/ws")
async def multistream_ws(websocket:WebSocket,_access:None=Depends(require_access))->None:
    await websocket.accept(); service=websocket.app.state.multistream_service; loop=asyncio.get_running_loop(); queue:asyncio.Queue[dict[str,Any]]=asyncio.Queue(); send_lock=asyncio.Lock()
    async def send(message:dict[str,Any])->None:
        async with send_lock: await websocket.send_json(message)
    def listener(event:dict[str,Any])->None: loop.call_soon_threadsafe(queue.put_nowait,event)
    service.subscribe(listener); await send({"type":"multistream.snapshot","data":await asyncio.to_thread(service.snapshot)})
    async def sender():
        while True: await send(await queue.get())
    task=asyncio.create_task(sender())
    try:
        while True:
            rid=None
            try:
                rid,op,p=_parse(await websocket.receive_text()); data=await asyncio.to_thread(_execute,service,op,p); await send({"type":"response","request_id":rid,"ok":True,"data":data})
            except StreamingError as exc: await send({"type":"response","request_id":rid,"ok":False,"error":{"code":exc.code,"message":str(exc)}})
            except Exception: await send({"type":"response","request_id":rid,"ok":False,"error":{"code":"internal_error","message":"Multistream request failed."}})
    except WebSocketDisconnect: pass
    finally: task.cancel(); await asyncio.gather(task,return_exceptions=True); service.unsubscribe(listener)
