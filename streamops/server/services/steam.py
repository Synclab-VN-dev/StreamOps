"""Application service for Steam status and lifecycle operations."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import threading
from typing import Literal, Protocol

from ..errors import SteamRestartInProgressError


@dataclass(frozen=True)
class SteamStatus:
    state: Literal["running", "stopped"]
    running: bool
    pid: int | None
    started_at: str | None
    uptime_seconds: int | None
    session_id: int | None
    interactive: bool
    installation_detected: bool

    def api_payload(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SteamRestartResult:
    status: Literal["ok"]
    action: Literal["restart"]
    running: bool
    pid: int
    big_picture_requested: bool

    @classmethod
    def from_status(cls, status: SteamStatus) -> "SteamRestartResult":
        if not status.running or status.pid is None:
            raise ValueError("A successful Steam restart must have a running process.")
        return cls(
            status="ok",
            action="restart",
            running=True,
            pid=status.pid,
            big_picture_requested=True,
        )

    def api_payload(self) -> dict[str, object]:
        return asdict(self)


class SteamBackend(Protocol):
    def status(self) -> SteamStatus: ...

    def restart(self) -> SteamStatus: ...


class SteamService:
    """Run blocking Steam operations off-loop and serialize restarts safely."""

    def __init__(self, backend: SteamBackend) -> None:
        self.backend = backend
        self._restart_lock = threading.Lock()

    async def status(self) -> SteamStatus:
        return await asyncio.to_thread(self.backend.status)

    async def restart(self) -> SteamRestartResult:
        status = await asyncio.to_thread(self._restart_sync_guarded)
        return SteamRestartResult.from_status(status)

    def _restart_sync_guarded(self) -> SteamStatus:
        if not self._restart_lock.acquire(blocking=False):
            raise SteamRestartInProgressError("Another Steam restart is already in progress.")
        try:
            return self.backend.restart()
        finally:
            self._restart_lock.release()
