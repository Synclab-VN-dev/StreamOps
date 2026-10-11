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


MARKER_REQUIRED_FIELDS = {
    "source",
    "device",
    "key",
    "virtualKey",
    "state",
    "process",
    "processId",
    "contextSource",
    "windowTitle",
}


def validate_event_draft(draft: EventDraft) -> None:
    if not draft.type:
        raise ValueError("event type is required")
    if draft.type != "input.marker.raw":
        return

    missing = sorted(MARKER_REQUIRED_FIELDS.difference(draft.data))
    if missing:
        raise ValueError(
            "input.marker.raw missing required fields: " + ", ".join(missing)
        )
    if draft.data.get("source") != "steamInput":
        raise ValueError("input.marker.raw source must be steamInput")
    if draft.data.get("device") != "keyboard":
        raise ValueError("input.marker.raw device must be keyboard")
    state = str(draft.data.get("state") or "").casefold()
    if state not in {"down", "up"}:
        raise ValueError("input.marker.raw state must be down or up")
    try:
        virtual_key = int(draft.data.get("virtualKey"))
        process_id = int(draft.data.get("processId"))
    except (TypeError, ValueError) as exc:
        raise ValueError("input.marker.raw virtualKey/processId must be integers") from exc
    if virtual_key <= 0 or process_id <= 0:
        raise ValueError("input.marker.raw virtualKey/processId must be positive")
    if not str(draft.data.get("key") or "").strip():
        raise ValueError("input.marker.raw key is required")
