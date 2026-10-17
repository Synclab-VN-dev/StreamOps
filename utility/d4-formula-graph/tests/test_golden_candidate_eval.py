"""Tests candidate actual from two Maxroll *source input shapes*, never Golden output."""
from copy import deepcopy
import json
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import graph
import golden_candidate_eval as evaluator

class DevelopmentCandidate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules=graph.read_json(HERE/"fixtures"/"candidate-source-level.json")
        cls.cases=[
            (graph.read_json(HERE/"fixtures"/"dev00-source-sanitized.json"),
             graph.read_json(HERE/"fixtures"/"dev00-visible-inventory.json"),50,50),
            (graph.read_json(HERE/"fixtures"/"dev01-source-sanitized.json"),
             graph.read_json(HERE/"fixtures"/"dev01-visible-inventory.json"),49,47),
        ]
    def test_dev_source_shapes_compute_one_actual_not_full_parity(self):
        for source,inventory,rows,unique in self.cases:
            with self.subTest(fixture=inventory["fixtureId"]):
                out=evaluator.build(source,inventory,self.rules)
                self.assertEqual(out["sourceRowCount"],rows)
                self.assertEqual(out["uniqueMetricCount"],unique)
                self.assertEqual(out["computedUniqueMetricCount"],1)
                self.assertEqual(out["computedDisplayRowCount"],1)
                actual=next(x for x in out["characterMetrics"]
                            if x["metricId"]==evaluator.LEVEL_ID)
                self.assertEqual(actual["raw"],source.get("level",
                    source.get("fixture",{}).get("level",70)))
                self.assertEqual(actual["status"],"CANDIDATE_COMPUTED_UNVERIFIED")
                self.assertEqual(out["verifiedMetrics"],0)
                self.assertEqual(out["maxrollParity"],"NOT_RUN")
                self.assertFalse(out["publishAllowed"])
                self.assertFalse(out["sourceExpectedImported"])
                self.assertEqual(out, evaluator.build(source,inventory,self.rules))
    def test_changed_input_changes_actual_and_hash_not_golden(self):
        source,index,_,_=self.cases[1]
        a=evaluator.build(source,index,self.rules)
        b=deepcopy(source)
        b["activeProfile"]["level"]=71
        b["level"]=71
        c=evaluator.build(b,index,self.rules)
        self.assertNotEqual(a["graphSha256"],c["graphSha256"])
        v=next(x for x in c["characterMetrics"] if x["metricId"]==evaluator.LEVEL_ID)
        self.assertEqual(v["raw"],71)
        self.assertEqual(v["display"],"71")
    def test_duplicate_metric_id_across_groups_preserves_two_rows(self):
        _,index,_,_=self.cases[1]
        ids=[x for x in index["metrics"] if x["metricId"]=="maxroll.heroDetails.431"]
        self.assertEqual(len(ids),2)
        self.assertEqual({x["group"] for x in ids},{"Resistances","Defensive"})
        self.assertEqual(len({(x["metricId"],x["group"]) for x in index["metrics"]}),49)
        self.assertEqual(len({x["metricId"] for x in index["metrics"]}),47)
    def test_no_holdout_and_no_source_expected_leak(self):
        src,idx,_,_=self.cases[0]
        d=deepcopy(idx);d["partition"]="HOLDOUT"
        with self.assertRaisesRegex(graph.GraphError,"HOLDOUT_EXPECTED"):
            evaluator.build(src,d,self.rules)
        d=deepcopy(src);d["expectedRawValue"]=70
        with self.assertRaisesRegex(graph.GraphError,"GOLDEN_EXPECTED_IN_GRAPH_INPUT"):
            evaluator.build(d,idx,self.rules)
        d=deepcopy(idx);d["metrics"][0]["raw"]=70
        with self.assertRaisesRegex(graph.GraphError,"INVALID_METRIC_INVENTORY_ROW"):
            evaluator.build(src,d,self.rules)
    def test_patch_hash_class_and_false_completeness_block(self):
        src,idx,_,_=self.cases[1]
        for field,value in [("patch","3.2.3"),("completeness","COMPLETE"),
                            ("level",15),("fingerprints",{"fullInputSha256":"0"*64})]:
            d=deepcopy(src)
            d[field]=value
            if field=="level":d["activeProfile"]["level"]=70
            with self.subTest(field=field),self.assertRaises(graph.GraphError):
                evaluator.build(d,idx,self.rules)
        d=deepcopy(src);d["activeProfile"]["class"]=3
        with self.assertRaisesRegex(graph.GraphError,"SOURCE_CLASS_MISMATCH"):
            evaluator.build(d,idx,self.rules)
    def test_one_position_duplicate_and_label_conflict_fail(self):
        src,idx,_,_=self.cases[1]
        for mutation in ("same_group","different_label"):
            d=deepcopy(idx)
            if mutation=="same_group":d["metrics"].append(deepcopy(d["metrics"][0]))
            else:
                a=next(x for x in d["metrics"] if x["metricId"]=="maxroll.heroDetails.431")
                a["label"]="Changed Armor Identity"
            with self.subTest(mutation=mutation),self.assertRaises(graph.GraphError):
                evaluator.build(src,d,self.rules)
    def test_reject_false_verified_or_unsupported_ast_or_rule(self):
        src,idx,_,_=self.cases[1]
        for change in ("verified","expected_literal","wrong_target","extra_action"):
            rr=deepcopy(self.rules)
            if change=="verified":rr[0]["verification"]["status"]="verified"
            if change=="expected_literal":rr[0]["mechanics"][0]["actions"][0]["value"]={
                "kind":"literal","value":70}
            if change=="wrong_target":rr[0]["mechanics"][0]["actions"][0]["stat"]="maxroll.heroDetails.900"
            if change=="extra_action":rr[0]["mechanics"][0]["actions"].append(
                deepcopy(rr[0]["mechanics"][0]["actions"][0]))
            with self.subTest(change=change):
                if change=="expected_literal":
                    # literal is schema-valid but forbidden as a source-backed rule.
                    with self.assertRaisesRegex(graph.GraphError,
                                                "CANDIDATE_SOURCE_VALUE_MUST_BE_REF_LEVEL"):
                        # A hardcoded known value is not allowed for level.
                        evaluator.build(src,idx,rr)
                else:
                    with self.assertRaises(graph.GraphError):
                        evaluator.build(src,idx,rr)
    def test_cli_output_and_nonzero_failed_patch(self):
        src,idx,_,_=self.cases[0]
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            for name,val in (("src",src),("idx",idx),("rules",self.rules)):
                (root/(name+".json")).write_text(json.dumps(val))
            cmd=[sys.executable,str(HERE/"golden_candidate_eval.py"),
                 "--source",str(root/"src.json"),"--inventory",str(root/"idx.json"),
                 "--rules",str(root/"rules.json"),"--report",str(root/"actual.json")]
            p=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr+p.stdout)
            self.assertEqual(graph.read_json(root/"actual.json")["computedUniqueMetricCount"],1)
            wrong=deepcopy(src);wrong["fixture"]["gameVersion"]="3.2.2"
            (root/"src.json").write_text(json.dumps(wrong))
            p=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(p.returncode,2)
            self.assertEqual(graph.read_json(root/"actual.json")["status"],"BLOCKED")
