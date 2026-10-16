"""#109 CI-02 read-only source/gate checks and synthetic locked-snapshot mutation tests."""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import registry as reg
import review_policy as policy


class ReviewPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog,cls.catalog_hash=reg.read_pinned_catalog()
        cls.policy=reg.load(reg.POLICY)
        cls.candidates=reg.load(HERE/"candidates.json")
        cls.lock=reg.load(policy.SYNTHETIC_LOCK)

    def evaluate(self,candidates=None,lock=None,policy_data=None):
        return policy.read_only_review(self.catalog,self.catalog_hash,
                  self.policy if policy_data is None else policy_data,
                  self.candidates if candidates is None else candidates,
                  self.lock if lock is None else lock)

    def test_exact_source_and_read_only_report(self):
        report=self.evaluate()
        self.assertEqual(report["status"],"PASS_CI02_READ_ONLY_POLICY_GUARDS_ONLY")
        self.assertEqual(report["sourcePinnedCount"],1)
        self.assertEqual(report["g2Semantics"],"NOT_VERIFIED")
        self.assertEqual(report["g3IndependentGolden"],"NOT_AVAILABLE")
        self.assertEqual(report["g4FullCharacterStats"],"NOT_VERIFIED")
        self.assertFalse(report["realApprovedSnapshotExists"])
        self.assertFalse(report["realPublishTested"])
        self.assertFalse(report["publishAllowed"])
        self.assertFalse(report["writeAttempted"])
        self.assertEqual(report["fullyVerifiedFormulas"],0)
        self.assertEqual(report,self.evaluate())

    def test_wrong_source_commit_and_source_location_block(self):
        for key,value in [
            ("sourceCommit","f"*40),
            ("sourceUrl","https://maxroll.gg/d4/planner/different"),
            ("sourceEvidence","https://github.com/example/not-independent"),
            ("sourceKind","MAXROLL_UNREVIEWED"),
        ]:
            items=deepcopy(self.candidates)
            items[0][key]=value
            with self.subTest(key=key),self.assertRaises(reg.RegistryError):
                self.evaluate(candidates=items)

    def test_unregistered_metric_without_pinned_source_blocks(self):
        items=deepcopy(self.candidates)
        items[0]["metricId"]="maxroll.heroDetails.480"
        items[0]["dsl"]=None
        with self.assertRaisesRegex(reg.RegistryError,"UNPINNED_MAXROLL_SOURCE"):
            self.evaluate(candidates=items)

    def test_false_golden_or_any_gate_pass_attempt_rejected(self):
        for gate in reg.GATES:
            items=deepcopy(self.candidates)
            items[0]["verificationGates"][gate]="PASS"
            with self.subTest(gate=gate),self.assertRaises(reg.RegistryError):
                self.evaluate(candidates=items)
        for key,value in [("state","ACTIVE"),("goldenStatus","APPROVED"),
                          ("ownerReview","approved-by-owner"),("researchGrade","VERIFIED")]:
            items=deepcopy(self.candidates)
            items[0][key]=value
            with self.subTest(key=key),self.assertRaises(reg.RegistryError):
                self.evaluate(candidates=items)

    def test_schema_or_source_patch_mismatch_blocks(self):
        for key,value in [("gamePatch","3.2.3"),("gameBuild","73883"),
                          ("classId","sorcerer")]:
            items=deepcopy(self.candidates)
            items[0][key]=value
            with self.subTest(key=key),self.assertRaises(reg.RegistryError):
                self.evaluate(candidates=items)
        items=deepcopy(self.candidates)
        items[0]["dsl"]["verification"]["status"]="verified"
        with self.assertRaises(reg.RegistryError):
            self.evaluate(candidates=items)

    def test_policy_changes_must_not_auto_authorize_publish(self):
        for key,value in [("autoPublish",True),("approvedGoldenCount",1),
                          ("numericUnknownFallback","ZERO"),
                          ("sourceCatalogGitBlob","f"*40)]:
            data=deepcopy(self.policy)
            data[key]=value
            with self.subTest(key=key),self.assertRaises(reg.RegistryError):
                self.evaluate(policy_data=data)

    def test_synthetic_lock_pinned_and_not_real_approval(self):
        pin=policy.validate_synthetic_lock(self.lock)
        self.assertEqual(pin,policy.SYNTHETIC_LOCK_PIN)
        self.assertEqual(self.lock["approvalKind"],"SIMULATED_APPROVAL_NOT_REAL")
        self.assertEqual(self.lock["realGoldenCount"],0)
        self.assertFalse(self.lock["publishedToProduction"])

    def test_changed_synthetic_lock_contents_refuse_overwrite_even_with_rehash(self):
        for kind in ("metric","approval","production","patch","extra"):
            copy=deepcopy(self.lock)
            if kind=="metric":copy["lockedRules"]["fake.direct"]=100
            if kind=="approval":copy["approvalKind"]="REAL_OWNER_APPROVED"
            if kind=="production":copy["publishedToProduction"]=True
            if kind=="patch":copy["patch"]="3.2.1"
            if kind=="extra":copy["unexpected"]=True
            with self.subTest(kind=kind),self.assertRaises(reg.RegistryError):
                self.evaluate(lock=copy)

    def test_no_mutation_api_even_if_same_data_or_claimed_approval(self):
        key=(self.lock["patch"],self.lock["classId"],self.lock["registryVersion"])
        for operation in ("PUBLISH","REPLACE_APPROVED","AUTO_PUBLISH","UPSERT_APPROVED"):
            for proposal in (self.lock["lockedRules"],{"fake.direct":999}):
                with self.subTest(operation=operation),self.assertRaisesRegex(
                    reg.RegistryError,"APPROVED_SNAPSHOT_IMMUTABLE_NO_WRITE_PATH"):
                    policy.check_immutable_key(self.lock,key,proposal,operation=operation)
        self.assertEqual(self.lock["lockedRules"],
                         {"fake.direct":1,"fake.nerf":5,
                          "fake.remove":4,"fake.stable":7})

    def test_no_approval_masquerade_from_synthetic_reference(self):
        key=(self.lock["patch"],self.lock["classId"],self.lock["registryVersion"])
        with self.assertRaisesRegex(reg.RegistryError,"LOCK_KEY_MISMATCH"):
            policy.check_immutable_key(self.lock,("3.2.1","rogue","1.0.0"),
                                       {},operation="PUBLISH")

    def test_cli_blocked_on_missing_lock_and_never_writes(self):
        with tempfile.TemporaryDirectory() as t:
            dest=Path(t)/"policy-report.json"
            good=subprocess.run([sys.executable,str(HERE/"review_policy.py"),
                         "--report",str(dest)],capture_output=True,text=True)
            self.assertEqual(good.returncode,0,good.stdout+good.stderr)
            self.assertEqual(reg.load(dest)["status"],
                             "PASS_CI02_READ_ONLY_POLICY_GUARDS_ONLY")
            bad=subprocess.run([sys.executable,str(HERE/"review_policy.py"),
                         "--lock",str(Path(t)/"missing"),"--report",str(dest)],
                         capture_output=True,text=True)
            self.assertEqual(bad.returncode,2)
            self.assertEqual(reg.load(dest)["status"],"BLOCKED")
            self.assertFalse(reg.load(dest)["publishAllowed"])
