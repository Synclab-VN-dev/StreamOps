"""Deterministic two-class source graph and controlled single-roll diff evidence."""
from __future__ import annotations
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import graph
import dev_source_graph as sourcegraph

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    base=Path(__file__).parent/"fixtures"
    rules=graph.read_json(base/"candidate-source-level.json")
    args.output.mkdir(parents=True,exist_ok=True)
    for name in ("dev00","dev01"):
        source=graph.read_json(base/(name+"-mechanics.json"))
        rolls=graph.read_json(base/(name+"-source-rolls.json"))
        inventory=graph.read_json(base/(name+"-visible-inventory.json"))
        baseline=sourcegraph.build(source,rolls,inventory,rules)
        after=deepcopy(rolls)
        after["slots"][0]["fields"]["explicits"][0]["values"][0]+=1
        changed=sourcegraph.build(source,after,inventory,rules)
        evidence=sourcegraph.diff(baseline,changed)
        graph.reject(baseline["graphSha256"]!=changed["graphSha256"]
                     and evidence["verifiedGameMetricDelta"]==0
                     and len(evidence["sourceChanges"]["changed"])==1
                     and evidence["sourceChanges"]["changed"][0].startswith("equipment/"),
                     "SOURCE_REAL_INPUT_MUTATION_NOT_REPRODUCIBLE")
        (args.output/(name+"-source-graph.json")).write_text(
            json.dumps(baseline,sort_keys=True,indent=2)+"\n",encoding="utf-8")
        (args.output/(name+"-source-graph-diff.json")).write_text(
            json.dumps(evidence,sort_keys=True,indent=2)+"\n",encoding="utf-8")
        print(name,"visible_rows",baseline["visibleMetricRows"],
              "unique_ids",baseline["uniqueMetricIds"],
              "graph_nodes",baseline["sourceNodeCount"],
              "changed",evidence["sourceChanges"]["changed"])
if __name__=="__main__":main()
