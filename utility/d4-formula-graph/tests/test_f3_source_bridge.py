"""Evidence gap report counts observed rolls separately from verified mappings."""
import copy
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import graph
import f3_source_bridge as b

class BridgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=graph.read_json(ROOT/"fixtures"/"dev00-source-rolls.json")
        cls.formula=graph.read_json(ROOT/"fixtures"/"f3-bounded-formula-ast.json")
    def test_rolls_are_not_automatic_metric_formula_sources(self):
        r=b.bridge(self.source,self.formula)
        self.assertEqual(r["observedRolls"],85)
        self.assertEqual(r["f3Formulas"],3)
        self.assertEqual(len(r["unmappedIntermediateDependencies"]),7)
        self.assertEqual(r["statFormulaMappingVerified"],0)
        self.assertEqual(r["computedMetricValues"],0)
        self.assertFalse(r["goldenExpectedLoaded"])
        self.assertTrue(all(x["actual"] is None for x in r["details"]))
    def test_source_mutation_changes_provenance_not_mapping_grade(self):
        source=copy.deepcopy(self.source)
        source["slots"][0]["fields"]["explicits"][0]["values"][0]+=1
        a=b.bridge(self.source,self.formula);v=b.bridge(source,self.formula)
        self.assertNotEqual(a["reportSha256"],v["reportSha256"])
        self.assertEqual(v["unmappedIntermediateDependencies"],a["unmappedIntermediateDependencies"])
        self.assertEqual(v["computedMetricValues"],0)
    def test_cannot_apply_rogue_f3_to_sorcerer(self):
        s=graph.read_json(ROOT/"fixtures"/"dev01-source-rolls.json")
        with self.assertRaisesRegex(graph.GraphError,"F3_RESEARCH_SCOPE_ROGUE_ONLY"):
            b.bridge(s,self.formula)
