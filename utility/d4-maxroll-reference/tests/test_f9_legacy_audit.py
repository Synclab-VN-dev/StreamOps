"""Offline evidence audit tests. No Maxroll session or production game required."""
import copy
import json
import runpy
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATE = runpy.run_path(str(ROOT / "check_f9.py"))["validate"]
AUDIT = json.loads((ROOT / "f9-legacy-26-audit.json").read_text())
CATALOG = json.loads((ROOT / "f8-character-metric-catalog.json").read_text())


class LegacyAuditTest(unittest.TestCase):
    def test_success(self):
        r = VALIDATE(AUDIT, CATALOG)
        self.assertEqual(r["status"], "PASS_BOUNDED_SOURCE_AUDIT_ONLY", r)
        self.assertEqual(r["legacyMetricsAudited"], 26)
        self.assertEqual(r["f4ArithmeticDeltasChecked"], 209)
        self.assertEqual(r["f5TooltipArithmeticChecked"], 24)
        self.assertEqual(r["f5RawWithinTooltipRoundingInterval"], 24)
        self.assertEqual(r["pvpInvarianceObservations"], 9)
        self.assertEqual(r["fullyVerified"], 0)

    def assert_rejected(self, mutation):
        candidate = copy.deepcopy(AUDIT)
        mutation(candidate)
        r = VALIDATE(candidate, CATALOG)
        self.assertEqual(r["status"], "FAIL", r)

    def test_missing_metric(self):
        self.assert_rejected(lambda a: a["metrics"].pop())

    def test_incorrect_f4_delta(self):
        self.assert_rejected(lambda a: a["metrics"][0]["f4SourceVectors"][0].__setitem__("reportedDelta", 999))

    def test_unjustified_formula_promotion(self):
        self.assert_rejected(lambda a: a["metrics"][0].__setitem__("fullFormulaVerified", True))

    def test_unjustified_pvp_causality(self):
        self.assert_rejected(lambda a: a["metrics"][-1].__setitem__("causalIsolation", "BOUNDED_ONLY"))

    def test_source_pin_change(self):
        self.assert_rejected(lambda a: a["immutableEvidence"].__setitem__("f4Commit", "different"))

    def test_tooltip_formula_change(self):
        self.assert_rejected(lambda a: a["f5RoundingVectors"]["allDamage"][0].__setitem__("reportedExpectedFromRoundedTooltips", 1))

    def test_tooltip_interval_outlier(self):
        self.assert_rejected(lambda a: a["f5RoundingVectors"]["criticalStrikeChance"][0].__setitem__("sourceRaw", -20))

    def test_error_tolerance_change(self):
        self.assert_rejected(lambda a: a["mathPolicy"].__setitem__("displayTooltipRoundingHalfStepPp", 1.0))

    def test_pvp_constant_change(self):
        self.assert_rejected(lambda a: a["f5RoundingVectors"]["pvpDamageReduction"][0].__setitem__("sourceRaw", 0.5))


if __name__ == "__main__":
    unittest.main()
