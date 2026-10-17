"""Target 20 count must be unique Golden PASS metric IDs, never CI unit counts."""
import sys,unittest
from pathlib import Path
from copy import deepcopy
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import graph,golden_candidate_eval,scoped_golden_verifier,target20_readiness

class M20Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        f=ROOT/"fixtures"
        cls.manifest=graph.read_json(f/"milestone20-source-targets.json")
        cls.source=graph.read_json(f/"dev00-source-sanitized.json")
        cls.inventory=graph.read_json(f/"dev00-visible-inventory.json")
        cls.rules=graph.read_json(f/"candidate-source-level.json")
        cls.golden=graph.read_json(f/"golden-dev"/"dev00-level.json")
    def results(self):
        a=golden_candidate_eval.build(self.source,self.inventory,self.rules)
        g=scoped_golden_verifier.verify(a,self.golden)
        return a,g
    def test_real_dev00_golden_1_of_20_not_full_parity(self):
        a,g=self.results()
        r=target20_readiness.audit(self.manifest,a,[g])
        self.assertEqual(r["verifiedUniqueMetricIds"],1)
        self.assertEqual(r["remainingUniqueMetricIds"],19)
        self.assertEqual(len(r["metrics"]),20)
        self.assertEqual(sum(x["status"]=="VERIFIED" for x in r["metrics"]),1)
        self.assertEqual(sum(x["status"]=="BLOCKED_NO_REAL_COMPUTED_ACTUAL" for x in r["metrics"]),19)
        self.assertEqual([x["label"] for x in r["metrics"] if x["status"]=="VERIFIED"],["Level"])
        self.assertFalse(r["goldenExpectedInjectedIntoGraph"])
        self.assertFalse(r["productionRulePromoted"])
        self.assertEqual(r["status"],"IN_PROGRESS")
        self.assertEqual(r["reportSha256"],graph.digest({k:v for k,v in r.items() if k!="reportSha256"}))
    def test_deterministic_and_no_golden_expected_values_on_uncomputed(self):
        a,g=self.results()
        r=target20_readiness.audit(self.manifest,a,[g])
        self.assertEqual(r,target20_readiness.audit(self.manifest,a,[g]))
        pending=[x for x in r["metrics"] if x["status"]!="VERIFIED"]
        self.assertTrue(all(x["verifiedGoldenRaw"] is None and
                            x["verifiedGoldenDisplay"] is None
                            for x in pending))
    def test_fake_passing_report_rejected(self):
        a,g=self.results()
        for mode in ("forge_verified_count","forge_actual_raw","forge_report_hash","wrong_class","duplicate"):
            bad=deepcopy(g)
            if mode=="forge_verified_count":bad["verifiedScoped"]=20
            elif mode=="forge_actual_raw":bad["metrics"][0]["actualRaw"]=123
            elif mode=="forge_report_hash":bad["reportSha256"]="0"*64
            elif mode=="wrong_class":bad["classId"]="sorcerer"
            with self.subTest(mode=mode),self.assertRaises(graph.GraphError):
                target20_readiness.audit(self.manifest,a,[bad,bad] if mode=="duplicate" else [bad])
    def test_class_support_cannot_auto_promote_rogue_20_into_sorcerer(self):
        a,g=self.results()
        source=graph.read_json(ROOT/"fixtures"/"dev01-source-sanitized.json")
        inventory=graph.read_json(ROOT/"fixtures"/"dev01-visible-inventory.json")
        other=golden_candidate_eval.build(source,inventory,self.rules)
        with self.assertRaises(graph.GraphError):
            target20_readiness.audit(self.manifest,other,[g])
    def test_no_shortcut_by_duplicate_metric_targets(self):
        a,g=self.results()
        d=deepcopy(self.manifest)
        d["metricSources"][19]=deepcopy(d["metricSources"][0])
        with self.assertRaises(graph.GraphError):
            target20_readiness.audit(d,a,[g])
    def test_uncomputed_source_cannot_be_declared_verified_by_reference(self):
        a,g=self.results()
        # Trying to promote an uncomputed metric through a copied Golden PASS
        # fails the original report checksum and/or actual evidence match.
        bad=deepcopy(g)
        bad["metrics"][0]["metricId"]="maxroll.heroDetails.108"
        bad["reportSha256"]=graph.digest({k:v for k,v in bad.items() if k!="reportSha256"})
        with self.assertRaises(graph.GraphError):
            target20_readiness.audit(self.manifest,a,[bad])
