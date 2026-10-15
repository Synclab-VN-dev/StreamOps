import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from check_f2 import validate

DATA = json.loads((ROOT / "f2-formula-catalog.json").read_text())

class TestF2(unittest.TestCase):
    def test_valid(self):
        report = validate(DATA)
        self.assertEqual(report["status"], "PASS_RESEARCH_CATALOG_ONLY")
        self.assertEqual(report["catalogedMetrics"], 9)
        self.assertEqual(report["visibleFixtureMetrics"], 50)
        self.assertEqual(report["approvedGoldenCount"], 0)

    def test_wrong_patch_fails(self):
        altered = json.loads(json.dumps(DATA))
        altered["baseline"]["gamePatch"] = "3.2.3"
        self.assertEqual(validate(altered)["status"], "FAIL")

    def test_false_approval_fails(self):
        altered = json.loads(json.dumps(DATA))
        altered["parity"]["approvedGoldenCount"] = 1
        self.assertEqual(validate(altered)["status"], "FAIL")

    def test_wrong_denominator_fails(self):
        altered = json.loads(json.dumps(DATA))
        altered["inventory"]["visibleTotal"] = 9
        self.assertEqual(validate(altered)["status"], "FAIL")

    def test_duplicate_metric_fails(self):
        d = json.loads(json.dumps(DATA))
        d["metrics"].append(d["metrics"][0].copy())
        self.assertEqual(validate(d)["status"], "FAIL")

    def test_unverified_formula_fails(self):
        d = json.loads(json.dumps(DATA))
        d["metrics"][0]["formulaStatus"] = "VERIFIED"
        self.assertEqual(validate(d)["status"], "FAIL")
