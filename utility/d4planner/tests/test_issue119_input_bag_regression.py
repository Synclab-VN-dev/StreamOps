"""Issue #119 Real-A marker+NVDA bag/compare acceptance regression.

Reduced, deterministic golden sequence from the owner's 2026-10-18 log.
No interaction with Steam, Diablo IV, NVDA or production databases.
"""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from d4planner.character.owned_items import OwnedItemsRepository
from d4planner.character.item_current import snapshot


class InputBagOwnershipTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.events = base / "events.db"
        self.character = base / "character.db"
        self.seq = 0
        with closing(sqlite3.connect(self.events)) as db, db:
            db.execute("""CREATE TABLE event_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                event_seq INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                type TEXT NOT NULL,
                data_json TEXT NOT NULL)""")

    def event(self, kind, data):
        self.seq += 1
        with closing(sqlite3.connect(self.events)) as db, db:
            db.execute(
                "INSERT INTO event_log(session_id,event_seq,timestamp,type,data_json) "
                "VALUES(?,?,?,?,?)",
                ("real-a-20261018", self.seq, "2026-10-18T12:39:23+07:00",
                 kind, json.dumps(data, ensure_ascii=False)),
            )

    def speech(self, *lines):
        for line in lines:
            self.event("speech.raw", {"text": line})

    def start(self):
        self.event("input.marker.raw", {
            "source": "steamInput", "device": "keyboard", "key": "F3",
            "virtualKey": 114, "state": "down", "controlId": "START",
            "process": "Diablo IV", "processId": 123,
            "contextSource": "rawInput", "windowTitle": "Diablo IV",
        })
        self.event("input.marker.raw", {
            "source": "steamInput", "device": "keyboard", "key": "F3",
            "virtualKey": 114, "state": "up", "controlId": "START",
            "process": "Diablo IV", "processId": 123,
            "contextSource": "rawInput", "windowTitle": "Diablo IV",
        })

    def header(self):
        self.speech(
            "NAAK", "No Title Selected", "Weapon Damage", "3,092",
            "Equipment", "CHARACTER", "Left shoulder button",
            "Right shoulder button", "CHARACTER",
            "Right analog stick click  Sort  Bag  Right action button Close",
        )

    def pair(self, *, actions=True):
        self.speech(
            "EQUIPPED", "[FAVORITED ITEM]. FEROCIOUS OCELOT'S EYE",
            "Legendary Amulet", "850 Item Power",
            "173 All Resist", "+141 Intelligence +[125 - 149]",
            "OCELOT'S EYE OF NEBULOUS BREWS", "Legendary Amulet",
            "850 Item Power", "157 All Resist (-1.5% Toughness)",
            "+128 Intelligence +[125 - 149] (-13)",
            "Properties lost when equipped:", "13.2% Cooldown Reduction",
            "Legendary Power",
        )
        if actions:
            self.speech(
                "Bottom action button", "Equip",
                "Top action button", "Hide Comparison",
                "Left action button", "Mark as Junk",
                "Left action button", "Hold", "Drop",
            )

    def repo(self):
        return OwnedItemsRepository(self.character, self.events)

    def test_real_a_pair_two_repeated_readings_inventory_only_selected(self):
        self.start()
        self.header()
        self.pair()
        self.pair()  # no second START: NVDA repeated the pair ~6 seconds later
        repo = self.repo()
        inventory = repo.listing(locations={"inventory"})
        self.assertEqual(inventory["observedTotal"], 1)
        self.assertEqual(inventory["coverage"]["inventory"], "PARTIAL")
        selected = inventory["items"][0]
        self.assertEqual(selected["name"], "OCELOT'S EYE OF NEBULOUS BREWS")
        self.assertEqual(selected["itemPower"], 850)
        self.assertEqual(selected["ownershipStatus"], "CONFIRMED")
        self.assertEqual(selected["ownershipEvidence"], "character-bag-actions-v1")
        self.assertEqual(selected["observationCount"], 2)
        self.assertIsNone(selected["location"]["slot"])
        self.assertIsNone(selected["pickedUpAt"])
        equipped = repo.listing(
            locations={"equipment"}, include_unverified=True)["items"]
        self.assertEqual(len(equipped), 1)
        self.assertEqual(equipped[0]["name"], "FEROCIOUS OCELOT'S EYE")
        self.assertEqual(equipped[0]["ownershipEvidence"], "equipped-marker-v1")
        self.assertEqual(len(repo.history()), 4)
        self.assertEqual(repo.sync(), 0)

    def test_no_input_is_not_sufficient_to_confirm_inventory(self):
        self.header()
        self.pair()
        repo = self.repo()
        self.assertEqual(repo.listing(locations={"inventory"})["items"], [])
        candidates = repo.listing(
            locations={"inventory"}, include_unverified=True)["items"]
        self.assertEqual(candidates[0]["ownershipStatus"], "NOT_CONFIRMED")

    def test_no_bag_hint_is_not_sufficient_to_confirm_inventory(self):
        self.start()
        self.speech("CHARACTER", "Equipment")
        self.pair()
        repo = self.repo()
        self.assertEqual(repo.listing(locations={"inventory"})["items"], [])
        self.assertTrue(all(x["ownershipStatus"] == "NOT_CONFIRMED"
                            for x in repo.listing(
                                locations={"inventory"},
                                include_unverified=True)["items"]))

    def test_without_selected_actions_remains_unconfirmed(self):
        self.start()
        self.header()
        self.pair(actions=False)
        self.speech("CHARACTER")  # flush incomplete candidate
        repo = self.repo()
        self.assertEqual(repo.listing(locations={"inventory"})["items"], [])
        candidates = repo.listing(
            locations={"inventory"}, include_unverified=True)["items"]
        self.assertEqual(candidates[0]["ownershipStatus"], "NOT_CONFIRMED")

    def test_equipped_prefix_cannot_leak_to_subsequent_item(self):
        self.start()
        self.header()
        self.speech(
            "EQUIPPED", "A", "Legendary Ring", "850 Item Power",
            "B", "Legendary Amulet", "850 Item Power",
            "Equip", "Mark as Junk", "Drop",
        )
        repo = self.repo()
        bag = repo.listing(locations={"inventory"})["items"]
        self.assertEqual(len(bag), 1)
        self.assertEqual(bag[0]["name"], "B")
        equipment = repo.listing(
            locations={"equipment"}, include_unverified=True)["items"]
        self.assertEqual(len(equipment), 1)
        self.assertEqual(equipment[0]["name"], "A")


    def test_real_a_1900_favorite_toggle_materializes_two_current_bag_items(self):
        """Regression: actual 19:00 owner speech uses Unmark Item, not Mark as Junk."""
        self.start()
        self.speech(
            "NAAK", "Weapon Damage", "3,092", "Equipment", "CHARACTER",
            "CHARACTER { throw \"SWITCH FAILED\" }",
            "CHARACTER", "Right analog stick click\u00a0Sort\u00a0Bag      Right action button\u00a0Close",
        )
        def amulet():
            self.speech(
                "EQUIPPED", "FRACTURED WINTERGLASS", "Unique Amulet",
                "850 Item Power", "157 All Resist",
                "+142 Intelligence +[125 - 149]",
                "[FAVORITED ITEM]. FEROCIOUS OCELOT&apos;S EYE",
                "Legendary Amulet", "850 Item Power",
                "10 ( +10/25) Quality", "173 All Resist",
                "+141 Intelligence +[125 - 149]",
                "Imprinted: Your Maximum Ferocity stacks are increased by 8 [6 - 9].",
                "Bottom action button", "Equip",
                "Top action button", "Hide\u00a0Comparison",
                "Left action button", "Unmark\u00a0Item",
                "Left action button", "Hold", "Drop",
            )
        amulet()
        amulet()  # two reads must not create two physical item rows
        self.speech(
            "EQUIPPED", "[FAVORITED ITEM]. STAFF OF LAM ESEN",
            "Unique Staff", "850 Item Power",
            "3,092 Damage Per Second",
            "[FAVORITED ITEM]. ORACLE&apos;S WAND OF SPLINTERING ENERGY",
            "Legendary Wand", "850 Item Power",
            "1,550 Damage Per Second",
            "+137 Intelligence +[125 - 149]",
            "Bottom action button", "Equip",
            "Top action button", "Hide\u00a0Comparison",
            "Left action button", "Unmark\u00a0Item",
            "Left action button", "Hold", "Drop",
        )
        repo = self.repo()
        self.assertEqual(repo.sync(session_id="real-a-20261018"), self.seq)
        db_snapshot = snapshot(self.character, locations={"inventory"})
        self.assertEqual(db_snapshot["observedTotal"], 2)
        self.assertEqual({item["name"] for item in db_snapshot["items"]}, {
            "FEROCIOUS OCELOT'S EYE",
            "ORACLE'S WAND OF SPLINTERING ENERGY",
        })
        self.assertGreater(db_snapshot["revision"], 0)
        self.assertIsNotNone(db_snapshot["lastCommittedAt"])
        self.assertTrue(all(
            item["ownershipStatus"] == "CONFIRMED" and
            item["ownershipEvidence"] == "character-bag-actions-v1"
            for item in db_snapshot["items"]
        ))
        # Distinct EQUIPPED comparison items must not become inventory.
        self.assertFalse(any(item["name"] in {
            "FRACTURED WINTERGLASS", "STAFF OF LAM ESEN"
        } for item in db_snapshot["items"]))
        old_revision = db_snapshot["revision"]
        self.assertEqual(repo.sync(session_id="real-a-20261018"), 0)
        self.assertEqual(snapshot(self.character)["revision"], old_revision)

    def test_favorite_item_without_action_toggle_is_not_confirmed(self):
        self.start()
        self.header()
        self.speech(
            "EQUIPPED", "OLD AMULET", "Unique Amulet", "850 Item Power",
            "[FAVORITED ITEM]. NEW AMULET", "Legendary Amulet",
            "850 Item Power", "Equip", "Hide Comparison", "Drop",
        )
        self.repo().sync(session_id="real-a-20261018")
        self.assertEqual(snapshot(self.character, locations={"inventory"})["items"], [])


if __name__ == "__main__":
    unittest.main()
