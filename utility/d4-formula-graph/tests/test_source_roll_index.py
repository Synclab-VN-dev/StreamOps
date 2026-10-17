"""Exact source roll counts plus changed-input/patch/duplicate safety gates."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import graph
import source_roll_index as m

class SourceIndex(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.witnesses=[
          graph.read_json(ROOT/"fixtures"/"dev00-source-rolls.json"),
          graph.read_json(ROOT/"fixtures"/"dev01-source-rolls.json")]
    def test_complete_roll_witness_from_dev_captures(self):
        for w,slot_count,rolls,group in zip(
            self.witnesses,(18,17),(85,40),
            ({"explicits":67,"tempered":11,"aspects":7},
             {"explicits":34,"tempered":2,"aspects":4})):
            with self.subTest(fixture=w["fixtureId"]):
                a=m.index(w)
                self.assertEqual(a["slotCount"],slot_count)
                self.assertEqual(a["rollCount"],rolls)
                self.assertEqual(a["groupCounts"],group)
                self.assertTrue(a["repeatedNids"])
                self.assertEqual(len({r["sourceId"] for r in a["contributors"]}),rolls)
                self.assertEqual(a["mappedStatCount"],0)
                self.assertEqual(a["computedRealStatsFromAffixes"],0)
                self.assertFalse(a["publishAllowed"])
                self.assertEqual(a,m.index(w))
    def test_same_nid_multiple_slots_not_overwritten(self):
        w=self.witnesses[0];d=m.index(w)
        entries=[r for r in d["contributors"] if r["nid"]==1829592]
        self.assertGreaterEqual(len(entries),3)
        self.assertEqual(len({r["sourceId"] for r in entries}),len(entries))
    def test_mutated_roll_changes_hash_and_source_only(self):
        w=deepcopy(self.witnesses[0])
        before=m.index(w)
        w["slots"][0]["fields"]["explicits"][0]["values"][0]+=1
        after=m.index(w)
        self.assertNotEqual(before["indexSha256"],after["indexSha256"])
        self.assertEqual(after["mappedStatCount"],0)
    def test_missing_known_metric_mapping_not_invented(self):
        d=m.index(self.witnesses[1])
        self.assertTrue(all(c["metricIds"]==[] and
                            c["metricMappingStatus"]=="UNKNOWN"
                            for c in d["contributors"]))
    def test_duplicate_slot_or_malicious_fields_fail(self):
        for case in ("slot","expected","nan","partition","patch","reference","unknown"):
            w=deepcopy(self.witnesses[0])
            if case=="slot":w["slots"].append(deepcopy(w["slots"][0]))
            if case=="expected":w["golden"]=70
            if case=="nan":w["slots"][0]["fields"]["explicits"][0]["values"][0]=float("nan")
            if case=="partition":w["partition"]="HOLDOUT"
            if case=="patch":w["patch"]="3.2.0"
            if case=="reference":w["inputFingerprintSha256"]="0"*64
            if case=="unknown":w["conditionalContext"]=0
            with self.subTest(case=case),self.assertRaises(graph.GraphError):
                m.index(w)
