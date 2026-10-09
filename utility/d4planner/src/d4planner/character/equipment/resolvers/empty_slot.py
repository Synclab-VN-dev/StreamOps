from __future__ import annotations

from ..decision import Resolution, ResolutionKind
from ..parser import NOISE, POWER_RE, parse_type
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
KNOWN_INTERSTITIAL_TOKENS = {
    "SKILLS UNAVAILABLE",
    "Re-equip item to access Skills",
}
MAX_INTERSTITIAL_EVENTS = 2


def _is_allowed_interstitial(text: str) -> bool:
    """Allow only Real-A-shaped non-structural lines between action and slot.

    Fail closed on arbitrary unknown text. Real-A has shown exact transient
    status messages and long explanatory tooltip sentences. Known UI noise,
    item structure, and action markers are never interstitial evidence.
    """

    if text in KNOWN_INTERSTITIAL_TOKENS:
        return True
    if text in SEMANTIC_TOKENS or text in NOISE:
        return False
    if POWER_RE.match(text):
        return False
    parsed_type = parse_type(text)
    if parsed_type and parsed_type[2] in KNOWN_ITEM_TYPES:
        return False
    return len(text) >= 40 and text.endswith((".", "!", "?"))


class EmptySlotResolver(BaseResolver):
    """Resolve equipped -> empty transitions from bounded Real-A evidence.

    Strong current-item evidence opens a pending transition. The slot may
    rebound immediately or after a short burst of approved interstitial lines.
    Anything structural, another slot, too many interstitials, arbitrary
    unknown text, or Ring fails closed without clearing current state.
    """

    name = "empty_slot"

    def can_handle(self, request: ResolverRequest) -> bool:
        return request.context.pending_empty_slot is not None

    def build_resolution(self, request: ResolverRequest) -> Resolution:
        pending = request.context.pending_empty_slot
        assert pending is not None
        count = request.context.pending_empty_interstitial_count

        if (
            request.incoming_slot == pending
            and pending in SINGLE_INSTANCE_SLOTS
        ):
            if count == 0:
                reason = "same_slot_immediate_rebound"
            elif count == 1:
                reason = "same_slot_rebound_after_one_interstitial"
            else:
                reason = "same_slot_rebound_after_two_interstitials"
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
            and count < MAX_INTERSTITIAL_EVENTS
            and _is_allowed_interstitial(request.line.text)
        ):
            next_count = count + 1
            return Resolution(
                resolver=self.name,
                kind=ResolutionKind.NO_MUTATION,
                reason=f"interstitial_{next_count}_allowed",
                slot=pending,
                source_seq_start=request.line.seq,
                source_seq_end=request.line.seq,
                keep_empty_pending=True,
            )

        reason = (
            "interstitial_limit_exceeded"
            if count >= MAX_INTERSTITIAL_EVENTS
            and _is_allowed_interstitial(request.line.text)
            else "semantic_or_unknown_event_before_same_slot_rebound"
        )
        return Resolution(
            resolver=self.name,
            kind=ResolutionKind.NO_MUTATION,
            reason=reason,
            slot=pending,
            source_seq_start=request.line.seq,
            source_seq_end=request.line.seq,
        )
