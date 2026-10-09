"""Stable, diagnostic-only contract shared by controller backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProbeStatus(str, Enum):
    UNAVAILABLE = "UNAVAILABLE"
    NO_DEVICE = "NO_DEVICE"
    DEVICE_PRESENT_BUT_NO_EVENTS = "DEVICE_PRESENT_BUT_NO_EVENTS"
    EVENTS_OBSERVED = "EVENTS_OBSERVED"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class ControlEdge:
    backend: str
    device_id: str
    raw_control_id: str
    state: str
    timestamp: str

    def __post_init__(self) -> None:
        if self.state not in ("DOWN", "UP"):
            raise ValueError("controller edge state must be DOWN or UP")

    def as_dict(self) -> dict[str, str]:
        return {
            "backend": self.backend,
            "deviceId": self.device_id,
            "rawControlId": self.raw_control_id,
            "state": self.state,
            "timestamp": self.timestamp,
        }


@dataclass(slots=True)
class BackendResult:
    backend: str
    status: ProbeStatus
    runtime: str = "AVAILABLE"
    devices: list[dict[str, Any]] = field(default_factory=list)
    events: list[ControlEdge] = field(default_factory=list)
    detail: str = ""

    def __post_init__(self) -> None:
        if self.status == ProbeStatus.UNAVAILABLE:
            self.runtime = "UNAVAILABLE"

    @property
    def usable(self) -> bool:
        return self.status == ProbeStatus.EVENTS_OBSERVED and bool(self.events)

    def as_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "runtime": self.runtime,
            "status": self.status.value,
            "controller": "YES" if self.devices else "NO",
            "devices": self.devices,
            "events": [event.as_dict() for event in self.events],
            "detail": self.detail,
        }


class EdgeTracker:
    """Emit only transitions, per (device, control); no synthetic keys."""

    def __init__(self, backend: str):
        self.backend = backend
        self._pressed: dict[str, set[str]] = {}

    def update(self, device_id: str, pressed: set[str], timestamp: str) -> list[ControlEdge]:
        previous = self._pressed.get(device_id, set())
        changes = [
            ControlEdge(self.backend, device_id, key, "UP", timestamp)
            for key in sorted(previous - pressed)
        ]
        changes += [
            ControlEdge(self.backend, device_id, key, "DOWN", timestamp)
            for key in sorted(pressed - previous)
        ]
        self._pressed[device_id] = set(pressed)
        return changes

    def disconnect(self, device_id: str, timestamp: str) -> list[ControlEdge]:
        return self.update(device_id, set(), timestamp)
