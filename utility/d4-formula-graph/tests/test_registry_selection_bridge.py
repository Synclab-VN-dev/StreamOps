"""#109 selector data may alter metadata only, never #110 raw actual or parity."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import subprocess
import json
import unittest
HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import graph
import registry_selection_bridge as bridge


def fixture(candidate=True):
    cat,h=graph.source_catalog()
    rows=[]
    for metric in sorted(cat["metrics"],key=lambda r:r["metricId"]):
        isfire=candidate and metric["metricId"]=="maxroll.heroDetails.446"
        rows.append({
            "metricId":metric["metricId"],"group":metric["group"],
            "state":"UNVERIFIED" if isfire else "UNKNOWN",
            "candidateId":"synthetic.fire-bounded-candidate" if isfire else None,
            "executableRule":None,"value":None,
            "sourceGrade":metric["formulaVerificationStatus"],
            "reason":"CANDIDATE_G2_G3_G4_NOT_VERIFIED" if isfire else
                     "NO_APPROVED_FORMULA_RULE",
        })
    data={
        "status":"BLOCKED_NO_APPROVED_EXECUTABLE_RULES",
        "artifactType":"INTERNAL_READ_ONLY_RULE_SELECTION_NOT_GRAPH_RESULT",
        "gamePatch":"3.2.1","gameBuild":"73552","classId":"rogue",
        "fixtureFingerprint":cat["fixture"]["inputSnapshotSha256"],
        "registrySnapshotSha256":"f"*64,
        "catalogSha256":h,
        "coverage":{"denominator":50,"missing":49 if candidate else 50,
                    "candidateUnverified":1 if candidate else 0,"activeRules":0,
                    "verifiedGameFormulas":0,"approvedGoldens":0,
                    "realMaxrollParity":"NOT_RUN"},
        "metrics":rows,"sourceOfExpectedGolden":"NOT_INCLUDED",
        "executableRules":[],"simulationContext":None,"publishAllowed":False,
    }
    data["selectionSha256"]=graph.digest(data)
    return data


class SelectorBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.overlay=graph.read_json(HERE/"fixtures"/"synthetic-alpha.json")
    def run_bridge(self,selection=None):
        return bridge.bind(self.overlay,selection if selection is not None else fixture())
    def test_50_rows_one_fire_candidate_other_49_unknown(self):
        a=self.run_bridge()
        self.assertEqual(a,self.run_bridge())
        self.assertEqual(a["ruleCoverage"]["unknown"],49)
        self.assertEqual(a["ruleCoverage"]["candidateUnverified"],1)
        self.assertEqual(len(a["characterMetrics"]),50)
        f=next(x for x in a["characterMetrics"] if x["metricId"]=="maxroll.heroDetails.446")
        self.assertEqual(f["sourceRuleStatus"],"UNVERIFIED")
        self.assertIsNone(f["activeRule"])
        self.assertTrue(all(x["raw"] is None and x["display"] is None
                            for x in a["characterMetrics"]))
        self.assertEqual(a["characterMetricsComputed"],0)
        self.assertEqual(a["realMaxrollParity"],"BLOCKED_NOT_RUN")
        self.assertEqual(a["graphSha256"],graph.digest({k:v for k,v in a.items()
                                                       if k!="graphSha256"}))
    def test_empty_candidate_source_keeps_50_explicit_unknown(self):
        a=self.run_bridge(fixture(False))
        self.assertEqual(a["ruleCoverage"]["unknown"],50)
        self.assertEqual(a["ruleCoverage"]["candidateUnverified"],0)
        self.assertTrue(all(x["sourceRuleStatus"]=="UNKNOWN" for x in a["characterMetrics"]))
    def test_false_active_rule_or_golden_always_rejected(self):
        for key,value in [
            ("executableRules",[{"id":"evil"}]),
            ("sourceOfExpectedGolden","OUTPUT_AS_EXPECTED"),
            ("publishAllowed",True),
            ("simulationContext",{"READY":True}),
        ]:
            d=fixture();d[key]=value;d["selectionSha256"]=graph.digest({
                k:v for k,v in d.items() if k!="selectionSha256"})
            with self.subTest(key=key),self.assertRaises(graph.GraphError):
                self.run_bridge(d)
        d=fixture();d["coverage"]["activeRules"]=1
        d["selectionSha256"]=graph.digest({k:v for k,v in d.items() if k!="selectionSha256"})
        with self.assertRaises(graph.GraphError):self.run_bridge(d)
    def test_source_mutations_rejected_even_with_recomputed_manifest(self):
        for key,value in [
            ("gameBuild","73999"),
            ("fixtureFingerprint","0"*64),
            ("registrySnapshotSha256","wrong"),
            ("catalogSha256","0"*64),
        ]:
            d=fixture();d[key]=value;d["selectionSha256"]=graph.digest({
                k:v for k,v in d.items() if k!="selectionSha256"})
            with self.subTest(key=key),self.assertRaises(graph.GraphError):
                self.run_bridge(d)
    def test_fake_metric_numeric_candidate_or_duplicate_must_fail(self):
        for key,value in [("state","VERIFIED"),("value",123),
                          ("executableRule",{"op":"add"}),
                          ("reason","GATES_PASS")]:
            d=fixture()
            d["metrics"][0][key]=value
            d["selectionSha256"]=graph.digest({
                k:v for k,v in d.items() if k!="selectionSha256"})
            with self.subTest(key=key),self.assertRaises(graph.GraphError):
                self.run_bridge(d)
        d=fixture();d["metrics"][0]["metricId"]=d["metrics"][1]["metricId"]
        d["selectionSha256"]=graph.digest({k:v for k,v in d.items() if k!="selectionSha256"})
        with self.assertRaises(graph.GraphError):self.run_bridge(d)
    def test_selection_checksum_is_enforced(self):
        d=fixture();d["coverage"]["missing"]=48
        with self.assertRaisesRegex(graph.GraphError,"REGISTRY_SELECTION_HASH_MISMATCH"):
            self.run_bridge(d)
        d["selectionSha256"]=graph.digest({
            k:v for k,v in d.items() if k!="selectionSha256"})
        with self.assertRaisesRegex(graph.GraphError,"REGISTRY_SELECTION_COVERAGE_MISMATCH"):
            self.run_bridge(d)
    def test_cli_accepts_synthetic_selection_and_blocks_wrong_patch(self):
        with tempfile.TemporaryDirectory() as d:
            inpath=Path(d)/"selection.json";outpath=Path(d)/"graph.json"
            inpath.write_text(json.dumps(fixture()))
            cmd=[sys.executable,str(HERE/"registry_selection_bridge.py"),
                 "--overlay",str(HERE/"fixtures"/"synthetic-alpha.json"),
                 "--selection",str(inpath),"--report",str(outpath)]
            p=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr+p.stdout)
            self.assertEqual(graph.read_json(outpath)["characterMetricsComputed"],0)
            fake=fixture();fake["gamePatch"]="3.2.2"
            fake["selectionSha256"]=graph.digest({
                k:v for k,v in fake.items() if k!="selectionSha256"})
            inpath.write_text(json.dumps(fake))
            p=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(p.returncode,2)
            self.assertEqual(graph.read_json(outpath)["status"],"BLOCKED")
