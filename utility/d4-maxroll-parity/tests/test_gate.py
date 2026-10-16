"""Synthetic TEST-ONLY vectors validate the comparator, never Maxroll accuracy."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gate import GROUPS, MISSING, compare_metric, verify

FIXTURE = json.loads((ROOT / "rogue-3.2.1.73552-fixture.json").read_text())


def rows(source, delta=0):
    return [{"id": group + "." + str(i), "group": group,
             "display": str(i + delta),
             **({"source": "MAXROLL_BROWSER_CAPTURE", "evidenceRef": "synthetic-harness-only",
                 "rawOrigin": "NOT_OBSERVED", "raw": None} if source == "expected" else {})}
            for group, count in GROUPS.items() for i in range(count)]


def fake_data():
    f = copy.deepcopy(FIXTURE)
    f["fixture"]["inputCompleteness"] = "COMPLETE"
    context = {k: f["fixture"][k] for k in (
        "classId", "level", "variant", "gamePatch", "gameBuild", "inputSnapshotSha256")}
    golden = {"fixture": context, "source": "MAXROLL_BROWSER_CAPTURE",
              "review": "INDEPENDENTLY_APPROVED",
              "evidenceManifestSha256": "a" * 64, "metrics": rows("expected"),
              "vectors": [{"id": key, "inputSnapshotSha256": sha,
                           "source": "MAXROLL_BROWSER_CAPTURE",
                           "metrics": rows("expected", delta)}
                          for key, sha, delta in (("v1", "b"*64, 3), ("v2", "c"*64, 7))]}
    actual = {"fixture": context, "source": "FORMULA_GRAPH", "graphSha256": "d" * 64,
              "ruleSetSha256": "e" * 64, "metrics": rows("actual"),
              "vectors": [{"id": key, "inputSnapshotSha256": sha,
                           "metrics": rows("actual", delta)}
                          for key, sha, delta in (("v1", "b"*64, 3), ("v2", "c"*64, 7))]}
    rules = {"patchBuild": "3.2.1.73552",
             "metrics": [{"id": r["id"], "status": "CAUSALLY_VERIFIED",
                          "expressionRef": "test:formula-only",
                          "independentVectorRefs": ["v1", "v2"]}
                         for r in golden["metrics"]]}
    return f, golden, actual, rules


class TestGate(unittest.TestCase):
    def test_real_rogue_fixture_is_blocked_without_real_goldens(self):
        report = verify(FIXTURE)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("FIXTURE_INPUTS_INCOMPLETE", report["blockers"])
        self.assertIn("MISSING_GOLDEN_ARTIFACT", report["blockers"])

    def test_synthetic_comparator_harness_not_real_maxroll_parity(self):
        report = verify(*fake_data())
        self.assertEqual(report["status"], "PASS", report)
        self.assertEqual(report["numeratorMatched"], 50)
        self.assertEqual(len(report["comparisons"]), 150)

    def test_display_mismatch(self):
        c = fake_data()
        c[2]["metrics"][0]["display"] = "WRONG"
        self.assertEqual(verify(*c)["status"], "FAIL")

    def test_variant_mismatch(self):
        c = fake_data()
        c[1]["fixture"]["variant"] = "#2"
        self.assertEqual(verify(*c)["status"], "BLOCKED")

    def test_missing_stat(self):
        c = fake_data()
        c[1]["metrics"].pop()
        self.assertEqual(verify(*c)["status"], "BLOCKED")

    def test_formula_missing(self):
        c = fake_data()
        c[3]["metrics"].pop()
        self.assertEqual(verify(*c)["status"], "BLOCKED")

    def test_formula_unverified(self):
        c = fake_data()
        c[3]["metrics"][0]["status"] = "UNKNOWN"
        self.assertEqual(verify(*c)["status"], "BLOCKED")

    def test_missing_changed_input_vector(self):
        c = fake_data()
        c[1]["vectors"].pop()
        self.assertEqual(verify(*c)["status"], "BLOCKED")

    def test_changed_vector_mismatch(self):
        c = fake_data()
        c[2]["vectors"][0]["metrics"][0]["display"] = "bad"
        self.assertEqual(verify(*c)["status"], "FAIL")

    def test_expected_origin_not_maxroll(self):
        c = fake_data()
        c[1]["source"] = "SYNTHETIC"
        self.assertEqual(verify(*c)["status"], "BLOCKED")

    def test_actual_origin_not_graph(self):
        c = fake_data()
        c[2]["source"] = "AI_PREDICTION"
        self.assertEqual(verify(*c)["status"], "BLOCKED")

    def test_unapproved_expected(self):
        c = fake_data()
        c[1]["review"] = "PENDING"
        self.assertEqual(verify(*c)["status"], "BLOCKED")

    def test_wrong_patch(self):
        c = fake_data()
        c[1]["fixture"]["gamePatch"] = "3.2.3"
        self.assertEqual(verify(*c)["status"], "BLOCKED")

    def test_duplicate_stat_id(self):
        c = fake_data()
        c[1]["metrics"][1]["id"] = c[1]["metrics"][0]["id"]
        self.assertEqual(verify(*c)["status"], "BLOCKED")

    def test_wrong_metric_groups(self):
        c = fake_data()
        c[1]["metrics"][0]["group"] = "offensive"
        self.assertEqual(verify(*c)["status"], "BLOCKED")

    def test_partial_base_input(self):
        c = fake_data()
        c[0]["fixture"]["inputCompleteness"] = "PARTIAL"
        self.assertEqual(verify(*c)["status"], "BLOCKED")

    def test_raw_exact(self):
        e = {"display": "1.20", "rawOrigin": "MAXROLL_RUNTIME", "raw": "1.2"}
        a = {"display": "1.20", "raw": "1.20000000001"}
        self.assertEqual(compare_metric(e, a)[0], "FAIL")
        a["raw"] = "1.2"
        self.assertEqual(compare_metric(e, a)[0], "PASS")

    def test_source_no_raw_does_not_invent_precision(self):
        e = {"display": "1.2", "rawOrigin": "NOT_OBSERVED", "raw": None}
        self.assertEqual(compare_metric(e, {"display": "1.2"})[0], "PASS")


if __name__ == "__main__":
    unittest.main()
