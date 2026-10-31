"""Resolve configured Windows virtual keys, never infer physical provenance."""
from __future__ import annotations

from .contract import ControllerProfile, DigitalBinding


class ControllerResolver:
    def __init__(self, profile: ControllerProfile) -> None:
        self.profile = profile
        self._by_vk = {entry.virtual_key: entry for entry in profile.digital}
        if len(self._by_vk) != profile.configured_count:
            raise ValueError("duplicate virtualKey in validated profile")

    def by_virtual_key(self, vk: int) -> DigitalBinding | None:
        if type(vk) is not int:
            return None
        return self._by_vk.get(vk)

    def by_control_id(self, name: str) -> DigitalBinding | None:
        if not isinstance(name, str):
            return None
        control = name.strip().upper()
        return next((x for x in self.profile.digital if x.control_id == control), None)
