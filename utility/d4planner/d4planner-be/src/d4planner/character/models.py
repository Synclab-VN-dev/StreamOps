from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ParsedItem:
    name: str
    item_type: str
    item_power: int
    favorite: bool = False
    ancestral: bool = False
    rarity: str | None = None
    base_stats: list[dict[str, Any]] = field(default_factory=list)
    affixes: list[dict[str, Any]] = field(default_factory=list)
    comparison: dict[str, list[str]] = field(default_factory=lambda: {"lost": [], "gained": []})
    effects_raw: list[str] = field(default_factory=list)
    metadata_raw: list[str] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EquipmentObservation:
    slot_family: str
    slot_index: int | None
    item: ParsedItem
    observed_at: str
    session_id: str
    seq_start: int
    seq_end: int
    confidence: str
    fingerprint: str
