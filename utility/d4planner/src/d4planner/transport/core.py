"""Protocol core for D4Planner Release 1 realtime transport."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
import hmac
import re
import time
from typing import Any, Protocol
from uuid import uuid4


PROTOCOL_VERSION = "d4planner-ws/v1"
TARGET_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
INTERNAL_CLOSE_SLOW_CONSUMER = "_d4planner_close_slow_consumer"
PUBLIC_TARGET_ERRORS = {
    "TARGET_INVALID": "Target cannot be activated.",
    "TARGET_CHANGED": "Target changed after listing; refresh the list.",
    "TARGET_NOT_FOUND": "Target is no longer available.",
    "TARGET_POLICY_INVALID": "Target assessment policy is invalid.",
}


class ProtocolViolation(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class TargetActivationError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class D4PlannerDomain(Protocol):
    async def list_targets(self) -> dict[str, Any]: ...

    async def activate_target(
        self, target_id: str, expected_sha256: str, expected_list_revision: int,
    ) -> dict[str, Any]: ...


@dataclass(slots=True)
class _Subscriber:
    queue: asyncio.Queue[dict[str, Any] | None]
    last_revision: int
    overflow_count: int = 0


class HudHub:
    """Committed HUD state plus a bounded, coalescing subscriber fan-out."""

    def __init__(self, initial_hud: dict[str, Any], *, backend_generation: int) -> None:
        self._latest = deepcopy(initial_hud)
        self._generation = backend_generation
        self._lock = asyncio.Lock()
        self._subscribers: dict[str, _Subscriber] = {}

    @property
    def latest_revision(self) -> int:
        return int(self._latest["hudRevision"])

    async def snapshot_and_subscribe(
        self,
    ) -> tuple[dict[str, Any], str, asyncio.Queue[dict[str, Any] | None]]:
        async with self._lock:
            subscription_id = f"sub-{uuid4().hex}"
            queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=1)
            self._subscribers[subscription_id] = _Subscriber(
                queue=queue, last_revision=self.latest_revision,
            )
            return deepcopy(self._latest), subscription_id, queue

    async def unsubscribe(self, subscription_id: str | None) -> None:
        if subscription_id is None:
            return
        async with self._lock:
            subscriber = self._subscribers.pop(subscription_id, None)
            # Wake an event pump blocked on the replaced subscription. The
            # sentinel is internal and is never serialized onto the wire.
            if subscriber is not None and subscriber.queue.empty():
                subscriber.queue.put_nowait(None)

    async def publish_after_commit(self, hud: dict[str, Any]) -> bool:
        """Publish a durable committed state. Duplicate/old results are ignored."""
        revision = int(hud["hudRevision"])
        async with self._lock:
            if revision <= self.latest_revision:
                return False
            self._latest = deepcopy(hud)
            for subscription_id, subscriber in tuple(self._subscribers.items()):
                message = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "messageId": f"update-{uuid4().hex}",
                    "type": "hud.update",
                    "correlationId": None,
                    "backendGeneration": self._generation,
                    "subscriptionId": subscription_id,
                    "previousHudRevision": subscriber.last_revision,
                    "hud": deepcopy(hud),
                }
                if subscriber.queue.full():
                    try:
                        subscriber.queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    subscriber.overflow_count += 1
                    if subscriber.overflow_count == 1:
                        message = {
                            "protocolVersion": PROTOCOL_VERSION,
                            "messageId": f"resync-{uuid4().hex}",
                            "type": "resync.required",
                            "correlationId": None,
                            "backendGeneration": self._generation,
                            "reason": "SLOW_CONSUMER",
                            "latestHudRevision": revision,
                        }
                    else:
                        message = {INTERNAL_CLOSE_SLOW_CONSUMER: True}
                subscriber.queue.put_nowait(message)
                subscriber.last_revision = revision
            return True


class D4PlannerProtocolSession:
    """One authenticated WS connection; business work remains behind ports."""

    def __init__(
        self,
        domain: D4PlannerDomain,
        hub: HudHub,
        *,
        credential: str,
        runtime_instance_id: str,
        backend_generation: int,
        origin: str,
        max_pending_messages: int = 32,
        max_requests_per_second: int = 64,
    ) -> None:
        if len(credential) < 32:
            raise ValueError("credential must have at least 32 characters")
        self.domain = domain
        self.hub = hub
        self._credential = credential
        self.runtime_instance_id = runtime_instance_id
        self.backend_generation = backend_generation
        self.origin = origin
        self.max_pending_messages = max_pending_messages
        self.max_requests_per_second = max_requests_per_second
        self.authenticated = False
        self.subscription_id: str | None = None
        self.subscription_queue: asyncio.Queue[dict[str, Any] | None] | None = None
        self._responses: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._request_times: list[float] = []

    async def authenticate(self, message: Any) -> dict[str, Any]:
        _closed_object(
            message,
            required={
                "protocolVersion", "messageId", "type", "correlationId",
                "backendGeneration", "credential", "origin", "lastSeen",
            },
        )
        if message["protocolVersion"] != PROTOCOL_VERSION or message["type"] != "hello":
            raise ProtocolViolation("INVALID_MESSAGE", "Unsupported protocol handshake.")
        if message["correlationId"] is not None:
            raise ProtocolViolation("INVALID_MESSAGE", "hello correlationId must be null.")
        if message["origin"] != self.origin:
            raise ProtocolViolation("ORIGIN_REJECTED", "Origin is not allowed.")
        last_seen = message["lastSeen"]
        if not isinstance(last_seen, dict) or set(last_seen) != {"hudRevision"}:
            raise ProtocolViolation("INVALID_MESSAGE", "Invalid lastSeen cursor.")
        cursor = last_seen["hudRevision"]
        if cursor is not None and (not isinstance(cursor, int) or isinstance(cursor, bool) or cursor < 0):
            raise ProtocolViolation("INVALID_MESSAGE", "Invalid lastSeen revision.")
        credential = message["credential"]
        if not isinstance(credential, str) or not hmac.compare_digest(credential, self._credential):
            raise ProtocolViolation("AUTH_FAILED", "Authentication failed.")
        self.authenticated = True
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "messageId": f"accepted-{uuid4().hex}",
            "type": "hello.accepted",
            "correlationId": message["messageId"],
            "runtimeInstanceId": self.runtime_instance_id,
            "backendGeneration": self.backend_generation,
            "sessionId": f"session-{uuid4().hex}",
            "limits": {
                "maxMessageBytes": 262_144,
                "maxPendingMessages": self.max_pending_messages,
            },
        }

    async def handle(self, message: Any) -> dict[str, Any]:
        if not self.authenticated:
            raise ProtocolViolation("AUTH_FAILED", "hello is required before requests.")
        self._check_rate()
        if not isinstance(message, dict):
            raise ProtocolViolation("INVALID_MESSAGE", "Message must be an object.")
        message_id = message.get("messageId")
        if not isinstance(message_id, str) or not message_id:
            raise ProtocolViolation("INVALID_MESSAGE", "messageId must be non-empty.")
        cached = self._responses.get(message_id)
        if cached is not None:
            return deepcopy(cached)
        if message.get("protocolVersion") != PROTOCOL_VERSION:
            raise ProtocolViolation("INVALID_MESSAGE", "Unsupported protocolVersion.")
        if message.get("backendGeneration") != self.backend_generation:
            raise ProtocolViolation("REVISION_CONFLICT", "Backend generation changed.", retryable=True)
        kind = message.get("type")
        if kind == "target.list.request":
            _simple_request(message, "target.list.request")
            data = await self.domain.list_targets()
            response = {
                "protocolVersion": PROTOCOL_VERSION,
                "messageId": f"targets-{uuid4().hex}",
                "type": "target.list.result",
                "correlationId": message_id,
                "backendGeneration": self.backend_generation,
                **deepcopy(data),
            }
        elif kind == "target.select.request":
            _closed_object(
                message,
                required={
                    "protocolVersion", "messageId", "type", "correlationId",
                    "backendGeneration", "targetId", "expectedSha256",
                    "expectedListRevision",
                },
            )
            if message["correlationId"] is not None:
                raise ProtocolViolation("INVALID_MESSAGE", "Request correlationId must be null.")
            target_id = message["targetId"]
            sha = message["expectedSha256"]
            if not isinstance(target_id, str) or TARGET_ID.fullmatch(target_id) is None:
                raise ProtocolViolation("INVALID_MESSAGE", "Unsafe targetId.")
            if not isinstance(sha, str) or SHA256.fullmatch(sha) is None:
                raise ProtocolViolation("INVALID_MESSAGE", "Invalid Target hash.")
            list_revision = message["expectedListRevision"]
            if (
                not isinstance(list_revision, int)
                or isinstance(list_revision, bool)
                or list_revision < 0
            ):
                raise ProtocolViolation("INVALID_MESSAGE", "Invalid Target list revision.")
            result = await self.domain.activate_target(
                target_id, sha, list_revision,
            )
            hud = result.pop("hud", None)
            if hud is not None:
                await self.hub.publish_after_commit(hud)
            response = {
                "protocolVersion": PROTOCOL_VERSION,
                "messageId": f"selected-{uuid4().hex}",
                "type": "target.select.result",
                "correlationId": message_id,
                "backendGeneration": self.backend_generation,
                **deepcopy(result),
            }
        elif kind == "hud.snapshot.request":
            _closed_object(
                message,
                required={
                    "protocolVersion", "messageId", "type", "correlationId",
                    "backendGeneration", "requestContext",
                },
            )
            if message["correlationId"] is not None or not isinstance(message["requestContext"], dict):
                raise ProtocolViolation("INVALID_MESSAGE", "Invalid snapshot request.")
            _validate_snapshot_context(message["requestContext"], self.runtime_instance_id)
            await self.hub.unsubscribe(self.subscription_id)
            hud, subscription_id, queue = await self.hub.snapshot_and_subscribe()
            self.subscription_id = subscription_id
            self.subscription_queue = queue
            response = {
                "protocolVersion": PROTOCOL_VERSION,
                "messageId": f"snapshot-{uuid4().hex}",
                "type": "hud.snapshot",
                "correlationId": message_id,
                "backendGeneration": self.backend_generation,
                "authoritative": True,
                "subscriptionId": subscription_id,
                "subscriptionAfterRevision": hud["hudRevision"],
                "requestContext": deepcopy(message["requestContext"]),
                "hud": hud,
            }
        elif kind == "ping":
            _closed_object(
                message,
                required={
                    "protocolVersion", "messageId", "type", "correlationId",
                    "backendGeneration", "sentAt",
                },
            )
            response = {
                "protocolVersion": PROTOCOL_VERSION,
                "messageId": f"pong-{uuid4().hex}",
                "type": "pong",
                "correlationId": message_id,
                "backendGeneration": self.backend_generation,
                "sentAt": message["sentAt"],
            }
        else:
            raise ProtocolViolation("INVALID_MESSAGE", "Unknown message type.")
        self._remember(message_id, response)
        return response

    async def close(self) -> None:
        await self.hub.unsubscribe(self.subscription_id)
        self.subscription_id = None
        self.subscription_queue = None

    def error(self, exc: ProtocolViolation | TargetActivationError, correlation_id: str | None) -> dict[str, Any]:
        message = str(exc)
        if isinstance(exc, TargetActivationError):
            message = PUBLIC_TARGET_ERRORS.get(exc.code, "Target activation failed.")
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "messageId": f"error-{uuid4().hex}",
            "type": "error",
            "correlationId": correlation_id,
            "backendGeneration": self.backend_generation,
            "code": exc.code,
            "message": message,
            "retryable": exc.retryable,
        }

    def _remember(self, message_id: str, response: dict[str, Any]) -> None:
        self._responses[message_id] = deepcopy(response)
        self._responses.move_to_end(message_id)
        while len(self._responses) > 128:
            self._responses.popitem(last=False)

    def _check_rate(self) -> None:
        now = time.monotonic()
        self._request_times = [stamp for stamp in self._request_times if now - stamp < 1]
        if len(self._request_times) >= self.max_requests_per_second:
            raise ProtocolViolation("INVALID_MESSAGE", "Request rate exceeded.", retryable=True)
        self._request_times.append(now)


def _simple_request(message: dict[str, Any], expected_type: str) -> None:
    _closed_object(
        message,
        required={
            "protocolVersion", "messageId", "type", "correlationId", "backendGeneration",
        },
    )
    if message["type"] != expected_type or message["correlationId"] is not None:
        raise ProtocolViolation("INVALID_MESSAGE", "Invalid request envelope.")


def _closed_object(message: Any, *, required: set[str]) -> None:
    if not isinstance(message, dict):
        raise ProtocolViolation("INVALID_MESSAGE", "Message must be an object.")
    missing = required - set(message)
    extras = set(message) - required
    if missing or extras:
        raise ProtocolViolation("INVALID_MESSAGE", "Message fields do not match the contract.")


def _validate_snapshot_context(context: dict[str, Any], runtime_instance_id: str) -> None:
    mode = context.get("mode")
    if mode == "DISCOVER_ACTIVE_CONTEXT":
        _closed_object(
            context,
            required={"mode", "reason", "attempt", "runtimeInstanceId", "minimumHudRevision"},
        )
        if context["reason"] not in {
            "INITIAL_CONNECTION", "BACKEND_GENERATION_CHANGED", "BACKEND_IDENTITY_CHANGED",
            "KNOWN_CONTEXT_CHANGED", "TIMEOUT_RETRY",
        }:
            raise ProtocolViolation("INVALID_MESSAGE", "Invalid discovery reason.")
        if not isinstance(context["attempt"], int) or isinstance(context["attempt"], bool) or context["attempt"] < 1:
            raise ProtocolViolation("INVALID_MESSAGE", "Invalid discovery attempt.")
    elif mode == "RESYNC_KNOWN_CONTEXT":
        _closed_object(
            context,
            required={"mode", "runtimeInstanceId", "minimumHudRevision", "expectedContext"},
        )
        expected = context["expectedContext"]
        if not isinstance(expected, dict) or set(expected) != {
            "state", "characterId", "targetId", "selectionRevision",
        }:
            raise ProtocolViolation("INVALID_MESSAGE", "Invalid known context.")
    else:
        raise ProtocolViolation("INVALID_MESSAGE", "Invalid snapshot mode.")
    if context["runtimeInstanceId"] != runtime_instance_id:
        raise ProtocolViolation("REVISION_CONFLICT", "Runtime instance changed.", retryable=True)
    minimum = context["minimumHudRevision"]
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 0:
        raise ProtocolViolation("INVALID_MESSAGE", "Invalid minimum HUD revision.")
