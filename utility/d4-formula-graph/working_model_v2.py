"""M20 candidate model v2: compose the existing Graph candidates with
corrected research-grade Strength. No Golden read, no rule promotion.

Compatibility adapter for the internal report; only Strength is replaced.
Other 19 metric IDs retain their original contributor/resolution semantics.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import graph
import working_model
import strength_model

def evaluate(source,inventory,targets,f3map,paragon,rolls,rules):
    original=working_model.evaluate(source,inventory,targets,f3map,paragon,rolls)
    corrected=strength_model.evaluate(source,paragon,rules)
    graph.reject(original["fixtureId"]==corrected["fixtureId"] and
                 original["classId"]==corrected["classId"] and
                 original["gamePatch"]==corrected["patch"] and
                 original["inputFingerprintSha256"]==
                 corrected["inputFingerprintSha256"],
                 "STRENGTH_AND_M20_FIXTURE_IDENTITY_MISMATCH")
    # Deep copy to keep pure and avoid mutating caller-owned candidates.
    out=json.loads(json.dumps(original))
    for row in out["metrics"]:
        if row["metricId"]!=corrected["metricId"]:
            continue
        graph.reject(not row["candidateIsCompleteActual"] and
                     row["modelStatus"]=="PROVISIONAL_PARTIAL_CONTRIBUTOR_SUBTOTAL",
                     "STRENGTH_ALREADY_FINAL_OR_NOT_SOURCE_DERIVED")
        row["candidateRaw"]=corrected["candidateRaw"]
        row["candidateDisplay"]=corrected["candidateDisplay"]
        row["contributions"]=corrected["components"]
        row["missingContributorFamilies"]=corrected["missingContributorFamilies"]
        row["assumption"]="RESEARCH_BASE_LEVEL_PLUS_NON_DUPLICATE_PARAGON_UNMAPPED_OTHERS"
        row["strengthSourceBreakdown"]=corrected["decomposition"]
        row["strengthSourceReportSha256"]=corrected["reportSha256"]
        row["candidateIsCompleteActual"]=False
        row["goldenVerified"]=False
        row["modelStatus"]="PROVISIONAL_REVISED_STRENGTH_RESEARCH_CANDIDATE"
        break
    else:
        raise graph.GraphError("STRENGTH_METRIC_ID_MISSING")
    out["strengthSourceReportSha256"]=corrected["reportSha256"]
    out["modelRevision"]="STRENGTH_SCOPED_RESEARCH_COMPOSITION_V2"
    out["newGoldenVerified"]=0
    out["publishAllowed"]=False
    out["goldenExpectedLoaded"]=False
    out["reportSha256"]=graph.digest({k:v for k,v in out.items()
                                      if k!="reportSha256"})
    return out

def main(argv=None):
    p=argparse.ArgumentParser()
    for name in ("source","inventory","targets","f3map","paragon","rolls","rules","report"):
        p.add_argument("--"+name,type=Path,required=True)
    a=p.parse_args(argv)
    try:
        read=graph.read_json
        result=evaluate(read(a.source),read(a.inventory),
                        read(a.targets),read(a.f3map),read(a.paragon),
                        read(a.rolls),read(a.rules))
        code=0
    except (OSError,ValueError,TypeError,KeyError,graph.GraphError) as exc:
        result={"status":"BLOCKED_SOURCE_STRENGTH_V2","reason":str(exc),
                "newGoldenVerified":0,"publishAllowed":False}
        code=2
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="metrics"},sort_keys=True))
    return code

if __name__=="__main__":sys.exit(main())
