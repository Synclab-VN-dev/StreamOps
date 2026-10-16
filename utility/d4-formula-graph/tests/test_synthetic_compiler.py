"""Synthetic #107 DSL three-family #110 regression; no Maxroll formula claims."""
import copy
from pathlib import Path
import sys
import unittest
HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import graph as g
import synthetic_compiler as engine

class ThreeFamilies(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src=g.read_json(HERE/"fixtures"/"synthetic-three-families.json")

    def test_g1_three_families_compose_exact_synthetic_outputs(self):
        x=engine.compose(self.src)
        self.assertEqual(x,engine.compose(self.src))
        self.assertEqual(x["stats"]["synthetic.damageBonus"],30)
        self.assertEqual(x["skills"]["synthetic.projectile"]["projectile_count"],2)
        self.assertEqual({r.get("sourceFamily") for r in x["trace"]},
                         {"active_skill","legendary_aspect","charm_set_bonus"})
        self.assertEqual(x["activeMaxrollFormulaCount"],0)
        self.assertFalse(x["publishAllowed"])
        self.assertEqual(x["maxrollParity"],"BLOCKED_NOT_RUN")
        self.assertEqual(x["manifestSha256"],g.digest({k:v for k,v in x.items()
                                                       if k!="manifestSha256"}))

    def test_conditional_aspect_and_charm_threshold(self):
        f=copy.deepcopy(self.src)
        f["input"]["aspectEquipped"]=False
        f["input"]["charmCount"]=1
        x=engine.compose(f)
        self.assertEqual(x["stats"]["synthetic.damageBonus"],0)
        self.assertEqual(sum(r["status"]=="SKIPPED_CONDITION" for r in x["trace"]),2)
        f["input"]["charmCount"]=2
        self.assertEqual(engine.compose(f)["stats"]["synthetic.damageBonus"],10)

    def test_order_independent_rule_arrangement(self):
        f=copy.deepcopy(self.src)
        f["rules"]=list(reversed(f["rules"]))
        x=engine.compose(self.src);y=engine.compose(f)
        self.assertEqual(x["stats"],y["stats"])
        self.assertEqual(x["skills"],y["skills"])
        self.assertEqual(x["trace"],y["trace"])

    def test_false_verified_and_wrong_patch_block(self):
        f=copy.deepcopy(self.src)
        f["rules"][1]["verification"]["status"]="verified"
        with self.assertRaises(g.GraphError):engine.compose(f)
        f=copy.deepcopy(self.src)
        f["rules"][0]["game"]["buildNumber"]="73883"
        with self.assertRaisesRegex(g.GraphError,"RULE_PATCH_MISMATCH"):engine.compose(f)

    def test_bad_operator_missing_reference_or_fake_real_mode_block(self):
        f=copy.deepcopy(self.src)
        f["rules"][0]["mechanics"][0]["actions"][0]["op"]="python_exec"
        with self.assertRaisesRegex(g.GraphError,"G1_SCHEMA_FAILURE"):engine.compose(f)
        f=copy.deepcopy(self.src)
        f["rules"][1]["mechanics"][0]["when"]={"kind":"ref","scope":"build","path":"notPresent"}
        with self.assertRaisesRegex(g.GraphError,"UNKNOWN_INPUT_REFERENCE"):engine.compose(f)
        f=copy.deepcopy(self.src)
        f["synthetic"]=False
        with self.assertRaisesRegex(g.GraphError,"REAL_RULE_EXECUTION_PROHIBITED"):engine.compose(f)

    def test_partial_family_or_unvalidated_conditions_block(self):
        f=copy.deepcopy(self.src)
        f["rules"][2]["source"]["kind"]="active_skill"
        with self.assertRaisesRegex(g.GraphError,"MISSING_SYNTHETIC_FAMILY"):engine.compose(f)
        f=copy.deepcopy(self.src)
        f["input"]["charmCount"]=-1
        with self.assertRaisesRegex(g.GraphError,"INVALID_SYNTHETIC_INPUT"):engine.compose(f)
