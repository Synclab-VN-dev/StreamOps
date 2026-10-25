"""Async typed client for the private long-lived Rule Kit worker."""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from .protocol import APPROVED_METHODS, PROTOCOL_VERSION, ProtocolError


@dataclass(frozen=True)
class RuleKitSessionRef:
    worker_instance_id: str
    worker_generation: int
    session_id: str
    lease_expires_at: str


class RuleKitRemoteError(RuntimeError):
    def __init__(self, code: str, message: str, details: object = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


class RuleKitClient:
    """Multiplexed correlation client; lifecycle remains owned by the wrapper."""

    def __init__(
        self,
        *,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        worker_instance_id: str,
        worker_generation: int,
        operation_timeout: float = 5.0,
        max_pending: int = 32,
    ) -> None:
        if operation_timeout <= 0 or max_pending <= 0:
            raise ValueError("operation_timeout and max_pending must be positive")
        self._reader = reader
        self._writer = writer
        self.worker_instance_id = worker_instance_id
        self.worker_generation = worker_generation
        self._operation_timeout = operation_timeout
        self._max_pending = max_pending
        self._pending: dict[str, asyncio.Future[Any]] = {}
        self._sessions: set[str] = set()
        self._write_lock = asyncio.Lock()
        self._writer_close_lock = asyncio.Lock()
        self._writer_cleanup_complete = False
        self._closed = False
        self._reader_task = asyncio.create_task(self._read_loop())

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    async def call(self, method: str, params: dict | None = None, *, timeout: float | None = None) -> Any:
        if method not in APPROVED_METHODS:
            raise ValueError(f"unsupported Rule Kit method: {method}")
        if self._closed:
            raise ProtocolError("Rule Kit client is closed")
        if len(self._pending) >= self._max_pending:
            raise RuleKitRemoteError("QUEUE_FULL", "Rule Kit request queue is full")
        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._pending[request_id] = future
        await self._send(
            {
                "type": "request",
                "protocolVersion": PROTOCOL_VERSION,
                "id": request_id,
                "method": method,
                "params": params or {},
            }
        )
        try:
            return await asyncio.wait_for(future, timeout or self._operation_timeout)
        except TimeoutError:
            with contextlib.suppress(BrokenPipeError, ConnectionError, ProtocolError):
                await self._send(
                    {
                        "type": "cancel",
                        "protocolVersion": PROTOCOL_VERSION,
                        "correlationId": request_id,
                    }
                )
            raise RuleKitRemoteError("TIMEOUT", f"Rule Kit operation timed out: {method}") from None
        finally:
            self._pending.pop(request_id, None)

    async def list_providers(self) -> list[dict]:
        return await self.call("listProviders")

    async def create_session(self, request: dict) -> RuleKitSessionRef:
        result = await self.call("createSession", request)
        session_id = result.get("sessionId") if isinstance(result, dict) else None
        if not isinstance(session_id, str) or not session_id:
            raise ProtocolError("createSession response has no sessionId")
        lease_expires_at = result.get("leaseExpiresAt")
        if not isinstance(lease_expires_at, str) or not lease_expires_at:
            raise ProtocolError("createSession response has no leaseExpiresAt")
        self._sessions.add(session_id)
        return RuleKitSessionRef(
            worker_instance_id=self.worker_instance_id,
            worker_generation=self.worker_generation,
            session_id=session_id,
            lease_expires_at=lease_expires_at,
        )

    def _session_id(self, session: str | RuleKitSessionRef) -> str:
        if isinstance(session, RuleKitSessionRef):
            if (
                session.worker_instance_id != self.worker_instance_id
                or session.worker_generation != self.worker_generation
            ):
                raise RuleKitRemoteError("STALE_WORKER_GENERATION", "session belongs to a previous worker")
            session_id = session.session_id
        else:
            session_id = session
        if session_id not in self._sessions:
            raise RuleKitRemoteError("STALE_WORKER_GENERATION", "session is not owned by this worker client")
        return session_id

    async def evaluate(self, session: str | RuleKitSessionRef, request: dict | None = None) -> dict:
        return await self.call("evaluate", {"sessionId": self._session_id(session), "options": request or {}})

    async def preview_changes(self, session: str | RuleKitSessionRef, request: dict) -> dict:
        return await self.call("previewChanges", {"sessionId": self._session_id(session), "request": request})

    async def commit_changes(self, session: str | RuleKitSessionRef, request: dict) -> dict:
        return await self.call("commitChanges", {"sessionId": self._session_id(session), "request": request})

    async def reset_session(self, session: str | RuleKitSessionRef, request: dict | None = None) -> dict:
        return await self.call("resetSession", {"sessionId": self._session_id(session), "options": request or {}})

    async def get_session(self, session: str | RuleKitSessionRef) -> dict:
        return await self.call("getSession", {"sessionId": self._session_id(session)})

    async def close_session(self, session: str | RuleKitSessionRef) -> None:
        session_id = self._session_id(session)
        await self.call("closeSession", {"sessionId": session_id})
        self._sessions.discard(session_id)

    async def shutdown_worker(self) -> None:
        if self._closed:
            return
        await self._send({"type": "shutdown", "protocolVersion": PROTOCOL_VERSION})

    async def close(self) -> None:
        self._closed = True
        self._sessions.clear()
        if not self._reader_task.done():
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
        error = ProtocolError("Rule Kit client closed")
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()
        await self._close_writer()

    async def _close_writer(self) -> None:
        """Close/abort the pipe within one operation-timeout budget.

        Windows Proactor transports may never resolve wait_closed after the
        child has already exited. Keep cleanup explicit, but never let that OS
        completion stall the BE shutdown path indefinitely.
        """
        async with self._writer_close_lock:
            if self._writer_cleanup_complete:
                return
            try:
                if not self._writer.is_closing():
                    self._writer.close()
                waiter = asyncio.create_task(self._writer.wait_closed())
                first_wait = self._operation_timeout / 2
                try:
                    await asyncio.wait_for(asyncio.shield(waiter), first_wait)
                    return
                except TimeoutError:
                    transport = getattr(self._writer, "transport", None)
                    abort = getattr(transport, "abort", None)
                    if callable(abort):
                        abort()
                    try:
                        await asyncio.wait_for(
                            asyncio.shield(waiter), self._operation_timeout - first_wait
                        )
                    except TimeoutError:
                        waiter.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await waiter
            except (OSError, ConnectionError):
                return
            finally:
                self._writer_cleanup_complete = True

    async def _send(self, message: dict) -> None:
        payload = json.dumps(message, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        async with self._write_lock:
            self._writer.write(payload)
            await self._writer.drain()

    async def _read_loop(self) -> None:
        try:
            while line := await self._reader.readline():
                try:
                    message = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    raise ProtocolError("worker emitted malformed JSON") from None
                if not isinstance(message, dict) or message.get("protocolVersion") != PROTOCOL_VERSION:
                    raise ProtocolError("worker response protocol mismatch")
                correlation_id = message.get("correlationId")
                future = self._pending.get(correlation_id)
                if future is None or future.done():
                    continue
                if message.get("type") == "result":
                    future.set_result(message.get("result"))
                elif message.get("type") == "error":
                    error = message.get("error") or {}
                    future.set_exception(
                        RuleKitRemoteError(
                            str(error.get("code", "WORKER_FAILURE")),
                            str(error.get("message", "Rule Kit worker failed")),
                            error.get("details"),
                        )
                    )
                else:
                    future.set_exception(ProtocolError("unknown worker response type"))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._fail_pending(error)
        finally:
            self._closed = True
            self._fail_pending(ProtocolError("Rule Kit worker pipe closed"))

    def _fail_pending(self, error: Exception) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
