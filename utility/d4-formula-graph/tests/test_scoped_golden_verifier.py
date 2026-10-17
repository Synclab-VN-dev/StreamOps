"""Real independent Maxroll Golden: Level 70 from pinned Rogue and Sorcerer captures."""
from copy import deepcopy
from pathlib import Path
import sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import graph
import golden_candidate_eval as calculator
import scoped_golden_verifier as verifier

class GoldenScopedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules=graph.read_json(ROOT/"fixtures"/"candidate-source-level.json")
        cls.data=[]
        for key in ("dev00","dev01"):
            source=graph.read_json(ROOT/"fixtures"/(key+"-source-sanitized.json"))
            inventory=graph.read_json(ROOT/"fixtures"/(key+"-visible-inventory.json"))
            golden=graph.read_json(ROOT/"fixtures"/"golden-dev"/(key+"-level.json"))
            cls.data.append((source,inventory,golden))
    def result(self,i):
        src,inv,golden=self.data[i]
        return calculator.build(src,inv,self.rules),golden

    def test_real_golden_verified_per_class_not_global(self):
        for i,classname in ((0,"rogue"),(1,"sorcerer")):
            actual,golden=self.result(i)
            report=verifier.verify(actual,golden)
            self.assertEqual(report["status"],"PASS_SCOPED")
            self.assertEqual(report["classId"],classname)
            self.assertEqual(report["verifiedScoped"],1)
            self.assertEqual(report["metrics"][0]["status"],"VERIFIED")
            self.assertEqual(report["metrics"][0]["rawDiff"],"0")
            self.assertEqual(report["metrics"][0]["actualDisplay"],"70")
            self.assertFalse(report["verifiedAcrossAllClasses"])
            self.assertFalse(report["fullCharacterStatsParity"])
            self.assertFalse(report["productionRulePromoted"])

    def test_source_level_71_fails_frozen_real_golden_70(self):
        for i,(src,inv,golden) in enumerate(self.data):
            s=deepcopy(src)
            if "activeProfile" in s:
                s["activeProfile"]["level"]=71
                s["level"]=71
            else:
                s["currentReadOnlyPublicProfile"]["level"]=71
                s["fixture"]["level"]=71
            report=verifier.verify(calculator.build(s,inv,self.rules),golden)
            self.assertEqual(report["status"],"FAIL_GOLDEN")
            self.assertEqual(report["verifiedScoped"],0)
            self.assertEqual(report["metrics"][0]["actualRaw"],71)

    def test_wrong_expected_raw_or_display_fails(self):
        actual,golden=self.result(0)
        for key,value in (("raw",71),("display","070")):
            g=deepcopy(golden)
            g["metrics"][0][key]=value
            with self.subTest(field=key):
                self.assertEqual(verifier.verify(actual,g)["status"],"FAIL_GOLDEN")

    def test_wrong_class_patch_input_runtime_and_reference_block(self):
        actual,golden=self.result(0)
        for key,value in (("classId","sorcerer"),("patch","3.2.3"),
                          ("inputSha256","0"*64),("runtimeSha256","1"*64)):
            bad=deepcopy(golden);bad[key]=value
            with self.subTest(key=key),self.assertRaises(graph.GraphError):
                verifier.verify(actual,bad)
        b=deepcopy(golden);b["source"]["commit"]="bad"
        with self.assertRaises(graph.GraphError):
            verifier.verify(actual,b)
        with self.assertRaises(graph.GraphError):
            verifier.verify(self.result(1)[0],golden)

    def test_missing_actual_stays_unverified(self):
        actual,golden=self.result(0)
        row=next(x for x in actual["characterMetrics"]
                 if x["metricId"]=="maxroll.heroDetails.279")
        row.update(raw=None,display=None,computed=False,status="UNKNOWN",trace=[])
        actual["graphSha256"]=graph.digest({k:v for k,v in actual.items()
                                          if k!="graphSha256"})
        r=verifier.verify(actual,golden)
        self.assertEqual(r["status"],"BLOCKED_UNCOMPUTED")
        self.assertEqual(r["verifiedScoped"],0)

    def test_expected_contamination_and_large_tolerance_block(self):
        actual,golden=self.result(0)
        actual["sourceExpectedImported"]=True
        with self.assertRaises(graph.GraphError):
            verifier.verify(actual,golden)
        actual,golden=self.result(0)
        g=deepcopy(golden);g["metrics"][0]["tolerance"]=1
        with self.assertRaises(graph.GraphError):
            verifier.verify(actual,g)

    def test_graph_hash_tampering_blocks(self):
        actual,golden=self.result(0)
        actual["characterMetrics"][0]["raw"]=12345
        with self.assertRaisesRegex(graph.GraphError,"ACTUAL_GRAPH_HASH_MISMATCH"):
            verifier.verify(actual,golden)
