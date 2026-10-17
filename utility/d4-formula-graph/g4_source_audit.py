"""#108 G4 input/Actual *coverage* audit, not Golden parity or rule verification.

Frozen UI visible-row inventory is independent of current graph output. Audit
counts UNKNOWN, missing, stale, unsupported and N/A by group; no missing value
may silently become 0 or be excluded. Does NOT read private Golden Expected.
"""
from __future__ import annotations
from collections import Counter
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import graph
import dev_source_graph

def require(x,why):graph.reject(x,why)
STATES=("MATCHED_VERIFIED","MISMATCHED_VERIFIED","CANDIDATE_UNVERIFIED","UNKNOWN","MISSING_GRAPH_ROW",
        "STALE_SOURCE","UNSUPPORTED","UNAVAILABLE","NOT_APPLICABLE")
EVIDENCE_STATES={"UNSUPPORTED","UNAVAILABLE","NOT_APPLICABLE"}

def key(row):
    return (row["group"].casefold().strip(),row["metricId"])

def analyze(reference,actual):
    require(type(reference)==dict and type(actual)==dict,
            "INVALID_G4_AUDIT_DOCUMENTS")
    fid=reference.get("fixtureId")
    require(fid in dev_source_graph.ALLOWED_CLASSES and
            dev_source_graph.inventory_blob(reference)==
              dev_source_graph.INVENTORY_BLOBS[fid] and
            reference.get("partition")=="DEVELOPMENT" and
            reference.get("classId")==dev_source_graph.ALLOWED_CLASSES[fid],
            "G4_FROZEN_SOURCE_METRIC_INVENTORY_NOT_PINNED")
    require(actual.get("artifactType")=="DEVELOPMENT_SOURCE_GRAPH_NOT_PUBLIC_BE"
            and actual.get("fixtureId")==fid and
            actual.get("classId")==reference["classId"] and
            actual.get("fullVerifiedStatCount")==0 and
            actual.get("sourceGoldenExpectedLoaded") is False and
            actual.get("holdoutExpectedLoaded") is False and
            actual.get("publishAllowed") is False,
            "G4_EXPECTED_OR_VERIFICATION_PROMOTION_FORBIDDEN")
    require(actual.get("graphSha256")==graph.digest({
        k:v for k,v in actual.items() if k!="graphSha256"}),
        "G4_GRAPH_CONTENT_HASH_MISMATCH")
    source=reference["metrics"]
    seen_source={key(x) for x in source}
    require(len(seen_source)==len(source),"G4_REFERENCE_DUPLICATE_UI_ROW")
    rows=actual.get("sourceStatActual")
    require(type(rows)==list,"G4_ACTUAL_ROW_COLLECTION_MISSING")
    actual_by_key={}
    for row in rows:
        k=key(row)
        require(k not in actual_by_key,"G4_DUPLICATE_ACTUAL_UI_ROW")
        require(k in seen_source,"G4_UNREFERENCED_ACTUAL_METRIC_PROJECTION")
        actual_by_key[k]=row
    stale=(actual.get("gamePatch")!=reference["gamePatch"] or
           actual.get("fixtureInputFingerprint")!=reference["inputFingerprintSha256"])
    groups={}
    entries=[]
    for source_row in source:
        group=source_row["group"]
        counts=groups.setdefault(group,{x:0 for x in STATES})
        a=actual_by_key.get(key(source_row))
        reason=None
        if stale:
            state="STALE_SOURCE";reason="PATCH_OR_INPUT_FINGERPRINT_MISMATCH"
        elif a is None:
            state="MISSING_GRAPH_ROW";reason="SOURCE_CAPTURED_UI_ROW_NOT_IN_GRAPH"
        else:
            require(a.get("label")==source_row["label"],
                    "G4_SOURCE_LABEL_CHANGED")
            status=a.get("status")
            if status=="CANDIDATE_COMPUTED_UNVERIFIED":
                require(a.get("computed") is True and
                        type(a.get("raw")) in (int,float) and
                        a.get("trace"),"G4_FAKE_CANDIDATE_COMPUTATION")
                state="CANDIDATE_UNVERIFIED"
                reason="G3_G4_INDEPENDENT_PARITY_NOT_VERIFIED"
            elif status in ("UNKNOWN","BLOCKED_UNKNOWN_FORMULA"):
                require(a.get("raw") is None and not a.get("computed"),
                        "G4_UNKNOWN_MUST_NOT_HAVE_NUMERIC_VALUE")
                state="UNKNOWN";reason="MISSING_VERIFIED_CHARACTER_STAT_FORMULA"
            elif status in EVIDENCE_STATES:
                require(a.get("raw") is None and
                        type(a.get("reason"))==str and len(a["reason"])>=8 and
                        (status!="NOT_APPLICABLE" or
                         bool(a.get("applicabilityEvidence"))),
                        "G4_UNSUPPORTED_NA_REQUIRES_EXPLICIT_EVIDENCE")
                state=status;reason=a["reason"]
            else:
                require(False,"G4_FORGED_METRIC_VERIFICATION_OR_INVALID_STATUS")
        counts[state]+=1
        entries.append({"metricId":source_row["metricId"],"group":group,
                        "label":source_row["label"],"state":state,
                        "sourceReason":reason,"actualValue":None if a is None else a.get("raw")})
    totals={x:sum(g[x] for g in groups.values()) for x in STATES}
    require(sum(totals.values())==len(source),"G4_METRIC_DENOMINATOR_DROP")
    result={
       "artifactType":"DEVELOPMENT_G4_VISIBLE_METRIC_COVERAGE_NOT_GOLDEN_PARITY",
       "fixtureId":fid,"classId":reference["classId"],
       "sourcePatch":reference["gamePatch"],
       "sourceFingerprint":reference["inputFingerprintSha256"],
       "sourceGraphSha256":actual["graphSha256"],
       "sourceInventoryGitBlob":dev_source_graph.INVENTORY_BLOBS[fid],
       "visibleMetricRows":len(source),
       "distinctMetricIds":len({x["metricId"] for x in source}),
       "groupCoverage":{g:{"visible":sum(counts.values()),**counts}
                         for g,counts in sorted(groups.items())},
       "totals":totals,"rows":entries,
       "missingActualRows":totals["MISSING_GRAPH_ROW"],
       "staleActualRows":totals["STALE_SOURCE"],
       "unknownFormulaRows":totals["UNKNOWN"],
       "unverifiedComputedRows":totals["CANDIDATE_UNVERIFIED"],
       "verifiedMatchedRows":totals["MATCHED_VERIFIED"],
       "verifiedMismatchedRows":totals["MISMATCHED_VERIFIED"],
       "goldenReferenceLoaded":False,"ownerApprovedGolden":False,
       "fullCapturedFixtureParity":"BLOCKED_NOT_VERIFIED",
       "status":"BLOCKED_G4_INDEPENDENT_GOLDEN_OR_FORMULAS_MISSING",
       "holdoutOpened":False,"publishAllowed":False,
    }
    result["auditSha256"]=graph.digest(result)
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--inventory",type=Path,required=True)
    p.add_argument("--source-graph",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    args=p.parse_args()
    try:
        out=analyze(graph.read_json(args.inventory),
                    graph.read_json(args.source_graph))
        rc=0
    except (graph.GraphError,TypeError,ValueError,KeyError,OSError) as e:
        out={"status":"BLOCKED","reason":str(e),"publishAllowed":False,
             "fullCapturedFixtureParity":"BLOCKED_NOT_VERIFIED"}
        rc=2
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in out.items() if k not in ("rows","groupCoverage")},sort_keys=True))
    return rc
if __name__=="__main__":raise SystemExit(main())
