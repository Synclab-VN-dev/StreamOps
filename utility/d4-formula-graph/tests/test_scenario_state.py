"""#110 Dev F F-INPUT-01 four unknown scenario states remain unknown in Graph."""
from __future__ import annotations
import copy
from pathlib import Path
import sys
import tempfile
import subprocess
import json
import unittest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import graph
import scenario_state as s
import scenario_graph


class ScenarioTruthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.unknown=graph.read_json(HERE/"fixtures"/"maxroll-unobserved-scenario.json")
        cls.fake=graph.read_json(HERE/"fixtures"/"synthetic-known-scenario.json")
        cls.overlay=graph.read_json(HERE/"fixtures"/"synthetic-alpha.json")

    def test_all_four_source_fields_explicitly_unknown(self):
        x=s.gate_trace(self.unknown,s.REFERENCE_GATES)
        self.assertEqual(x,s.gate_trace(self.unknown,s.REFERENCE_GATES))
        self.assertEqual(x["truthCoverage"]["unknown"],4)
        self.assertEqual(x["truthCoverage"]["knownSynthetic"],0)
        self.assertEqual(x["truthCoverage"]["knownReal"],0)
        self.assertEqual(len(x["trace"]),4)
        self.assertTrue(all(y["result"]=="UNKNOWN" and
                            y["effectExecution"]=="BLOCKED_UNKNOWN_CONDITION"
                            and not y["realFormulaExecuted"] for y in x["trace"]))
        self.assertIsNone(x["maxrollFormulaValues"])
        self.assertFalse(x["publishAllowed"])
        self.assertEqual(x["traceSha256"],graph.digest(
            {k:v for k,v in x.items() if k!="traceSha256"}))

    def test_bounded_boolean_tristate_never_coerces_unknown_to_false(self):
        self.assertEqual(s.tri_and([s.TRUE,s.UNKNOWN]),s.UNKNOWN)
        self.assertEqual(s.tri_and([s.FALSE,s.UNKNOWN]),s.FALSE)
        self.assertEqual(s.tri_or([s.FALSE,s.UNKNOWN]),s.UNKNOWN)
        self.assertEqual(s.tri_or([s.TRUE,s.UNKNOWN]),s.TRUE)
        self.assertEqual(s.evaluate_condition(self.unknown,{
            "op":"and","conditions":[s.REFERENCE_GATES["target_vulnerable"],
                                     s.REFERENCE_GATES["proc_active"]]}),s.UNKNOWN)

    def test_synthetic_known_cases_do_not_promote_real_formula_values(self):
        a=s.gate_trace(self.fake,s.REFERENCE_GATES)
        self.assertEqual(a["truthCoverage"]["knownSynthetic"],4)
        self.assertEqual(a["truthCoverage"]["knownReal"],0)
        self.assertTrue(all(x["result"]==s.TRUE for x in a["trace"]))
        self.assertFalse(a["approvedScenario"])
        self.assertFalse(a["publishAllowed"])
        actual=scenario_graph.build(self.overlay,self.fake)
        self.assertEqual(actual["characterMetricsComputed"],0)
        self.assertEqual(actual["characterMetricsUnknown"],50)
        self.assertIsNone(actual["simulationContext"])
        self.assertTrue(all(r["raw"] is None for r in actual["characterMetrics"]))

    def test_two_scenarios_change_hash_but_never_change_real_stats(self):
        base=scenario_graph.build(self.overlay,self.unknown)
        fake=scenario_graph.build(self.overlay,self.fake)
        self.assertNotEqual(base["graphSha256"],fake["graphSha256"])
        self.assertEqual(base,scenario_graph.build(self.overlay,self.unknown))
        self.assertEqual(base["scenarioTruthCoverage"]["unknown"],4)
        self.assertEqual(fake["scenarioTruthCoverage"]["knownSynthetic"],4)
        self.assertEqual(base["sourceGraphSha256"],fake["sourceGraphSha256"])
        self.assertEqual(base["characterMetrics"],fake["characterMetrics"])
        self.assertEqual(base["graphSha256"],graph.digest({
            k:v for k,v in base.items() if k!="graphSha256"}))

    def test_missing_field_and_extra_field_fail_closed(self):
        d=copy.deepcopy(self.unknown)
        del d["fields"][s.FIELDS[0]]
        with self.assertRaisesRegex(graph.GraphError,"MISSING_OR_UNEXPECTED"):
            s.validate(d)
        d=copy.deepcopy(self.unknown)
        d["fields"]["conditional.injected"]={"state":"UNKNOWN","value":None,
                                               "evidenceStatus":"NOT_OBSERVED_IN_STATIC_PLANNER"}
        with self.assertRaisesRegex(graph.GraphError,"MISSING_OR_UNEXPECTED"):
            s.validate(d)

    def test_unapproved_real_known_even_with_apparently_good_value(self):
        d=copy.deepcopy(self.unknown)
        d["fields"][s.FIELDS[0]]=copy.deepcopy(self.fake["fields"][s.FIELDS[0]])
        with self.assertRaisesRegex(graph.GraphError,"UNVERIFIED_RUNTIME_SCENARIO_PROMOTION"):
            s.validate(d)
        d=copy.deepcopy(self.fake)
        d["fields"][s.FIELDS[0]]["state"]="KNOWN_REAL"
        with self.assertRaisesRegex(graph.GraphError,"UNVERIFIED_RUNTIME_SCENARIO_PROMOTION"):
            s.validate(d)

    def test_null_unknown_must_not_hide_numeric_value(self):
        d=copy.deepcopy(self.unknown)
        d["fields"][s.FIELDS[0]]["value"]={"vulnerable":False}
        with self.assertRaisesRegex(graph.GraphError,"UNKNOWN_FIELD_MUST_HAVE_NULL"):
            s.validate(d)

    def test_typed_validators_boolean_integer_ratio_time(self):
        for field,key,value in [
            (s.FIELDS[0],"vulnerable",1),
            (s.FIELDS[1],"uptimeRatio",1.01),
            (s.FIELDS[1],"procActive",0),
            (s.FIELDS[2],"ferocity",-1),
            (s.FIELDS[2],"blackSoulstoneSouls",0.5),
            (s.FIELDS[3],"snapshotSeconds",float("nan")),
            (s.FIELDS[3],"elapsedSeconds",-1),
        ]:
            d=copy.deepcopy(self.fake)
            d["fields"][field]["value"][key]=value
            with self.subTest(field=field,key=key,value=value):
                with self.assertRaises(graph.GraphError):
                    s.validate(d)
        d=copy.deepcopy(self.fake)
        d["fields"][s.FIELDS[3]]["value"]["snapshotSeconds"]=20
        with self.assertRaisesRegex(graph.GraphError,"SCENARIO_SNAPSHOT_AFTER_CURRENT_TIME"):
            s.validate(d)

    def test_wrong_patch_class_fingerprint_and_false_observation_rejected(self):
        for key,value in [("gamePatch","3.2.2"),("gameBuild","73900"),
                          ("classId","sorcerer"),("sourceFixtureFingerprint","0"*64),
                          ("mode","MAXROLL_RUNTIME_VERIFIED")]:
            d=copy.deepcopy(self.unknown);d[key]=value
            with self.subTest(key=key),self.assertRaises(graph.GraphError):
                s.validate(d)
        d=copy.deepcopy(self.unknown)
        d["fields"][s.FIELDS[1]]["evidenceStatus"]="OWNER_APPROVED"
        with self.assertRaises(graph.GraphError):
            s.validate(d)

    def test_unknown_invalid_references_fail_closed(self):
        for cond in [
            {"op":"equals","field":s.FIELDS[0],"key":"invented","expected":True},
            {"op":"equals","field":s.FIELDS[0],"key":"vulnerable","expected":1},
            {"op":"eval","code":"__import__('os').system('echo')"},
            {"op":"and","conditions":[]},
        ]:
            with self.subTest(expr=cond),self.assertRaises(graph.GraphError):
                s.evaluate_condition(self.unknown,cond)

    def test_cli_fails_closed_when_source_context_is_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/"scenario.json"
            cmd=[sys.executable,str(HERE/"scenario_graph.py"),
                 "--overlay",str(HERE/"fixtures"/"synthetic-alpha.json"),
                 "--scenario",str(HERE/"fixtures"/"maxroll-unobserved-scenario.json"),
                 "--report",str(out)]
            p=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr+p.stdout)
            obj=json.loads(out.read_text())
            self.assertEqual(obj["characterMetricsComputed"],0)
            self.assertEqual(obj["scenarioTruthCoverage"]["unknown"],4)
            bad=copy.deepcopy(self.unknown)
            bad["gamePatch"]="3.2.2"
            wrong=Path(tmp)/"wrong.json";wrong.write_text(json.dumps(bad))
            p=subprocess.run(cmd[:5]+[str(wrong)]+cmd[6:],
                             capture_output=True,text=True)
            self.assertEqual(p.returncode,2)
            self.assertEqual(json.loads(out.read_text())["status"],"BLOCKED")
