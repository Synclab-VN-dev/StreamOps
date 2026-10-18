"""#119 SOLID v2 regression: real-A 21:38 Feet -> Two-Handed + comparison.

Reduced from the owner's October 18 NVDA timeline; not a complete
canonical events.db export. These *independent* expectations must fail against
the 43cb996 baseline before fixing the implementation.
"""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3

from d4planner.character.equipment.projector import EquipmentProjector
from d4planner.character.repository import EquipmentRepository
from d4planner.character.owned_items import OwnedItemsRepository
from d4planner.character.item_current import snapshot


def equipment_speech(projector, lines, session="real-a-2138"):
    for seq, value in enumerate(lines, 1):
        projector.consume({
            "eventSeq": seq, "sessionId": session,
            "timestamp": f"2026-10-18T21:38:{seq % 60:02}+07:00",
            "type": "speech.raw", "data": {"text": value},
        })


def owned_events(path: Path, lines, session="real-a-2138"):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("""CREATE TABLE event_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,event_seq INTEGER NOT NULL,
            timestamp TEXT NOT NULL,type TEXT NOT NULL,data_json TEXT NOT NULL)""")
        events = [
            ("input.marker.raw", {"state": "down", "controlId": "START", "key": "F3"}),
            ("speech.raw", {"text": "CHARACTER"}),
            ("speech.raw", {"text": "Right analog stick click  Sort  Bag  Right action button Close"}),
        ] + [("speech.raw", {"text": x}) for x in lines]
        for seq, (kind, payload) in enumerate(events, 1):
            db.execute(
                "INSERT INTO event_log(session_id,event_seq,timestamp,type,data_json) "
                "VALUES(?,?,?,?,?)",
                (session, seq, f"2026-10-18T21:38:{seq % 60:02}+07:00",
                 kind, json.dumps(payload)),
            )


def comparison_pair():
    return [
        "EQUIPPED", "STAFF OF LAM ESEN", "Unique Staff", "850 Item Power",
        "3,092 Damage Per Second",
        "HENRI'S PERQUISITION", "Unique Focus", "850 Item Power",
        "1,494 Damage Per Second",
        "Bottom action button", "Equip",
        "Top action button", "Hide Comparison",
        "Left action button", "Mark as Junk",
        "Left action button", "Hold", "Drop",
    ]


def test_real_a_equipment_slot_transition_feet_to_two_handed(tmp_path):
    repo = EquipmentRepository(tmp_path / "character.db")
    projector = EquipmentProjector(repo)
    equipment_speech(projector, [
        "Feet", "EQUIPPED", "RUNIC CLEATS OF RALLYING REVERSAL",
        "Ancestral Legendary Boots", "900 Item Power", "Unequip",
        "Two-Handed", "EQUIPPED", "STAFF OF LAM ESEN",
        "Unique Staff", "850 Item Power", "Unequip",
    ])
    records = {r["slotFamily"]: r["name"] for r in repo.list_equipment()}
    assert records["boots"] == "RUNIC CLEATS OF RALLYING REVERSAL"
    assert records["main_hand"] == "STAFF OF LAM ESEN"
    assert len(records) == 2


def test_real_a_unknown_slot_cannot_reuse_feet_for_staff(tmp_path):
    repo = EquipmentRepository(tmp_path / "character.db")
    projector = EquipmentProjector(repo)
    equipment_speech(projector, [
        "Feet", "EQUIPPED", "RUNIC CLEATS OF RALLYING REVERSAL",
        "Ancestral Legendary Boots", "900 Item Power", "Unequip",
        "Unknown Slot Panel", "EQUIPPED", "STAFF OF LAM ESEN",
        "Unique Staff", "850 Item Power", "Unequip",
    ])
    records = {r["slotFamily"]: r["name"] for r in repo.list_equipment()}
    assert records["boots"] == "RUNIC CLEATS OF RALLYING REVERSAL"
    assert len(records) == 1  # no invented current from unrecognized slot


def test_comparison_before_equipment_scan_never_creates_physical_duplicate(tmp_path):
    character = tmp_path / "character.db"
    events = tmp_path / "events.db"
    owned_events(events, comparison_pair() + comparison_pair())
    repository = OwnedItemsRepository(character, events)
    assert repository.sync(session_id="real-a-2138") > 0
    snap = snapshot(character)
    assert [x["name"] for x in snap["items"]] == ["HENRI'S PERQUISITION"]
    # The comparison is retained in the evidence/audit projection instead.
    with closing(sqlite3.connect(character)) as db:
        n = db.execute(
            "SELECT count(*) FROM owned_item_observation WHERE item_name='STAFF OF LAM ESEN'"
        ).fetchone()[0]
    assert n >= 1
    equipment_speech(
        EquipmentProjector(EquipmentRepository(character)),
        ["Two-Handed", "EQUIPPED", "STAFF OF LAM ESEN",
         "Unique Staff", "850 Item Power", "Unequip"],
    )
    current = snapshot(character)["items"]
    assert len(current) == 2
    assert {(x["name"], x["location"]["type"]) for x in current} == {
        ("STAFF OF LAM ESEN", "equipment"),
        ("HENRI'S PERQUISITION", "inventory"),
    }
    assert not any(x["id"].startswith("eq-hint:") for x in current)


def test_replay_is_idempotent_without_physical_candidate_rows(tmp_path):
    character = tmp_path / "character.db"
    events = tmp_path / "events.db"
    owned_events(events, comparison_pair() + comparison_pair())
    repository = OwnedItemsRepository(character, events)
    repository.sync(session_id="real-a-2138")
    before = snapshot(character)
    assert repository.sync(session_id="real-a-2138") == 0
    after = snapshot(character)
    assert before["revision"] == after["revision"]
    assert before["items"] == after["items"]
    assert [x["name"] for x in after["items"]] == ["HENRI'S PERQUISITION"]
