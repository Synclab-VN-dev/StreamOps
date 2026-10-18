"""#119 domain reducer: the single intent-to-current mutation boundary.

Producer-specific parsers (NVDA Bag, Equipment, verified grid scan) submit
immutable physical-item intents. The reducer decides *whether* state may change;
storage is injected via a narrow port. Raw comparison/candidate tooltips never
acquire write permission. No NVDA, Engine, SQLite or CLI imports are allowed here.

Future cases extend observation strategies; they must not bypass this reducer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Protocol


Source = Literal["equipped-slot", "bag-selected", "verified-grid"]


@dataclass(frozen=True, slots=True)
class CurrentItemIntent:
    source: Source
    key: str
    payload: Mapping[str, Any]
    fingerprint: str
    scope: str | None = None


class ItemWritePort(Protocol):
    """Interface Segregation: write primitives only; no DB/UI coupling."""

    def upsert(self, intent: CurrentItemIntent) -> bool: ...

    def invalidate_slot(self, slot: str, except_key: str,
                        intent: CurrentItemIntent) -> None: ...

    def limit_ring_positions(self, intent: CurrentItemIntent) -> None: ...


class CurrentItemReducer:
    """Evidence policy and location invariants shared by all producers.

    The interface is intentionally small. Item fingerprints identify a reading,
    not necessarily a globally unique physical object. Reconciliation between
    verified container scans must use stable physical proof, never names alone.
    """

    def __init__(self, port: ItemWritePort):
        self._port = port

    def apply(self, intent: CurrentItemIntent) -> bool:
        item = intent.payload
        if item.get("ownershipStatus") != "CONFIRMED":
            return False
        location = item.get("location") or {}
        name = str(item.get("name") or "").strip()
        if not name or location.get("type") not in {
            "equipment", "inventory", "stash", "unknown"
        }:
            return False

        if intent.source == "equipped-slot":
            slot = location.get("slot")
            if location.get("type") != "equipment" or not slot:
                return False
            if slot != "ring":
                self._port.invalidate_slot(slot, intent.key, intent)
            changed = self._port.upsert(intent)
            if slot == "ring":
                self._port.limit_ring_positions(intent)
            return changed

        if intent.source == "bag-selected":
            if (location.get("type") != "inventory"
                    or item.get("ownershipEvidence") != "character-bag-actions-v1"):
                return False
            return self._port.upsert(intent)

        if intent.source == "verified-grid":
            if not intent.scope or item.get("observationConfidence") != "HIGH":
                return False
            return self._port.upsert(intent)

        return False
