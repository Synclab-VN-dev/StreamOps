from __future__ import annotations

from ..decision import Resolution, ResolutionKind
from ..parser import POWER_RE, parse_type
from ..slots import SINGLE_INSTANCE_SLOTS
from .base import BaseResolver, ResolverRequest


KNOWN_ITEM_TYPES = {
    "Helm",
    "Chest Armor",
    "Gloves",
    "Pants",
    "Boots",
    "Wand",
    "Focus",
    "Ring",
    "Amulet",
    "Sword",
}

SEMANTIC_TOKENS = {"EQUIPPED", "Equip", "Unequip"}


def _is_neutral_text(text: str) -> bool:
    """Return True only for text with no known resolver structure."""

    if text in SEMANTIC_TOKENS:
        return False
    if POWER_RE.match(text):
        return False
    parsed_type = parse_type(text)
    if parsed_type and parsed_type[2] in KNOWN_ITEM_TYPES:
        return False
    return True


class EmptySlotResolver(BaseResolver):
    """Resolve equipped -> empty transitions from bounded Real-A evidence.

    Strong current-item evidence opens a pending transition. The slot may
    rebound immediately or after exactly one neutral accessibility line.
    Anything structural, another slot, a second neutral line, or Ring fails
    closed without clearing current state.
    """

    name = "empty_slot"

    def can_handle(self, request: ResolverRequest) -> bool:
        return request.context.pending_empty_slot is not None

    def build_resolution(self, request: ResolverRequest) -> Resolution:
        pending = request.context.pending_empty_slot
        assert pending is not None

        if (
            request.incoming_slot == pending
            and pending in SINGLE_INSTANCE_SLOTS
        ):
            reason = (
                "same_slot_immediate_rebound"
                if request.context.pending_empty_neutral_count == 0
                else "same_slot_rebound_after_one_neutral"
            )
            return Resolution(
                resolver=self.name,
                kind=ResolutionKind.CLEAR_SLOT,
                reason=reason,
                slot=pending,
                source_seq_start=request.line.seq,
                source_seq_end=request.line.seq,
            )

        if request.incoming_slot is not None:
            return Resolution(
                resolver=self.name,
                kind=ResolutionKind.NO_MUTATION,
                reason=f"next_event_slot:{request.incoming_slot}",
                slot=pending,
                source_seq_start=request.line.seq,
                source_seq_end=request.line.seq,
            )

        if (
            pending in SINGLE_INSTANCE_SLOTS
            and request.context.pending_empty_neutral_count == 0
            and _is_neutral_text(request.line.text)
        ):
            return Resolution(
                resolver=self.name,
                kind=ResolutionKind.NO_MUTATION,
                reason="one_neutral_event_allowed",
                slot=pending,
                source_seq_start=request.line.seq,
                source_seq_end=request.line.seq,
                keep_empty_pending=True,
            )

        reason = (
            "second_neutral_event"
            if request.context.pending_empty_neutral_count > 0
            and _is_neutral_text(request.line.text)
            else "semantic_event_before_same_slot_rebound"
        )
        return Resolution(
            resolver=self.name,
            kind=ResolutionKind.NO_MUTATION,
            reason=reason,
            slot=pending,
            source_seq_start=request.line.seq,
            source_seq_end=request.line.seq,
        )
