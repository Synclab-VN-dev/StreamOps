"""Real F3 source UI-only, not a Golden expected or product stat fixture."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
import graph
import primary_paragon_source as layer

class RealParagonSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=graph.read_json(BASE/"fixtures"/"dev00-paragon-tooltip-source.json")
    def test_actual_observed_node_contributions_are_not_full_stat(self):
        r=layer.capture(self.source)
        self.assertEqual(r["activeNodeCount"],270)
        self.assertGreater(r["observedFlatAttributeLineCount"],100)
        self.assertEqual(r["observedParagonUiFlatSums"],
            {"Strength":339.0,"Intelligence":413.0,
             "Willpower":75.0,"Dexterity":569.0})
        self.assertTrue(all(x is None for x in r["characterStatActual"].values()))
        self.assertEqual(r["verifiedUniqueMetricIdsAdded"],0)
        self.assertFalse(r["independentGoldenCompared"])
        self.assertFalse(r["publishAllowed"])
        self.assertEqual(r,layer.capture(self.source))
    def test_change_observed_line_changes_only_partial_contribution(self):
        source=deepcopy(self.source)
        row=next(x for x in source["nodes"] if x["tooltip"]=="Normal Node\n+5 Strength")
        row["tooltip"]="Normal Node\n+7 Strength"
        before=layer.capture(self.source)
        after=layer.capture(source)
        self.assertEqual(after["observedParagonUiFlatSums"]["Strength"],
                         before["observedParagonUiFlatSums"]["Strength"]+2)
        self.assertNotEqual(after["sourceProjectionSha256"],
                            before["sourceProjectionSha256"])
        self.assertIsNone(after["characterStatActual"]["Strength"])
    def test_missing_or_forged_source_fail_closed(self):
        for mutation in ("nodes","blob","patch","expected","inactive","position"):
            v=deepcopy(self.source)
            if mutation=="nodes":v["nodes"].pop()
            if mutation=="blob":v["source"]["gitBlobSha"]="0"*40
            if mutation=="patch":v["patch"]="3.2.3"
            if mutation=="expected":v["expectedRawValue"]=418
            if mutation=="inactive":v["nodes"][0]["className"]="d4t-node"
            if mutation=="position":v["nodes"][1]["index"]=0
            with self.subTest(mutation=mutation),self.assertRaises(graph.GraphError):
                layer.capture(v)
    def test_semantic_extra_lines_never_become_flat_core_stats(self):
        v=deepcopy(self.source)
        v["nodes"][0]["tooltip"]="Board Attachment Gate\n+5 Strength\n+30% Strength\nBonus: +100 Strength if condition met"
        r=layer.capture(v)
        self.assertEqual(r["observedParagonUiFlatSums"]["Strength"],
                         layer.capture(self.source)["observedParagonUiFlatSums"]["Strength"])
        self.assertTrue(r["unclassifiedAttributeLines"])
