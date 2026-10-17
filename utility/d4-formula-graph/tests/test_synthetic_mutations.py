"""#110 six independent synthetic build mutations; stat real parity stays BLOCKED."""
import copy
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import graph
import synthetic_mutations

class MutationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.overlay=graph.read_json(ROOT/"fixtures"/"synthetic-alpha.json")
        cls.fixture=graph.read_json(ROOT/"fixtures"/"synthetic-three-families.json")

    def test_six_mutations_have_independent_test_only_expected_vectors(self):
        result=synthetic_mutations.run(self.overlay,self.fixture)
        self.assertEqual(result["status"],"PASS_SYNTHETIC_CI02_MUTATIONS_ONLY")
        self.assertEqual(result["testCaseCount"],6)
        self.assertEqual(len({x["case"] for x in result["cases"]}),6)
        self.assertTrue(all(x["beforeGraphSha256"]!=x["afterGraphSha256"]
                            and x["maxrollMetricsComputed"]==0
                            for x in result["cases"]))
        self.assertFalse(result["publishAllowed"])
        self.assertEqual(result["reportSha256"],graph.digest({
            k:v for k,v in result.items() if k!="reportSha256"}))

    def test_rule_data_change_preserves_independent_vectors_and_detects_mismatch(self):
        d=copy.deepcopy(self.fixture)
        d["rules"][1]["mechanics"][0]["actions"][0]["value"]["value"]=21
        with self.assertRaisesRegex(graph.GraphError,"SYNTHETIC_GOLDEN_EXPECTATION_DRIFT"):
            synthetic_mutations.run(self.overlay,d)
