"""Domain-level SOLID contract tests; no sqlite, game or NVDA dependencies."""
from __future__ import annotations

from dataclasses import replace

import pytest

from d4planner.character.current_reducer import CurrentItemIntent, CurrentItemReducer
from d4planner.character.equipment.slot_policy import (
    DEFAULT_SLOT_TYPES, KnownTypes, SlotTypePolicy,
)


class FakePort:
    def __init__(self):
        self.items = {}
        self.operations = []

    def upsert(self, intent):
        before = self.items.get(intent.key)
        after = dict(intent.payload)
        self.operations.append(("upsert", intent.key))
        self.items[intent.key] = after
        return before != after

    def invalidate_slot(self, slot, except_key, intent):
        self.operations.append(("invalidate_slot", slot))
        for key, item in self.items.items():
            if key != except_key and (item.get("location") or {}).get("slot") == slot:
                item["location"] = {"type": "unknown", "slot": None, "tab": None}

    def limit_ring_positions(self, intent):
        self.operations.append(("limit_ring_positions",))


def intent(source="bag-selected", name="BAG ITEM", key="physical-1",
           slot=None, status="CONFIRMED", evidence="character-bag-actions-v1",
           scope=None, confidence="HIGH"):
    where = "equipment" if source == "equipped-slot" else "inventory"
    if source == "verified-grid":
        where = "stash"
    return CurrentItemIntent(
        source=source, key=key, fingerprint=name,
        payload={"name": name,
                 "location": {"type": where, "slot": slot, "tab": None},
                 "ownershipStatus": status,
                 "ownershipEvidence": evidence,
                 "observationConfidence": confidence},
        scope=scope,
    )


@pytest.mark.parametrize("source", ["bag-selected", "equipped-slot", "verified-grid"])
def test_all_sources_reject_unconfirmed_without_storage_side_effects(source):
    port = FakePort()
    proposal = intent(source=source, slot="main_hand", scope="character-a",
                      status="NOT_CONFIRMED")
    assert CurrentItemReducer(port).apply(proposal) is False
    assert port.operations == []


def test_selected_bag_requires_strong_source_specific_evidence():
    port = FakePort()
    reducer = CurrentItemReducer(port)
    unproven = intent(evidence="equipped-marker-v1")
    assert not reducer.apply(unproven)
    assert not port.items
    assert reducer.apply(intent())
    assert list(port.items) == ["physical-1"]


def test_equipment_single_slot_replaced_only_via_verified_intent():
    port = FakePort()
    reducer = CurrentItemReducer(port)
    assert reducer.apply(intent(source="equipped-slot", name="BOOTS", key="a",
                                slot="boots"))
    assert reducer.apply(intent(source="equipped-slot", name="NEW BOOTS", key="b",
                                slot="boots"))
    assert port.items["a"]["location"]["type"] == "unknown"
    assert port.items["b"]["location"]["type"] == "equipment"


def test_ring_position_keeps_two_distinct_identified_items():
    port = FakePort()
    reducer = CurrentItemReducer(port)
    assert reducer.apply(intent(source="equipped-slot", name="RING A", key="a", slot="ring"))
    assert reducer.apply(intent(source="equipped-slot", name="RING B", key="b", slot="ring"))
    assert len(port.items) == 2
    assert ("invalidate_slot", "ring") not in port.operations
    assert ("limit_ring_positions",) in port.operations


def test_grid_writes_require_scoped_high_evidence():
    port = FakePort()
    reducer = CurrentItemReducer(port)
    assert not reducer.apply(intent(source="verified-grid", name="A"))
    assert not reducer.apply(intent(source="verified-grid", name="A",
                                    scope="character-1", confidence="LOW"))
    assert reducer.apply(intent(source="verified-grid", name="A", scope="character-1"))


def test_slot_type_rules_are_extensible_without_editing_projector():
    assert DEFAULT_SLOT_TYPES.allows("main_hand", "Staff")
    assert DEFAULT_SLOT_TYPES.allows("boots", "Boots")
    assert not DEFAULT_SLOT_TYPES.allows("boots", "Staff")
    assert not DEFAULT_SLOT_TYPES.allows("helm", "Staff")
    extended = SlotTypePolicy((KnownTypes("off_hand", frozenset({"Orb"})),))
    assert extended.allows("off_hand", "Orb")
    assert not extended.allows("boots", "Orb")
    assert not extended.allows("off_hand", "Staff")
