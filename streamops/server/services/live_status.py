"""Realtime livestream status fan-out for the future Stream Manage page."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime
import json
from typing import Any


class LiveStatusHub:
    def __init__(self, service: Any, *, reconcile_interval: float = 1.0, heartbeat_interval: float = 15.0) -> None:
        self.service = service
        self.reconcile_interval = reconcile_interval
        self.heartbeat_interval = heartbeat_interval
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._refresh = asyncio.Event()
        self._refresh_lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._latest: dict[str, Any] | None = None
        self._signature: str | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._monitor_task is not None:
            return
        self._loop = asyncio.get_running_loop()
        self._monitor_task = asyncio.create_task(self._monitor(), name="live-status-monitor")
        self._heartbeat_task = asyncio.create_task(self._heartbeat(), name="live-status-heartbeat")

    async def close(self) -> None:
        tasks = [task for task in (self._monitor_task, self._heartbeat_task) if task is not None]
        self._monitor_task = None
        self._heartbeat_task = None
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._subscribers.clear()
        self._loop = None

    def trigger_refresh(self) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._refresh.set)

    async def subscribe(self, *, fresh: bool = False) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
        if fresh or self._latest is None:
            await self.refresh()
        async with self._refresh_lock:
            self._subscribers.add(queue)
            if self._latest is not None:
                self._put_latest(queue, _event("stream.snapshot", self._latest))
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    async def refresh(self) -> dict[str, Any]:
        async with self._refresh_lock:
            snapshot = await asyncio.to_thread(self.service.snapshot)
            snapshot = {"generated_at": _now(), **snapshot}
            signature = _signature(snapshot)
            self._latest = snapshot
            if signature != self._signature:
                self._signature = signature
                self._broadcast(_event("stream.snapshot", snapshot))
            return snapshot

    async def _monitor(self) -> None:
        while True:
            # Stream status is only needed by the dedicated Stream Manage page.
            # Do not create background OBS websocket traffic while nobody is
            # subscribed; REST status remains available on demand.
            if self._subscribers:
                try:
                    await self.refresh()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    pass
            try:
                await asyncio.wait_for(self._refresh.wait(), timeout=self.reconcile_interval)
                self._refresh.clear()
            except TimeoutError:
                pass

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            self._broadcast(_event("stream.heartbeat", {"generated_at": _now()}))

    def _broadcast(self, message: dict[str, Any]) -> None:
        for queue in tuple(self._subscribers):
            self._put_latest(queue, message)

    @staticmethod
    def _put_latest(queue: asyncio.Queue[dict[str, Any]], message: dict[str, Any]) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(deepcopy(message))


def _signature(snapshot: dict[str, Any]) -> str:
    comparable = deepcopy(snapshot)
    comparable.pop("generated_at", None)
    return json.dumps(comparable, sort_keys=True, separators=(",", ":"))


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"type": "event", "event": name, "data": deepcopy(data)}


def _now() -> str:
    return datetime.now(UTC).isoformat()
