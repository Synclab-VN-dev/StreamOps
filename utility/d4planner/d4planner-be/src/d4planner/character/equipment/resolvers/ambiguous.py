from __future__ import annotations

from ..decision import Resolution, ResolutionKind
from .base import BaseResolver, ResolverRequest


class AmbiguousResolver(BaseResolver):
    """Fail-closed fallback for item observations with insufficient evidence."""

    name = "ambiguous"

    def can_handle(self, request: ResolverRequest) -> bool:
        return request.action == "Unequip"

    def build_resolution(self, request: ResolverRequest) -> Resolution:
        segment = request.segment or []
        return Resolution(
            resolver=self.name,
            kind=ResolutionKind.NO_MUTATION,
            reason="missing_exact_equipped_marker",
            slot=request.context.slot,
            action=request.action,
            item_name=segment[0].text if segment else None,
            source_seq_start=segment[0].seq if segment else None,
            source_seq_end=request.line.seq,
        )
