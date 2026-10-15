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
