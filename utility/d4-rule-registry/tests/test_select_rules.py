"""#109 deterministic rule selection: no unverified rule can enter consumer input."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import subprocess

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import registry as reg
import select_rules as pick


class SelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog,cls.sha=reg.read_pinned_catalog()
        cls.policy=reg.load(reg.POLICY)
        cls.candidates=reg.load(HERE/"candidates.json")
        cls.request=reg.load(HERE/"fixtures"/"rogue-request.json")

    def evaluate(self,candidates=None,request=None):
        return pick.resolve(self.catalog,self.sha,self.policy,
            self.candidates if candidates is None else candidates,
            self.request if request is None else request)

    def test_exact_50_ids_deterministic_and_explicit_unavailable(self):
        a=self.evaluate()
        self.assertEqual(a,self.evaluate())
        self.assertEqual(a["status"],"BLOCKED_NO_APPROVED_EXECUTABLE_RULES")
        self.assertEqual(a["coverage"]["denominator"],50)
        self.assertEqual(a["coverage"]["missing"],49)
        self.assertEqual(a["coverage"]["candidateUnverified"],1)
        self.assertEqual(a["coverage"]["activeRules"],0)
        self.assertEqual(len(a["metrics"]),50)
        self.assertEqual(len({x["metricId"] for x in a["metrics"]}),50)
        self.assertIsNone(a["simulationContext"])
        self.assertFalse(a["publishAllowed"])
        self.assertEqual(a["selectionSha256"],
                         reg.sha256({k:v for k,v in a.items() if k!="selectionSha256"}))
        self.assertTrue(all(x["value"] is None and x["executableRule"] is None
                            for x in a["metrics"]))

    def test_observational_fire_is_unverified_not_active(self):
        a=self.evaluate()
        fire=next(x for x in a["metrics"] if x["metricId"]=="maxroll.heroDetails.446")
        self.assertEqual(fire["state"],"UNVERIFIED")
        self.assertEqual(fire["reason"],"CANDIDATE_G2_G3_G4_NOT_VERIFIED")
        self.assertIsNone(fire["executableRule"])

    def test_null_candidates_remain_uncomputed(self):
        out=self.evaluate(candidates=[])
        self.assertEqual(out["coverage"]["missing"],50)
        self.assertEqual(out["coverage"]["candidateUnverified"],0)
        self.assertTrue(all(x["state"]=="UNKNOWN" for x in out["metrics"]))

    def test_fixture_patch_class_and_request_extra_field_refused(self):
        for key,bad in [("gamePatch","3.2.3"),("gameBuild","73883"),
                        ("classId","sorcerer"),("fixtureFingerprint","f"*64)]:
            req=dict(self.request,**{key:bad})
            with self.subTest(key=key),self.assertRaises(reg.RegistryError):
                self.evaluate(request=req)
        with self.assertRaisesRegex(reg.RegistryError,"INVALID_SELECTION_INPUT"):
            self.evaluate(request=dict(self.request, sourceExpected=50))

    def test_promotion_must_not_affect_selected_value(self):
        for key,value in [("state","ACTIVE"),("goldenStatus","APPROVED"),
                          ("verificationGates",{g:"PASS" for g in reg.GATES})]:
            c=copy.deepcopy(self.candidates)
            c[0][key]=value
            with self.subTest(key=key),self.assertRaises(reg.RegistryError):
                self.evaluate(candidates=c)

    def test_cli_success_writes_blocked_selection_not_false_golden(self):
        with tempfile.TemporaryDirectory() as t:
            target=Path(t)/"selection.json"
            cmd=[sys.executable,str(HERE/"select_rules.py"),"--report",str(target)]
            p=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            out=reg.load(target)
            self.assertEqual(out["status"],"BLOCKED_NO_APPROVED_EXECUTABLE_RULES")
            self.assertEqual(out["coverage"]["verifiedGameFormulas"],0)
            self.assertEqual(out["sourceOfExpectedGolden"],"NOT_INCLUDED")
            bad=Path(t)/"bad.json"
            bad.write_text(json.dumps(dict(self.request,gameBuild="73883")))
            p=subprocess.run(cmd+["--request",str(bad)],capture_output=True,text=True)
            self.assertEqual(p.returncode,2)
            self.assertEqual(reg.load(target)["status"],"BLOCKED")
