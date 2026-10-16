"""#109 offline registry contract and synthetic patch lifecycle tests."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("d4_109_registry", HERE / "registry.py")
reg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reg)


def candidate(metric="maxroll.heroDetails.446", id="candidate.rogue.fire"):
    return {
        "id": id,
        "metricId": metric,
        "gamePatch": "3.2.1",
        "gameBuild": "73552",
        "classId": "rogue",
        "state": "CANDIDATE_UNVERIFIED",
        "sourceKind": "MAXROLL_SOURCE_OBSERVATION",
        "sourceUrl": "https://maxroll.gg/d4/planner/1g1any0x#3",
        "sourceCommit": "918aa4b0e1845d34909a8b847a324b445e3805a7",
        "sourceEvidence": "https://github.com/Synclab-VN-dev/StreamOps/issues/106#issuecomment-6212668905",
        "researchGrade": "BOUNDED_VERIFIED",
        "dependencies": [],
        "dsl": None,
        "goldenStatus": "NOT_APPROVED",
        "verificationGates": {g: "NOT_RUN" for g in reg.GATES},
        "ownerReview": None
    }


class RegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog, cls.source_hash = reg.read_pinned_catalog()
        cls.policy = reg.load(reg.POLICY)
        cls.ids = {v["metricId"] for v in cls.catalog["metrics"]}

    def test_catalog_is_pinned_and_all_source_rows_present(self):
        actual = reg.snapshot(self.catalog, self.source_hash, self.policy, [])
        self.assertEqual(len(actual["metrics"]), 50)
        self.assertEqual(actual["coverage"]["unknownRuleCount"], 50)
        self.assertEqual(actual["coverage"]["activeRules"], 0)
        self.assertEqual(actual["coverage"]["sourceBounded"], 27)
        self.assertEqual(actual["coverage"]["sourcePartial"], 23)
        self.assertEqual(actual["coverage"]["approvedGolden"], 0)
        self.assertEqual(actual["coverage"]["fullParity"], "BLOCKED")
        self.assertTrue(all(row["activeRule"] is None and row["calculatedValue"] is None
                            and row["maxrollParity"].startswith("BLOCKED") for row in actual["metrics"]))

    def test_snapshot_is_deterministic_and_order_invariant(self):
        a = reg.snapshot(self.catalog, self.source_hash, self.policy, [])
        b = reg.snapshot(self.catalog, self.source_hash, self.policy, [])
        self.assertEqual(a["snapshotSha256"], b["snapshotSha256"])
        self.assertEqual(a["snapshotSha256"], reg.sha256({k: v for k,v in a.items()
                                                          if k != "snapshotSha256"}))

    def test_catalog_blob_immutability(self):
        path = HERE / "policy.json"
        with self.assertRaisesRegex(reg.RegistryError, "SOURCE_CATALOG_BLOB_MISMATCH"):
            reg.read_pinned_catalog(path)

    def test_owner_pinned_policy_guard(self):
        for key, value in [("gameBuild", "73883"), ("oracle", "BLIZZARD"),
                           ("autoPublish", True), ("approvedGoldenCount", 50),
                           ("numericUnknownFallback", "ZERO")]:
            with self.subTest(key=key):
                p = dict(self.policy, **{key:value})
                with self.assertRaises(reg.RegistryError):
                    reg.snapshot(self.catalog, self.source_hash, p, [])

    def test_one_bounded_candidate_is_not_an_active_formula(self):
        c = candidate()
        result = reg.snapshot(self.catalog, self.source_hash, self.policy, [c])
        self.assertEqual(result["coverage"]["candidateUnverified"], 1)
        self.assertEqual(result["coverage"]["unknownRuleCount"], 49)
        self.assertEqual(result["coverage"]["fullyVerifiedFormulas"], 0)
        self.assertEqual(result["coverage"]["activeRules"], 0)
        self.assertIsNone(next(x for x in result["metrics"]
                               if x["metricId"] == c["metricId"])["activeRule"])

    def test_duplicate_candidate_or_metric_refused(self):
        c = candidate()
        with self.assertRaisesRegex(reg.RegistryError, "DUPLICATE_CANDIDATE"):
            reg.snapshot(self.catalog, self.source_hash, self.policy, [c,c])
        d = candidate(id="candidate.rogue.fire.v2")
        with self.assertRaisesRegex(reg.RegistryError, "DUPLICATE_CANDIDATE"):
            reg.snapshot(self.catalog, self.source_hash, self.policy, [c,d])

    def test_wrong_patch_and_unlisted_metric_refused(self):
        for key, bad in [("gamePatch","3.2.3"), ("gameBuild","73883"),
                         ("classId","sorcerer"), ("metricId","maxroll.heroDetails.fake")]:
            c = candidate()
            c[key] = bad
            with self.subTest(key=key), self.assertRaises(reg.RegistryError):
                reg.snapshot(self.catalog, self.source_hash, self.policy, [c])

    def test_false_verified_golden_or_owner_promotions_fail(self):
        for key, bad in [("state","ACTIVE"), ("goldenStatus","APPROVED"),
                         ("researchGrade","VERIFIED"), ("ownerReview","https://github.com/fake"),
                         ("verificationGates", {g:"PASS" for g in reg.GATES}),
                         ("maxrollExpected",42)]:
            c = candidate()
            c[key] = bad
            with self.subTest(key=key), self.assertRaises(reg.RegistryError):
                reg.snapshot(self.catalog, self.source_hash, self.policy, [c])

    def test_missing_source_or_bogus_data_rejected(self):
        for key, bad in [("sourceEvidence", ""), ("sourceUrl", "http://fake"),
                         ("sourceCommit","not-sha"), ("sourceKind","AI_GENERATED")]:
            c = candidate()
            c[key] = bad
            with self.subTest(key=key), self.assertRaises(reg.RegistryError):
                reg.check_candidate(c, self.ids)

    def test_missing_dependency_and_g2_cycle_refused(self):
        bad = candidate()
        bad["dependencies"] = ["maxroll.heroDetails.9999999"]
        with self.assertRaises(reg.RegistryError):
            reg.check_candidate(bad, self.ids)
        a = candidate()
        b = candidate("maxroll.heroDetails.480", "candidate.rogue.armor")
        a["dependencies"] = [b["metricId"]]
        b["dependencies"] = [a["metricId"]]
        with self.assertRaisesRegex(reg.RegistryError, "G2_CANDIDATE_DEPENDENCY_CYCLE"):
            reg.snapshot(self.catalog, self.source_hash, self.policy, [a,b])

    def test_schema_invalid_dsl_refused_by_g1(self):
        c = candidate()
        c["dsl"] = {"schemaVersion":"1.0.0","ruleId":c["id"],
                    "game":{"gameVersion":"3.2.1","buildNumber":"73552"},
                    "source":{"kind":"item","gameId":"example.fake"},
                    "mechanics":[{"id":"fake","phase":"on_cast","trigger":{"kind":"always"},
                                  "actions":[{"op":"execute_python","code":"1+1"}]}],
                    "verification":{"status":"draft","confidence":"unknown",
                                    "evidence":[{"kind":"synthetic_fixture","note":"test"}]}}
        with self.assertRaisesRegex(reg.RegistryError,"SCHEMA_EXTENSION_REQUIRED"):
            reg.check_candidate(c, self.ids)

    def test_synthetic_patch_cycle_reproducible_with_all_delta_kinds(self):
        fixture = reg.load(HERE / "fixtures" / "synthetic-patch-cycle.json")
        a = reg.simulate_synthetic_patch_cycle(fixture)
        b = reg.simulate_synthetic_patch_cycle(fixture)
        self.assertEqual(a,b)
        self.assertEqual(a["diff"], {"added":["fake.add"],"removed":["fake.remove"],
                       "buffed":["fake.direct"],"nerfed":["fake.nerf"],"unchanged":["fake.stable"]})
        self.assertEqual(a["oldHash"], a["rollbackHash"])
        self.assertTrue(a["restoredExactly"])
        self.assertFalse(a["activePublish"])
        self.assertEqual(a["maxrollParity"],"NOT_TESTED")

    def test_real_patch_delta_rejected(self):
        data = reg.load(HERE / "fixtures" / "synthetic-patch-cycle.json")
        data["synthetic"] = False
        with self.assertRaisesRegex(reg.RegistryError,"REAL_PATCH_MUTATION_FORBIDDEN"):
            reg.simulate_synthetic_patch_cycle(data)

    def test_immutable_fire_source_candidate_without_executable_formula(self):
        records = reg.load(HERE / "candidates.json")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["metricId"], "maxroll.heroDetails.446")
        self.assertEqual(records[0]["sourceCommit"],
                         "918aa4b0e1845d34909a8b847a324b445e3805a7")
        self.assertIsNone(records[0]["dsl"])
        result = reg.snapshot(self.catalog, self.source_hash, self.policy, records)
        fire = next(x for x in result["metrics"] if x["metricId"] == records[0]["metricId"])
        self.assertEqual(fire["ruleStatus"], "CANDIDATE_UNVERIFIED")
        self.assertIsNone(fire["activeRule"])
        self.assertIsNone(fire["calculatedValue"])

    def test_cli_success_and_fail_closed_error_report(self):
        with tempfile.TemporaryDirectory() as td:
            good = Path(td) / "report.json"
            proc = subprocess.run([sys.executable, str(HERE/"registry.py"), "--report", str(good)],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            report = reg.load(good)
            self.assertEqual(report["status"], "PASS_REGISTRY_STRUCTURE_ONLY")
            self.assertEqual(report["coverage"]["candidateUnverified"], 1)
            self.assertEqual(report["coverage"]["unknownRuleCount"], 49)
            self.assertEqual(report["coverage"]["activeRules"], 0)
            bad = Path(td) / "bad.json"
            proc = subprocess.run([sys.executable, str(HERE/"registry.py"), "--report", str(bad),
                                   "--catalog", str(HERE/"policy.json")],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(reg.load(bad)["status"], "BLOCKED")

if __name__ == "__main__":
    unittest.main()
