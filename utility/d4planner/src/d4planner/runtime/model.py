"""Runtime state and status models for D4Planner."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class RuntimeState(StrEnum):
    STOPPED = "STOPPED"
    BOOTSTRAPPING = "BOOTSTRAPPING"
    NVDA_READY = "NVDA_READY"
    TOLK_READY = "TOLK_READY"
    GAME_STARTING = "GAME_STARTING"
    GAME_ATTACHED = "GAME_ATTACHED"
    CAPTURE_READY = "CAPTURE_READY"
    RUNNING = "RUNNING"
    WAITING_FOR_GAME = "WAITING_FOR_GAME"
    RESTART_REQUIRED = "RESTART_REQUIRED"
    BLOCKED = "BLOCKED"
    DEGRADED = "DEGRADED"


ALLOWED_TRANSITIONS: dict[RuntimeState, set[RuntimeState]] = {
    RuntimeState.STOPPED: {RuntimeState.BOOTSTRAPPING},
    RuntimeState.BOOTSTRAPPING: {
        RuntimeState.NVDA_READY,
        RuntimeState.BLOCKED,
        RuntimeState.DEGRADED,
        RuntimeState.RESTART_REQUIRED,
        RuntimeState.STOPPED,
    },
    RuntimeState.NVDA_READY: {
        RuntimeState.TOLK_READY,
        RuntimeState.BLOCKED,
        RuntimeState.DEGRADED,
        RuntimeState.RESTART_REQUIRED,
        RuntimeState.STOPPED,
    },
    RuntimeState.TOLK_READY: {
        RuntimeState.GAME_STARTING,
        RuntimeState.GAME_ATTACHED,
        RuntimeState.RESTART_REQUIRED,
        RuntimeState.BLOCKED,
        RuntimeState.DEGRADED,
        RuntimeState.STOPPED,
    },
    RuntimeState.GAME_STARTING: {
        RuntimeState.GAME_ATTACHED,
        RuntimeState.WAITING_FOR_GAME,
        RuntimeState.RESTART_REQUIRED,
        RuntimeState.BLOCKED,
        RuntimeState.DEGRADED,
        RuntimeState.STOPPED,
    },
    RuntimeState.GAME_ATTACHED: {
        RuntimeState.CAPTURE_READY,
        RuntimeState.WAITING_FOR_GAME,
        RuntimeState.RESTART_REQUIRED,
        RuntimeState.DEGRADED,
        RuntimeState.STOPPED,
    },
    RuntimeState.CAPTURE_READY: {
        RuntimeState.RUNNING,
        RuntimeState.WAITING_FOR_GAME,
        RuntimeState.DEGRADED,
        RuntimeState.STOPPED,
    },
    RuntimeState.RUNNING: {
        RuntimeState.WAITING_FOR_GAME,
        RuntimeState.DEGRADED,
        RuntimeState.RESTART_REQUIRED,
        RuntimeState.STOPPED,
    },
    RuntimeState.WAITING_FOR_GAME: {
        RuntimeState.GAME_ATTACHED,
        RuntimeState.GAME_STARTING,
        RuntimeState.DEGRADED,
        RuntimeState.RESTART_REQUIRED,
        RuntimeState.STOPPED,
    },
    RuntimeState.RESTART_REQUIRED: {
        RuntimeState.BOOTSTRAPPING,
        RuntimeState.STOPPED,
    },
    RuntimeState.BLOCKED: {
        RuntimeState.BOOTSTRAPPING,
        RuntimeState.STOPPED,
    },
    RuntimeState.DEGRADED: {
        RuntimeState.NVDA_READY,
        RuntimeState.TOLK_READY,
        RuntimeState.GAME_ATTACHED,
        RuntimeState.RUNNING,
        RuntimeState.WAITING_FOR_GAME,
        RuntimeState.BLOCKED,
        RuntimeState.RESTART_REQUIRED,
        RuntimeState.STOPPED,
    },
}


def can_transition(current: RuntimeState, target: RuntimeState) -> bool:
    if current == target:
        return True
    return target in ALLOWED_TRANSITIONS.get(current, set())


@dataclass(slots=True)
class ProcessInfo:
    name: str
    pid: int
    session_id: int | None = None
    started_at: str | None = None
    path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TolkHealth:
    reader: str | None
    speech: bool
    braille: bool = False
    error: str | None = None

    @property
    def ready(self) -> bool:
        return (self.reader or "").casefold() == "nvda" and self.speech and not self.error

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RuntimeStatus:
    state: RuntimeState
    updated_at: str
    detail: str = ""
    supervisor_pid: int | None = None
    session_id: str | None = None
    session_dir: str | None = None
    active_console_session_id: int | None = None
    nvda: ProcessInfo | None = None
    steam: ProcessInfo | None = None
    game: ProcessInfo | None = None
    tolk: TolkHealth | None = None
    capture_active: bool = False
    silent: bool = True
    last_event_at: str | None = None
    last_error: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "updatedAt": self.updated_at,
            "detail": self.detail,
            "supervisorPid": self.supervisor_pid,
            "sessionId": self.session_id,
            "sessionDir": self.session_dir,
            "activeConsoleSessionId": self.active_console_session_id,
            "nvda": self.nvda.as_dict() if self.nvda else None,
            "steam": self.steam.as_dict() if self.steam else None,
            "game": self.game.as_dict() if self.game else None,
            "tolk": self.tolk.as_dict() if self.tolk else None,
            "captureActive": self.capture_active,
            "silent": self.silent,
            "lastEventAt": self.last_event_at,
            "lastError": self.last_error,
            "extras": self.extras,
        }
