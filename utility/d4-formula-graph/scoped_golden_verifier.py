"""Golden verification scoped to class+fixture+patch, independent of formula calculation.

Only data from captured DEVELOPMENT Golden is read by verify(); the formula
engine never receives Golden Expected. A passing metric is VERIFIED only in
the named fixture scope; this does not approve a production rule.
"""
from __future__ import annotations
from decimal import Decimal,InvalidOperation
import argparse,json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import golden_candidate_eval as evaluator
import graph

def require(cond,error):graph.reject(cond,error)
def dec(x):
    require(type(x) in (int,float),"INVALID_NUMERIC_GOLDEN")
    try:v=Decimal(str(x))
    except InvalidOperation:raise graph.GraphError("INVALID_NUMERIC_GOLDEN")
    require(v.is_finite(),"NONFINITE_GOLDEN")
    return v

def verify(actual,golden):
    require(type(golden)==dict and golden.get("schema")=="scoped-maxroll-golden-v1"
            and golden.get("partition")=="DEVELOPMENT","INVALID_GOLDEN_REFERENCE")
    require(type(actual)==dict and actual.get("artifactType")==
            "INTERNAL_GOLDEN_DRIVEN_CANDIDATE_ACTUAL_NOT_PUBLIC_BE"
            and actual.get("partition")=="DEVELOPMENT"
            and actual.get("sourceExpectedImported") is False
            and actual.get("publishAllowed") is False,"ACTUAL_MUST_BE_INDEPENDENT")
    require(actual.get("graphSha256")==graph.digest(
            {k:v for k,v in actual.items() if k!="graphSha256"}),
            "ACTUAL_GRAPH_HASH_MISMATCH")
    for a,b in (("fixtureId","fixtureId"),("classId","classId"),
                ("gamePatch","patch"),("sourceInputFingerprint","inputSha256"),
                ("runtimeSourceSha256","runtimeSha256")):
        require(actual.get(a)==golden.get(b),"GOLDEN_SCOPE_MISMATCH_"+a)
    source=golden.get("source",{})
    require(source.get("repository")=="Synclab-VN-dev/synclab-agent"
            and source.get("commit")=="bb4c5cc6b2135583eb708f0a3f374060675b6c0b"
            and source.get("path")==(
                "evidence/StreamOps-108/F-GOLDEN-01/20261017-batch-01/"
                "development/"+golden["fixtureId"]+"/expected-maxroll.json")
            and type(source.get("gitBlobSha"))==str
            and len(source["gitBlobSha"])==40,"UNPINNED_GOLDEN_SOURCE")
    require(type(golden.get("metrics"))==list and golden["metrics"],
            "EMPTY_GOLDEN_SUBSET")
    rows=actual.get("characterMetrics",[])
    lookup={(r["group"].casefold(),r["metricId"]):r for r in rows}
    require(len(lookup)==len(rows),"DUPLICATE_VISIBLE_METRIC_POSITION")
    result=[];seen=set()
    for target in golden["metrics"]:
        key=(target["group"].casefold(),target["id"])
        require(key in lookup and key not in seen
                and lookup[key]["label"].casefold()==target["label"].casefold(),
                "GOLDEN_METRIC_CLASS_GROUP_LABEL_MISMATCH")
        seen.add(key);candidate=lookup[key]
        require(dec(target["tolerance"])==0,"UNAPPROVED_TOLERANCE")
        computed=candidate.get("computed") is True and bool(candidate.get("trace"))
        if not computed:
            status="NOT_VERIFIED";delta=None
        else:
            delta=dec(candidate["raw"])-dec(target["raw"])
            status=("VERIFIED" if delta==0
                    and candidate.get("display")==target["display"]
                    else "FAIL")
        result.append({"metricId":target["id"],"group":target["group"],
                       "status":status,"testResult":"PASS" if status=="VERIFIED"
                       else "BLOCKED" if not computed else "FAIL",
                       "expectedRaw":target["raw"],"actualRaw":candidate.get("raw"),
                       "expectedDisplay":target["display"],
                       "actualDisplay":candidate.get("display"),
                       "rawDiff":str(delta) if delta is not None else None,
                       "trace":candidate.get("trace",[])})
    count=sum(x["status"]=="VERIFIED" for x in result)
    failures=sum(x["status"]=="FAIL" for x in result)
    report={"schema":"scoped-character-stat-verification-v1",
            "classId":golden["classId"],"fixtureId":golden["fixtureId"],
            "gamePatch":golden["patch"],
            "inputFingerprintSha256":golden["inputSha256"],
            "runtimeSourceSha256":golden["runtimeSha256"],
            "goldenSource":source,"goldenSubsetSha256":graph.digest(golden),
            "actualSha256":actual["graphSha256"],
            "ruleSetSha256":actual["candidateRuleSetSha256"],
            "status":"PASS_SCOPED" if count==len(result) else
                     "FAIL_GOLDEN" if failures else "BLOCKED_UNCOMPUTED",
            "verifiedScoped":count,"failures":failures,
            "blocked":len(result)-count-failures,
            "verifiedAcrossAllClasses":False,
            "fullCharacterStatsParity":False,
            "productionRulePromoted":False,"holdoutUsed":False,
            "metrics":result}
    report["reportSha256"]=graph.digest(report)
    return report

def main():
    p=argparse.ArgumentParser()
    for k in ("source","inventory","rules","golden","report"):
        p.add_argument("--"+k,type=Path,required=True)
    a=p.parse_args()
    try:
        # Source-derived Actual is finished before the independent reference is loaded.
        computed=evaluator.build(graph.read_json(a.source),
                graph.read_json(a.inventory),graph.read_json(a.rules))
        result=verify(computed,graph.read_json(a.golden))
        status=0 if result["status"]=="PASS_SCOPED" else 1
    except (OSError,ValueError,TypeError,KeyError,graph.GraphError) as error:
        result={"status":"BLOCKED_INVALID_REFERENCE_OR_GRAPH","error":str(error),
                "verifiedScoped":0}
        status=2
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps({k:v for k,v in result.items() if k!="metrics"},sort_keys=True))
    return status

if __name__=="__main__":sys.exit(main())
