from __future__ import annotations

from d4planner.character.equipment.context import EquipmentContext, EquipmentLine
from d4planner.character.equipment.decision import ResolutionKind
from d4planner.character.equipment.resolvers import (
    ResolverRequest,
    empty_slot_resolver_pipeline,
    item_resolver_pipeline,
    ring_resolver_pipeline,
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


def test_empty_slot_resolver_allows_bounded_interstitial_burst():
    context = EquipmentContext(pending_empty_slot="gloves")
    pipeline = empty_slot_resolver_pipeline()

    first = pipeline.resolve(
        ResolverRequest(
            context=context,
            line=_line("SKILLS UNAVAILABLE", 40),
            incoming_slot=None,
        )
    )
    assert first is not None
    assert first.kind == ResolutionKind.NO_MUTATION
    assert first.keep_empty_pending is True
    assert first.reason == "interstitial_1_allowed"

    context.keep_empty_pending()
    second = pipeline.resolve(
        ResolverRequest(
            context=context,
            line=_line("Re-equip item to access Skills", 41),
            incoming_slot=None,
        )
    )
    assert second is not None
    assert second.kind == ResolutionKind.NO_MUTATION
    assert second.keep_empty_pending is True
    assert second.reason == "interstitial_2_allowed"

    context.keep_empty_pending()
    rebound = pipeline.resolve(
        ResolverRequest(
            context=context,
            line=_line("Hands", 42),
            incoming_slot="gloves",
        )
    )
    assert rebound is not None
    assert rebound.kind == ResolutionKind.CLEAR_SLOT
    assert rebound.reason == "same_slot_rebound_after_two_interstitials"


def test_empty_slot_resolver_third_interstitial_and_semantic_evidence_cancel():
    context = EquipmentContext(
        pending_empty_slot="helm",
        pending_empty_interstitial_count=2,
    )
    third = empty_slot_resolver_pipeline().resolve(
        ResolverRequest(
            context=context,
            line=_line("Another explanatory tooltip sentence that is long enough to end here.", 50),
            incoming_slot=None,
        )
    )
    assert third is not None
    assert third.kind == ResolutionKind.NO_MUTATION
    assert third.keep_empty_pending is False
    assert third.reason == "interstitial_limit_exceeded"

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
        assert semantic.reason == "semantic_or_unknown_event_before_same_slot_rebound"


def test_ring_resolver_occupied_probe_is_navigation_not_removal():
    context = EquipmentContext(
        ring_pending_fingerprint="ring-a-fp",
        ring_pending_item_name="RING A",
    )
    pipeline = ring_resolver_pipeline()

    probe = pipeline.resolve(
        ResolverRequest(
            context=context,
            line=_line("Ring", 60),
            incoming_slot="ring",
        )
    )
    assert probe is not None
    assert probe.kind == ResolutionKind.NO_MUTATION
    assert probe.open_ring_probe is True
    assert probe.reason == "ring_probe_started"

    context.open_ring_probe()
    occupied = pipeline.resolve(
        ResolverRequest(
            context=context,
            line=_line("EQUIPPED", 61),
            incoming_slot=None,
        )
    )
    assert occupied is not None
    assert occupied.kind == ResolutionKind.NO_MUTATION
    assert occupied.delete_fingerprint is None
    assert occupied.reason == "ring_probe_occupied"


def test_ring_resolver_bare_probe_deletes_only_pending_fingerprint():
    context = EquipmentContext(
        ring_pending_fingerprint="ring-a-fp",
        ring_pending_item_name="RING A",
    )
    pipeline = ring_resolver_pipeline()

    probe = pipeline.resolve(
        ResolverRequest(
            context=context,
            line=_line("Ring", 70),
            incoming_slot="ring",
        )
    )
    assert probe is not None and probe.open_ring_probe
    context.open_ring_probe()

    bare = pipeline.resolve(
        ResolverRequest(
            context=context,
            line=_line("Hands", 71),
            incoming_slot="gloves",
        )
    )
    assert bare is not None
    assert bare.kind == ResolutionKind.DELETE_ITEM
    assert bare.delete_fingerprint == "ring-a-fp"
    assert bare.reason == "bare_ring_slot_confirmed"
