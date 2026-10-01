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
        receive_task = asyncio.create_task(websocket.receive())
        while True:
            message_task = asyncio.create_task(queue.get())
            done, _pending = await asyncio.wait(
                (receive_task, message_task), return_when=asyncio.FIRST_COMPLETED
            )
            if receive_task in done:
                if not message_task.done():
                    message_task.cancel()
                    await asyncio.gather(message_task, return_exceptions=True)
                event = receive_task.result()
                if event["type"] == "websocket.disconnect":
                    break
                receive_task = asyncio.create_task(websocket.receive())
                continue
            await websocket.send_json(message_task.result())
    except WebSocketDisconnect:
        pass
    finally:
        for task in (receive_task, message_task):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (receive_task, message_task) if task is not None),
            return_exceptions=True,
        )
        hub.unsubscribe(queue)
