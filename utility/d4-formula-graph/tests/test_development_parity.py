"""No Goldens embedded here: development parity uses synthetic expected for CI."""
import copy
import unittest
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import graph
import golden_candidate_eval
import development_parity

class DevParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules=graph.read_json(ROOT/"fixtures"/"candidate-source-level.json")
        cls.fixture=graph.read_json(ROOT/"fixtures"/"dev01-visible-inventory.json")
        cls.source=graph.read_json(ROOT/"fixtures"/"dev01-source-sanitized.json")
    def basis(self):
        a=golden_candidate_eval.build(self.source,self.fixture,self.rules)
        expected={
            "schema":"F-GOLDEN-01-maxroll-expected-v1",
            "fixtureId":"DEV-01","partition":"DEVELOPMENT",
            "origin":"SYNTHETIC_TEST_ONLY",
            "patch":a["gamePatch"],
            "inputFingerprintSha256":a["sourceInputFingerprint"],
            "metricCount":len(a["characterMetrics"]),
            # ALL test expected values below SYNTHETIC, not source/oracle, and not persisted
            "metrics":[{
                "metricId":x["metricId"],"group":x["group"],"label":x["label"],
                "raw":70 if x["metricId"]==golden_candidate_eval.LEVEL_ID else 1,
                "display":"70" if x["metricId"]==golden_candidate_eval.LEVEL_ID else "1",
                "provenance":{"raw":"MAXROLL_CDP_RUNTIME_DIRECT",
                              "display":"MAXROLL_BROWSER_UI_DIRECT"}
            } for x in a["characterMetrics"]]
        }
        return a,expected
    def test_dev_49_rows_47_unique_matching_level_not_full_pass(self):
        a,e=self.basis()
        r=development_parity.compare(a,e,test_only=True)
        self.assertEqual(r["sourceRows"],49)
        self.assertEqual(r["uniqueMetricIds"],47)
        self.assertEqual(r["candidateComputedUnique"],1)
        self.assertEqual(r["matchedUnverifiedRows"],1)
        self.assertEqual(r["mismatchedUnverifiedRows"],0)
        self.assertEqual(r["blockedRows"],48)
        self.assertEqual(r["status"],"DEVELOPMENT_PARTIAL_BLOCKED")
        self.assertFalse(r["allMetricsVerified"])
        self.assertEqual(r["fullMaxrollParity"],"BLOCKED_NOT_RUN")
    def test_wrong_candidate_detected_not_tuned(self):
        a,e=self.basis()
        e["metrics"][2]["raw"]=99 # ensure explicit Level row below
        l=next(x for x in e["metrics"] if x["metricId"]==golden_candidate_eval.LEVEL_ID)
        l["raw"]=75
        r=development_parity.compare(a,e,test_only=True)
        self.assertEqual(r["mismatchedUnverifiedRows"],1)
        self.assertEqual(r["status"],"DEVELOPMENT_CANDIDATE_MISMATCH")
        self.assertNotEqual(r["details"][2]["rawDiff"],"0")
    def test_holdout_expected_is_never_allowed(self):
        a,e=self.basis()
        e["fixtureId"]="HOLDOUT-01"
        e["partition"]="HOLDOUT"
        with self.assertRaises(graph.GraphError):
            development_parity.compare(a,e,test_only=True)
    def test_mutated_actual_checksum_blocked(self):
        a,e=self.basis()
        a["characterMetrics"][2]["raw"]=999
        with self.assertRaisesRegex(graph.GraphError,"GRAPH_MANIFEST_SHA_MISMATCH"):
            development_parity.compare(a,e,test_only=True)
    def test_missing_position_or_swapped_patch_blocked(self):
        a,e=self.basis()
        d=copy.deepcopy(e);d["metrics"]=d["metrics"][:-1]
        d["metricCount"]-=1
        with self.assertRaisesRegex(graph.GraphError,"EXPECTED_ACTUAL_VISIBLE_ROW_SET_MISMATCH"):
            development_parity.compare(a,d,test_only=True)
        d=copy.deepcopy(e);d["patch"]="3.2.3"
        with self.assertRaisesRegex(graph.GraphError,"EXPECTED_ACTUAL_PATCH_OR_FIXTURE_MISMATCH"):
            development_parity.compare(a,d,test_only=True)
    def test_inconsistent_duplicate_expected_rejected(self):
        a,e=self.basis()
        items=[x for x in e["metrics"] if x["metricId"]=="maxroll.heroDetails.431"]
        self.assertEqual(len(items),2)
        items[1]["raw"]=float(items[1]["raw"])+10
        with self.assertRaisesRegex(graph.GraphError,"CONFLICTING_DUPLICATE_EXPECTED_METRIC"):
            development_parity.compare(a,e,test_only=True)
    def test_unknown_cannot_appear_as_numeric(self):
        a,e=self.basis()
        a["characterMetrics"][0]["raw"]=0
        a["graphSha256"]=graph.digest({k:v for k,v in a.items() if k!="graphSha256"})
        with self.assertRaisesRegex(graph.GraphError,"UNKNOWN_METRIC_MUST_BE_NULL"):
            development_parity.compare(a,e,test_only=True)
    def test_synthetic_expected_cannot_pass_real_compare(self):
        a,e=self.basis()
        with self.assertRaisesRegex(graph.GraphError,"INVALID_EXPECTED_SOURCE"):
            development_parity.compare(a,e)
        e["origin"]="MAXROLL_BROWSER_CAPTURE"
        with self.assertRaisesRegex(graph.GraphError,"INVALID_EXPECTED_SOURCE"):
            development_parity.compare(a,e,test_only=True)
    def test_no_promoting_for_one_metric(self):
        a,e=self.basis()
        a["verifiedMetrics"]=1
        a["graphSha256"]=graph.digest({k:v for k,v in a.items() if k!="graphSha256"})
        with self.assertRaisesRegex(graph.GraphError,"FALSE_GOLDEN_OR_PRODUCTION_PROMOTION"):
            development_parity.compare(a,e,test_only=True)
