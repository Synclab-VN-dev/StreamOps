"""Issue #119 unified Engine projection: transaction/restart/replay invariants.

Synthetic replay of selected real-A speech shapes. Windows/Steam/Diablo are not
used. Source events.db is never mutated by projection.
"""
from __future__ import annotations

from contextlib import closing
import json
import sqlite3

import pytest

from d4planner.character import item_current
from d4planner.character.equipment.projector import EquipmentProjector
from d4planner.character.repository import EquipmentRepository
from d4planner.character.owned_items import OwnedItemsRepository


def make_events(path, lines):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("""CREATE TABLE event_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,event_seq INTEGER,timestamp TEXT,
            type TEXT,data_json TEXT)""")
        for seq, (kind, payload) in enumerate(lines, 1):
            db.execute(
                "INSERT INTO event_log(session_id,event_seq,timestamp,type,data_json) "
                "VALUES(?,?,?,?,?)",
                ("real-a-session", seq, f"2026-10-18T21:38:{seq:02}+07:00",
                 kind, json.dumps(payload)),
            )


def speech(*values):
    return [("speech.raw", {"text": text}) for text in values]


def log_lines():
    return [
        *speech(
            "Feet", "EQUIPPED", "RUNIC CLEATS OF RALLYING REVERSAL",
            "Ancestral Legendary Boots", "900 Item Power", "Unequip",
            "Two-Handed", "EQUIPPED", "STAFF OF LAM ESEN",
            "Unique Staff", "850 Item Power", "Unequip",
        ),
        ("input.marker.raw", {"state": "down", "controlId": "START", "key": "F3"}),
        *speech("CHARACTER",
                "Right analog stick click  Sort  Bag  Right action button Close",
                "EQUIPPED", "STAFF OF LAM ESEN", "Unique Staff",
                "850 Item Power", "3,092 Damage Per Second",
                "HENRI'S PERQUISITION", "Unique Focus", "850 Item Power",
                "1,494 Damage Per Second", "Bottom action button", "Equip",
                "Top action button", "Hide Comparison",
                "Left action button", "Mark as Junk",
                "Left action button", "Hold", "Drop"),
    ]


def test_one_engine_batch_equipment_and_bag_atomic_snapshot(tmp_path):
    character = tmp_path / "character.db"
    events = tmp_path / "events.db"
    lines = log_lines()
    make_events(events, lines)
    projector = EquipmentProjector(EquipmentRepository(character))
    resolver = OwnedItemsRepository(character, events)
    assert resolver.sync(session_id="real-a-session",
                         equipment_projector=projector) == len(lines)
    snap = item_current.snapshot(character)
    assert {(x["name"], x["location"]["type"],
             x["location"]["slot"]) for x in snap["items"]} == {
        ("RUNIC CLEATS OF RALLYING REVERSAL", "equipment", "boots"),
        ("STAFF OF LAM ESEN", "equipment", "main_hand"),
        ("HENRI'S PERQUISITION", "inventory", None),
    }
    with closing(sqlite3.connect(character)) as db:
        row = db.execute(
            "SELECT last_event_rowid FROM item_projection_state WHERE id=1"
        ).fetchone()
        assert row[0] == len(lines)
        row = db.execute(
            "SELECT last_event_rowid FROM owned_item_checkpoint WHERE id=1"
        ).fetchone()
        assert row[0] == len(lines)
        row = db.execute(
            "SELECT last_event_seq FROM projector_checkpoint WHERE consumer='equipment-v1'"
        ).fetchone()
        assert row[0] == len(lines)
    original_revision = snap["revision"]
    assert resolver.sync(session_id="real-a-session",
                         equipment_projector=projector) == 0
    assert item_current.snapshot(character)["revision"] == original_revision


def test_failure_rolls_back_both_current_and_cursors_then_replays(tmp_path):
    character = tmp_path / "character.db"
    events = tmp_path / "events.db"
    lines = log_lines()
    make_events(events, lines)

    class FailOnce(EquipmentProjector):
        def __init__(self, repository):
            super().__init__(repository)
            self.armed = True

        def consume(self, event, *, connection=None):
            super().consume(event, connection=connection)
            # Fail AFTER Equipment and Bag have written within the same batch.
            if event["eventSeq"] == 11 and self.armed:
                self.armed = False
                raise RuntimeError("injected projection failure")

    projector = FailOnce(EquipmentRepository(character))
    resolver = OwnedItemsRepository(character, events)
    with pytest.raises(RuntimeError, match="injected projection failure"):
        resolver.sync(session_id="real-a-session",
                      equipment_projector=projector)
    assert item_current.snapshot(character)["items"] == []
    with closing(sqlite3.connect(character)) as db:
        assert db.execute(
            "SELECT count(*) FROM owned_item_checkpoint"
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT count(*) FROM projector_checkpoint"
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT count(*) FROM owned_item_observation"
        ).fetchone()[0] == 0

    # Context + source cursor were rewound and can replay cleanly.
    assert resolver.sync(session_id="real-a-session",
                         equipment_projector=projector) == len(lines)
    assert len(item_current.snapshot(character)["items"]) == 3


def test_dev_v3_old_projection_refused_without_wiping_it(tmp_path):
    path = tmp_path / "character.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.row_factory = sqlite3.Row
        item_current.schema(db)
        db.execute("UPDATE item_projection_state SET projection_version=2")
    with closing(sqlite3.connect(path)) as db, db:
        db.row_factory = sqlite3.Row
        with pytest.raises(RuntimeError, match="isolated clean PR120 HomeDir"):
            item_current.schema(db)
        assert db.execute(
            "SELECT projection_version FROM item_projection_state"
        ).fetchone()[0] == 2
