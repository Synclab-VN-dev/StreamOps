from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models import EquipmentObservation
from ..repository import EquipmentRepository
from .parser import fingerprint, is_item_anchor, normalize, parse_item

SLOTS = {
    "Head": "helm",
    "Torso": "chest",
    "Hands": "gloves",
    "Legs": "pants",
    "Feet": "boots",
    "Main Hand": "main_hand",
    "Off-Hand": "off_hand",
    "Ring": "ring",
    "Neck": "amulet",
}

# These slots have a single current occupant. Ring is intentionally excluded:
# Diablo IV has two ring slots while the current contract keeps slot_index=None,
# so "Ring ... Unequip -> Ring" can simply mean focus moved to the other ring.
SINGLE_INSTANCE_SLOTS = frozenset(SLOTS.values()) - {"ring"}


@dataclass
class _Line:
    text: str
    seq: int
    timestamp: str
    session_id: str


class EquipmentProjector:
    def __init__(self, repository: EquipmentRepository):
        self.repository = repository
        self.slot: str | None = None
        self.equipped_marker = False
        self.lookback: list[_Line] = []
        self.active: list[_Line] | None = None
        # An equipped item always ends on the action label "Unequip".
        # If the *very next* accessibility event rebounds to the same
        # single-instance slot, Real-A shows that the button was activated and
        # the slot is now empty. This marker deliberately survives one event.
        self._just_resolved_unequip_slot: str | None = None

    def consume(self, event: dict[str, Any]) -> None:
        if event.get("type") != "speech.raw":
            return

        seq = int(event.get("eventSeq") or 0)
        session = str(event.get("sessionId") or "")
        ts = str(event.get("timestamp") or "")
        checkpoint = self.repository.checkpoint()
        if checkpoint and checkpoint[0] == session and seq <= checkpoint[1]:
            return

        text = normalize(str((event.get("data") or {}).get("text") or ""))
        line = _Line(text, seq, ts, session)
        observation = None
        empty_slot_family = None

        # The empty-slot signal is adjacency-sensitive. Any event other than
        # the same slot consumes the marker without clearing state.
        previous_unequip_slot = self._just_resolved_unequip_slot
        self._just_resolved_unequip_slot = None

        if text in SLOTS:
            incoming_slot = SLOTS[text]
            if (
                previous_unequip_slot == incoming_slot
                and incoming_slot in SINGLE_INSTANCE_SLOTS
            ):
                empty_slot_family = incoming_slot
            self.slot = incoming_slot
            self.equipped_marker = False
            self.active = None
            self.lookback = []
        elif text == "EQUIPPED":
            self.equipped_marker = True

        if self.active is not None:
            self.active.append(line)
            if text in {"Equip", "Unequip"}:
                if text == "Unequip" and self.slot and self.equipped_marker:
                    raw = [x.text for x in self.active]
                    item = parse_item(raw)
                    observation = EquipmentObservation(
                        self.slot,
                        None,
                        item,
                        ts,
                        session,
                        self.active[0].seq,
                        seq,
                        "HIGH",
                        fingerprint(self.slot, item),
                    )
                    self._just_resolved_unequip_slot = self.slot
                self.active = None
                self.equipped_marker = False
                self.lookback = []
        else:
            self.lookback.append(line)
            self.lookback = self.lookback[-3:]
            if len(self.lookback) == 3 and is_item_anchor(
                *(x.text for x in self.lookback)
            ):
                self.active = list(self.lookback)
                self.lookback = []

        self.repository.commit_event(
            session_id=session,
            event_seq=seq,
            updated_at=ts,
            observation=observation,
            empty_slot_family=empty_slot_family,
        )
