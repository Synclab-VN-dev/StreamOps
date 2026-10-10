"""Provider-independent game registry and controlled metadata migration."""
from __future__ import annotations
import logging
from typing import Literal, Protocol
from .models import GameDefinition
from .providers.static import StaticProvider

logger = logging.getLogger(__name__)
ProviderMode = Literal["static", "shadow", "merged"]

class GameCatalogProvider(Protocol):
    def discover(self) -> list[GameDefinition]: ...

class GameCatalogService:
    def __init__(self, static: StaticProvider | None = None, discovery: GameCatalogProvider | None = None,
                 *, mode: ProviderMode = "static"):
        if mode not in ("static", "shadow", "merged"):
            raise ValueError("invalid provider mode")
        self.static, self.discovery, self.mode = static or StaticProvider(), discovery, mode
        self._definitions: dict[str, GameDefinition] = {}
        self.version = 0
        self.conflicts: dict[str, str] = {}

    def refresh(self) -> list[GameDefinition]:
        base = self.static.discover()
        registry = {game.id: game for game in base}
        self.conflicts = {}
        if self.discovery is not None and self.mode != "static":
            try:
                external = self.discovery.discover()
                if len({item.id for item in external}) != len(external):
                    raise ValueError("duplicate provider identity")
                for discovered in external:
                    current = registry.get(discovered.id)
                    if current is None:
                        # A supplemental provider cannot add trusted lifecycle policies.
                        continue
                    if discovered.provider != current.provider or discovered.providerGameId != current.providerGameId:
                        self.conflicts[current.id] = "provider_identity_conflict"
                    elif self.mode == "shadow" and discovered.name != current.name:
                        logger.info("game shadow metadata differs: %s", current.id)
                    elif self.mode == "merged":
                        # Keep security policy, enabled flag, launch/detection/stop and canonical id from static.
                        registry[current.id] = current.model_copy(update={"name": discovered.name, "metadataSource": "steam_local"})
            except Exception:
                logger.exception("optional discovery failed; reverting to static catalog")
                if self.mode == "merged":
                    self.conflicts = {game.id: "provider_unavailable" for game in base}
        if registry != self._definitions or not self.version:
            self._definitions = registry
            self.version += 1
        return list(self._definitions.values())

    def get(self, game_id: str) -> GameDefinition | None:
        if not self.version:
            self.refresh()
        return self._definitions.get(game_id)

    def list(self) -> list[GameDefinition]:
        if not self.version:
            self.refresh()
        return list(self._definitions.values())
