"""Source-backed Strength working model tests. Golden is compared only after
source-only evaluation and is never injected into Formula Graph inputs.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import sys
import unittest
HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import graph
import strength_model

ROOT=HERE/"fixtures"
def read(name):return graph.read_json(ROOT/name)

class StrengthWorkingModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=read("dev00-source-sanitized.json")
        cls.paragon=read("dev00-paragon-tooltip-source.json")
        cls.rules=read("strength-rogue-research-rules.json")

    def calc(self,**changed):
        args={"source":self.source,"paragon_witness":self.paragon,
              "rules":self.rules}
        args.update(changed)
        return strength_model.evaluate(**args)

    def test_source_derived_nonduplicate_strength(self):
        out=self.calc()
        self.assertEqual(out["metricId"],"maxroll.heroDetails.108")
        self.assertEqual(out["candidateRaw"],349)
        self.assertFalse(out["candidateIsCompleteActual"])
        self.assertFalse(out["goldenVerified"])
        self.assertFalse(out["publishAllowed"])
        d=out["decomposition"]
        self.assertEqual(d["observedNaiveTooltipTotal"],339)
        self.assertEqual(d["nonSocketNodeFlatSubtotal"],253)
        self.assertEqual(d["observedGateEndpoints"],8)
        self.assertEqual(d["creditedGateConnections"],4)
        self.assertEqual(d["displayedGateEndpointSubtotalExcludedAsDuplicate"],20)
        self.assertEqual(d["observedGlyphSocketStrengthSummariesExcluded"],46)
        self.assertEqual(d["effectiveFlatSubtotal"],273)
        self.assertEqual(d["classBaseLevelSubtotal"],76)
        self.assertEqual([x["value"] for x in out["components"]],[76,273])
        self.assertEqual(len(out["missingContributorFamilies"]),5)
        self.assertEqual(out,self.calc())

    def test_strength_node_change_is_causal_without_rewriting_other_nodes(self):
        p=deepcopy(self.paragon)
        node=next(n for n in p["nodes"] if n["tooltip"]=="Normal Node\n+5 Strength")
        node["tooltip"]="Normal Node\n+7 Strength"
        out=self.calc(paragon_witness=p)
        self.assertEqual(out["candidateRaw"],351)
        self.assertEqual(out["decomposition"]["effectiveFlatSubtotal"],275)
        self.assertNotEqual(out["reportSha256"],self.calc()["reportSha256"])

    def test_glyph_socket_summary_is_not_a_second_grant(self):
        p=deepcopy(self.paragon)
        node=next(n for n in p["nodes"] if (n["tooltip"] or "").startswith("Glyph Socket\n")
                  and "+46 Strength" in n["tooltip"])
        node["tooltip"]=node["tooltip"].replace("+46 Strength","+58 Strength")
        out=self.calc(paragon_witness=p)
        self.assertEqual(out["candidateRaw"],349)
        self.assertEqual(out["decomposition"]["observedGlyphSocketStrengthSummariesExcluded"],58)

    def test_gate_inconsistent_or_class_wrong_is_blocked(self):
        p=deepcopy(self.paragon)
        gate=next(n for n in p["nodes"] if "d4t-gate" in n["className"])
        gate["className"]=gate["className"].replace("d4t-gate","d4t-r1")
        with self.assertRaisesRegex(graph.GraphError,"GATE_PAIRS"):
            self.calc(paragon_witness=p)
        profile=deepcopy(self.source)
        profile["fixture"]["class"]="Sorcerer"
        with self.assertRaises(graph.GraphError):
            self.calc(source=profile)

    def test_expected_contamination_and_false_promotion_blocked(self):
        contaminated=deepcopy(self.source)
        contaminated["expectedRawValue"]=418
        with self.assertRaisesRegex(graph.GraphError,"GOLDEN"):
            self.calc(source=contaminated)
        rules=deepcopy(self.rules)
        rules["verification"]="VERIFIED"
        with self.assertRaisesRegex(graph.GraphError,"UNPROVEN"):
            self.calc(rules=rules)

    def test_independent_original_dev_golden_diagnostic_is_mismatch_not_verified(self):
        # Golden file is read strictly AFTER source-only Actual is finished.
        actual=self.calc()
        original=(ROOT/"golden-dev"/"dev00-original-50.json").read_bytes()
        sha=hashlib.sha1(b"blob "+str(len(original)).encode()+b"\0"+original).hexdigest()
        self.assertEqual(sha,"6220f636f66c9d113c0b41f13480d09d7bed4dc0")
        golden=json.loads(original)
        self.assertEqual(golden["fixture"]["inputSnapshotSha256"],
                         actual["inputFingerprintSha256"])
        strength=next(x for x in golden["metrics"] if x["metricId"]==actual["metricId"])
        self.assertEqual(strength["expectedRawValue"],418)
        self.assertEqual(strength["expectedDisplayValue"],"418")
        self.assertEqual(actual["candidateRaw"]-strength["expectedRawValue"],-69)
        self.assertFalse(actual["goldenVerified"])

if __name__=="__main__":
    unittest.main()
