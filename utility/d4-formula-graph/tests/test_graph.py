"""#110 preliminary graph result cannot borrow expected Golden or publish 0-valued metrics."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import graph as g


class GraphSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog,cls.sha=g.source_catalog()
        cls.a=g.read_json(HERE/"fixtures"/"synthetic-alpha.json")
        cls.b=g.read_json(HERE/"fixtures"/"synthetic-beta.json")

    def build(self,overlay=None):
        return g.build_graph(self.catalog,self.sha,self.a if overlay is None else overlay)

    def test_full_50_visible_metrics_unknown_not_calculated(self):
        o=self.build()
        self.assertEqual(o["status"],"BLOCKED_NO_VERIFIED_MAXROLL_RULES")
        self.assertEqual(o["coverage"]["identified"],50)
        self.assertEqual(o["coverage"]["computed"],0)
        self.assertEqual(o["coverage"]["unknown"],50)
        self.assertEqual(len(o["characterMetrics"]),50)
        self.assertEqual(len({x["metricId"] for x in o["characterMetrics"]}),50)
        self.assertEqual(len(o["metricNodes"]),50)
        self.assertEqual(o["observedDependencyEdges"],[])
        self.assertTrue(all(x["status"]=="UNKNOWN" and x["raw"] is None
                            and x["display"] is None and not x["computed"]
                            and x["unit"] is None for x in o["characterMetrics"]))
        self.assertIsNone(o["simulationContext"])
        self.assertFalse(o["expectedMaxrollValuesIncluded"])
        self.assertFalse(o["runExecutableCandidates"])
        self.assertEqual(o["graphSha256"],g.digest({k:v for k,v in o.items()
                                                   if k!="graphSha256"}))

    def test_same_graph_hash_and_two_independent_synthetic_overlays(self):
        a=self.build()
        self.assertEqual(a,self.build())
        b=self.build(self.b)
        self.assertNotEqual(a["graphSha256"],b["graphSha256"])
        self.assertNotEqual(a["syntheticOverlaySha256"],b["syntheticOverlaySha256"])
        self.assertEqual(a["coverage"],b["coverage"])
        self.assertTrue(all(x["status"]=="UNKNOWN" for x in b["characterMetrics"]))

    def test_changed_equipment_skill_set_affects_hash_but_does_not_invent_values(self):
        previous=self.build()
        for key,name,value in [("equipment","mainHand","synthetic.other"),
                               ("skills","synthetic.projectile",4),
                               ("charms","synthetic.set",3)]:
            b=deepcopy(self.a)
            b[key][name]=value
            with self.subTest(key=key):
                o=self.build(b)
                self.assertNotEqual(previous["graphSha256"],o["graphSha256"])
                self.assertEqual(o["coverage"]["computed"],0)

    def test_wrong_patch_class_input_fingerprint_and_expected_injection(self):
        for key,bad in [("gamePatch","3.2.3"),
                        ("gameBuild","73883"),("classId","sorcerer"),
                        ("sourceFixtureFingerprint","f"*64)]:
            d=deepcopy(self.a)
            d[key]=bad
            with self.subTest(key=key),self.assertRaises(g.GraphError):
                self.build(d)
        d=deepcopy(self.a)
        d["context"]["maxrollExpected"]=123
        with self.assertRaisesRegex(g.GraphError,"SOURCE_EXPECTED_AS_ACTUAL_FORBIDDEN"):
            self.build(d)

    def test_invalid_rank_and_wrong_transport_shape_rejected(self):
        d=deepcopy(self.a)
        d["skills"]["synthetic.projectile"]=-1
        with self.assertRaisesRegex(g.GraphError,"INVALID_SYNTHETIC_SKILL_RANK"):
            self.build(d)
        d=deepcopy(self.a)
        d["characterMetrics"]=[{"value":9000}]
        with self.assertRaisesRegex(g.GraphError,"INVALID_BUILD_FIELDS"):
            self.build(d)

    def test_generic_topological_sort_and_cycle_missing_ref_fails_closed(self):
        self.assertEqual(g.topological_sort(["attack","damage","bonus"],
                                             [["attack","damage"],["bonus","damage"]]),
                         ["attack","bonus","damage"])
        with self.assertRaisesRegex(g.GraphError,"GRAPH_DEPENDENCY_CYCLE"):
            g.topological_sort(["A","B"],[["A","B"],["B","A"]])
        with self.assertRaisesRegex(g.GraphError,"UNRESOLVED_GRAPH_REFERENCE"):
            g.topological_sort(["A"],[["A","B"]])
        with self.assertRaisesRegex(g.GraphError,"GRAPH_DEPENDENCY_CYCLE"):
            g.topological_sort(["A"],[["A","A"]])

    def test_cli_report_explicitly_blocked_truth_without_failure_to_emit(self):
        with tempfile.TemporaryDirectory() as d:
            output=Path(d)/"graph.json"
            cmd=[sys.executable,str(HERE/"graph.py"),"--overlay",
                 str(HERE/"fixtures"/"synthetic-alpha.json"),"--report",str(output)]
            r=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr+r.stdout)
            self.assertEqual(g.read_json(output)["status"],
                             "BLOCKED_NO_VERIFIED_MAXROLL_RULES")
            b=json.loads((HERE/"fixtures"/"synthetic-beta.json").read_text())
            b["gamePatch"]="3.2.3"
            wrong=Path(d)/"wrong.json"
            wrong.write_text(json.dumps(b))
            r=subprocess.run(cmd[:3]+[str(wrong)]+cmd[4:],
                             capture_output=True,text=True)
            self.assertEqual(r.returncode,2)
            self.assertEqual(g.read_json(output)["status"],"BLOCKED")
