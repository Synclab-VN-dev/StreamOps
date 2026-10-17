"""Two independently captured DEV source inventories: G4 coverage fail-closed."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import graph
import dev_source_graph
import golden_candidate_eval
import g4_source_audit as gate
class AuditG4(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f=[]
        rule=graph.read_json(ROOT/"fixtures"/"candidate-source-level.json")
        for name in ("dev00","dev01"):
            source=graph.read_json(ROOT/"fixtures"/(name+"-mechanics.json"))
            rolls=graph.read_json(ROOT/"fixtures"/(name+"-source-rolls.json"))
            inventory=graph.read_json(ROOT/"fixtures"/(name+"-visible-inventory.json"))
            computed=dev_source_graph.build(source,rolls,inventory,rule)
            cls.f.append((inventory,computed))
    @staticmethod
    def rehash(a):
        a["graphSha256"]=graph.digest({k:v for k,v in a.items() if k!="graphSha256"})
    def test_exact_two_development_group_denominators(self):
        for inventory,actual in self.f:
            r=gate.analyze(inventory,actual)
            self.assertEqual(r["visibleMetricRows"],len(inventory["metrics"]))
            self.assertEqual(r["distinctMetricIds"],len({x["metricId"] for x in inventory["metrics"]}))
            self.assertEqual(r["unverifiedComputedRows"],1)
            self.assertEqual(r["unknownFormulaRows"],len(inventory["metrics"])-1)
            self.assertEqual(r["missingActualRows"],0)
            self.assertEqual(sum(g["visible"] for g in r["groupCoverage"].values()),
                             len(inventory["metrics"]))
            self.assertEqual(sum(r["totals"].values()),len(inventory["metrics"]))
            self.assertFalse(r["ownerApprovedGolden"])
            self.assertEqual(r["fullCapturedFixtureParity"],"BLOCKED_NOT_VERIFIED")
            self.assertEqual(r,gate.analyze(inventory,actual))
    def test_one_dropped_actual_row_is_measured_not_hidden(self):
        inventory,actual=self.f[0]
        a=deepcopy(actual)
        a["sourceStatActual"].pop(-1)
        self.rehash(a)
        r=gate.analyze(inventory,a)
        self.assertEqual(r["visibleMetricRows"],50)
        self.assertEqual(r["missingActualRows"],1)
        self.assertEqual(r["unknownFormulaRows"],48)
        self.assertEqual(r["status"],"BLOCKED_G4_INDEPENDENT_GOLDEN_OR_FORMULAS_MISSING")
    def test_wrong_patch_and_changed_input_fingerprint_stale_all(self):
        inv,a=self.f[1]
        for prop,value in (("gamePatch","3.2.3"),("fixtureInputFingerprint","0"*64)):
            altered=deepcopy(a);altered[prop]=value;self.rehash(altered)
            r=gate.analyze(inv,altered)
            self.assertEqual(r["staleActualRows"],49)
            self.assertEqual(r["unverifiedComputedRows"],0)
            self.assertEqual(r["fullCapturedFixtureParity"],"BLOCKED_NOT_VERIFIED")
    def test_duplicates_and_fake_verified_rejected(self):
        inv,a=self.f[0]
        for mode in ("duplicate","verified","unexpected","fake_golden"):
            changed=deepcopy(a)
            if mode=="duplicate":
                changed["sourceStatActual"].append(deepcopy(changed["sourceStatActual"][0]))
            if mode=="verified":
                changed["sourceStatActual"][0]["status"]="VERIFIED_INDEPENDENT_MAXROLL_PARITY"
            if mode=="unexpected":
                changed["sourceStatActual"][0]["metricId"]="maxroll.heroDetails.123456789999"
            if mode=="fake_golden":
                changed["sourceGoldenExpectedLoaded"]=True
            self.rehash(changed)
            with self.subTest(mode=mode),self.assertRaises(graph.GraphError):
                gate.analyze(inv,changed)
    def test_unsupported_unavailable_and_na_require_reason(self):
        inv,a=self.f[0]
        for name in ("UNSUPPORTED","UNAVAILABLE","NOT_APPLICABLE"):
            changed=deepcopy(a)
            changed["sourceStatActual"][-1].update(
                status=name,reason="UNOBSERVED_MECHANISM_NOT_VERIFIED",
                applicabilityEvidence=("SOURCE_EXPLICIT_NOT_APPLICABLE" if name=="NOT_APPLICABLE" else None))
            self.rehash(changed)
            out=gate.analyze(inv,changed)
            self.assertEqual(out["totals"][name],1)
            self.assertEqual(out["fullCapturedFixtureParity"],"BLOCKED_NOT_VERIFIED")
            del changed["sourceStatActual"][-1]["reason"]
            self.rehash(changed)
            with self.assertRaises(graph.GraphError):gate.analyze(inv,changed)
    def test_source_inventory_group_or_visible_row_mutation_rejected(self):
        inv,a=self.f[0]
        for mod in ("drop","group","label"):
            src=deepcopy(inv)
            if mod=="drop":src["metrics"].pop()
            if mod=="group":src["metrics"][0]["group"]+="x"
            if mod=="label":src["metrics"][0]["label"]+="x"
            with self.subTest(mod=mod),self.assertRaises(graph.GraphError):
                gate.analyze(src,a)
