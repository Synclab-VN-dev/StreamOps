from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class EquipmentLine:
    text: str
    seq: int
    timestamp: str
    session_id: str


@dataclass
class EquipmentContext:
    """Mutable stream context owned by EquipmentProjector.

    Resolvers inspect this state but repository mutations remain outside them.
    """

    slot: str | None = None
    equipped_marker: bool = False
    lookback: list[EquipmentLine] = field(default_factory=list)
    active: list[EquipmentLine] | None = None
    pending_empty_slot: str | None = None
    pending_empty_neutral_count: int = 0

    def reset_for_slot(self, slot: str) -> None:
        self.slot = slot
        self.equipped_marker = False
        self.active = None
        self.lookback = []

    def reset_segment(self) -> None:
        self.active = None
        self.equipped_marker = False
        self.lookback = []

    def start_empty_pending(self, slot: str) -> None:
        self.pending_empty_slot = slot
        self.pending_empty_neutral_count = 0

    def keep_empty_pending(self) -> None:
        self.pending_empty_neutral_count += 1

    def clear_empty_pending(self) -> None:
        self.pending_empty_slot = None
        self.pending_empty_neutral_count = 0
