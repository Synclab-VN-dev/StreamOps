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
        f["input"]["equippedItems"]=[]
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


    def test_ci02_item_variant_rune_charm_and_rank_are_data_driven(self):
        reference=engine.compose(self.src)
        cases=[
            ("remove_item","equippedItems",[],10,2),
            ("add_other_item","equippedItems",["synthetic.item.other"],10,2),
            ("variant_beta","variant","synthetic.beta",30,1),
            ("remove_rune","runeCount",0,20,2),
            ("remove_charm_set","charmCount",1,20,2),
            ("rank_up","skillRank",2,30,3),
        ]
        for case,key,value,expected_bonus,expected_projectile in cases:
            with self.subTest(case=case):
                other=copy.deepcopy(self.src)
                other["input"][key]=value
                out=engine.compose(other)
                self.assertEqual(out["stats"]["synthetic.damageBonus"],expected_bonus)
                self.assertEqual(out["skills"]["synthetic.projectile"]["projectile_count"],
                                 expected_projectile)
                self.assertNotEqual(reference["manifestSha256"],out["manifestSha256"])
                self.assertEqual(out["activeMaxrollFormulaCount"],0)
                self.assertEqual(out["maxrollParity"],"BLOCKED_NOT_RUN")

    def test_ci02_bad_item_list_variant_rune_and_rank_fail_closed(self):
        for key,value in [
            ("equippedItems",["synthetic.item.aspect-a","synthetic.item.aspect-a"]),
            ("equippedItems",["actual.user_item"]),
            ("equippedItems",["synthetic.item.z","synthetic.item.a"]),
            ("variant","ChargeBolt"),
            ("variant","synthetic.gamma"),
            ("runeCount",-1),
            ("runeCount",True),
            ("skillRank",2.5),
            ("skillRank",999),
        ]:
            d=copy.deepcopy(self.src)
            d["input"][key]=value
            with self.subTest(key=key,value=value):
                with self.assertRaisesRegex(g.GraphError,"INVALID_SYNTHETIC_INPUT"):
                    engine.compose(d)

    def test_ci02_unsupported_source_dsl_expression_stays_blocked(self):
        d=copy.deepcopy(self.src)
        d["rules"][0]["mechanics"][0]["actions"][0]["value"]={
            "kind":"call","fn":"lookup","args":[{"kind":"literal","value":"a"}]}
        with self.assertRaisesRegex(g.GraphError,"UNSUPPORTED_FUNCTION_OR_ARITY"):
            engine.compose(d)
