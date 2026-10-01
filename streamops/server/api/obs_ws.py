"""WebSocket transport for shared OBS runtime snapshots."""

import asyncio

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from ..auth import require_access


router = APIRouter()


@router.websocket("/api/v1/obs/ws")
async def obs_status_websocket(websocket: WebSocket, _access: None = Depends(require_access)) -> None:
    await websocket.accept()
    hub = websocket.app.state.obs_status_hub
    queue = await hub.subscribe()
    receive_task: asyncio.Task[dict] | None = None
    message_task: asyncio.Task[dict] | None = None
    try:
        while True:
            receive_task = asyncio.create_task(websocket.receive())
            message_task = asyncio.create_task(queue.get())
            done, pending = await asyncio.wait(
                (receive_task, message_task), return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            if receive_task in done:
                event = receive_task.result()
                if event["type"] == "websocket.disconnect":
                    break
                continue
            await websocket.send_json(message_task.result())
    except WebSocketDisconnect:
        pass
    finally:
        for task in (receive_task, message_task):
            if task is not None and not task.done():
                task.cancel()
        hub.unsubscribe(queue)
