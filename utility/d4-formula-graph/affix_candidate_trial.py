"""#110 source item-affix contributor trial (HYPOTHESIS ONLY).

Uses actual captured item-roll identity/amount witnesses, but coefficient,
affix->metric association, conditional interaction are TEST-ONLY hypotheses.
NEVER inject proposed totals into Maxroll Character Stats actual.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import graph
import golden_candidate_eval as source_gate

def guard(ok,code):graph.reject(ok,code)

def validate_witness(w):
    guard(type(w)==dict and set(w)=={"fixtureId","partition","classId",
          "patch","sourceInputFingerprintSha256","items","scope"},
          "INVALID_AFFIX_SOURCE_WITNESS")
    guard(w["fixtureId"] in ("DEV-00","DEV-01") and
          w["partition"]=="DEVELOPMENT" and
          w["classId"] in ("rogue","sorcerer") and
          w["patch"]=="3.2.1.73552" and
          w["scope"]=="OBSERVED_EQUIPMENT_SUBSET_ONLY" and
          type(w["sourceInputFingerprintSha256"])==str and
          graph.SHA64.fullmatch(w["sourceInputFingerprintSha256"]),
          "INVALID_WITNESS_PROVENANCE_OR_SCOPE")
    guard(type(w["items"])==list and len(w["items"])<=16,"INVALID_WITNESS_ITEMS")
    ids=set()
    for item in w["items"]:
        guard(type(item)==dict and set(item)=={"slotId","itemId","explicits"},
              "INVALID_WITNESS_ITEM")
        guard(type(item["slotId"])==str and item["slotId"] not in ids and
              type(item["itemId"])==str and item["itemId"] and
              type(item["explicits"])==list,
              "DUPLICATED_OR_INVALID_WITNESS_SLOT")
        ids.add(item["slotId"])
        nids=set()
        for roll in item["explicits"]:
            guard(type(roll)==dict and set(roll)=={"nid","values"} and
                  type(roll["nid"])==int and roll["nid"]>0 and
                  roll["nid"] not in nids and
                  type(roll["values"])==list and len(roll["values"])<=4 and
                  all(type(x) in (int,float) and math.isfinite(x)
                      for x in roll["values"]),
                  "INVALID_OBSERVED_AFFIX_ROLL")
            nids.add(roll["nid"])
    return graph.digest(w)

def validated_hypothesis(h):
    guard(type(h)==dict and set(h)=={"mode","metricId",
         "numeratorNid","multiplierNid","numeratorRollIndex",
         "numeratorScale","multiplierIfPresent","unit"},
          "INVALID_HYPOTHESIS_SHAPE")
    guard(h["mode"]=="HYPOTHESIS_TEST_ONLY"
          and type(h["metricId"])==str
          and h["metricId"].startswith("maxroll.heroDetails.")
          and type(h["numeratorNid"])==int and h["numeratorNid"]>0
          and type(h["multiplierNid"])==int and h["multiplierNid"]>0
          and h["numeratorNid"]!=h["multiplierNid"]
          and type(h["numeratorRollIndex"])==int
          and 0<=h["numeratorRollIndex"]<4
          and type(h["numeratorScale"]) in (float,int)
          and math.isfinite(h["numeratorScale"])
          and type(h["multiplierIfPresent"]) in (float,int)
          and math.isfinite(h["multiplierIfPresent"])
          and h["unit"]=="HYPOTHETICAL_NOT_GAME_UNIT",
          "INVALID_UNVERIFIED_HYPOTHESIS")
    return graph.digest(h)

def run(w,h):
    sha=validate_witness(w)
    hs=validated_hypothesis(h)
    affixes={}
    for item in w["items"]:
        for roll in item["explicits"]:
            nid=roll["nid"]
            guard(nid not in affixes,"AMBIGUOUS_NID_MULTIPLE_SOURCES")
            affixes[nid]={"values":roll["values"],"slotId":item["slotId"],
                          "itemId":item["itemId"]}
    numerator=affixes.get(h["numeratorNid"])
    multiplier=affixes.get(h["multiplierNid"])
    if numerator is None:
        trial=None;status="MISSING_SOURCE_CONTRIBUTOR_UNKNOWN"
    else:
        ix=h["numeratorRollIndex"]
        guard(ix<len(numerator["values"]),"MISSING_CAPTURED_ROLL_VALUE")
        trial=(numerator["values"][ix]*h["numeratorScale"]*
               (h["multiplierIfPresent"] if multiplier is not None else 1))
        guard(math.isfinite(trial),"TRIAL_NONFINITE")
        status="HYPOTHETICAL_ONLY_NOT_GAME_FORMULA"
    trace=[{"nid":nid,"observed":nid in affixes,
            "slotId":affixes[nid]["slotId"] if nid in affixes else None,
            "values":affixes[nid]["values"] if nid in affixes else None}
           for nid in (h["numeratorNid"],h["multiplierNid"])]
    result={
        "artifactType":"INTERNAL_AFFIX_HYPOTHESIS_TRACE_NOT_MAXROLL_ACTUAL",
        "fixtureId":w["fixtureId"],"classId":w["classId"],"patch":w["patch"],
        "sourceSha256":sha,"hypothesisSha256":hs,
        "metricId":h["metricId"],"status":status,
        "observedContributorTrace":trace,
        "trialValueNotStatActual":trial,
        "maxrollMetricActual":None,
        "completeContributorCoverage":False,
        "realFormulaVerified":False,
        "sourceScope":"OBSERVED_EQUIPMENT_SUBSET_ONLY",
        "expectedSourceIncluded":False,
        "realMaxrollParity":"NOT_RUN",
        "simulationContext":None,"publishAllowed":False,
    }
    result["reportSha256"]=graph.digest(result)
    return result

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--witness",type=Path,required=True)
    p.add_argument("--hypothesis",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args(argv)
    try:
        out=run(graph.read_json(a.witness),graph.read_json(a.hypothesis))
        rc=0
    except (graph.GraphError,OSError,ValueError,KeyError,TypeError) as e:
        out={"status":"BLOCKED","error":str(e),"publishAllowed":False};rc=2
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(out,sort_keys=True))
    return rc
if __name__=="__main__":
    sys.exit(main())
