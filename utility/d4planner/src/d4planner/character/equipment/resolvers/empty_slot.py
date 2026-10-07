from __future__ import annotations

from ..decision import Resolution, ResolutionKind
from ..slots import SINGLE_INSTANCE_SLOTS
from .base import BaseResolver, ResolverRequest


class EmptySlotResolver(BaseResolver):
    """Resolve the current immediate-rebound empty-slot rule.

    This refactor intentionally preserves #63 behavior. Support for one neutral
    event is added only after architecture regression tests are green.
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
            return Resolution(
                resolver=self.name,
                kind=ResolutionKind.CLEAR_SLOT,
                reason="same_slot_immediate_rebound",
                slot=pending,
                source_seq_start=request.line.seq,
                source_seq_end=request.line.seq,
            )

        if request.incoming_slot is not None:
            reason = f"next_event_slot:{request.incoming_slot}"
        else:
            reason = "next_event_not_same_slot"

        return Resolution(
            resolver=self.name,
            kind=ResolutionKind.NO_MUTATION,
            reason=reason,
            slot=pending,
            source_seq_start=request.line.seq,
            source_seq_end=request.line.seq,
        )
