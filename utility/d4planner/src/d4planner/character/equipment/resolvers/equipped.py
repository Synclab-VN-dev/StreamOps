from __future__ import annotations

from ...models import EquipmentObservation
from ..decision import Resolution, ResolutionKind
from ..parser import fingerprint, parse_item, parse_type
from ..slot_policy import DEFAULT_SLOT_TYPES
from .base import BaseResolver, ResolverRequest


class EquippedResolver(BaseResolver):
    name = "equipped"

    def can_handle(self, request: ResolverRequest) -> bool:
        return request.action == "Unequip"

    def validate(self, request: ResolverRequest) -> str | None:
        if not request.segment:
            return "missing_item_segment"
        if not request.context.slot:
            return "missing_slot_context"
        if not request.context.equipped_marker:
            return "missing_exact_equipped_marker"
        # A slot header is contextual evidence, not proof that the next
        # tooltip belongs to it. Reject a Staff under a stale Feet context.
        if len(request.segment) < 2:
            return "missing_item_type"
        parsed = parse_type(request.segment[1].text)
        if not parsed or not DEFAULT_SLOT_TYPES.allows(
            request.context.slot, parsed[2]
        ):
            return "item_type_incompatible_with_slot"
        return None

    def build_resolution(self, request: ResolverRequest) -> Resolution:
        assert request.segment
        assert request.context.slot

        item = parse_item([line.text for line in request.segment])
        start = request.segment[0].seq
        end = request.line.seq
        observation = EquipmentObservation(
            request.context.slot,
            None,
            item,
            request.line.timestamp,
            request.line.session_id,
            start,
            end,
            "HIGH",
            fingerprint(request.context.slot, item),
        )
        return Resolution(
            resolver=self.name,
            kind=ResolutionKind.UPSERT,
            reason="slot+equipped+anchor+terminal_unequip",
            slot=request.context.slot,
            action=request.action,
            item_name=item.name,
            parsed_item=item,
            observation=observation,
            source_seq_start=start,
            source_seq_end=end,
            start_empty_pending=True,
        )
