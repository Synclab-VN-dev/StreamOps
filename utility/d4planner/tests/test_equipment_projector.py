from __future__ import annotations

import json
from pathlib import Path

from d4planner.character.equipment.parser import is_item_anchor, normalize, parse_item
from d4planner.character.equipment.projector import EquipmentProjector
from d4planner.character.repository import EquipmentRepository
from d4planner.character.service import CharacterService


FIXTURES = Path(__file__).parent / "fixtures" / "equipment"


def test_item_anchor_does_not_require_equipped():
    assert is_item_anchor("TEST HELM", "Rare Helm", "850 Item Power")


def test_favorite_html_type_and_base_stats():
    item = parse_item([
        "[FAVORITED ITEM]. ENCASED SPECTACLE&apos;S COWL",
        "Legendary Helm",
        "850 Item Power",
        "1,275 Armor",
        "+94 Intelligence +[83 - 99]",
        "Requires Level 70. Account Bound.",
    ])
    assert item.name == "ENCASED SPECTACLE'S COWL"
    assert item.favorite is True
    assert item.rarity == "Legendary"
    assert item.ancestral is False
    assert item.item_type == "Helm"
    assert item.base_stats[0]["kind"] == "armor"
    assert item.base_stats[0]["value"] == 1275
    assert item.affixes[0]["value"] == 94
    assert item.affixes[0]["rollMin"] == 83


def test_comparison_is_not_intrinsic_affix():
    item = parse_item([
        "CANDIDATE", "Legendary Ring", "850 Item Power",
        "Properties lost when equipped:", "+10% Attack Speed",
        "Properties gained when equipped:", "+20 Maximum Life",
    ])
    assert item.affixes == []
    assert item.comparison["lost"] == ["+10% Attack Speed"]
    assert item.comparison["gained"] == ["+20 Maximum Life"]


def test_exact_equipped_marker_only(tmp_path):
    repo = EquipmentRepository(tmp_path / "character.db")
    p = EquipmentProjector(repo)
    texts = ["Head", "Requires Level 70. Unique Equipped.", "TEST", "Rare Helm", "850 Item Power", "Unequip"]
    for seq, text in enumerate(texts, 1):
        p.consume({"eventSeq": seq, "type": "speech.raw", "timestamp": f"t{seq}", "sessionId": "s", "data": {"text": text}})
    assert repo.list_equipment() == []


def test_candidate_equip_never_updates_current(tmp_path):
    repo = EquipmentRepository(tmp_path / "character.db")
    p = EquipmentProjector(repo)
    texts = ["Head", "EQUIPPED", "CURRENT", "Rare Helm", "850 Item Power", "Unequip",
             "Head", "EQUIPPED", "CANDIDATE", "Rare Helm", "900 Item Power", "Equip"]
    for seq, text in enumerate(texts, 1):
        p.consume({"eventSeq": seq, "type": "speech.raw", "timestamp": f"t{seq:02}", "sessionId": "s", "data": {"text": text}})
    rows = repo.list_equipment()
    assert len(rows) == 1
    assert rows[0]["name"] == "CURRENT"


def test_two_rings_are_distinct_without_fabricated_index(tmp_path):
    repo = EquipmentRepository(tmp_path / "character.db")
    p = EquipmentProjector(repo)
    seq = 0
    for name, power in [("RING A", 850), ("RING B", 900)]:
        for text in ["Ring", "EQUIPPED", name, "Unique Ring", f"{power} Item Power", "118 All Resist", "Unequip"]:
            seq += 1
            p.consume({"eventSeq": seq, "type": "speech.raw", "timestamp": f"t{seq:02}", "sessionId": "s", "data": {"text": text}})
    rows = repo.list_equipment()
    assert [r["name"] for r in rows] == ["RING A", "RING B"]
    assert all(r["slotIndex"] is None for r in rows)


def test_golden_929_events_resolve_expected_equipment(tmp_path):
    repo = EquipmentRepository(tmp_path / "character.db")
    projector = EquipmentProjector(repo)
    events = [json.loads(x) for x in (FIXTURES / "golden_2026-10-07.jsonl").read_text(encoding="utf-8").splitlines()]
    expected = json.loads((FIXTURES / "golden_2026-10-07.expected.json").read_text(encoding="utf-8"))
    assert len(events) == 929
    for event in events:
        projector.consume(event)
    rows = repo.list_equipment()
    want = expected["expectedEquipment"]
    assert len(rows) == 10
    assert [(r["slotFamily"], r["name"], r["itemPower"]) for r in rows] == [
        (x["slotFamily"], x["name"], x["itemPower"]) for x in want
    ]
    assert all(r["slotIndex"] is None for r in rows)
    forbidden = {x["name"] for x in expected["mustNotResolveAsCurrent"]}
    assert not forbidden.intersection(r["name"] for r in rows)


def test_checkpoint_skips_replayed_event(tmp_path):
    repo = EquipmentRepository(tmp_path / "character.db")
    p = EquipmentProjector(repo)
    event={"eventSeq": 10, "type": "speech.raw", "timestamp": "t", "sessionId": "s", "data": {"text": "Head"}}
    p.consume(event)
    assert repo.checkpoint() == ("s", 10)
    p.consume(event)
    assert repo.checkpoint() == ("s", 10)


def test_service_reads_materialized_db_only(tmp_path):
    repo = EquipmentRepository(tmp_path / "character.db")
    service = CharacterService(tmp_path / "character.db")
    assert service.equipment() == []
