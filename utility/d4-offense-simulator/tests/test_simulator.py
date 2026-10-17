"""Acceptance vectors for sandbox event primitives; no game-real DPS."""
from copy import deepcopy
import json,sys,unittest
from pathlib import Path
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE))
import simulator as s
class SimulatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.d=json.loads((BASE/"fixtures"/"synthetic-context.json").read_text())
    def test_exact_damage_rank_and_horizon(self):
        d=deepcopy(self.d);d.update(rate=2,horizon=2,rank=2,rankBonus=.1,
                 critChance=0,procChance=0,cost=0,cooldown=0)
        r=s.simulate(d)
        self.assertEqual(r["eventCount"],4)
        self.assertAlmostEqual(r["syntheticDps"],240)
        self.assertIsNone(r["realDps"])
        self.assertFalse(r["publishAllowed"])
    def test_proc_critical_bounds_and_icd(self):
        d=deepcopy(self.d);d.update(horizon=3,rate=4,critChance=1,procChance=1,
             procIcd=1,cooldown=.5,cost=0)
        r=s.simulate(d)
        self.assertEqual(r["eventCount"],6)
        self.assertEqual([e["time"] for e in r["events"] if e["procExtra"]],[0,1,2])
        d.update(critChance=0,procChance=0)
        self.assertGreater(r["syntheticDps"],s.simulate(d)["syntheticDps"])
    def test_resource_and_cooldown(self):
        d=deepcopy(self.d);d.update(rate=2,horizon=3,resource=5,cost=5,
                                      regen=0,procChance=0,critChance=0)
        self.assertEqual(s.simulate(d)["eventCount"],1)
        d["regen"]=10
        self.assertGreater(s.simulate(d)["eventCount"],1)
    def test_seed_determinism_and_convergence(self):
        self.assertEqual(s.simulate(self.d),s.simulate(self.d))
        d=deepcopy(self.d);d.update(rate=1,horizon=20,critChance=.5,
                  procChance=0,cost=0,rank=0,power=10,cooldown=0)
        vals=[]
        for seed in range(200):
            d["seed"]=seed;vals.append(s.simulate(d)["syntheticDps"])
        expected=10*(1+.5*(d["critMultiplier"]-1))
        self.assertLess(abs(sum(vals)/len(vals)-expected),expected*.07)
    def test_invalid_values_and_limits(self):
        for k,v in (("mode","REAL"),("rate",0),("horizon",0),
                    ("critChance",1.1),("procChance",float("nan")),
                    ("seed",-1),("resource",1000),("uptime",2)):
            d=deepcopy(self.d);d[k]=v
            with self.subTest(k=k),self.assertRaises(s.Blocked):s.simulate(d)
    def test_stale_patch_and_missing_identity_rejected(self):
        graph={"artifactType":"DEVELOPMENT_SOURCE_GRAPH_NOT_PUBLIC_BE",
               "graphSha256":"0"*64,"gamePatch":"3.2.3",
               "publishAllowed":False,"sourceStatActual":[],
               "scenarioStates":{}}
        out=s.require_graph(graph,["maxroll.heroDetails.3"])
        self.assertEqual(out["status"],"BLOCKED")
        self.assertTrue(out["stalePatch"])
        self.assertIsNone(out["realDps"])
        graph["gamePatch"]="3.2.1.73552"
        graph["graphSha256"]=None
        out=s.require_graph(graph,["maxroll.heroDetails.3"])
        self.assertTrue(out["invalidGraphIdentity"])
        self.assertEqual(out["status"],"BLOCKED")
    def test_unknown_critical_graph_blocks_and_never_recomputes(self):
        g={"artifactType":"DEVELOPMENT_SOURCE_GRAPH_NOT_PUBLIC_BE",
           "graphSha256":"0"*64,"publishAllowed":False,
           "sourceStatActual":[{"metricId":"maxroll.heroDetails.3","raw":None,
                                "status":"UNKNOWN"},
                               {"metricId":"maxroll.heroDetails.431","raw":200,
                                "status":"CANDIDATE_COMPUTED_UNVERIFIED"}],
           "scenarioStates":{"procUptime":"UNKNOWN"}}
        r=s.require_graph(g,["maxroll.heroDetails.3"])
        self.assertEqual(r["status"],"BLOCKED")
        self.assertFalse(r["statRecalculation"])
        self.assertFalse(r["completeCharacterStatParity"])
        self.assertIsNone(r["realDps"])
