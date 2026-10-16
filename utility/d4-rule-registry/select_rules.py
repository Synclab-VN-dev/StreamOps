"""#109 deterministic read-only registry selection. Internal artifact, NOT public BE transport.

All current rules are non-active. A compatible candidate is NOT an executable rule.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import registry

def resolve(catalog,catalog_sha,policy,candidates,request):
    registry.require(isinstance(request,dict) and
                     set(request)=={"gamePatch","gameBuild","classId","fixtureFingerprint"},
                     "INVALID_SELECTION_INPUT")
    registry.require((request.get("gamePatch"),request.get("gameBuild"),
                      request.get("classId"))==
                     (registry.PATCH,registry.BUILD,registry.CLASS),"SELECTION_PATCH_CLASS_MISMATCH")
    registry.require(request.get("fixtureFingerprint")==
                     catalog.get("fixture",{}).get("inputSnapshotSha256"),
                     "SELECTION_FIXTURE_FINGERPRINT_MISMATCH")
    frozen=registry.snapshot(catalog,catalog_sha,policy,candidates)
    original=frozen["snapshotSha256"]
    registry.require(original==registry.sha256({k:v for k,v in frozen.items()
                                                if k!="snapshotSha256"}),
                     "REGISTRY_SNAPSHOT_HASH_MISMATCH")
    require_catalog=set(m["metricId"] for m in catalog["metrics"])
    registry.require(len(require_catalog)==50 and len(frozen["metrics"])==50,
                     "REGISTRY_INCOMPLETE")
    # Do not use research-grade as an execution-grade confidence.
    result=[]
    for row in frozen["metrics"]:
        mid=row["metricId"]
        registry.require(mid in require_catalog and row["activeRule"] is None
                         and row["calculatedValue"] is None,
                         "ACTIVE_RULE_WITHOUT_APPROVAL")
        registry.require(row["ruleStatus"] in {"UNKNOWN","CANDIDATE_UNVERIFIED"},
                         "FALSE_RULE_PROMOTION")
        is_candidate=row["ruleStatus"]=="CANDIDATE_UNVERIFIED"
        result.append({
            "metricId":mid,
            "group":row["group"],
            "state":"UNVERIFIED" if is_candidate else "UNKNOWN",
            "candidateId":row["candidateId"] if is_candidate else None,
            "executableRule":None,
            "value":None,
            "sourceGrade":row["sourceFormulaResearchStatus"],
            "reason":"CANDIDATE_G2_G3_G4_NOT_VERIFIED" if is_candidate
                     else "NO_APPROVED_FORMULA_RULE",
        })
    result=sorted(result,key=lambda row:row["metricId"])
    registry.require(len(result)==50 and len({x["metricId"] for x in result})==50,
                     "INCOMPLETE_SELECTED_METRICS")
    selection={
        "status":"BLOCKED_NO_APPROVED_EXECUTABLE_RULES",
        "artifactType":"INTERNAL_READ_ONLY_RULE_SELECTION_NOT_GRAPH_RESULT",
        "gamePatch":registry.PATCH,
        "gameBuild":registry.BUILD,
        "classId":registry.CLASS,
        "fixtureFingerprint":request["fixtureFingerprint"],
        "registrySnapshotSha256":original,
        "catalogSha256":catalog_sha,
        "coverage":{"denominator":50,"missing":49,"candidateUnverified":1,
                    "activeRules":0,"verifiedGameFormulas":0,
                    "approvedGoldens":0,"realMaxrollParity":"NOT_RUN"},
        "metrics":result,
        "sourceOfExpectedGolden":"NOT_INCLUDED",
        "executableRules":[],
        "simulationContext":None,
        "publishAllowed":False,
    }
    # An empty candidate list is a valid and still blocked state.
    selection["coverage"]["missing"]=sum(x["state"]=="UNKNOWN" for x in result)
    selection["coverage"]["candidateUnverified"]=sum(x["state"]=="UNVERIFIED" for x in result)
    selection["selectionSha256"]=registry.sha256(selection)
    return selection

def main(argv=None):
    p=argparse.ArgumentParser(description="Read-only exact-patch rule-selection debug report")
    p.add_argument("--request",type=Path,default=HERE/"fixtures"/"rogue-request.json")
    p.add_argument("--candidates",type=Path,default=HERE/"candidates.json")
    p.add_argument("--report",type=Path,required=True)
    args=p.parse_args(argv)
    try:
        catalog,source_sha=registry.read_pinned_catalog()
        result=resolve(catalog,source_sha,registry.load(registry.POLICY),
                       registry.load(args.candidates),registry.load(args.request))
        code=0  # Successfully produced a BLOCKED selection artifact.
    except (registry.RegistryError,ValueError,TypeError,KeyError,OSError,UnicodeError,
            ImportError) as exc:
        result={"status":"BLOCKED","errors":[str(exc)],
                "publishAllowed":False,"executableRules":[],
                "realMaxrollParity":"NOT_RUN"}
        code=2
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="metrics"},sort_keys=True))
    return code

if __name__=="__main__":
    sys.exit(main())
