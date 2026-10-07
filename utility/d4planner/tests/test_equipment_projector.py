from __future__ import annotations

import json
from pathlib import Path

import pytest

from d4planner.character.equipment.parser import is_item_anchor, parse_item
from d4planner.character.equipment.projector import EquipmentProjector
from d4planner.character.repository import EquipmentRepository
from d4planner.runtime.diagnostics import MemoryDiagnosticsSink
from d4planner.character.service import CharacterService


FIXTURES = Path(__file__).parent / "fixtures" / "equipment"


def _consume_texts(
    projector: EquipmentProjector,
    texts: list[str],
    *,
    session: str = "s",
    start_seq: int = 1,
) -> int:
    seq = start_seq
    for text in texts:
        projector.consume(
            {
                "eventSeq": seq,
                "type": "speech.raw",
                "timestamp": f"t{seq:04}",
                "sessionId": session,
                "data": {"text": text},
            }
        )
        seq += 1
    return seq


def test_item_anchor_does_not_require_equipped():
    assert is_item_anchor("TEST HELM", "Rare Helm", "850 Item Power")


def test_equipment_semantic_diagnostics_explain_resolver_and_db_decisions(tmp_path):
    repo = EquipmentRepository(tmp_path / "character.db")
    diagnostics = MemoryDiagnosticsSink(component="equipment")
    projector = EquipmentProjector(repo, diagnostics)

    _consume_texts(
        projector,
        [
            "Head",
            "EQUIPPED",
            "CURRENT HELM",
            "Rare Helm",
            "850 Item Power",
            "Unequip",
            "Head",
        ],
    )

    events = [record["event"] for record in diagnostics.records]
    assert "anchor.detected" in events
    assert "parse.success" in events
    assert "observation.high" in events
    assert "empty.pending" in events
    assert "db.upsert" in events
    assert "empty.confirmed" in events
    assert "db.clear" in events
    assert repo.list_equipment() == []

    confirmed = next(
        record for record in diagnostics.records if record["event"] == "empty.confirmed"
    )
    assert confirmed["slot"] == "helm"
    assert confirmed["reason"] == "same_slot_immediate_rebound"
    assert confirmed["sourceSeq"] == 7


def test_equipment_diagnostics_never_change_projector_behavior(tmp_path):
    class BrokenDiagnostics:
        def emit(self, _event, **_fields):
            raise OSError("diagnostics disk unavailable")

    repo = EquipmentRepository(tmp_path / "character.db")
    projector = EquipmentProjector(repo, BrokenDiagnostics())
    _consume_texts(
        projector,
        [
            "Head",
            "EQUIPPED",
            "CURRENT HELM",
            "Rare Helm",
            "850 Item Power",
            "Unequip",
        ],
    )
    rows = repo.list_equipment()
    assert len(rows) == 1
    assert rows[0]["name"] == "CURRENT HELM"


def test_favorite_html_type_and_base_stats():
    item = parse_item(
        [
            "[FAVORITED ITEM]. ENCASED SPECTACLE&apos;S COWL",
            "Legendary Helm",
            "850 Item Power",
            "1,275 Armor",
            "+94 Intelligence +[83 - 99]",
            "Requires Level 70. Account Bound.",
        ]
    )
    assert item.name == "ENCASED SPECTACLE'S COWL"
    assert item.favorite is True
    assert item.rarity == "Legendary"
    assert item.ancestral is False
    assert item.item_type == "Helm"
    assert item.base_stats[0]["kind"] == "armor"
    assert item.base_stats[0]["value"] == 1275
    assert item.affixes[0]["value"] == 94
    assert item.affixes[0]["rollMin"] == 83


