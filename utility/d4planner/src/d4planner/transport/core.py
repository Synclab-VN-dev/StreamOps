"""D5 authenticated notification transport. Business data lives in SQLite."""
from __future__ import annotations
import asyncio
from copy import deepcopy
import hmac
from typing import Any, Protocol
from uuid import uuid4

PROTOCOL_VERSION = 'd4planner-notify/v1'
INTERNAL_CLOSE_SLOW_CONSUMER = '_d4planner_close_slow_consumer'

class ProtocolViolation(Exception):
    def __init__(self, code, message, *, retryable=False):
        super().__init__(message)
        self.code, self.retryable = code, retryable

class TargetActivationError(ProtocolViolation):
    pass

class D4PlannerDomain(Protocol):
    async def list_targets(self) -> dict[str, Any]: ...
    async def activate_target(self, target_id, expected_sha256, expected_list_revision) -> dict[str, Any]: ...

def checkpoint(value):
    if set(value) != {'dbId', 'epoch', 'hudRevision'}:
        raise ValueError('NOTIFICATION_REQUIRES_DB_CHECKPOINT')
    if any(not isinstance(value[k], str) or not value[k] or len(value[k]) > 160 for k in ('dbId', 'epoch')):
        raise ValueError('INVALID_DB_IDENTITY')
    if type(value['hudRevision']) is not int or not 0 <= value['hudRevision'] <= 9007199254740991:
        raise ValueError('INVALID_DB_REVISION')
    return deepcopy(value)

class HudHub:
    """Bounded coalescing notifications, containing no HUD business data."""
    def __init__(self, initial_hud, *, backend_generation):
        self._latest = checkpoint(initial_hud)
        self._lock = asyncio.Lock()
        self._subscribers = {}

    @property
    def latest_revision(self):
        return self._latest['hudRevision']

    def _notification(self):
        return {'protocolVersion': PROTOCOL_VERSION, 'type': 'hud.committed',
                'messageId': uuid4().hex, **self._latest}

    async def snapshot_and_subscribe(self):
        async with self._lock:
            key = uuid4().hex
            queue = asyncio.Queue(maxsize=1)
            self._subscribers[key] = queue
            return self._notification(), key, queue

    async def unsubscribe(self, subscription_id):
        async with self._lock:
            queue = self._subscribers.pop(subscription_id, None)
            if queue is not None and queue.empty():
                queue.put_nowait(None)

    async def publish_after_commit(self, value):
        value = checkpoint(value)
        async with self._lock:
            if (value['dbId'], value['epoch']) == (self._latest['dbId'], self._latest['epoch']) and value['hudRevision'] <= self.latest_revision:
                return False
            self._latest = value
            for queue in self._subscribers.values():
                if queue.full():
                    queue.get_nowait()
                queue.put_nowait(self._notification())
            return True

class D4PlannerProtocolSession:
    def __init__(self, domain, hub, *, credential, runtime_instance_id, backend_generation,
                 origin, max_pending_messages=32, max_requests_per_second=64):
        if len(credential) < 32:
            raise ValueError('credential must have at least 32 characters')
        self.hub, self._credential, self.origin = hub, credential, origin
        self.authenticated = False
        self.subscription_id = self.subscription_queue = None

    async def authenticate(self, message):
        if not isinstance(message, dict) or set(message) != {'protocolVersion','type','messageId','credential','origin'}:
            raise ProtocolViolation('INVALID_MESSAGE', 'Invalid hello')
        if message['protocolVersion'] != PROTOCOL_VERSION or message['type'] != 'hello' or not isinstance(message['messageId'], str) or not 1 <= len(message['messageId']) <= 160:
            raise ProtocolViolation('INVALID_MESSAGE', 'Invalid hello')
        if message['origin'] != self.origin:
            raise ProtocolViolation('ORIGIN_REJECTED', 'Origin is not allowed')
        if not isinstance(message['credential'], str) or not hmac.compare_digest(message['credential'], self._credential):
            raise ProtocolViolation('AUTH_FAILED', 'Authentication failed')
        self.authenticated = True
        latest, self.subscription_id, self.subscription_queue = await self.hub.snapshot_and_subscribe()
        self.subscription_queue.put_nowait(latest)
        return {'protocolVersion': PROTOCOL_VERSION, 'type':'hello.accepted',
                'messageId':uuid4().hex, 'correlationId':message['messageId']}

    async def handle(self, message):
        raise ProtocolViolation('UNSUPPORTED_METHOD', 'Notification socket accepts no business requests')

    def error(self, exc, correlation_id=None):
        return {'protocolVersion':PROTOCOL_VERSION, 'type':'error','messageId':uuid4().hex,'code':exc.code}

    async def close(self):
        await self.hub.unsubscribe(self.subscription_id)
        self.subscription_queue = None
