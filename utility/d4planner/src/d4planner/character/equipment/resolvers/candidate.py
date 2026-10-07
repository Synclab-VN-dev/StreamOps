from __future__ import annotations

from ..decision import Resolution, ResolutionKind
from ..parser import parse_item
from .base import BaseResolver, ResolverRequest


class CandidateResolver(BaseResolver):
    name = "candidate"

    def can_handle(self, request: ResolverRequest) -> bool:
        return request.action == "Equip"

    def validate(self, request: ResolverRequest) -> str | None:
        return None if request.segment else "missing_item_segment"

    def build_resolution(self, request: ResolverRequest) -> Resolution:
        assert request.segment
        item_name = request.segment[0].text
        parsed = None
        error_type = None
        error = None
        try:
            parsed = parse_item([line.text for line in request.segment])
            item_name = parsed.name
        except Exception as exc:
            # Preserve existing fail-closed candidate behavior: malformed
            # candidate data is diagnostic only and never mutates current state.
            error_type = type(exc).__name__
            error = str(exc)

        return Resolution(
            resolver=self.name,
            kind=ResolutionKind.NO_MUTATION,
            reason="terminal_equip",
            slot=request.context.slot,
            action=request.action,
            item_name=item_name,
            parsed_item=parsed,
            source_seq_start=request.segment[0].seq,
            source_seq_end=request.line.seq,
            parse_error_type=error_type,
            parse_error=error,
        )
