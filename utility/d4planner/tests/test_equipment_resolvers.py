from __future__ import annotations

from d4planner.character.equipment.context import EquipmentContext, EquipmentLine
from d4planner.character.equipment.decision import ResolutionKind
from d4planner.character.equipment.resolvers import (
    ResolverRequest,
    empty_slot_resolver_pipeline,
    item_resolver_pipeline,
)
from d4planner.character.equipment.resolvers.base import BaseResolver
from d4planner.character.equipment.decision import Resolution


def _line(text: str, seq: int = 1) -> EquipmentLine:
    return EquipmentLine(text, seq, f"t{seq}", "s")


def _segment(action: str, *, item: str = "TEST HELM") -> list[EquipmentLine]:
    return [
        _line(item, 1),
        _line("Rare Helm", 2),
        _line("850 Item Power", 3),
        _line(action, 4),
    ]


def test_base_resolver_uses_template_method_order():
    calls: list[str] = []

    class ProbeResolver(BaseResolver):
        name = "probe"

        def can_handle(self, request):
            calls.append("can_handle")
            return True

        def validate(self, request):
            calls.append("validate")
            return None

        def build_resolution(self, request):
            calls.append("build_resolution")
            return Resolution(
                resolver=self.name,
                kind=ResolutionKind.NO_MUTATION,
                reason="probe",
            )

    decision = ProbeResolver().resolve(
        ResolverRequest(context=EquipmentContext(), line=_line("x"))
    )

    assert decision is not None
    assert decision.resolver == "probe"
    assert calls == ["can_handle", "validate", "build_resolution"]


def test_item_pipeline_equipped_resolver_has_priority_for_strong_evidence():
    context = EquipmentContext(slot="helm", equipped_marker=True)
    segment = _segment("Unequip")

    decision = item_resolver_pipeline().resolve(
        ResolverRequest(
            context=context,
            line=segment[-1],
            segment=segment,
            action="Unequip",
        )
    )

    assert decision is not None
    assert decision.resolver == "equipped"
    assert decision.kind == ResolutionKind.UPSERT
    assert decision.observation is not None
    assert decision.item_name == "TEST HELM"
    assert decision.start_empty_pending is True


def test_item_pipeline_candidate_never_mutates_current_equipment():
    context = EquipmentContext(slot="helm", equipped_marker=True)
    segment = _segment("Equip", item="CANDIDATE HELM")

    decision = item_resolver_pipeline().resolve(
        ResolverRequest(
            context=context,
            line=segment[-1],
            segment=segment,
            action="Equip",
        )
    )

    assert decision is not None
    assert decision.resolver == "candidate"
    assert decision.kind == ResolutionKind.NO_MUTATION
    assert decision.reason == "terminal_equip"
    assert decision.observation is None


def test_item_pipeline_falls_back_to_ambiguous_without_exact_equipped_marker():
    context = EquipmentContext(slot="helm", equipped_marker=False)
    segment = _segment("Unequip")

    decision = item_resolver_pipeline().resolve(
        ResolverRequest(
            context=context,
            line=segment[-1],
            segment=segment,
            action="Unequip",
        )
    )

    assert decision is not None
    assert decision.resolver == "ambiguous"
    assert decision.kind == ResolutionKind.NO_MUTATION
    assert decision.reason == "missing_exact_equipped_marker"


def test_empty_slot_resolver_preserves_immediate_rebound_contract():
    context = EquipmentContext(pending_empty_slot="amulet")
    decision = empty_slot_resolver_pipeline().resolve(
        ResolverRequest(
            context=context,
            line=_line("Neck", 20),
            incoming_slot="amulet",
        )
    )

    assert decision is not None
    assert decision.resolver == "empty_slot"
    assert decision.kind == ResolutionKind.CLEAR_SLOT
    assert decision.slot == "amulet"


def test_empty_slot_resolver_fail_closed_for_different_slot_and_ring():
    pipeline = empty_slot_resolver_pipeline()

    different = pipeline.resolve(
        ResolverRequest(
            context=EquipmentContext(pending_empty_slot="off_hand"),
            line=_line("Ring", 30),
            incoming_slot="ring",
        )
    )
    assert different is not None
    assert different.kind == ResolutionKind.NO_MUTATION
    assert different.reason == "next_event_slot:ring"

    ring = pipeline.resolve(
        ResolverRequest(
            context=EquipmentContext(pending_empty_slot="ring"),
            line=_line("Ring", 31),
            incoming_slot="ring",
        )
    )
    assert ring is not None
    assert ring.kind == ResolutionKind.NO_MUTATION
    assert ring.reason == "next_event_slot:ring"


def test_empty_slot_resolver_allows_exactly_one_neutral_event():
    context = EquipmentContext(pending_empty_slot="amulet")

    neutral = empty_slot_resolver_pipeline().resolve(
        ResolverRequest(
            context=context,
            line=_line(
                "Incapacitated enemies cannot perform actions due to Daze, Fear, Frozen, Knockdown or Stun.",
                40,
            ),
            incoming_slot=None,
        )
    )
    assert neutral is not None
    assert neutral.kind == ResolutionKind.NO_MUTATION
    assert neutral.keep_empty_pending is True
    assert neutral.reason == "one_neutral_event_allowed"

    context.keep_empty_pending()
    rebound = empty_slot_resolver_pipeline().resolve(
        ResolverRequest(
            context=context,
            line=_line("Neck", 41),
            incoming_slot="amulet",
        )
    )
    assert rebound is not None
    assert rebound.kind == ResolutionKind.CLEAR_SLOT
    assert rebound.reason == "same_slot_rebound_after_one_neutral"


def test_empty_slot_resolver_second_neutral_and_semantic_evidence_cancel():
    context = EquipmentContext(
        pending_empty_slot="helm",
        pending_empty_neutral_count=1,
    )
    second_noise = empty_slot_resolver_pipeline().resolve(
        ResolverRequest(
            context=context,
            line=_line("another tooltip sentence", 50),
            incoming_slot=None,
        )
    )
    assert second_noise is not None
    assert second_noise.kind == ResolutionKind.NO_MUTATION
    assert second_noise.keep_empty_pending is False
    assert second_noise.reason == "second_neutral_event"

    for text in ("EQUIPPED", "Equip", "Unequip", "Rare Helm", "850 Item Power", "blank", "Left action button", "Hold"):
        semantic = empty_slot_resolver_pipeline().resolve(
            ResolverRequest(
                context=EquipmentContext(pending_empty_slot="helm"),
                line=_line(text, 51),
                incoming_slot=None,
            )
        )
        assert semantic is not None
        assert semantic.kind == ResolutionKind.NO_MUTATION
        assert semantic.keep_empty_pending is False
        assert semantic.reason == "semantic_event_before_same_slot_rebound"