def test_real_a_weapon_quality_is_base_stat_not_affix():
    item = parse_item(
        [
            "ORACLE'S WAND OF SPLINTERING ENERGY",
            "Legendary Wand",
            "850 Item Power",
            "1,550 Damage Per Second",
            "3 ( +3/25) Quality",
            "+91 Weapon Damage [70 - 117]",
        ]
    )
    quality = [stat for stat in item.base_stats if stat["kind"] == "quality"]
    assert len(quality) == 1
    assert quality[0]["value"] == 3
    assert quality[0]["bonus"] == 3
    assert quality[0]["max"] == 25
    assert all("Quality" not in affix["raw"] for affix in item.affixes)


def test_comparison_is_not_intrinsic_affix():
    item = parse_item(
        [
            "CANDIDATE",
            "Legendary Ring",
            "850 Item Power",
            "Properties lost when equipped:",
            "+10% Attack Speed",
            "Properties gained when equipped:",
            "+20 Maximum Life",
        ]
    )
    assert item.affixes == []
    assert item.comparison["lost"] == ["+10% Attack Speed"]
    assert item.comparison["gained"] == ["+20 Maximum Life"]


def test_exact_equipped_marker_only(tmp_path):
    repo = EquipmentRepository(tmp_path / "character.db")
    projector = EquipmentProjector(repo)
    _consume_texts(
        projector,
        [
            "Head",
            "Requires Level 70. Unique Equipped.",
            "TEST",
            "Rare Helm",
            "850 Item Power",
            "Unequip",
        ],
    )
    assert repo.list_equipment() == []


def test_candidate_equip_never_updates_current(tmp_path):
    repo = EquipmentRepository(tmp_path / "character.db")
    projector = EquipmentProjector(repo)
    _consume_texts(
        projector,
        [
            "Head",
            "EQUIPPED",
            "CURRENT",
            "Rare Helm",
            "850 Item Power",
            "Unequip",
            # A non-slot event means this is browsing, not the exact
            # Unequip-action rebound signal.
            "blank",
            "Head",
            "EQUIPPED",
            "CANDIDATE",
            "Rare Helm",
            "900 Item Power",
            "Equip",
        ],
    )
    rows = repo.list_equipment()
    assert len(rows) == 1
    assert rows[0]["name"] == "CURRENT"


@pytest.mark.parametrize(
    ("slot_label", "type_line", "slot_family"),
    [
        ("Head", "Rare Helm", "helm"),
        ("Torso", "Rare Chest Armor", "chest"),
        ("Hands", "Rare Gloves", "gloves"),
        ("Legs", "Rare Pants", "pants"),
        ("Feet", "Rare Boots", "boots"),
        ("Main Hand", "Magic Sword", "main_hand"),
        ("Off-Hand", "Rare Focus", "off_hand"),
        ("Neck", "Rare Amulet", "amulet"),
    ],
)
def test_same_slot_rebound_after_unequip_clears_single_instance_slot(
    tmp_path,
    slot_label,
    type_line,
    slot_family,
):
    repo = EquipmentRepository(tmp_path / f"{slot_family}.db")
    projector = EquipmentProjector(repo)
    next_seq = _consume_texts(
        projector,
        [
            slot_label,
            "EQUIPPED",
            f"CURRENT {slot_family.upper()}",
            type_line,
            "850 Item Power",
            "Unequip",
        ],
    )

    rows = repo.list_equipment()
    assert len(rows) == 1
    assert rows[0]["slotFamily"] == slot_family

    projector.consume(
        {
            "eventSeq": next_seq,
            "type": "speech.raw",
            "timestamp": f"t{next_seq:04}",
            "sessionId": "s",
            "data": {"text": slot_label},
        }
    )

    assert repo.list_equipment() == []
    assert repo.checkpoint() == ("s", next_seq)


