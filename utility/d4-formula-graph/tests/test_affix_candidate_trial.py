"""Affix roll witnesses from F-GOLDEN DEV-00, interaction hypothesis never stat."""
import copy
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import graph
import affix_candidate_trial as a

class AffixWitness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=graph.read_json(ROOT/"fixtures"/"dev00-affix-source-witness.json")
        cls.h=graph.read_json(ROOT/"fixtures"/"dev00-affix-interaction-hypothesis.json")
    def test_real_witness_roll_provenance_but_hypothesis_not_actual(self):
        got=a.run(self.source,self.h)
        self.assertAlmostEqual(got["trialValueNotStatActual"],100)
        self.assertIsNone(got["maxrollMetricActual"])
        self.assertFalse(got["completeContributorCoverage"])
        self.assertFalse(got["realFormulaVerified"])
        self.assertFalse(got["publishAllowed"])
        self.assertEqual(got["status"],"HYPOTHETICAL_ONLY_NOT_GAME_FORMULA")
        self.assertEqual(got,a.run(self.source,self.h))
    def test_changed_roll_changes_interaction_not_maxroll_stat(self):
        w=copy.deepcopy(self.source)
        w["items"][0]["explicits"][1]["values"][0]=0.2
        z=a.run(w,self.h)
        self.assertAlmostEqual(z["trialValueNotStatActual"],200)
        self.assertIsNone(z["maxrollMetricActual"])
    def test_remove_multiplier_reveals_source_is_not_independently_verified(self):
        w=copy.deepcopy(self.source)
        w["items"][0]["explicits"]=w["items"][0]["explicits"][1:]
        result=a.run(w,self.h)
        self.assertAlmostEqual(result["trialValueNotStatActual"],10)
        self.assertFalse(result["realFormulaVerified"])
    def test_missing_numerator_does_not_become_zero(self):
        w=copy.deepcopy(self.source)
        w["items"][0]["explicits"]=w["items"][0]["explicits"][:1]
        out=a.run(w,self.h)
        self.assertIsNone(out["trialValueNotStatActual"])
        self.assertEqual(out["status"],"MISSING_SOURCE_CONTRIBUTOR_UNKNOWN")
    def test_reject_false_provenance_or_bad_roll(self):
        for m in ("patch","partition","scope","nan","duplicate"):
            w=copy.deepcopy(self.source)
            if m=="patch":w["patch"]="3.2.3"
            if m=="partition":w["partition"]="HOLDOUT"
            if m=="scope":w["scope"]="ALL_CONTRIBUTORS_VERIFIED"
            if m=="nan":w["items"][0]["explicits"][0]["values"][0]=float("nan")
            if m=="duplicate":w["items"][0]["explicits"].append(
                copy.deepcopy(w["items"][0]["explicits"][0]))
            with self.subTest(m=m),self.assertRaises(graph.GraphError):
                a.run(w,self.h)
    def test_rule_cannot_promote_to_prod_or_claim_unit(self):
        for k,v in [("mode","VERIFIED"),("unit","dexterity"),
                    ("numeratorRollIndex",99),("numeratorScale",float("inf"))]:
            d=copy.deepcopy(self.h);d[k]=v
            with self.subTest(k=k),self.assertRaises(graph.GraphError):
                a.run(self.source,d)
