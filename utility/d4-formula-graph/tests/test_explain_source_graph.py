"""E2E-01 human-readable explanation from two actual captured source builds."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import graph
import dev_source_graph
import g4_source_audit
import explain_source_graph
class ExplanationE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases=[]
        rules=graph.read_json(ROOT/"fixtures"/"candidate-source-level.json")
        for name in ("dev00","dev01"):
            base=ROOT/"fixtures"
            s=graph.read_json(base/(name+"-mechanics.json"))
            w=graph.read_json(base/(name+"-source-rolls.json"))
            inv=graph.read_json(base/(name+"-visible-inventory.json"))
            g=dev_source_graph.build(s,w,inv,rules)
            audit=g4_source_audit.analyze(inv,g)
            cls.cases.append((g,audit))
    def test_readable_explanation_covers_all_source_metrics_in_two_classes(self):
        for actual,audit in self.cases:
            text=explain_source_graph.explain(actual,audit)
            self.assertEqual(text.count("| `maxroll.heroDetails."),audit["visibleMetricRows"])
            self.assertIn("Formula verified: **0**",text)
            self.assertIn("Golden parity: **BLOCKED**",text)
            self.assertIn("HOLDOUT expected: **NOT OPENED**",text)
            self.assertIn("source-input candidate",text)
            self.assertIn("UNKNOWN",text)
            self.assertEqual(text,explain_source_graph.explain(actual,audit))
    def test_mismatched_graph_and_coverage_is_rejected(self):
        a,coverage=self.cases[0]
        b,_=self.cases[1]
        with self.assertRaisesRegex(graph.GraphError,
                                    "G4_EXPLANATION_WRONG_SOURCE_GRAPH"):
            explain_source_graph.explain(a,self.cases[1][1])
        manipulated=deepcopy(coverage)
        manipulated["rows"].pop()
        with self.assertRaises(graph.GraphError):
            explain_source_graph.explain(a,manipulated)
        manipulated=deepcopy(a)
        manipulated["publishAllowed"]=True
        manipulated["graphSha256"]=graph.digest({
           k:v for k,v in manipulated.items() if k!="graphSha256"})
        with self.assertRaises(graph.GraphError):
            explain_source_graph.explain(manipulated,coverage)
