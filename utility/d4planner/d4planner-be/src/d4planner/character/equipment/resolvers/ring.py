from __future__ import annotations

from ..decision import Resolution, ResolutionKind
from .base import BaseResolver, ResolverRequest


class RingResolver(BaseResolver):
    """Track ring focus without treating an anonymous bare slot as a removal."""

    name = "ring"

    def can_handle(self, request: ResolverRequest) -> bool:
        return request.context.ring_pending_fingerprint is not None

    def build_resolution(self, request: ResolverRequest) -> Resolution:
        assert request.context.ring_pending_fingerprint is not None

        if not request.context.ring_probe_open:
            if request.incoming_slot == "ring":
                return Resolution(
                    resolver=self.name,
                    kind=ResolutionKind.NO_MUTATION,
                    reason="ring_probe_started",
                    slot="ring",
                    item_name=request.context.ring_pending_item_name,
                    source_seq_start=request.line.seq,
                    source_seq_end=request.line.seq,
                    open_ring_probe=True,
                )
            return Resolution(
                resolver=self.name,
                kind=ResolutionKind.NO_MUTATION,
                reason="ring_probe_not_started",
                slot="ring",
                item_name=request.context.ring_pending_item_name,
                source_seq_start=request.line.seq,
                source_seq_end=request.line.seq,
            )

        if request.line.text == "EQUIPPED":
            return Resolution(
                resolver=self.name,
                kind=ResolutionKind.NO_MUTATION,
                reason="ring_probe_occupied",
                slot="ring",
                item_name=request.context.ring_pending_item_name,
                source_seq_start=request.line.seq,
                source_seq_end=request.line.seq,
            )

        if request.incoming_slot is not None:
            return Resolution(
                resolver=self.name,
                kind=ResolutionKind.NO_MUTATION,
                reason="ring_probe_position_unverified",
                slot="ring",
                item_name=request.context.ring_pending_item_name,
                source_seq_start=request.line.seq,
                source_seq_end=request.line.seq,
            )

        return Resolution(
            resolver=self.name,
            kind=ResolutionKind.NO_MUTATION,
            reason="ring_probe_unexpected_event",
            slot="ring",
            item_name=request.context.ring_pending_item_name,
            source_seq_start=request.line.seq,
            source_seq_end=request.line.seq,
        )
