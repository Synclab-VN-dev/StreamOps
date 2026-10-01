"""Shared OBS runtime status monitor for browser WebSocket clients."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime
import json
from typing import Any

from ..obs import ObsManager
from .obs_scene import ObsSceneService


class ObsStatusHub:
    """Maintain one OBS monitor and fan changed snapshots out to subscribers."""

    def __init__(
        self,
        manager: ObsManager,
        scene_service: ObsSceneService,
        capture_service: Any,
        *,
        reconcile_interval: float = 1.0,
        heartbeat_interval: float = 15.0,
    ) -> None:
        self.manager = manager
        self.scene_service = scene_service
        self.capture_service = capture_service
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
        self._monitor_task = asyncio.create_task(self._monitor(), name="obs-status-monitor")
        self._heartbeat_task = asyncio.create_task(self._heartbeat(), name="obs-status-heartbeat")

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
                self._put_latest(queue, _event("obs.snapshot", self._latest))
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    async def refresh(self) -> dict[str, Any]:
        async with self._refresh_lock:
            runtime = await asyncio.to_thread(self.manager.status)
            runtime_payload = runtime.api_payload()
            current_scene = None
            if runtime.state == "READY":
                try:
                    current_scene = await asyncio.to_thread(self.scene_service.current_scene)
                except Exception:
                    current_scene = None
            snapshot = {
                "generated_at": _now(),
                "node": {
                    "status": "ok",
                    "capture_ready": bool(self.capture_service.ready),
                    "capture_backend": self.capture_service.backend_name,
                },
                "runtime": runtime_payload,
                "obs": {"current_scene": current_scene},
            }
            signature = _snapshot_signature(snapshot)
            self._latest = snapshot
            if signature != self._signature:
                self._signature = signature
                self._broadcast(_event("obs.snapshot", snapshot))
            return snapshot

    async def _monitor(self) -> None:
        while True:
            try:
                await self.refresh()
            except asyncio.CancelledError:
                raise
            except Exception:
                # A transient status failure must not terminate the shared monitor.
                pass
            try:
                await asyncio.wait_for(self._refresh.wait(), timeout=self.reconcile_interval)
                self._refresh.clear()
            except TimeoutError:
                pass

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            self._broadcast(_event("obs.heartbeat", {"generated_at": _now()}))

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


def _snapshot_signature(snapshot: dict[str, Any]) -> str:
    comparable = deepcopy(snapshot)
    comparable.pop("generated_at", None)
    comparable.get("runtime", {}).get("process", {}).pop("uptime_seconds", None)
    return json.dumps(comparable, sort_keys=True, separators=(",", ":"))


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"type": "event", "event": name, "data": deepcopy(data)}
