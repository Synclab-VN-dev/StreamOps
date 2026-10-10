"""Single GameService facade for REST, WS and CLI."""
from __future__ import annotations
from .catalog import GameCatalogService
from .lifecycle import GameLifecycle, GameServiceError
from .observer import GameObserver
from .status_hub import GameStatusHub

class GameService:
    def __init__(self, catalog: GameCatalogService, observer: GameObserver,
                 hub: GameStatusHub, lifecycle: GameLifecycle):
        self.catalog, self.observer, self.hub, self.lifecycle = catalog, observer, hub, lifecycle

    async def list(self, provider: str | None = None):
        if provider is not None and provider != "steam":
            raise GameServiceError("invalid_provider","Unsupported provider.")
        games = [r.model_dump() for r in await self.observer.list()
                 if provider is None or r.provider == provider]
        return {"games":games,"total":len(games),"revision":self.hub.revision,
                "catalog_version":self.catalog.version}

    async def get(self, game_id: str):
        value = await self.observer.get(game_id)
        if value is None:
            raise GameServiceError("game_not_found","Game is not registered.")
        return value.model_dump()

    async def action(self, game_id: str, action: str, key: str):
        op = await self.lifecycle.submit(game_id, action, key)
        return {"operation_id": op["id"], "game_id": op["game_id"],
                "action": op["action"], "status": op["status"], "phase": op["phase"],
                "code": op["code"]}

    def operation(self, operation_id: str):
        value = self.lifecycle.store.get(operation_id)
        if value is None:
            raise GameServiceError("operation_not_found","Unknown operation.")
        return {"operation_id":value["id"], **value}

    async def reconcile(self, game_id: str):
        return await self.get(game_id)

    async def refresh_catalog(self):
        old = self.catalog.version
        self.catalog.refresh()
        await self.observer.refresh()
        if old != self.catalog.version:
            self.hub.catalog_changed()
        return {"catalog_version":self.catalog.version,"revision":self.hub.revision}
