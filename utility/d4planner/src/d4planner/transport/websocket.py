"""Real loopback WebSocket adapter for the Release 1 protocol core."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
from typing import Any

from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from .core import (
    D4PlannerDomain,
    D4PlannerProtocolSession,
    HudHub,
    INTERNAL_CLOSE_SLOW_CONSUMER,
    ProtocolViolation,
    TargetActivationError,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WebSocketServerConfig:
    credential: str
    runtime_instance_id: str
    backend_generation: int
    origin: str
    host: str = "127.0.0.1"
    port: int = 0
    max_message_bytes: int = 262_144
    max_pending_messages: int = 32
    max_connections: int = 32
    handshake_timeout_seconds: float = 3.0
    send_timeout_seconds: float = 3.0

    def __post_init__(self) -> None:
        if self.host not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("D4Planner WebSocket must bind loopback only")
        if len(self.credential) < 32:
            raise ValueError("credential must have at least 32 characters")
        if self.max_connections < 1:
            raise ValueError("max_connections must be positive")
        if self.handshake_timeout_seconds <= 0 or self.send_timeout_seconds <= 0:
            raise ValueError("transport timeouts must be positive")


class D4PlannerWebSocketServer:
    def __init__(self, config: WebSocketServerConfig, domain: D4PlannerDomain, hub: HudHub) -> None:
        self.config = config
        self.domain = domain
        self.hub = hub
        self._server: Server | None = None
        self._connection_slots = asyncio.Semaphore(config.max_connections)

    @property
    def port(self) -> int:
        if self._server is None or not self._server.sockets:
            raise RuntimeError("server is not started")
        return int(self._server.sockets[0].getsockname()[1])

    async def start(self) -> None:
        if self._server is not None:
            return
        self._server = await serve(
            self._handle,
            self.config.host,
            self.config.port,
            origins=[self.config.origin],
            max_size=self.config.max_message_bytes,
            max_queue=self.config.max_pending_messages,
            ping_interval=None,
        )

    async def close(self) -> None:
        if self._server is None:
            return
        server, self._server = self._server, None
        server.close()
        await server.wait_closed()

    async def _handle(self, websocket: ServerConnection) -> None:
        acquired = False
        try:
            await asyncio.wait_for(self._connection_slots.acquire(), timeout=0.05)
            acquired = True
        except TimeoutError:
            await websocket.close(code=1013, reason="CONNECTION_LIMIT")
            return
        session = D4PlannerProtocolSession(
            self.domain,
            self.hub,
            credential=self.config.credential,
            runtime_instance_id=self.config.runtime_instance_id,
            backend_generation=self.config.backend_generation,
            origin=self.config.origin,
            max_pending_messages=self.config.max_pending_messages,
        )
        send_lock = asyncio.Lock()
        event_task: asyncio.Task[None] | None = None
        try:
            try:
                first = await asyncio.wait_for(
                    websocket.recv(), timeout=self.config.handshake_timeout_seconds,
                )
            except TimeoutError:
                await websocket.close(code=1008, reason="AUTH_TIMEOUT")
                return
            hello: Any = None
            try:
                hello = _decode(first)
                accepted = await session.authenticate(hello)
            except ProtocolViolation as exc:
                await self._send(websocket, send_lock, session.error(exc, _message_id(hello)))
                await websocket.close(code=1008, reason=exc.code)
                return
            await self._send(websocket, send_lock, accepted)
            event_task = asyncio.create_task(
                self._pump_events(websocket, session, send_lock),
                name="d4planner-ws-events",
            )
            async for raw in websocket:
                candidate: Any = None
                correlation_id: str | None = None
                try:
                    candidate = _decode(raw)
                    correlation_id = _message_id(candidate)
                    response = await session.handle(candidate)
                except (ProtocolViolation, TargetActivationError) as exc:
                    response = session.error(exc, correlation_id)
                except Exception as exc:
                    # Exception text and traceback may contain private Target
                    # paths or data supplied by a domain adapter.
                    logger.error(
                        "D4Planner WebSocket internal error exception_type=%s",
                        type(exc).__name__,
                    )
                    response = session.error(
                        ProtocolViolation("INTERNAL", "Internal transport error."), correlation_id,
                    )
                await self._send(websocket, send_lock, response)
        except ConnectionClosed:
            pass
        finally:
            if event_task is not None:
                event_task.cancel()
                await asyncio.gather(event_task, return_exceptions=True)
            await session.close()
            if acquired:
                self._connection_slots.release()

    async def _pump_events(
        self,
        websocket: ServerConnection,
        session: D4PlannerProtocolSession,
        send_lock: asyncio.Lock,
    ) -> None:
        while True:
            queue = session.subscription_queue
            if queue is None:
                await asyncio.sleep(0.005)
                continue
            message = await queue.get()
            if message is None or queue is not session.subscription_queue:
                continue
            if message.get(INTERNAL_CLOSE_SLOW_CONSUMER) is True:
                await websocket.close(code=1013, reason="SLOW_CONSUMER")
                return
            try:
                await self._send(websocket, send_lock, message)
            except TimeoutError:
                await websocket.close(code=1013, reason="SLOW_CONSUMER")
                return

    async def _send(
        self,
        websocket: ServerConnection,
        send_lock: asyncio.Lock,
        message: dict[str, Any],
    ) -> None:
        async with send_lock:
            await asyncio.wait_for(
                websocket.send(json.dumps(message)),
                timeout=self.config.send_timeout_seconds,
            )


def _decode(raw: str | bytes) -> Any:
    if isinstance(raw, bytes):
        raise ProtocolViolation("INVALID_MESSAGE", "Binary frames are not supported.")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProtocolViolation("INVALID_MESSAGE", "Message must be valid JSON.") from exc


def _message_id(message: Any) -> str | None:
    if isinstance(message, dict) and isinstance(message.get("messageId"), str):
        return message["messageId"]
    return None
