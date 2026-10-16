"""#109 synthetic append-only staging history and tamper rejection."""
from __future__ import annotations
import copy
from pathlib import Path
import sys
import unittest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import registry as reg
import versioned_history as h


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.fixture=reg.load(HERE/"fixtures"/"synthetic-patch-cycle.json")
        self.ledger=h.build(self.fixture)

    def test_replay_is_deterministic_and_rollback_real(self):
        self.assertEqual(self.ledger,h.build(self.fixture))
        result=h.verify(self.ledger)
        self.assertEqual(result["status"],"PASS_SYNTHETIC_LEDGER_REPLAY_ONLY")
        self.assertEqual(result["count"],3)
        self.assertTrue(result["rolledBackExactly"])
        self.assertEqual(self.ledger["oldRulesHash"],self.ledger["rollbackRulesHash"])
        self.assertNotEqual(self.ledger["oldRulesHash"],self.ledger["newRulesHash"])
        self.assertNotEqual(self.ledger["events"][0]["eventHash"],
                            self.ledger["events"][2]["eventHash"])
        self.assertEqual(self.ledger["events"][2]["parentEventHash"],
                         self.ledger["events"][1]["eventHash"])

    def test_mutated_payload_must_not_be_accepted(self):
        m=copy.deepcopy(self.ledger)
        m["events"][1]["rules"]["fake.direct"]=999
        with self.assertRaisesRegex(reg.RegistryError,"MODIFIED_LEDGER_EVENT"):
            h.verify(m)

    def test_rewritten_hash_cannot_hide_unreconciled_delta(self):
        m=copy.deepcopy(self.ledger)
        m["events"][1]["rules"]["fake.direct"]=999
        m["events"][1]["eventHash"]=reg.sha256({k:v for k,v in m["events"][1].items()
                                               if k!="eventHash"})
        m["events"][2]["parentEventHash"]=m["events"][1]["eventHash"]
        # Deliberately recompute ALL ordinary integrity fields to expose the
        # independent semantic added/buffed/nerfed diff gate, not the hash gate.
        m["newRulesHash"]=reg.sha256(m["events"][1]["rules"])
        m["events"][2]["eventHash"]=reg.sha256({k:v for k,v in m["events"][2].items()
                                               if k!="eventHash"})
        m["manifestHash"]=reg.sha256({k:v for k,v in m.items() if k!="manifestHash"})
        with self.assertRaisesRegex(reg.RegistryError,"PATCH_DIFF_MISMATCH"):
            h.verify(m)

    def test_replay_rejects_broken_parent_and_rollback(self):
        m=copy.deepcopy(self.ledger)
        m["events"][2]["parentEventHash"]="0"*64
        with self.assertRaisesRegex(reg.RegistryError,"BROKEN_LEDGER_CHAIN"):
            h.verify(m)
        m=copy.deepcopy(self.ledger)
        m["events"][2]["rules"]["fake.nerf"]=20
        with self.assertRaises(reg.RegistryError):
            h.verify(m)

    def test_no_live_or_non_synthetic_fixture(self):
        f=copy.deepcopy(self.fixture)
        f["synthetic"]=False
        with self.assertRaisesRegex(reg.RegistryError,"REAL_PATCH_MUTATION_FORBIDDEN"):
            h.build(f)
        m=copy.deepcopy(self.ledger)
        m["activePublish"]=True
        with self.assertRaisesRegex(reg.RegistryError,"UNSAFE_LEDGER"):
            h.verify(m)

    def test_event_omission_or_forced_publish_fails_closed(self):
        m=copy.deepcopy(self.ledger)
        m["events"].pop()
        with self.assertRaisesRegex(reg.RegistryError,"INCOMPLETE_EVENT_HISTORY"):
            h.verify(m)
        m=copy.deepcopy(self.ledger)
        m["events"][1]["active"]=True
        with self.assertRaisesRegex(reg.RegistryError,"BROKEN_LEDGER_CHAIN"):
            h.verify(m)
