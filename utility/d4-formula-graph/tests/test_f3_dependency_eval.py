"""F3 three real observed runtime expressions; outputs UNKNOWN for DEV capture."""
import copy
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import f3_dependency_eval as f
import graph

class F3Bindings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=graph.read_json(ROOT/"fixtures"/"f3-bounded-formula-ast.json")
    def test_real_source_input_unknown_no_zero_or_golden(self):
        d=f.run(self.data,{"mode":"SOURCE_UNKNOWN","values":{}})
        self.assertEqual(len(d["results"]),3)
        self.assertEqual(d["realMaxrollActualComputed"],0)
        self.assertTrue(all(x["characterStatActual"] is None
                            and x["status"].startswith("UNKNOWN")
                            and x["missingRuntimeVariables"]
                            for x in d["results"]))
        self.assertEqual(d["formulaFullVerified"],0)
    def test_bounded_f3_math_synthetic_variables_only(self):
        vv={"Weapon_Speed_Percent_Bonus":0.2,
            "Weapon_Speed_Percent_Reduction":0.1,
            "Dexterity_Total":230.8,
            "Attack_Speed_Percent_Bonus":1.5,
            "Attack_Speed_Percent_Reduction":0.2,
            "Cast_Speed_Percent_Temp_Bonus":0.5,
            "Cast_Speed_Percent_Temp_Reduction":0.1}
        d=f.run(self.data,{"mode":"SYNTHETIC_TEST_ONLY","values":vv})
        m={x["metricId"]:x for x in d["results"]}
        self.assertEqual(m["maxroll.heroDetails.111"]["trialOnly"],230)
        self.assertAlmostEqual(m["maxroll.heroDetails.114"]["trialOnly"],1.1)
        self.assertAlmostEqual(m["maxroll.heroDetails.3"]["trialOnly"],1.4)
        self.assertEqual(d["realMaxrollActualComputed"],0)
        self.assertTrue(all(x["characterStatActual"] is None for x in d["results"]))
    def test_no_zero_substitution_for_missing_deps(self):
        d=f.run(self.data,{"mode":"SYNTHETIC_TEST_ONLY",
                           "values":{"Weapon_Speed_Percent_Bonus":0.2}})
        self.assertTrue(all(x["trialOnly"] is None for x in d["results"]))
    def test_true_source_rejects_value_forgery(self):
        with self.assertRaisesRegex(graph.GraphError,"REAL_VARIABLE_VALUES_NOT_PROVEN"):
            f.run(self.data,{"mode":"SOURCE_UNKNOWN","values":{"Dexterity_Total":230}})
    def test_formula_ast_and_patch_cannot_be_replaced(self):
        for mutation in ("patch","source","fake_metric","unknown_ref","extra"):
            data=copy.deepcopy(self.data)
            if mutation=="patch":data["patch"]="3.2.3"
            if mutation=="source":data["sourceCommit"]="foobar"
            if mutation=="fake_metric":data["formulas"][0]["f3EvidenceStatus"]="VERIFIED"
            if mutation=="unknown_ref":data["formulas"][0]["ast"]={"ref":"Golden_Expected"}
            if mutation=="extra":data["formulas"][0]["ast"]["extra"]=1
            with self.subTest(mutation=mutation),self.assertRaises(graph.GraphError):
                f.run(data,{"mode":"SOURCE_UNKNOWN","values":{}})
    def test_no_cross_class_f3_reuse(self):
        with self.assertRaisesRegex(graph.GraphError,"F3_CLASS_FIXTURE_SCOPE_MISMATCH"):
            f.run(self.data,{"mode":"SOURCE_UNKNOWN","values":{}},fixture="DEV-01")
