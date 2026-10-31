from __future__ import annotations

from ..decision import Resolution, ResolutionKind
from .base import BaseResolver, ResolverRequest


class RingResolver(BaseResolver):
    """Resolve exact ring removal from a bare-ring accessibility probe.

    A HIGH equipped Ring observation only creates a candidate. The next Ring
    header opens a probe. EQUIPPED immediately after that header proves normal
    navigation to an occupied ring and cancels deletion. A following slot
    header before EQUIPPED proves the probed physical ring position is bare,
    so only the candidate item's fingerprint is removed.
    """

    name = "ring"

    def can_handle(self, request: ResolverRequest) -> bool:
        return request.context.ring_pending_fingerprint is not None

    def build_resolution(self, request: ResolverRequest) -> Resolution:
        fingerprint = request.context.ring_pending_fingerprint
        assert fingerprint is not None

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
                kind=ResolutionKind.DELETE_ITEM,
                reason="bare_ring_slot_confirmed",
                slot="ring",
                item_name=request.context.ring_pending_item_name,
                source_seq_start=request.line.seq,
                source_seq_end=request.line.seq,
                delete_fingerprint=fingerprint,
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
