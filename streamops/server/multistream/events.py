"""Thread-safe domain event fan-out for the multistream core."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import threading
from typing import Any


EventListener = Callable[[dict[str, Any]], None]


class MultistreamEventBus:
    def __init__(self) -> None:
        self._listeners: set[EventListener] = set()
        self._lock = threading.RLock()

    def subscribe(self, listener: EventListener) -> None:
        with self._lock:
            self._listeners.add(listener)

    def unsubscribe(self, listener: EventListener) -> None:
        with self._lock:
            self._listeners.discard(listener)

    def publish(
        self,
        event_type: str,
        destination_id: str,
        data: dict[str, Any],
    ) -> None:
        event = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "destination_id": destination_id,
            "data": data,
        }
        with self._lock:
            listeners = tuple(self._listeners)
        for listener in listeners:
            listener(event)
