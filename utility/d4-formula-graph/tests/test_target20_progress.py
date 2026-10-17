"""20 real-scope target accounting, no fabricated candidate/Golden PASS."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
import graph
import target20_progress as target

class Target20Scope(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p=BASE/"fixtures"
        cls.source=graph.read_json(p/"dev00-source-sanitized.json")
        cls.inv=graph.read_json(p/"dev00-visible-inventory.json")
        cls.rules=graph.read_json(p/"candidate-source-level.json")
        cls.manifest=graph.read_json(p/"golden-target-20.json")
        cls.level=graph.read_json(p/"golden-dev"/"dev00-level.json")
    def output(self,manifest=None,source=None):
        return target.run(source or self.source,self.inv,self.rules,
                          manifest or self.manifest,self.level)
    def test_goal_has_20_real_distinct_maxroll_metric_ids(self):
        r=self.output()
        self.assertEqual(r["target"],20)
        self.assertEqual(len(r["records"]),20)
        self.assertEqual(len({x["metricId"] for x in r["records"]}),20)
        self.assertEqual(r["verifiedUniqueMetricIds"],1)
        self.assertEqual(r["blockedMetricIds"],19)
        self.assertEqual(r["remainingToTarget"],19)
        self.assertEqual(r["failedMetricIds"],0)
        self.assertEqual(r["fixtureId"],"DEV-00")
        self.assertEqual(r["classId"],"rogue")
        self.assertFalse(r["allTargetVerified"])
        self.assertFalse(r["captureComplete"])
    def test_actual_level_pinned_real_golden_is_only_current_pass(self):
        r=self.output()
        passes=[x for x in r["records"] if x["state"]=="VERIFIED"]
        self.assertEqual([(x["metricId"],x["label"]) for x in passes],
                         [("maxroll.heroDetails.279","Level")])
        self.assertTrue(all(not x["candidateHasActual"] for x in r["records"]
                            if x["state"]=="BLOCKED"))
        self.assertFalse(r["holdoutOpened"])
        self.assertFalse(r["productionRulePromoted"])
    def test_missing_stat_never_promoted_by_inventory_or_f3_expressions(self):
        r=self.output()
        for x in r["records"]:
            if x["metricId"]!="maxroll.heroDetails.279":
                self.assertEqual(x["state"],"BLOCKED")
                self.assertEqual(x["reason"],"NO_SOURCE_DERIVED_FORMULA_ACTUAL")
    def test_swapped_duplicate_or_fake_metric_rejected(self):
        for mutation in ("duplicate","count","fake","label","class","patch"):
            m=copy.deepcopy(self.manifest)
            if mutation=="duplicate":m["metrics"][1]=copy.deepcopy(m["metrics"][0])
            if mutation=="count":m["metrics"]=m["metrics"][:-1]
            if mutation=="fake":m["metrics"][1]["metricId"]="maxroll.heroDetails.999999"
            if mutation=="label":m["metrics"][1]["label"]="Wrong label"
            if mutation=="class":m["initialClassId"]="sorcerer"
            if mutation=="patch":m["patch"]="3.3.0"
            with self.subTest(mutation=mutation),self.assertRaises(graph.GraphError):
                self.output(manifest=m)
    def test_different_build_level_fails_real_golden_not_kept_as_verified(self):
        s=copy.deepcopy(self.source)
        s["currentReadOnlyPublicProfile"]["level"]=71
        s["fixture"]["level"]=71
        with self.assertRaisesRegex(graph.GraphError,"BASELINE_GOLDEN_LEVEL_REGRESSION"):
            self.output(source=s)
    def test_modified_private_golden_blob_cannot_be_used(self):
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/"expected-maxroll.json"
            f.write_text(json.dumps({"origin":"MAXROLL_BROWSER_CAPTURE",
                                     "metrics":[]})+"\n")
            with self.assertRaisesRegex(graph.GraphError,
                                        "PRIVATE_GOLDEN_CAPTURE_BLOB_MISMATCH"):
                target.load_private_capture(f,self.manifest,{
                    "gamePatch":"3.2.1.73552",
                    "sourceInputFingerprint":self.inv["inputFingerprintSha256"]})
    def test_captured_expected_cannot_be_smuggled_into_formula_input(self):
        s=copy.deepcopy(self.source);s["expectedRawValue"]=70
        with self.assertRaises(graph.GraphError): self.output(source=s)
