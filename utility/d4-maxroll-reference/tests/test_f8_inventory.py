"""Negative/source-integrity checks for #106 F8. Does not test game formulas."""
import copy
import json
import runpy
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
validate = runpy.run_path(str(ROOT / "check_f8.py"))["validate"]
fixture = json.loads((ROOT / "f8-character-metric-catalog.json").read_text(encoding="utf-8"))


class SourceMetricInventoryTests(unittest.TestCase):
    def test_accepted_research_only(self):
        out = validate(fixture)
        self.assertEqual(out["status"], "PASS_SOURCE_INVENTORY_ONLY", out)
        self.assertEqual(out["catalogedMetricIds"], 50)
        self.assertEqual(out["proposedFormulaStatusCounts"],
                         {"BOUNDED_VERIFIED": 27, "PARTIAL": 23})
        self.assertEqual(out["independentGraphParity"], "NOT_RUN")

    def reject(self, update):
        candidate = copy.deepcopy(fixture)
        update(candidate)
        output = validate(candidate)
        self.assertEqual(output["status"], "FAIL", output)

    def test_missing_metric_fails(self):
        self.reject(lambda c: c["metrics"].pop())

    def test_duplicate_metric_fails(self):
        self.reject(lambda c: c["metrics"].__setitem__(1, c["metrics"][0]))

    def test_stable_id_swap_fails(self):
        self.reject(lambda c: c["metrics"][0].__setitem__("metricId", "maxroll.heroDetails.999999"))

    def test_group_mismatch_fails(self):
        self.reject(lambda c: c["metrics"][0].__setitem__("group", "offensive"))

    def test_cross_patch_fails(self):
        self.reject(lambda c: c["baseline"].__setitem__("gameBuild", "73883"))

    def test_incomplete_input_promotion_fails(self):
        self.reject(lambda c: c["fixture"].__setitem__("inputCompleteness", "COMPLETE"))

    def test_golden_promotion_fails(self):
        self.reject(lambda c: c["coverage"].__setitem__("approvedGoldenCount", 50))

    def test_graph_parity_promotion_fails(self):
        self.reject(lambda c: c["metrics"][0].__setitem__("maxrollGraphParity", "PASS"))

    def test_formula_promotion_fails(self):
        self.reject(lambda c: c["metrics"][0].__setitem__("formulaVerificationStatus", "VERIFIED"))

    def test_old_grades_retained(self):
        self.reject(lambda c: c["metrics"][0].__setitem__("legacyF5Status", "PARTIAL"))

    def test_fire_raw_helper_not_verified(self):
        self.reject(lambda c: next(m for m in c["metrics"] if
                                      m["metricId"] == "maxroll.heroDetails.446")
                    ["formulaCandidate"].__setitem__("verifiedExactHelper", True))

    def test_fire_cap_not_verified(self):
        self.reject(lambda c: next(m for m in c["metrics"] if
                                      m["metricId"] == "maxroll.heroDetails.446")
                    ["formulaCandidate"].__setitem__("provenExplicitCap", True))

    def test_no_invented_effect_dependencies(self):
        self.reject(lambda c: c["metrics"][0]["dependencies"].append("imaginaryRule"))

    def test_no_silent_zero_of_unknown(self):
        self.reject(lambda c: c["policy"].__setitem__("unknownNeverZero", False))

    def test_source_mechanics_not_promoted_to_rule_data(self):
        self.reject(lambda c: next(m for m in c["metrics"] if
                                    m["sourceReportedMechanic"] is not None)
                    ["sourceReportedMechanic"].__setitem__("kind", "VERIFIED_RULE"))

    def test_source_mechanics_not_silently_removed(self):
        self.reject(lambda c: next(m for m in c["metrics"] if
                                    m["sourceReportedMechanic"] is not None)
                    .__setitem__("sourceReportedMechanic", None))

    def test_no_auto_audit_grade(self):
        self.reject(lambda c: c["provenance"].__setitem__("sourceReview", "VERIFIED"))

    def test_denominator_not_global(self):
        self.reject(lambda c: c["coverage"].__setitem__("denominator", 999))


if __name__ == "__main__":
    unittest.main()
