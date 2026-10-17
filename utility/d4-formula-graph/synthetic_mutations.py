"""#110 executable synthetic mutation report: reference vectors are TEST ONLY."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import graph
import demo_graph

CASES=[
    ("removed_item","equippedItems",[],10,2),
    ("added_unrelated_item","equippedItems",["synthetic.item.other"],10,2),
    ("variant_switched","variant","synthetic.beta",30,1),
    ("rune_count_changed","runeCount",0,20,2),
    ("charm_set_count_changed","charmCount",1,20,2),
    ("skill_rank_changed","skillRank",2,30,3),
]


def run(overlay,source):
    original=demo_graph.build(overlay,source)
    graph.reject(original["realCharacterComputed"]==0 and
                 original["syntheticOutputOnly"]["stats"]["synthetic.damageBonus"]==30
                 and original["syntheticOutputOnly"]["skills"]["synthetic.projectile"]["projectile_count"]==2,
                 "SYNTHETIC_GOLDEN_EXPECTATION_DRIFT")
    records=[]
    for case,key,value,bonus,count in CASES:
        changed=deepcopy(source)
        changed["input"][key]=value
        after=demo_graph.build(overlay,changed)
        measured=after["syntheticOutputOnly"]
        graph.reject(measured["stats"]["synthetic.damageBonus"]==bonus and
                     measured["skills"]["synthetic.projectile"]["projectile_count"]==count,
                     "SYNTHETIC_EXPECTED_ACTUAL_MISMATCH_"+case)
        graph.reject(after["graphSha256"]!=original["graphSha256"],
                     "SYNTHETIC_GRAPH_HASH_DID_NOT_CHANGE_"+case)
        graph.reject(after["realCharacterComputed"]==0 and
                     after["unknownCharacterMetrics"]==50
                     and all(x["raw"] is None and x["display"] is None
                             for x in after["characterMetrics"]),
                     "SYNTHETIC_ACTUAL_LEAK_INTO_MAXROLL_"+case)
        records.append({
            "case":case,"changedInput":key,
            "beforeGraphSha256":original["graphSha256"],
            "afterGraphSha256":after["graphSha256"],
            "expectedSyntheticBonus":bonus,
            "actualSyntheticBonus":measured["stats"]["synthetic.damageBonus"],
            "expectedSyntheticProjectileCount":count,
            "actualSyntheticProjectileCount":measured["skills"]["synthetic.projectile"]["projectile_count"],
            "maxrollMetricsComputed":0,
            "realMaxrollParity":"BLOCKED_NOT_RUN",
        })
    report={
        "status":"PASS_SYNTHETIC_CI02_MUTATIONS_ONLY",
        "kind":"INTERNAL_SYNTHETIC_BUILD_GRAPH_DIFF_NOT_MAXROLL_PARITY",
        "baselineGraphSha256":original["graphSha256"],
        "cases":records,
        "testCaseCount":len(records),
        "maxrollVerifiedFormulas":0,
        "simulationContext":None,
        "publishAllowed":False,
    }
    report["reportSha256"]=graph.digest(report)
    return report


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--overlay",type=Path,required=True)
    p.add_argument("--fixture",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args(argv)
    try:
        result=run(graph.read_json(a.overlay),graph.read_json(a.fixture))
        rc=0
    except (graph.GraphError,OSError,ValueError,KeyError,UnicodeError,TypeError) as exc:
        result={"status":"BLOCKED","errors":[str(exc)],"publishAllowed":False}
        rc=2
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps({k:v for k,v in result.items() if k!="cases"},sort_keys=True))
    return rc
if __name__=="__main__":
    sys.exit(main())
