"""M20 executable working model: real source partials, injected future families,
case A/B/C regression, and an independent DEV-00 Golden diagnostic."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import json
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import graph
import golden_candidate_eval as existing
import working_model as model
import working_model_golden_diag as diag

FIX=ROOT/"fixtures"
def read(name):return graph.read_json(FIX/name)

class WorkingModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=read("dev00-source-sanitized.json")
        cls.inventory=read("dev00-visible-inventory.json")
        cls.targets=read("golden-target-20.json")
        cls.f3=read("f3-target20-source-map.json")
        cls.paragon=read("dev00-paragon-tooltip-source.json")
        cls.rolls=read("dev00-source-rolls.json")
        cls.expected=(FIX/"golden-dev"/"dev00-original-50.json").read_bytes()

    def run_model(self, **changes):
        args = dict(source=self.source, inventory=self.inventory,
                    targets=self.targets, f3map=self.f3,
                    paragon_witness=self.paragon,roll_witness=self.rolls)
        args.update(changes)
        return model.evaluate(**args)

    def test_real_270_nodes_and_20_candidates_without_fake_verified(self):
        a=self.run_model()
        self.assertEqual(a["targetUniqueMetricIds"],20)
        self.assertEqual(a["numericCandidates"],7)
        self.assertEqual(a["provisionalCandidates"],6)
        self.assertGreater(a["observedRollsWithoutTrustedMetricMapping"],40)
        self.assertFalse(a["goldenExpectedLoaded"])
        self.assertEqual(a["newGoldenVerified"],0)
        self.assertEqual(a,self.run_model())
        rows={r["metricId"]:r for r in a["metrics"]}
        for name,observed in [("Strength",339),("Intelligence",413),
                               ("Willpower",75),("Dexterity",569)]:
            record=rows[model.PRIMARY[name]]
            self.assertEqual(record["candidateRaw"],observed)
            self.assertFalse(record["candidateIsCompleteActual"])
            self.assertTrue(record["missingContributorFamilies"])
            self.assertTrue(record["contributions"])
        self.assertEqual(rows[model.LEVEL]["candidateRaw"],70)
        self.assertTrue(rows[model.LEVEL]["candidateIsCompleteActual"])
        self.assertEqual(sum(r["candidateRaw"] is None for r in a["metrics"]),13)
        self.assertFalse(a["publishAllowed"])

    def test_independent_full_20_expected_diffs_are_diagnostic_not_promoted(self):
        # Production working model executes fully before the Expected is read.
        a=self.run_model()
        result=diag.compare(a,self.expected)
        rows={r["metricId"]:r for r in result["metrics"]}
        self.assertEqual(result["comparedMetricIds"],20)
        self.assertEqual(result["newGoldenVerified"],0)
        self.assertEqual(result["counts"]["SOURCE_LEVEL_SAMPLE_MATCH_NEEDS_ORIGINAL_GATE"],1)
        self.assertEqual(result["counts"]["PROVISIONAL_MISMATCH"],6)
        self.assertEqual(result["counts"]["BLOCKED_NO_CANDIDATE"],13)
        # These Expected values are asserted only INSIDE independent diagnostic tests.
        self.assertEqual(rows[model.PRIMARY["Strength"]]["rawDiffActualMinusExpected"],"-79")
        self.assertEqual(rows[model.PRIMARY["Intelligence"]]["rawDiffActualMinusExpected"],"-79")
        self.assertEqual(rows[model.PRIMARY["Willpower"]]["rawDiffActualMinusExpected"],"-127")
        self.assertEqual(rows[model.PRIMARY["Dexterity"]]["rawDiffActualMinusExpected"],"-1833")
        self.assertTrue(all(r["verificationClaim"] == "NONE_FROM_THIS_DIAGNOSTIC"
                            for r in result["metrics"]))

    def test_new_contributor_case_extends_without_rewriting_old_handlers(self):
        class ObservedBase:
            family="CLASS_BASE_AND_LEVEL"
            def produce(self,source,paragon,rolls):
                # Synthetic-only strategy demonstration, NOT a Rogue base rule.
                return (model.SourceContribution(model.PRIMARY["Strength"],self.family,
                        7,"synthetic-class-base","SYNTHETIC_UNIT_TEST_NOT_SOURCE_APPROVED"),)
        baseline=self.run_model()
        extra=self.run_model(registry=model.ModelRegistry(
            (model.ProfileLevel(),model.ParagonFlatTooltip(),__import__("paragon_damage_contributors").ParagonPercentDamage(),ObservedBase())))
        old={r["metricId"]:r for r in baseline["metrics"]}
        new={r["metricId"]:r for r in extra["metrics"]}
        self.assertEqual(new[model.PRIMARY["Strength"]]["candidateRaw"],
                         old[model.PRIMARY["Strength"]]["candidateRaw"]+7)
        self.assertEqual(new[model.PRIMARY["Intelligence"]]["candidateRaw"],
                         old[model.PRIMARY["Intelligence"]]["candidateRaw"])
        self.assertEqual(new[model.LEVEL]["candidateRaw"],old[model.LEVEL]["candidateRaw"])
        self.assertTrue(new[model.PRIMARY["Strength"]]["missingContributorFamilies"])
        self.assertFalse(new[model.PRIMARY["Strength"]]["candidateIsCompleteActual"])
        self.assertEqual(extra["newGoldenVerified"],0)

    def test_perturbed_real_paragon_source_changes_candidate_not_expected(self):
        variant=deepcopy(self.paragon)
        row=next(x for x in variant["nodes"] if x["tooltip"]=="Normal Node\n+5 Strength")
        row["tooltip"]="Normal Node\n+7 Strength"
        before=self.run_model()
        after=self.run_model(paragon_witness=variant)
        b={r["metricId"]:r for r in before["metrics"]}
        a={r["metricId"]:r for r in after["metrics"]}
        self.assertEqual(a[model.PRIMARY["Strength"]]["candidateRaw"],
                         b[model.PRIMARY["Strength"]]["candidateRaw"]+2)
        self.assertEqual(a[model.PRIMARY["Dexterity"]]["candidateRaw"],
                         b[model.PRIMARY["Dexterity"]]["candidateRaw"])
        self.assertNotEqual(before["reportSha256"],after["reportSha256"])
        self.assertEqual(after["newGoldenVerified"],0)

    def test_new_percent_provider_keeps_old_contributor_cases(self):
        output=self.run_model()
        rows={r["metricId"]:r for r in output["metrics"]}
        for mid in model.PERCENT_DAMAGE_IDS:
            row=rows[mid]
            self.assertGreater(row["candidateRaw"],0)
            self.assertTrue(row["candidateDisplay"].endswith("%"))
            self.assertEqual(row["modelStatus"],"PROVISIONAL_PARTIAL_CONTRIBUTOR_SUBTOTAL")
            self.assertTrue(row["missingContributorFamilies"])
            self.assertTrue(all(c["family"]=="PARAGON_UI_PERCENT_DAMAGE"
                                for c in row["contributions"]))
            self.assertFalse(row["candidateIsCompleteActual"])
        self.assertEqual(rows[model.PRIMARY["Strength"]]["candidateRaw"],339)
        self.assertEqual(rows[model.LEVEL]["candidateRaw"],70)

    def test_no_magic_zero_for_unmapped_13_metrics(self):
        output=self.run_model()
        unknown=[x for x in output["metrics"] if x["candidateRaw"] is None]
        self.assertEqual(len(unknown),13)
        self.assertTrue(all(x["candidateDisplay"] is None and
                            x["assumption"]=="UNAVAILABLE_RUNTIME_DEPENDENCIES_NOT_DEFAULTED"
                            for x in unknown))

    def test_wrong_patch_input_provenance_and_golden_smuggling_rejected(self):
        for field in ("sourceExpected","wrongPatch","paragonBlob","rollFixture","target"):
            input_ = dict(source=self.source,inventory=self.inventory,
                          targets=self.targets,f3map=self.f3,
                          paragon_witness=self.paragon,roll_witness=self.rolls)
            if field=="sourceExpected":
                input_["source"]=deepcopy(self.source)
                input_["source"]["expectedRawValue"]=418
            elif field=="wrongPatch":
                input_["inventory"]=deepcopy(self.inventory)
                input_["inventory"]["gamePatch"]="3.2.2"
            elif field=="paragonBlob":
                input_["paragon_witness"]=deepcopy(self.paragon)
                input_["paragon_witness"]["source"]["gitBlobSha"]="0"*40
            elif field=="rollFixture":
                input_["roll_witness"]=deepcopy(self.rolls)
                input_["roll_witness"]["classId"]="sorcerer"
            elif field=="target":
                input_["targets"]=deepcopy(self.targets)
                input_["targets"]["metrics"][0]["label"]="wrong"
            with self.subTest(field=field),self.assertRaises(graph.GraphError):
                model.evaluate(**input_)

    def test_duplicate_strategy_or_source_and_forged_golden_rejected(self):
        with self.assertRaisesRegex(graph.GraphError,"DUPLICATE"):
            model.ModelRegistry((model.ProfileLevel(),model.ProfileLevel()))
        class BadStrategy:
            family="MYSTERY"
            def produce(self,source,paragon,rolls):
                return [model.SourceContribution(model.LEVEL,self.family,70,
                                                 "fake","FAKE")]
        with self.assertRaisesRegex(graph.GraphError,"STRATEGY_RESULT"):
            self.run_model(registry=model.ModelRegistry((BadStrategy(),)))
        a=self.run_model()
        for forged in ("hash","claims","actual"):
            changed=deepcopy(a)
            if forged=="hash":changed["reportSha256"]="0"*64
            if forged=="claims":changed["newGoldenVerified"]=20
            if forged=="actual":changed["metrics"][1]["candidateRaw"]=418
            with self.subTest(forged=forged),self.assertRaises(graph.GraphError):
                diag.compare(changed,self.expected)
        with self.assertRaisesRegex(graph.GraphError,"GOLDEN_CAPTURE_BLOB_MISMATCH"):
            diag.compare(a,self.expected+b" ")

if __name__=="__main__":
    unittest.main()
