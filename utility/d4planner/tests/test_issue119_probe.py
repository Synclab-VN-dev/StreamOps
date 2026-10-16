"""Unit tests for the read-only issue #119 evidence probe (synthetic DB)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[3] / "scripts" / "acceptance" / "issue119_probe.py"
spec = importlib.util.spec_from_file_location("issue119_probe", MODULE)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        self.state = self.home / "state"
        self.state.mkdir(parents=True)
        self.session = "session-a"
        self.write_status()
        self.db = sqlite3.connect(self.state / "events.db")
        self.addCleanup(self.db.close)
        self.db.execute("CREATE TABLE event_log(session_id TEXT,event_seq INTEGER,timestamp TEXT,type TEXT,data_json TEXT)")
        self.db.commit()

    def write_status(self, session=None):
        data = {"sessionId": session or self.session, "state": "RUNNING", "supervisorPid": 200,
                "captureActive": True, "extras": {"inputMarker": {
                    "state": "ACTIVE", "layoutId": "xbox-steaminput-18-v1", "configuredDigitalCount": 16,
                    "droppedCount": 0, "overflow": False}}}
        (self.state / "runtime.json").write_text(json.dumps(data), encoding="utf-8")

    def add(self, seq, event_type, data):
        self.db.execute("INSERT INTO event_log VALUES(?,?,?,?,?)", (self.session, seq,
                        "2026-10-17T10:00:00+07:00", event_type, json.dumps(data)))
        self.db.commit()

    def begin(self):
        path = Path(self.temp.name) / "begin.json"
        probe.write_json(path, probe.snapshot(self.home))
        return path

    def test_mixed_speech_input_order_and_unverified_anchor(self):
        base = self.begin()
        self.add(1, "input.marker.raw", {"key":"F11", "controlId":"A", "state":"down"})
        self.add(2, "speech.raw", {"text":"EXAMPLE GLOVES"})
        self.add(3, "speech.raw", {"text":"Ancestral Legendary Gloves"})
        self.add(4, "speech.raw", {"text":"900 Item Power"})
        self.add(5, "input.marker.raw", {"key":"F11", "controlId":"A", "state":"up"})
        out = Path(self.temp.name) / "out"
        summary = probe.finish(self.home, base, out)
        self.assertEqual(summary["speechCount"], 3)
        self.assertEqual(summary["inputCount"], 2)
        self.assertEqual(summary["inputEdges"], {"down":1, "up":1})
        self.assertEqual(summary["checks"]["controller_16_key_profile"], "PASS")
        self.assertEqual(summary["coverage"]["stash"], "UNVERIFIED")
        self.assertEqual(summary["anchorCount"], 1)
        item = json.loads((out / "item-anchors-unverified.json").read_text())[0]
        self.assertEqual(item["ownership"], "UNVERIFIED")
        events = [json.loads(row) for row in (out / "events.jsonl").read_text().splitlines()]
        self.assertEqual([row["eventSeq"] for row in events], [1,2,3,4,5])

    def test_missing_input_is_blocked_not_pass(self):
        base = self.begin()
        self.add(1, "speech.raw", {"text":"Inventory"})
        summary = probe.finish(self.home, base, Path(self.temp.name)/"no-input")
        self.assertEqual(summary["checks"]["configured_input_edges_observed"], "BLOCKED")

    def test_refuses_to_splice_sessions(self):
        base = self.begin()
        self.write_status(session="session-b")
        with self.assertRaisesRegex(RuntimeError, "session changed"):
            probe.finish(self.home, base, Path(self.temp.name)/"bad")

    def test_duplicate_item_observations_not_deduplicated(self):
        base = self.begin()
        for i in range(2):
            self.add(i*3+1, "speech.raw", {"text":"SAME RING"})
            self.add(i*3+2, "speech.raw", {"text":"Rare Ring"})
            self.add(i*3+3, "speech.raw", {"text":"850 Item Power"})
        summary = probe.finish(self.home, base, Path(self.temp.name)/"dupe")
        self.assertEqual(summary["anchorCount"], 2)

    def test_missing_database_is_blocked(self):
        self.db.close()
        (self.state / "events.db").unlink()
        with self.assertRaisesRegex(RuntimeError, "missing"):
            probe.snapshot(self.home)


if __name__ == "__main__":
    unittest.main()
