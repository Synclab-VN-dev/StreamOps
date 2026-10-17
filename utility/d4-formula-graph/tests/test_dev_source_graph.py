"""Two genuine public Maxroll build input shapes: structural source→graph tests."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import graph
import dev_source_graph as g
import source_roll_index

class CaptureGraphTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules=graph.read_json(ROOT/"fixtures"/"candidate-source-level.json")
        cls.cases=[]
        for f in ("dev00","dev01"):
            cls.cases.append((
                graph.read_json(ROOT/"fixtures"/(f+"-mechanics.json")),
                graph.read_json(ROOT/"fixtures"/(f+"-source-rolls.json")),
                graph.read_json(ROOT/"fixtures"/(f+"-visible-inventory.json"))))
    def test_source_fixtures_two_classes_full_inventory_no_goldens(self):
        for s,w,index in self.cases:
            with self.subTest(f=s["fixtureId"]):
                a=g.build(s,w,index,self.rules)
                self.assertEqual(a["visibleMetricRows"],len(index["metrics"]))
                self.assertEqual(a["uniqueMetricIds"],len({m["metricId"] for m in index["metrics"]}))
                self.assertEqual(a["candidateComputedUnique"],1)
                self.assertEqual(a["unmappedObservedRolls"],
                                 source_roll_index.index(w)["rollCount"])
                self.assertEqual(len(a["nodes"]),len({x["nodeId"] for x in a["nodes"]}))
                self.assertEqual(a,g.build(s,w,index,self.rules))
                self.assertFalse(a["publishAllowed"])
                self.assertIsNone(a["simulationContext"])
                self.assertEqual(a["fullVerifiedStatCount"],0)
                self.assertEqual(set(a["scenarioStates"].values()),{"UNKNOWN"})
                self.assertEqual(len(a["sourceStatActual"]),len(index["metrics"]))
    def test_changed_affix_roll_changes_graph_but_never_assumes_stat(self):
        s,w,index=self.cases[0]
        before=g.build(s,w,index,self.rules)
        ww=deepcopy(w)
        ww["slots"][0]["fields"]["explicits"][0]["values"][0]+=1
        after=g.build(s,ww,index,self.rules)
        delta=g.diff(before,after)
        self.assertEqual(len(delta["sourceChanges"]["changed"]),1)
        self.assertTrue(delta["sourceChanges"]["changed"][0].startswith("equipment/"))
        self.assertEqual(after["candidateComputedUnique"],1)
        self.assertEqual(delta["verifiedGameMetricDelta"],0)
    def test_changed_variant_skill_rank_rune_charm_and_board(self):
        for s,w,index in self.cases:
            before=g.build(s,w,index,self.rules)
            mutations=[]
            v=deepcopy(s);v["variant"]+=".test";mutations.append((v,w,"build/variant"))
            v=deepcopy(s);k=next(iter(v["skillRanks"]));v["skillRanks"][k]+=1;mutations.append((v,w,"skill-rank/"+k))
            v=deepcopy(s);v["sockets"][0]["values"].append("Rune_Synthetic_Only");mutations.append((v,w,"sockets/"+v["sockets"][0]["slotId"]))
            v=deepcopy(s);v["paragonBoards"][0]["glyphLevel"]=(v["paragonBoards"][0]["glyphLevel"]-1 if v["paragonBoards"][0]["glyphLevel"]>0 else 1);mutations.append((v,w,"paragon/"))
            vv=deepcopy(w);vv["slots"]=vv["slots"][1:];v=deepcopy(s);v["sockets"]=v["sockets"][1:]
            # Slot addition/removal must mutate both independently captured source views.
            mutations.append((v,vv,"equipment/"))
            for v,rolls,prefix in mutations:
                with self.subTest(fixture=s["fixtureId"],prefix=prefix):
                    a=g.build(v,rolls,index,self.rules)
                    d=g.diff(before,a)
                    changed=d["sourceChanges"]["changed"]+d["sourceChanges"]["removed"]+d["sourceChanges"]["added"]
                    self.assertTrue(any(x.startswith(prefix) for x in changed))
                    self.assertNotEqual(before["graphSha256"],a["graphSha256"])
                    self.assertEqual(a["fullVerifiedStatCount"],0)
                    self.assertEqual(a["uniqueMetricIds"],before["uniqueMetricIds"])
    def test_invalid_fixture_wrong_class_patch_and_goldens_rejected(self):
        s,w,index=self.cases[0]
        for op in ("patch","class","partition","golden","duplicate","unknownstate"):
            v=deepcopy(s)
            if op=="patch":v["gamePatch"]="3.2.3"
            if op=="class":v["classId"]="sorcerer"
            if op=="partition":v["partition"]="HOLDOUT"
            if op=="golden":v["expectedRaw"]=70
            if op=="duplicate":v["sockets"].append(deepcopy(v["sockets"][0]))
            if op=="unknownstate":v["sourceTruths"]="KNOWN_ZERO"
            with self.subTest(op=op),self.assertRaises(graph.GraphError):
                g.build(v,w,index,self.rules)
    def test_visible_inventory_missing_group_and_label_all_fail_closed(self):
        for s,w,index in self.cases:
            self.assertEqual(g.inventory_blob(index),g.INVENTORY_BLOBS[s["fixtureId"]])
            for mode in ("drop","swap_group","change_label","duplicate"):
                changed=deepcopy(index)
                if mode=="drop":changed["metrics"].pop(-1)
                elif mode=="swap_group":changed["metrics"][0]["group"]+="Changed"
                elif mode=="change_label":changed["metrics"][0]["label"]+=" Changed"
                else:changed["metrics"].append(deepcopy(changed["metrics"][0]))
                with self.subTest(fixture=s["fixtureId"],mode=mode),self.assertRaises(graph.GraphError):
                    g.build(s,w,changed,self.rules)
    def test_cross_class_or_mutated_patch_diff_blocks(self):
        a=g.build(*self.cases[0],self.rules)
        b=g.build(*self.cases[1],self.rules)
        with self.assertRaises(graph.GraphError):g.diff(a,b)
