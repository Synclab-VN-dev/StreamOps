"""#109 synthetic patch agent evidence integrity, independent diff and negative cases."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import patch_proposal as p
import registry as reg


class PatchProposalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=p.SOURCE.read_bytes()
        cls.evidence=reg.load(p.EVIDENCE)

    def test_source_pinned_generate_four_distinct_changes_and_hash(self):
        result=p.build(self.source,self.evidence)
        self.assertEqual(result["status"],"PASS_SYNTHETIC_CANDIDATE_GENERATION_ONLY")
        self.assertEqual(result["sourceChangeCoverage"],{"changed":4,"sourced":4,"gameVerified":0})
        self.assertEqual({x["changeType"] for x in result["candidates"]},
                         {"added","removed","buffed","nerfed"})
        self.assertEqual(result["reportSha256"],
                         reg.sha256({k:v for k,v in result.items() if k!="reportSha256"}))
        self.assertEqual(result,p.build(self.source,self.evidence))
        self.assertEqual(next(x for x in result["candidates"] if x["metricId"]=="fake.remove")["sourcePointer"],
                         "fixtures/synthetic-patch-cycle.json#/old/rules/fake.remove")
        self.assertTrue(all(not x["active"] and x["schemaVersion"]=="1.0.0"
                            and x["verificationGates"]["G3"]=="NOT_RUN" for x in result["candidates"]))
        self.assertFalse(result["autoPublish"])
        self.assertFalse(result["schemaChanged"])

    def test_modified_source_cannot_rewrite_expected(self):
        tampered=self.source.replace(b'"fake.direct": 2',b'"fake.direct": 200')
        self.assertNotEqual(tampered,self.source)
        with self.assertRaisesRegex(reg.RegistryError,"UNAPPROVED_SOURCE_MUTATION"):
            p.build(tampered,self.evidence)

    def test_unsourced_or_duplicate_delta_rejected(self):
        for change in ("missing","duplicate","extra"):
            data=copy.deepcopy(self.evidence)
            if change=="missing": data["records"].pop()
            if change=="duplicate": data["records"][0]=copy.deepcopy(data["records"][1])
            if change=="extra": data["records"].append(copy.deepcopy(data["records"][0]))
            with self.subTest(change=change),self.assertRaises(reg.RegistryError):
                p.build(self.source,data)

    def test_per_source_patch_and_pointer_grade_guards(self):
        bads=[("sourceSha256","0"*64),("sourceKind","maxroll_ui_observation"),
              ("synthetic",False),("gameFormulaVerification","VERIFIED")]
        for key,value in bads:
            d=copy.deepcopy(self.evidence)
            d[key]=value
            with self.subTest(key=key),self.assertRaises(reg.RegistryError):
                p.build(self.source,d)
        for key,value in (("category","added"),("sourcePointer","fake"),
                          ("scope","PRODUCTION"),("sourceGitBlobSha1","0"*40)):
            d=copy.deepcopy(self.evidence)
            d["records"][0][key]=value
            with self.subTest(key=key),self.assertRaisesRegex(
                    reg.RegistryError,"EVIDENCE_POINTER_OR_CATEGORY_MISMATCH"):
                p.build(self.source,d)

    def test_disallow_real_patch_and_unknown_game_rules(self):
        d=copy.deepcopy(self.evidence)
        d["synthetic"]=False
        with self.assertRaises(reg.RegistryError):
            p.build(self.source,d)
        d=copy.deepcopy(self.evidence)
        d["records"][0]["metricId"]="maxroll.heroDetails.446"
        with self.assertRaises(reg.RegistryError):
            p.build(self.source,d)

    def test_cli_emits_blocked_not_false_pass_on_source_loss(self):
        with tempfile.TemporaryDirectory() as root:
            report=Path(root)/"good.json"
            x=subprocess.run([sys.executable,str(HERE/"patch_proposal.py"),
                              "--report",str(report)],capture_output=True,text=True)
            self.assertEqual(x.returncode,0,x.stderr+x.stdout)
            self.assertEqual(reg.load(report)["sourceChangeCoverage"]["sourced"],4)
            y=subprocess.run([sys.executable,str(HERE/"patch_proposal.py"),
                              "--report",str(report),"--source",str(Path(root)/"missing")],
                              capture_output=True,text=True)
            self.assertEqual(y.returncode,2)
            self.assertEqual(reg.load(report)["status"],"BLOCKED")
