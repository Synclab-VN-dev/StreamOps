"""Issue #119: conservative owned-item projection + CLI acceptance gates.

Synthetic, source-informed fixtures; REAL-A ownership requires separate proof.
"""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from d4planner.character.owned_items import OwnedItemsRepository
from d4planner.cli import main


class OwnedItemsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        (self.home / "state").mkdir()
        self.event_db = self.home / "state/events.db"
        self.char_db = self.home / "state/character.db"
        with sqlite3.connect(self.event_db) as db:
            db.execute("""CREATE TABLE event_log(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL, event_seq INTEGER NOT NULL,
                timestamp TEXT NOT NULL, type TEXT NOT NULL,
                data_json TEXT NOT NULL,
                UNIQUE(session_id,event_seq))""")
        self.seq = 0

    def speech(self, *lines, session="s-one"):
        with sqlite3.connect(self.event_db) as db:
            for line in lines:
                self.seq += 1
                db.execute(
                    "INSERT INTO event_log(session_id,event_seq,timestamp,type,data_json) VALUES(?,?,?,?,?)",
                    (session,self.seq,"2026-10-17T09:39:00+07:00",
                     "speech.raw",json.dumps({"text":line},ensure_ascii=False)))

    def input(self, line="Take"):
        with sqlite3.connect(self.event_db) as db:
            self.seq += 1
            db.execute(
                "INSERT INTO event_log(session_id,event_seq,timestamp,type,data_json) VALUES(?,?,?,?,?)",
                ("s-one",self.seq,"2026-10-17T09:39:00+07:00","input.marker.raw",
                 json.dumps({"controlId":"A","key":"F11","state":"down","text":line})))

    def repo(self):
        return OwnedItemsRepository(self.char_db, self.event_db)

    def fixture(self):
        # Same multi-tab STASH/CHEST sequence pattern as the real-A sample.
        self.speech("STASH", "CHEST 1",
                    "RAZORPLATE", "Unique Chest Armor", "850 Item Power",
                    "314 Armor", "Take", "Store",
                    "CHEST 2", "THE SAME RING", "Legendary Ring", "900 Item Power",
                    "+10% Critical Strike Chance", "CHEST 3",
                    "CHEST 2", "THE SAME RING", "Legendary Ring", "900 Item Power",
                    "+10% Critical Strike Chance", "STASH")
        self.input()
        self.speech("CHARACTER", "ITEM IN BAG", "Legendary Gloves", "900 Item Power",
                    "+2 Core Skills", "CHARACTER")

    def test_observations_never_confirm_ownership_tab_or_physical_id(self):
        self.fixture()
        repo = self.repo()
        self.assertEqual(repo.sync(), self.seq)
        payload = repo.listing(locations={"all"}, include_unverified=True)
        self.assertEqual(payload["observedTotal"], 4)
        self.assertEqual([x["name"] for x in payload["items"]].count("THE SAME RING"), 2)
        for item in payload["items"]:
            self.assertEqual(item["ownershipStatus"], "NOT_CONFIRMED")
            self.assertIsNone(item["location"]["tab"])
            self.assertIsNone(item["pickedUpAt"])
        self.assertEqual({x["location"]["type"] for x in payload["items"]}, {"stash","inventory"})
        self.assertEqual(payload["coverage"]["stash"]["overall"], "PARTIAL")
        self.assertEqual([x["tab"] for x in payload["coverage"]["stash"]["tabs"]], [1,2,3])
        self.assertEqual(repo.listing(locations={"all"})["items"], [])
        self.assertEqual(repo.listing(locations={"stash"}, include_unverified=True)["observedTotal"], 3)
        self.assertEqual(repo.listing(locations={"inventory"}, include_unverified=True)["observedTotal"], 1)
        self.assertEqual(repo.listing(locations={"all"},rarity="unique",include_unverified=True)["observedTotal"],1)

    def test_incremental_idempotent_replay_and_append_only_observations(self):
        self.fixture()
        repo = self.repo()
        self.assertEqual(repo.sync(), self.seq)
        original = repo.history()
        self.assertEqual(len(original), 4)
        self.assertEqual(repo.sync(), 0)
        self.assertEqual(repo.history(), original)
        # A new session has an independent local event_seq (canonical row ID is global).
        with sqlite3.connect(self.event_db) as db:
            for i,text in enumerate(["STASH","CHEST 1","ANOTHER ITEM","Legendary Helm",
                                      "850 Item Power","CHEST 2"], 1):
                db.execute("INSERT INTO event_log(session_id,event_seq,timestamp,type,data_json) VALUES(?,?,?,?,?)",
                           ("s-two",i,"2026-10-17T10:00:00+07:00",
                            "speech.raw",json.dumps({"text":text})))
        self.assertEqual(repo.sync(),6)
        self.assertEqual(len(repo.history()),5)
        self.assertEqual(repo.sync(),0)
        self.assertEqual(len(repo.history()),5)

    def test_cli_json_filters_history_export_and_no_event_writes(self):
        self.fixture()
        import os
        old = os.environ.get("D4PLANNER_HOME")
        os.environ["D4PLANNER_HOME"] = str(self.home)
        self.addCleanup(lambda: os.environ.pop("D4PLANNER_HOME", None) if old is None else os.environ.__setitem__("D4PLANNER_HOME",old))
        def call(*argv):
            stdout, stderr = StringIO(), StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(list(argv))
            return code,stdout.getvalue(),stderr.getvalue()
        before = self.event_db.read_bytes()
        code,stdout,err = call("items","--json","--include-unverified","--location","stash")
        self.assertEqual((code,err),(0,""))
        payload=json.loads(stdout)
        self.assertEqual(payload["observedTotal"],3)
        code,stdout,err=call("items","status","--json")
        self.assertEqual(code,0)
        self.assertEqual(json.loads(stdout)["coverage"]["overall"],"PARTIAL")
        code,stdout,err=call("items","history","--json")
        self.assertEqual(code,0)
        self.assertEqual(len(json.loads(stdout)["observations"]),4)
        target=self.home/"owned-history.jsonl"
        code,stdout,err=call("items","export","--format","jsonl","--output",str(target))
        self.assertEqual((code,err),(0,""))
        self.assertEqual(len([json.loads(s) for s in target.read_text(encoding="utf-8").splitlines()]),4)
        code,stdout,err=call("items","export","--output",str(target))
        self.assertEqual(code,2)
        self.assertIn("Refusing to overwrite",err)
        code,stdout,err=call("items","--location","invalid")
        self.assertEqual(code,2)
        self.assertEqual(self.event_db.read_bytes(),before)

    def test_unrecognized_tooltip_or_command_never_create_false_item(self):
        self.speech("STASH","CHEST 1","Take","Equip","EQUIPPED",
                    "AN ITEM","Legendary Ring","not item power","CHEST 2")
        repo=self.repo()
        self.assertEqual(repo.listing(locations={"all"},include_unverified=True)["items"],[])
        self.assertEqual(repo.history(),[])

    def test_high_confidence_equipment_retains_legacy_projection(self):
        with sqlite3.connect(self.char_db) as db:
            db.execute("""CREATE TABLE equipment_current(
               id INTEGER PRIMARY KEY, slot_family TEXT, slot_index INTEGER,
               item_name TEXT,item_type TEXT,item_power INTEGER,item_json TEXT,
               observed_at TEXT,source_session_id TEXT,source_event_seq_start INTEGER,
               source_event_seq_end INTEGER, confidence TEXT)""")
            for i,confidence in enumerate(("HIGH","LOW"),1):
                db.execute("""INSERT INTO equipment_current VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                           (i,"ring",i,f"RING {i}","Ring",850,
                            json.dumps({"rarity":"Legendary","affixes":[]}),
                            "2026-10-17T09:00:00+07:00","s-equipment",i,i+3,confidence))
        payload=self.repo().listing(locations={"all"})
        self.assertEqual([v["name"] for v in payload["items"]],["RING 1"])
        self.assertEqual(payload["items"][0]["ownershipStatus"],"CONFIRMED")
        self.assertEqual(self.repo().listing(locations={"stash"})["items"],[])


if __name__ == "__main__":
    unittest.main()
