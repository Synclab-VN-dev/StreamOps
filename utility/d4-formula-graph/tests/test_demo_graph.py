"""#110 synthetic G1 families join one source graph without leaking numeric Maxroll."""
from pathlib import Path
from copy import deepcopy
import sys
import unittest
HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import graph
import demo_graph

class DemoGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.overlay=graph.read_json(HERE/"fixtures"/"synthetic-alpha.json")
        cls.rules=graph.read_json(HERE/"fixtures"/"synthetic-three-families.json")

    def test_deterministic_graph_manifest_contains_three_synthetic_families(self):
        a=demo_graph.build(self.overlay,self.rules)
        self.assertEqual(a,demo_graph.build(self.overlay,self.rules))
        self.assertEqual(a["status"],
                         "PASS_SYNTHETIC_COMPOSITION_GRAPH_ONLY_REAL_MAXROLL_BLOCKED")
        self.assertEqual(len(a["characterMetrics"]),50)
        self.assertEqual(a["realCharacterComputed"],0)
        self.assertEqual(a["unknownCharacterMetrics"],50)
        self.assertEqual(len(a["syntheticMechanicNodes"]),3)
        self.assertTrue(all(x["notMaxroll"] for x in a["syntheticMechanicNodes"]))
        self.assertTrue(all(x["raw"] is None and x["display"] is None
                            for x in a["characterMetrics"]))
        self.assertEqual(a["syntheticOutputOnly"]["stats"]["synthetic.damageBonus"],30)
        self.assertIsNone(a["simulationContext"])
        self.assertEqual(a["graphSha256"],graph.digest({k:v for k,v in a.items()
                                                       if k!="graphSha256"}))

    def test_changed_rule_data_or_conditions_change_graph_without_engine_change(self):
        a=demo_graph.build(self.overlay,self.rules)
        b=deepcopy(self.rules)
        b["rules"][1]["mechanics"][0]["actions"][0]["value"]["value"]=30
        c=demo_graph.build(self.overlay,b)
        self.assertNotEqual(a["graphSha256"],c["graphSha256"])
        self.assertEqual(c["syntheticOutputOnly"]["stats"]["synthetic.damageBonus"],40)
        d=deepcopy(self.rules)
        d["input"]["charmCount"]=1
        e=demo_graph.build(self.overlay,d)
        self.assertNotEqual(a["graphSha256"],e["graphSha256"])
        self.assertEqual(e["syntheticOutputOnly"]["stats"]["synthetic.damageBonus"],20)
        self.assertEqual(e["realCharacterComputed"],0)

    def test_wrong_patch_prevents_cross_source_graph_composition(self):
        d=deepcopy(self.rules)
        d["gameBuild"]="73883"
        with self.assertRaises(graph.GraphError):
            demo_graph.build(self.overlay,d)
