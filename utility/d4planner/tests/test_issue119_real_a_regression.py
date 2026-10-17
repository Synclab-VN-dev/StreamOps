"""Real-A #119 regression: omitted typed anchors must survive replay."""
from __future__ import annotations
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from d4planner.character.owned_items import OwnedItemsRepository

class RealAAnchorRegression(unittest.TestCase):
    def test_types_replay_and_no_fake_ownership(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = root / "events.db"
            target = root / "character.db"
            names = ["Set Charm"]*21 + ["Rare Charm"]*4 + ["Legendary Staff"]*6 + ["Legendary Horadric Seal"]*5
            with closing(sqlite3.connect(events)) as db, db:
                db.execute("CREATE TABLE event_log(id INTEGER PRIMARY KEY, session_id TEXT, event_seq INTEGER, timestamp TEXT, type TEXT, data_json TEXT)")
                lines = ["CHARACTER"]
                for index, kind in enumerate(names):
                    lines += [f"Item {index}", kind, "850 Item Power", "Take"]
                lines += ["STASH"]
                for i, line in enumerate(lines, 1):
                    db.execute("INSERT INTO event_log VALUES(?,?,?,?,?,?)", (i,"real-a-fixture",i,"2026-10-17T10:00:00+07:00","speech.raw", json.dumps({"text": line})))
            repo = OwnedItemsRepository(target, events)
            data = repo.listing(locations={"all"}, include_unverified=True)
            self.assertEqual(data["observedTotal"], 36)
            self.assertEqual(sum(x["rarity"] == "Set" for x in data["items"]),21)
            self.assertEqual(sum(x["rarity"] == "Rare" for x in data["items"]),4)
            self.assertTrue(all(x["ownershipStatus"] == "NOT_CONFIRMED" for x in data["items"]))
            self.assertTrue(all(x["location"]["tab"] is None for x in data["items"]))
            self.assertEqual(repo.sync(),0)
            self.assertEqual(len(repo.history()),36)
if __name__ == "__main__":
    unittest.main()
