"""Strength formula V2 spans full 20 ID candidate report without
changing the other 19 metrics or promoting a provisional source subtotal."""
import sys
import unittest
from pathlib import Path
HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import graph
import working_model
import working_model_v2
import working_model_golden_diag

F=HERE/"fixtures"
def read(name):return graph.read_json(F/name)

class ScopedStrengthM20Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.args={
            "source":read("dev00-source-sanitized.json"),
            "inventory":read("dev00-visible-inventory.json"),
            "targets":read("golden-target-20.json"),
            "f3map":read("f3-target20-source-map.json"),
            "paragon":read("dev00-paragon-tooltip-source.json"),
            "rolls":read("dev00-source-rolls.json"),
            "rules":read("strength-rogue-research-rules.json"),
        }

    def test_v2_replaces_strength_only_without_golden_leakage(self):
        a=self.args
        old=working_model.evaluate(a["source"],a["inventory"],a["targets"],
                                   a["f3map"],a["paragon"],a["rolls"])
        new=working_model_v2.evaluate(**a)
        orig={r["metricId"]:r for r in old["metrics"]}
        now={r["metricId"]:r for r in new["metrics"]}
        self.assertEqual(len(now),20)
        self.assertEqual(now["maxroll.heroDetails.108"]["candidateRaw"],349)
        self.assertEqual(orig["maxroll.heroDetails.108"]["candidateRaw"],339)
        for mid in orig:
            if mid=="maxroll.heroDetails.108":continue
            self.assertEqual(orig[mid],now[mid])
        self.assertFalse(now["maxroll.heroDetails.108"]["candidateIsCompleteActual"])
        self.assertEqual(new["newGoldenVerified"],0)
        self.assertFalse(new["goldenExpectedLoaded"])
        self.assertEqual(new,self.__class__.build_again())
        self.assertEqual(new["reportSha256"],graph.digest(
            {k:v for k,v in new.items() if k!="reportSha256"}))

    @classmethod
    def build_again(cls):
        return working_model_v2.evaluate(**cls.args)

    def test_pinned_dev_golden_reports_mismatch_not_false_verified(self):
        new=self.build_again()
        expected=(F/"golden-dev"/"dev00-original-50.json").read_bytes()
        report=working_model_golden_diag.compare(new,expected)
        row=next(x for x in report["metrics"]
                 if x["metricId"]=="maxroll.heroDetails.108")
        self.assertEqual(row["actualCandidateRaw"],349)
        self.assertEqual(row["expectedRaw"],418)
        self.assertEqual(row["rawDiffActualMinusExpected"],"-69")
        self.assertEqual(row["status"],"PROVISIONAL_MISMATCH")
        self.assertEqual(report["newGoldenVerified"],0)
        self.assertEqual(report["counts"]["BLOCKED_NO_CANDIDATE"],13)
        self.assertEqual(report["counts"]["PROVISIONAL_MISMATCH"],6)
        self.assertEqual(report["counts"]["SOURCE_LEVEL_SAMPLE_MATCH_NEEDS_ORIGINAL_GATE"],1)

if __name__=="__main__":unittest.main()
