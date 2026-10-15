"""Negative regression for issue #106 design-only gate (stdlib unittest)."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from check import audit, calculate, check_fixtures, check_inventory, check_vectors, load

class DesignGateTests(unittest.TestCase):
    def setUp(self):
        self.inventory = load(ROOT / "mechanics.json")
        self.fixtures = load(ROOT / "fixtures.json")
        self.vectors = load(ROOT / "vectors.json")

    def test_complete_design_matrix_passes(self):
        result = audit(self.inventory, self.fixtures, self.vectors)
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(set(result["gates"]), {"CI-01", "CI-02", "CI-03"})
        self.assertEqual(result["counts"]["globalCoverageDenominator"], "UNKNOWN")
        self.assertIsNone(result["counts"]["globalCoveragePercent"])
        self.assertEqual(result["ownerDesignApproval"], "PENDING_MAN_01")
        self.assertEqual(result["independentGameAccuracy"], "NOT_VERIFIED")

    def test_patch_promotion_rejected(self):
        data = copy.deepcopy(self.inventory)
        next(m for m in data["mechanics"] if m["id"] == "all-damage-additive")["patch"] = "3.2.3"
        self.assertTrue(any("cross patches" in e for e in check_inventory(data)))

    def test_synthetic_mechanic_cannot_be_verified(self):
        data = copy.deepcopy(self.inventory)
        entry = next(m for m in data["mechanics"] if m["id"] == "multiple-hits")
        entry["status"] = "VERIFIED_VECTOR_SCOPED"
        entry["patch"] = "3.2.1.73552"
        self.assertTrue(check_inventory(data))

    def test_unknown_numeric_fallback_rejected(self):
        data = copy.deepcopy(self.inventory)
        data["patchPolicy"]["missingMechanic"] = "ASSUME_ZERO"
        self.assertIn("unknown mechanic must fail closed", check_inventory(data))

    def test_missing_source_fails(self):
        data = copy.deepcopy(self.inventory)
        data["mechanics"][0]["sourceIds"] = ["made-up-reference"]
        self.assertTrue(any("missing source" in e for e in check_inventory(data)))

    def test_duplicate_mechanic_fails(self):
        data = copy.deepcopy(self.inventory)
        data["mechanics"].append(copy.deepcopy(data["mechanics"][0]))
        self.assertTrue(any("duplicate/empty mechanic" in e for e in check_inventory(data)))

    def test_reference_expected_is_independently_computed(self):
        data = copy.deepcopy(self.vectors)
        entry = next(v for v in data["vectors"] if v["id"] == "proc-quarter")
        entry["expected"] = "999"
        self.assertTrue(any("arithmetic mismatch" in e for e in check_vectors(data)))

    def test_missing_edge_case_fails_coverage(self):
        data = copy.deepcopy(self.vectors)
        data["vectors"] = [v for v in data["vectors"] if v["op"] != "event_order"]
        self.assertTrue(any("missing required mechanics test groups" in e
                            for e in check_vectors(data)))

    def test_blocked_cycle_must_not_produce_number(self):
        data = copy.deepcopy(self.vectors)
        entry = next(v for v in data["vectors"] if v["id"] == "cyclic-proc-blocked")
        entry["expected"] = "0"
        entry["status"] = "PASS_SYNTHETIC"
        errors = check_vectors(data)
        self.assertTrue(any("fail-closed case has numeric" in e for e in errors))
        self.assertTrue(any("status mismatch" in e for e in errors))

    def test_patch_guard_with_same_patches_rejected(self):
        data = copy.deepcopy(self.vectors)
        entry = next(v for v in data["vectors"] if v["id"] == "patch-mismatch-blocked")
        entry["inputs"]["patch"] = "3.2.3"
        self.assertTrue(any("matching versions" in e for e in check_vectors(data)))

    def test_synthetic_fixture_cannot_claim_game_accuracy(self):
        data = copy.deepcopy(self.fixtures)
        data["gameAccuracy"] = "BLIZZARD_VERIFIED"
        self.assertIn("fixture accuracy overclaim",
                      check_fixtures(data, {"synthetic-design-106"}))

    def test_fixtures_recalculate_independently(self):
        data = copy.deepcopy(self.fixtures)
        data["fixtures"][2]["expectedDamageTotal"] = "1841"
        self.assertTrue(any("arithmetic mismatch" in e
                            for e in check_fixtures(data, {"synthetic-design-106"})))

    def test_negative_proc_chance_rejected(self):
        with self.assertRaises(ValueError):
            calculate("proc_expected", {"base": "10", "triggerDamage": "5", "chance": "-0.1"})

    def test_immunity_does_not_emit_damage(self):
        self.assertEqual(calculate("mitigated_damage",
            {"base": "999", "immune": True, "mitigation": "0"}), 0)

    def test_rounding_is_not_hardcoded_as_one_universal_policy(self):
        # Numeric vectors assert Decimal semantics, no UI rounding or maxroll claim.
        self.assertEqual(calculate("proc_expected",
            {"base": "100", "chance": "0.25", "triggerDamage": "40"}), 110)
        self.assertNotIn("tooltipDisplay", self.vectors)

    def test_invalid_crit_chance_fails(self):
        with self.assertRaises(ValueError):
            calculate("crit_expected",
                {"base": "100", "chance": "-0.9", "extra": ".5", "cap": "1"})

if __name__ == "__main__":
    unittest.main()
