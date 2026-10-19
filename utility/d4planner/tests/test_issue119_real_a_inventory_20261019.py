"""Real-A Oct 19 21:01: derived NVDA regression (owner's 14 physical items).

The log was copied from D4Planner live speech, not an exported canonical DB.
Nine equipped items, five inventory items; four bag items have just ONE item
anchor after EQUIPPED. The selected item's Equip/Unmark/Drop actions prove
Bag selection within START + CHARACTER + Sort Bag; this is not a comparison.
"""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3

from d4planner.character.item_current import snapshot
from d4planner.character.owned_items import OwnedItemsRepository
from d4planner.character.repository import EquipmentRepository
from d4planner.character.equipment.projector import EquipmentProjector


EQUIPPED = (
    ("Two-Handed", "STAFF OF LAM ESEN", "Unique Staff", 850, "main_hand"),
    ("Feet", "RUNIC CLEATS OF RALLYING REVERSAL", "Ancestral Legendary Boots", 900, "boots"),
    ("Legs", "MAGE-LORD'S RUNIC LEGGINGS", "Ancestral Legendary Pants", 900, "pants"),
    ("Hands", "SOVEREIGN VAMBRACES OF OVERWHELMING CURRENTS",
     "Ancestral Legendary Gloves", 900, "gloves"),
    ("Torso", "RAIMENT OF THE INFINITE", "Unique Chest Armor", 850, "chest"),
    ("Head", "SNOWVEILED SPECTACLE'S COWL", "Legendary Helm", 850, "helm"),
    ("Neck", "FEROCIOUS VULGAR CHAIN", "Ancestral Legendary Amulet", 900, "amulet"),
    ("Ring", "STORM SPLITTER'S ADORNED-IN-BLOOD", "Ancestral Legendary Ring", 900, "ring"),
    ("Ring", "CIRCLE OF ELEMENTAL ATTUNEMENT", "Ancestral Legendary Ring", 900, "ring"),
)

BAG = (
    ("MAGE-LORD'S SPECTACLE'S COWL", "Ancestral Legendary Helm", 900),
    ("HENRI'S PERQUISITION", "Unique Focus", 850),
    ("FRACTURED WINTERGLASS", "Unique Amulet", 850),
    ("ORACLE'S WAND OF SPLINTERING ENERGY", "Legendary Wand", 850),
    ("FEROCIOUS OCELOT'S EYE", "Legendary Amulet", 850),
)


def _write_events(db_path: Path, sequence: list[tuple[str, str | dict]]) -> None:
    with closing(sqlite3.connect(db_path)) as db, db:
        db.execute("""CREATE TABLE event_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,event_seq INTEGER NOT NULL,
            timestamp TEXT NOT NULL,type TEXT NOT NULL,data_json TEXT NOT NULL)""")
        for seq, (kind, payload) in enumerate(sequence, 1):
            data = {"text": payload} if kind == "speech.raw" else payload
            db.execute(
                "INSERT INTO event_log(session_id,event_seq,timestamp,type,data_json) "
                "VALUES(?,?,?,?,?)",
                ("real-a-20261019-2101", seq, "2026-10-19T21:01:06+07:00",
                 kind, json.dumps(data, ensure_ascii=False)),
            )


def _real_a_sequence():
    events: list[tuple[str, str | dict]] = [
        ("input.marker.raw", {"state": "down", "key": "F3", "controlId": "START"}),
        ("speech.raw", "CHARACTER"),
        ("speech.raw", "Right analog stick click\u00a0Sort\u00a0Bag      Right action button\u00a0Close"),
        # Real-A Mage-Lord's cowl: comparison equipped Helm then Bag selection.
        *[("speech.raw", s) for s in (
            "EQUIPPED", "SNOWVEILED SPECTACLE'S COWL", "Legendary Helm",
            "850 Item Power", "1,275 Armor",
        )],
    ]
    def selected(name, kind, power):
        return [
            ("speech.raw", "[FAVORITED ITEM]. " + name),
            ("speech.raw", kind), ("speech.raw", f"{power} Item Power"),
            ("speech.raw", "1,275 Armor"),
            ("speech.raw", "Bottom action button"), ("speech.raw", "Equip"),
            ("speech.raw", "Top action button"),
            ("speech.raw", "Hide\u00a0Comparison"),
            ("speech.raw", "Left action button"),
            ("speech.raw", "Unmark\u00a0Item"),
            ("speech.raw", "Left action button"),
            ("speech.raw", "Hold"), ("speech.raw", "Drop"),
        ]
    events.extend(selected(*BAG[0]))
    # These FOUR Real-A single-anchors have EQUIPPED prefix but contain
    # selected-Bag actions and no separate second item anchor.
    for entry in BAG[1:]:
        events.append(("input.marker.raw", {"state": "down", "controlId": "DPAD_RIGHT"}))
        events.append(("speech.raw", "EQUIPPED"))
        events.extend(selected(*entry))
    # A separate Equipment visit contains physical slot + Unequip evidence.
    for label, name, kind, power, _slot in EQUIPPED:
        events.extend(("speech.raw", text) for text in (
            label, "EQUIPPED", name, kind, f"{power} Item Power", "Unequip",
        ))
    return events


def test_real_a_14_distinct_items_combined_engine_pipeline(tmp_path):
    events = tmp_path / "events.db"
    character = tmp_path / "character.db"
    sequence = _real_a_sequence()
    _write_events(events, sequence)
    reader = OwnedItemsRepository(character, events)
    projector = EquipmentProjector(EquipmentRepository(character))
    assert reader.sync(session_id="real-a-20261019-2101",
                       equipment_projector=projector) == len(sequence)
    snap = snapshot(character)
    actual = {(i["name"], i["location"]["type"],
               i["location"]["slot"]) for i in snap["items"]}
    expected = {(name, "inventory", None) for name, _, _ in BAG}
    expected.update((name, "equipment", slot)
                    for _, name, _, _, slot in EQUIPPED)
    assert actual == expected
    assert snap["observedTotal"] == 14
    assert all(i["ownershipStatus"] == "CONFIRMED" for i in snap["items"])
    assert reader.sync(session_id="real-a-20261019-2101",
                       equipment_projector=projector) == 0
    assert snapshot(character)["observedTotal"] == 14


def test_single_anchor_after_equipped_without_actions_is_not_inventory(tmp_path):
    events = tmp_path / "events.db"
    character = tmp_path / "character.db"
    seq = _real_a_sequence()[:3] + [
        ("speech.raw", "EQUIPPED"),
        ("speech.raw", "FRACTURED WINTERGLASS"),
        ("speech.raw", "Unique Amulet"),
        ("speech.raw", "850 Item Power"),
        ("speech.raw", "Hide Comparison"),
        ("speech.raw", "CHARACTER"),
    ]
    _write_events(events, seq)
    repo = OwnedItemsRepository(character, events)
    repo.sync(session_id="real-a-20261019-2101")
    assert not snapshot(character)["items"]


def test_single_anchor_after_equipped_without_start_bag_is_not_inventory(tmp_path):
    events = tmp_path / "events.db"
    character = tmp_path / "character.db"
    seq = [("speech.raw", "CHARACTER"),
           ("speech.raw", "EQUIPPED")] + [
               ("speech.raw", x) for x in (
                   "HENRI'S PERQUISITION", "Unique Focus", "850 Item Power",
                   "Equip", "Unmark Item", "Drop")]
    _write_events(events, seq)
    repo = OwnedItemsRepository(character, events)
    repo.sync(session_id="real-a-20261019-2101")
    assert not snapshot(character)["items"]
