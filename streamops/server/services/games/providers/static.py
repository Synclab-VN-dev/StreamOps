"""Packaged static catalog: a policy allowlist, not runtime evidence."""
from __future__ import annotations
import json
from importlib.resources import files
from ..models import Seed, GameDefinition

class StaticProvider:
    name = "static"
    def __init__(self, *, seed: dict | None = None):
        self._seed = seed

    def discover(self) -> list[GameDefinition]:
        raw = self._seed
        if raw is None:
            raw = json.loads(files("streamops.server").joinpath("data/games.seed.json").read_text(encoding="utf-8"))
        return list(Seed.model_validate(raw).games)
