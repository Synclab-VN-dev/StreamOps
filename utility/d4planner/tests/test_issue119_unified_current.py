"""Issue #119 redesigned current-state API: engine writes, CLI reads.

Synthetic only. Real NVDA/Steam/Diablo IV verification remains MAN on A.
"""
from __future__ import annotations
from contextlib import closing, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from d4planner.character import item_current
from d4planner.character.owned_items import OwnedItemsRepository
from d4planner.cli import main


class UnifiedCurrentTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.state = self.root / "state"
        self.state.mkdir()
        self.db = self.state / "character.db"
        self.events = self.state / "events.db"
        with closing(sqlite3.connect(self.events)) as db, db:
            db.execute("""CREATE TABLE event_log(
                id INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT NOT NULL,
                event_seq INTEGER NOT NULL,timestamp TEXT NOT NULL,
                type TEXT NOT NULL,data_json TEXT NOT NULL)""")
        self.seq = {}

    def init(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.row_factory = sqlite3.Row
            item_current.schema(db)
            db.commit()

    def observe(self, name="AMULET A", session="s1"):
        return {
            "name": name, "itemType": "Amulet", "itemPower": 850,
            "rarity": "Legendary", "ancestral": False,
            "location": {"type": "inventory", "slot": None, "tab": None},
            "baseStats": [], "affixes": [{"raw": "+99 Intelligence"}],
            "effectsRaw": [], "metadataRaw": [],
            "ownershipStatus": "CONFIRMED",
            "observationConfidence": "HIGH",
            "ownershipEvidence": "character-bag-actions-v1",
            "firstSeenAt": "2026-10-18T10:00:00+07:00",
            "lastSeenAt": "2026-10-18T10:00:00+07:00",
            "sourceSessionId": session,
            "sourceEventSeqStart": 2, "sourceEventSeqEnd": 15,
        }

    def event(self, session, kind, payload):
        seq = self.seq.get(session, 0) + 1
        self.seq[session] = seq
        with closing(sqlite3.connect(self.events)) as db, db:
            db.execute("INSERT INTO event_log(session_id,event_seq,timestamp,type,data_json) VALUES(?,?,?,?,?)",
                       (session, seq, "2026-10-18T10:00:00+07:00",
                        kind, json.dumps(payload)))
    def speech(self, session, *lines):
        for line in lines:
            self.event(session, "speech.raw", {"text": line})

    def test_single_table_readonly_snapshot_and_location_move(self):
        self.init()
        before = self.observe()
        with closing(sqlite3.connect(self.db)) as db, db:
            db.row_factory = sqlite3.Row
            item_current.upsert(db, "real-1", before, fingerprint="hash1")
        first = item_current.snapshot(self.db)
        self.assertEqual(first["observedTotal"], 1)
        self.assertEqual(first["items"][0]["location"]["type"], "inventory")
        self.assertEqual(first["revision"], 1)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.row_factory = sqlite3.Row
            self.assertFalse(item_current.upsert(db, "real-1", before, fingerprint="hash1"))
        self.assertEqual(item_current.snapshot(self.db)["revision"], 1)
        after = dict(before)
        after["location"] = {"type": "equipment", "slot": "amulet", "tab": None}
        after["lastSeenAt"] = "2026-10-18T10:01:00+07:00"
        with closing(sqlite3.connect(self.db)) as db, db:
            db.row_factory = sqlite3.Row
            item_current.upsert(db, "real-1", after, fingerprint="hash1")
        actual = item_current.snapshot(self.db)
        self.assertEqual(actual["observedTotal"], 1)
        self.assertEqual(actual["revision"], 2)
        self.assertEqual(actual["items"][0]["location"]["type"], "equipment")
        self.assertEqual(item_current.snapshot(
            self.db, locations={"inventory"})["observedTotal"], 0)
        self.assertEqual(item_current.snapshot(
            self.db, locations={"equipment"})["observedTotal"], 1)

    def test_cli_item_reads_character_only_without_creating_event_store(self):
        self.init()
        with closing(sqlite3.connect(self.db)) as db, db:
            db.row_factory = sqlite3.Row
            item_current.upsert(db, "x", self.observe(), fingerprint="hash")
        self.events.unlink()
        original = os.environ.get("D4PLANNER_HOME")
        os.environ["D4PLANNER_HOME"] = str(self.root)
        self.addCleanup(lambda: os.environ.pop("D4PLANNER_HOME", None)
                        if original is None else os.environ.__setitem__(
                            "D4PLANNER_HOME", original))
        def call(*args):
            out = StringIO()
            with redirect_stdout(out):
                code = main(["item", *args])
            self.assertEqual(code, 0)
            return json.loads(out.getvalue())
        self.assertEqual(call("--json")["observedTotal"], 1)
        self.assertEqual(call("--location", "inventory", "--json")["observedTotal"], 1)
        self.assertEqual(call("--location", "equipment", "--json")["observedTotal"], 0)
        with patch("d4planner.cli.time.sleep", side_effect=KeyboardInterrupt):
            self.assertEqual(call("--attach", "--json")["items"],
                             call("--json")["items"])
        self.assertFalse(self.events.exists())

    def test_engine_session_gate_and_cross_session_current_preservation(self):
        self.speech("older", "CHARACTER", "PREVIOUS ITEM", "Legendary Amulet",
                    "850 Item Power", "Drop")
        self.event("active", "input.marker.raw",
                   {"state": "down", "controlId": "START", "key": "F3"})
        self.speech("active", "CHARACTER",
                    "Right analog stick click  Sort  Bag",
                    "EQUIPPED", "OLD EQUIPPED", "Legendary Amulet",
                    "850 Item Power", "AMULET A", "Legendary Amulet",
                    "850 Item Power", "Equip", "Mark as Junk", "Drop")
        repo = OwnedItemsRepository(self.db, self.events)
        processed = repo.sync(session_id="active")
        self.assertEqual(processed, self.seq["active"])
        items = item_current.snapshot(self.db, locations={"inventory"})["items"]
        self.assertEqual([x["name"] for x in items], ["AMULET A"])
        self.assertEqual(repo.sync(session_id="active"), 0)
        revision = item_current.snapshot(self.db)["revision"]
        self.speech("newer", "CHARACTER", "NOT AN ITEM")
        repo.sync(session_id="newer")
        self.assertEqual(item_current.snapshot(self.db)["revision"], revision)
        # Comparison is audit-only; physical current contains only verified Bag.
        self.assertEqual(item_current.snapshot(self.db)["observedTotal"], 1)

    def test_dev_clean_bootstrap_does_not_import_legacy_equipment(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("""CREATE TABLE equipment_current(
                id INTEGER PRIMARY KEY,slot_family TEXT,slot_index INTEGER,
                item_name TEXT,item_type TEXT,item_power INTEGER,item_json TEXT,
                observed_at TEXT,source_session_id TEXT,
                source_event_seq_start INTEGER,source_event_seq_end INTEGER,
                confidence TEXT)""")
            db.execute("INSERT INTO equipment_current VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (1, "amulet", 0, "OLD AMULET", "Amulet", 850,
                        json.dumps({"rarity": "Legendary"}),
                        "2026-10-18T10:00:00+07:00", "old", 1, 3, "HIGH"))
            db.commit()
            db.row_factory = sqlite3.Row
            item_current.schema(db)
            db.commit()
        items = item_current.snapshot(self.db)["items"]
        self.assertEqual(items, [])  # DEV v3 intentionally starts clean
        self.assertEqual(item_current.snapshot(self.db)["revision"], 0)

    def test_attach_emits_only_committed_revision_changes(self):
        self.init()
        original = os.environ.get("D4PLANNER_HOME")
        os.environ["D4PLANNER_HOME"] = str(self.root)
        self.addCleanup(lambda: os.environ.pop("D4PLANNER_HOME", None)
                        if original is None else os.environ.__setitem__(
                            "D4PLANNER_HOME", original))
        calls = [0]
        def advance(_seconds):
            calls[0] += 1
            if calls[0] == 1:
                with closing(sqlite3.connect(self.db)) as db, db:
                    db.row_factory = sqlite3.Row
                    item_current.upsert(
                        db, "item-a", self.observe(), fingerprint="a")
            else:
                raise KeyboardInterrupt
        output = StringIO()
        with patch("d4planner.cli.time.sleep", side_effect=advance):
            with redirect_stdout(output):
                rc = main(["item", "--attach", "--json"])
        self.assertEqual(rc, 0)
        snapshots = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([x["revision"] for x in snapshots], [0, 1])
        self.assertEqual([x["observedTotal"] for x in snapshots], [0, 1])
        self.assertEqual(len(snapshots[1]["items"]), 1)


    def test_equipment_slot_change_keeps_unknown_item_not_fake_removal(self):
        self.init()
        item = self.observe()
        item["location"] = {"type": "equipment", "slot": "amulet", "tab": None}
        with closing(sqlite3.connect(self.db)) as db, db:
            db.row_factory = sqlite3.Row
            item_current.upsert(db, "old-equip", item, fingerprint="old")
            item_current.mark_location_unknown(
                db, "location='equipment' AND slot=?", ("amulet",),
                when="2026-10-18T10:01:00+07:00", session="s2")
        snap = item_current.snapshot(self.db)
        self.assertEqual(snap["observedTotal"], 1)
        self.assertEqual(snap["items"][0]["location"]["type"], "unknown")
        self.assertEqual(snap["items"][0]["presenceStatus"], "LOCATION_UNVERIFIED")
        self.assertEqual(item_current.snapshot(
            self.db, locations={"equipment"})["observedTotal"], 0)


    def test_one_shot_uat_runner_passes_snapshot_and_fails_closed_head(self):
        import importlib.util
        import subprocess
        repo_root = Path(__file__).resolve().parents[3]
        script = repo_root / "scripts/acceptance/issue119_item_current_uat.py"
        spec = importlib.util.spec_from_file_location("issue119_current_uat", script)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        rejected = module.run(repo_root, self.root, "incorrect-head",
                              self.root / "blocked")
        self.assertEqual(rejected["status"], "BLOCKED")
        self.assertTrue((self.root / "blocked/report.json").is_file())

        self.init()
        with closing(sqlite3.connect(self.db)) as db, db:
            db.row_factory = sqlite3.Row
            item_current.upsert(db, "a", self.observe(), fingerprint="a")
        head = subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            text=True).strip()
        accepted = module.run(repo_root, self.root, head, self.root / "positive")
        self.assertEqual(accepted["status"], "PASS_SNAPSHOT_ONLY")
        self.assertEqual(
            [x["status"] for x in accepted["cases"] if x["id"].startswith("UC-03-")],
            ["PASS", "PASS", "PASS"])
        self.assertTrue((self.root / "positive/inventory.stdout.json").is_file())
        self.assertFalse(any(x["id"] == "UC-07-REAL-A" and x["status"] == "PASS"
                             for x in accepted["cases"]))



    def test_read_only_issue119_probe_reports_projection_without_db_writes(self):
        import importlib.util
        script = (Path(__file__).resolve().parents[3] /
                  "scripts/acceptance/issue119_projection_probe.py")
        spec = importlib.util.spec_from_file_location("issue119_projection_probe", script)
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # setUp() intentionally creates events.db, so exercise the missing
        # database path under a distinct empty home instead.
        empty_home = self.root / "empty-home"
        empty = module.report(empty_home)
        self.assertFalse(empty["characterDbPresent"])
        self.assertFalse(empty["eventsDbPresent"])
        self.assertFalse((empty_home / "state" / "events.db").exists())
        self.assertFalse(self.db.exists())

        self.init()
        with closing(sqlite3.connect(self.db)) as db, db:
            db.row_factory = sqlite3.Row
            item_current.upsert(db, "local-item", self.observe(), fingerprint="hash")
        self.event("active", "speech.raw", {"text": "CHARACTER"})
        before = self.db.stat().st_mtime_ns
        actual = module.report(self.root)
        self.assertTrue(actual["eventsDbPresent"])
        self.assertEqual(actual["recentEventSessions"][0]["speechCount"], 1)
        self.assertEqual(actual["currentItems"][0]["name"], "AMULET A")
        self.assertGreater(actual["itemProjectionState"]["revision"], 0)
        self.assertEqual(before, self.db.stat().st_mtime_ns)



if __name__ == "__main__":
    unittest.main()
