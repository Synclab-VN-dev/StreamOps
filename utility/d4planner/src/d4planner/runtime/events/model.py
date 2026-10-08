"""Canonical D4Planner runtime event contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class EventDraft:
    type: str
    data: dict[str, Any]
    timestamp: str | None = None


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    event_seq: int
    type: str
    timestamp: str
    session_id: str
    data: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "eventSeq": self.event_seq,
            "type": self.type,
            "timestamp": self.timestamp,
            "sessionId": self.session_id,
            "data": self.data,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EventEnvelope":
        data = value.get("data") if isinstance(value.get("data"), dict) else {}
        return cls(
            event_seq=int(value["eventSeq"]),
            type=str(value["type"]),
            timestamp=str(value["timestamp"]),
            session_id=str(value["sessionId"]),
            data=dict(data),
        )
