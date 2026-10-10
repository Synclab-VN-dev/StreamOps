"""Single verified observer; no game runtime claims from static registry."""
from __future__ import annotations
import asyncio
from typing import Protocol
from .models import GameDefinition, GameObservation, GameRecord, ProcessIdentity, utc_now
from .catalog import GameCatalogService
from ...platform.windows.game_process import GamePlatformError

class GamePlatform(Protocol):
    def inspect(self, game: GameDefinition) -> GameObservation: ...
    def start(self, game: GameDefinition) -> None: ...
    def stop(self, game: GameDefinition, expected: ProcessIdentity) -> None: ...

class GameObserver:
    def __init__(self, catalog: GameCatalogService, platform: GamePlatform):
        self.catalog = catalog
        self.platform = platform
        self._hub = None
        self._last: dict[str, GameRecord] = {}
        self._lock = asyncio.Lock()

    def bind_hub(self, hub) -> None:
        self._hub = hub

    async def refresh(self) -> list[GameRecord]:
        async with self._lock:
            result: list[GameRecord] = []
            for game in self.catalog.list():
                error = self.catalog.conflicts.get(game.id)
                try:
                    if error:
                        raise GamePlatformError("game_identity_ambiguous", error)
                    observed = await asyncio.to_thread(self.platform.inspect, game)
                    # timestamp and update version are owned by the hub.
                    observed = observed.model_copy(update={"process": observed.process.model_copy(
                        update={"observed_at": utc_now()})})
                    proc = observed.process
                    controllable = game.enabled and observed.installed is True and proc.state != "UNKNOWN"
                    has_window = observed.window in ("BACKGROUND", "FOREGROUND")
                    caps = {
                        "start": bool(controllable and proc.state == "STOPPED"),
                        "stop": bool(controllable and proc.state == "RUNNING" and has_window),
                        "restart": bool(controllable and proc.state == "RUNNING" and has_window),
                    }
                    reason = None if any(caps.values()) else "not_verified_or_unsafe"
                except GamePlatformError as exc:
                    observed = GameObservation(process=ProcessIdentity(state="UNKNOWN", stale=True, observed_at=utc_now()))
                    caps = {"start": False, "stop": False, "restart": False}
                    reason = exc.code
                except Exception:
                    observed = GameObservation(process=ProcessIdentity(state="UNKNOWN", stale=True, observed_at=utc_now()))
                    caps = {"start": False, "stop": False, "restart": False}
                    reason = "game_status_unknown"
                result.append(GameRecord(id=game.id, provider=game.provider, name=game.name,
                    metadataSource=game.metadataSource, enabled=game.enabled,
                    observation=observed, capabilities=caps, capability_reason=reason))
            self._last = {item.id: item for item in result}
            if self._hub is not None:
                self._hub.publish(result)
            return result

    async def get(self, game_id: str) -> GameRecord | None:
        await self.refresh()
        return self._last.get(game_id)

    async def list(self) -> list[GameRecord]:
        return await self.refresh()
