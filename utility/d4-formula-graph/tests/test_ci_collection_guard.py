"""Negative regression: missing, truncated, skipped, xfailed collection is blocked."""
from pathlib import Path
import sys, unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import ci_collection_guard as guard
class GuardTests(unittest.TestCase):
    def test_complete_log_is_pass_only_for_all_ran(self):
        out=guard.inspect_log("test_foo ... ok\nRan 3 tests in 0.010s\n\nOK\n",
                              ["X.test_a","X.test_b","X.test_c"],minimum=3)
        self.assertEqual(out["executed"],3)
        self.assertFalse(out["publishAllowed"])
        self.assertEqual(out["independentGoldenParity"],"NOT_RUN")
    def test_missing_skip_xfail_failed_import_and_duplicate_are_blocked(self):
        ids=["X.test_a","X.test_b","X.test_c"]
        logs=[
          "Ran 2 tests in 0.010s\n\nOK\n",
          "Ran 3 tests in 0.010s\n\nOK (skipped=1)\n",
          "Ran 3 tests in 0.010s\n\nOK (expected failures=1)\n",
          "Ran 3 tests in 0.010s\n\nFAILED (failures=1)\n",
          "Ran 3 tests in 0.010s\n\nOK\nRan 3 tests in 0.010s\n\nOK\n",
          "Ran 3 tests in 0.010s\n\nOK\nskipped 'not available'\n",
          "Ran 3 tests in 0.010s\n\nOK\nxfail marker\n",
        ]
        for log in logs:
            with self.subTest(log=log),self.assertRaises(guard.CollectionBlocked):
                guard.inspect_log(log,ids,minimum=3)
        with self.assertRaises(guard.CollectionBlocked):
            guard.inspect_log("Ran 3 tests in 0.010s\n\nOK\n",ids[:2],minimum=3)
        with self.assertRaises(guard.CollectionBlocked):
            guard.inspect_log("Ran 3 tests in 0.010s\n\nOK\n",
                              ["X.test_a","X.test_a","X.test_b"],minimum=3)
