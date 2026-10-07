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
    pending_empty_interstitial_count: int = 0
    ring_pending_fingerprint: str | None = None
    ring_pending_item_name: str | None = None
    ring_probe_open: bool = False

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
        self.pending_empty_interstitial_count = 0

    def keep_empty_pending(self) -> None:
        self.pending_empty_interstitial_count += 1

    def clear_empty_pending(self) -> None:
        self.pending_empty_slot = None
        self.pending_empty_interstitial_count = 0

    def start_ring_pending(self, fingerprint: str, item_name: str) -> None:
        self.ring_pending_fingerprint = fingerprint
        self.ring_pending_item_name = item_name
        self.ring_probe_open = False

    def open_ring_probe(self) -> None:
        self.ring_probe_open = True

    def clear_ring_pending(self) -> None:
        self.ring_pending_fingerprint = None
        self.ring_pending_item_name = None
        self.ring_probe_open = False