@pytest.mark.parametrize(
    ("slot_label", "type_line", "slot_family", "interstitial_text"),
    [
        (
            "Head",
            "Rare Helm",
            "helm",
            "Frozen enemies cannot move or attack. Enemies can be Frozen by repeatedly Chilling them.",
        ),
        ("Hands", "Rare Gloves", "gloves", "SKILLS UNAVAILABLE"),
        (
            "Feet",
            "Rare Boots",
            "boots",
            "Stealthed characters cannot be directly targeted by enemies. Using an attack or taking damage will instantly remove Stealth.",
        ),
        (
            "Neck",
            "Rare Amulet",
            "amulet",
            "Incapacitated enemies cannot perform actions due to Daze, Fear, Frozen, Knockdown or Stun.",
        ),
    ],
)
def test_real_a_one_interstitial_event_then_same_slot_clears(
    tmp_path,
    slot_label,
    type_line,
    slot_family,
    interstitial_text,
):
    repo = EquipmentRepository(tmp_path / f"{slot_family}-neutral.db")
    diagnostics = MemoryDiagnosticsSink(component="equipment")
    projector = EquipmentProjector(repo, diagnostics)

    _consume_texts(
        projector,
        [
            slot_label,
            "EQUIPPED",
            f"CURRENT {slot_family.upper()}",
            type_line,
            "850 Item Power",
            "Unequip",
            interstitial_text,
            slot_label,
        ],
    )

    assert repo.list_equipment() == []
    keep = next(
        record for record in diagnostics.records
        if record["event"] == "empty.pending_keep"
    )
    assert keep["slot"] == slot_family
    assert keep["interstitialCount"] == 1
    confirmed = next(
        record for record in diagnostics.records
        if record["event"] == "empty.confirmed"
    )
    assert confirmed["reason"] == "same_slot_rebound_after_one_interstitial"


def test_two_interstitial_events_cancel_empty_transition(tmp_path):
    repo = EquipmentRepository(tmp_path / "character.db")
    projector = EquipmentProjector(repo)

    _consume_texts(
        projector,
        [
            "Head",
            "EQUIPPED",
            "CURRENT HELM",
            "Rare Helm",
            "850 Item Power",
            "Unequip",
            "First explanatory tooltip sentence that is long enough to end here.",
            "Second explanatory tooltip sentence that is long enough to end here.",
            "Head",
        ],
    )

    rows = repo.list_equipment()
    assert len(rows) == 1
    assert rows[0]["name"] == "CURRENT HELM"


def test_semantic_event_cancels_empty_transition_before_later_same_slot(tmp_path):
    repo = EquipmentRepository(tmp_path / "character.db")
    projector = EquipmentProjector(repo)

    _consume_texts(
        projector,
        [
            "Head",
            "EQUIPPED",
            "CURRENT HELM",
            "Rare Helm",
            "850 Item Power",
            "Unequip",
            "EQUIPPED",
            "Head",
        ],
    )

    rows = repo.list_equipment()
    assert len(rows) == 1
    assert rows[0]["name"] == "CURRENT HELM"


def test_different_slot_after_unequip_does_not_clear_previous_slot(tmp_path):
    repo = EquipmentRepository(tmp_path / "character.db")
    projector = EquipmentProjector(repo)
    _consume_texts(
        projector,
        [
            "Head",
            "EQUIPPED",
            "CURRENT HELM",
            "Rare Helm",
            "850 Item Power",
            "Unequip",
            "Torso",
        ],
    )

    rows = repo.list_equipment()
    assert len(rows) == 1
    assert rows[0]["slotFamily"] == "helm"
    assert rows[0]["name"] == "CURRENT HELM"


