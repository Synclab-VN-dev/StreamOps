"""Equipment slot/type consistency: an OCP extension registry.

Context labels establish *candidate* slots. A tooltip can claim that slot only
when its parsed physical item type is compatible. This prevents a stale Feet
context from turning a two-handed Staff into equipped Boots.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class SlotTypeRule(Protocol):
    """Small read-only contract for independently extensible item families."""

    def allows(self, slot: str, item_type: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class KnownTypes:
    slot: str
    types: frozenset[str]

    def allows(self, slot: str, item_type: str) -> bool:
        return slot == self.slot and item_type in self.types


class SlotTypePolicy:
    """All recognized slots are validated; unknown types fail closed.

    Each extension contributes one rule instead of modifying projector logic.
    The policy is pure and is shared by every EquipmentResolver instance.
    """

    def __init__(self, rules: tuple[SlotTypeRule, ...]):
        self._rules = rules

    def allows(self, slot: str | None, item_type: str | None) -> bool:
        if not slot or not item_type:
            return False
        return any(rule.allows(slot, item_type) for rule in self._rules)


DEFAULT_SLOT_TYPES = SlotTypePolicy((
    KnownTypes("helm", frozenset({"Helm"})),
    KnownTypes("chest", frozenset({"Chest Armor"})),
    KnownTypes("gloves", frozenset({"Gloves"})),
    KnownTypes("pants", frozenset({"Pants"})),
    KnownTypes("boots", frozenset({"Boots"})),
    KnownTypes("main_hand", frozenset({
        "Wand", "Staff", "Sword", "Dagger", "Mace", "Axe", "Scythe",
        "Bow", "Crossbow", "Polearm", "Two-Handed Sword",
        "Two-Handed Mace", "Two-Handed Axe", "Two-Handed Scythe",
    })),
    KnownTypes("off_hand", frozenset({"Focus", "Shield", "Totem"})),
    KnownTypes("ring", frozenset({"Ring"})),
    KnownTypes("amulet", frozenset({"Amulet"})),
))