def test_two_rings_are_distinct_without_fabricated_index(tmp_path):
    repo = EquipmentRepository(tmp_path / "character.db")
    projector = EquipmentProjector(repo)

    next_seq = _consume_texts(
        projector,
        [
            "Ring",
            "EQUIPPED",
            "RING A",
            "Unique Ring",
            "850 Item Power",
            "118 All Resist",
            "Unequip",
        ],
    )
    assert [r["name"] for r in repo.list_equipment()] == ["RING A"]

    # Ring -> Ring is ambiguous because there are two physical ring slots.
    # Never interpret this rebound as empty under the slotIndex=None contract.
    projector.consume(
        {
            "eventSeq": next_seq,
            "type": "speech.raw",
            "timestamp": f"t{next_seq:04}",
            "sessionId": "s",
            "data": {"text": "Ring"},
        }
    )
    assert [r["name"] for r in repo.list_equipment()] == ["RING A"]

    _consume_texts(
        projector,
        [
            "EQUIPPED",
            "RING B",
            "Unique Ring",
            "900 Item Power",
            "118 All Resist",
            "Unequip",
        ],
        start_seq=next_seq + 1,
    )
    rows = repo.list_equipment()
    assert [r["name"] for r in rows] == ["RING A", "RING B"]
    assert all(r["slotIndex"] is None for r in rows)


def test_golden_929_events_resolve_expected_equipment(tmp_path):
    repo = EquipmentRepository(tmp_path / "character.db")
    projector = EquipmentProjector(repo)
    events = [
        json.loads(x)
        for x in (FIXTURES / "golden_2026-10-07.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    expected = json.loads(
        (FIXTURES / "golden_2026-10-07.expected.json").read_text(encoding="utf-8")
    )
    assert len(events) == 929
    for event in events:
        projector.consume(event)

    rows = repo.list_equipment()
    want = expected["expectedEquipment"]
    assert len(rows) == 10
    got_non_ring = [
        (r["slotFamily"], r["name"], r["itemPower"])
        for r in rows
        if r["slotFamily"] != "ring"
    ]
    want_non_ring = [
        (x["slotFamily"], x["name"], x["itemPower"])
        for x in want
        if x["slotFamily"] != "ring"
    ]
    assert got_non_ring == want_non_ring
    got_rings = {
        (r["name"], r["itemPower"]) for r in rows if r["slotFamily"] == "ring"
    }
    want_rings = {
        (x["name"], x["itemPower"]) for x in want if x["slotFamily"] == "ring"
    }
    assert got_rings == want_rings
    assert all(r["slotIndex"] is None for r in rows)
    forbidden = {x["name"] for x in expected["mustNotResolveAsCurrent"]}
    assert not forbidden.intersection(r["name"] for r in rows)


def test_real_a_main_hand_unequip_fixture_materializes_empty(tmp_path):
    repo = EquipmentRepository(tmp_path / "character.db")
    projector = EquipmentProjector(repo)
    events = [
        json.loads(x)
        for x in (FIXTURES / "unequip_mainhand_real_a_2026-10-07.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    for event in events[:-1]:
        projector.consume(event)

    rows = repo.list_equipment()
    assert len(rows) == 1
    assert rows[0]["slotFamily"] == "main_hand"
    assert rows[0]["name"] == "ORACLE'S WAND OF SPLINTERING ENERGY"
    quality = next(
        stat for stat in rows[0]["baseStats"] if stat["kind"] == "quality"
    )
    assert quality["value"] == 3
    assert quality["bonus"] == 3
    assert quality["max"] == 25

    projector.consume(events[-1])

    assert repo.list_equipment() == []
    assert CharacterService(tmp_path / "character.db").equipment() == []
    assert repo.checkpoint() == (
        "efcda10d675c4bc182753be033562300",
        3652,
    )


def test_checkpoint_skips_replayed_event(tmp_path):
    repo = EquipmentRepository(tmp_path / "character.db")
    projector = EquipmentProjector(repo)
    event = {
        "eventSeq": 10,
        "type": "speech.raw",
        "timestamp": "t",
        "sessionId": "s",
        "data": {"text": "Head"},
    }
    projector.consume(event)
    assert repo.checkpoint() == ("s", 10)
    projector.consume(event)
    assert repo.checkpoint() == ("s", 10)


def test_service_reads_materialized_db_only(tmp_path):
    EquipmentRepository(tmp_path / "character.db")
    service = CharacterService(tmp_path / "character.db")
    assert service.equipment() == []
