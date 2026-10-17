"""Internal #109 selection -> #110 blocked Graph evidence bridge.

Selection is only a read-only artifact, NEVER the source of executable rules.
This does not introduce or approve a public BE transport.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import graph

HEADERS={"status","artifactType","gamePatch","gameBuild","classId",
         "fixtureFingerprint","registrySnapshotSha256","catalogSha256",
         "coverage","metrics","sourceOfExpectedGolden","executableRules",
         "simulationContext","publishAllowed","selectionSha256"}
ROW_KEYS={"metricId","group","state","candidateId","executableRule",
          "value","sourceGrade","reason"}
COVERAGE_KEYS={"denominator","missing","candidateUnverified","activeRules",
               "verifiedGameFormulas","approvedGoldens","realMaxrollParity"}
GRADES={"PARTIAL","BOUNDED_VERIFIED","VERIFIED"}


def bind(overlay,selected):
    cat,source_sha=graph.source_catalog()
    original=graph.build_graph(cat,source_sha,overlay)
    graph.reject(type(selected)==dict and set(selected)==HEADERS,
                 "INVALID_REGISTRY_SELECTION_ENVELOPE")
    graph.reject(selected["artifactType"]==
                 "INTERNAL_READ_ONLY_RULE_SELECTION_NOT_GRAPH_RESULT" and
                 selected["status"]=="BLOCKED_NO_APPROVED_EXECUTABLE_RULES",
                 "REGISTRY_SELECTION_MUST_BE_NONEXECUTABLE")
    graph.reject((selected["gamePatch"],selected["gameBuild"],selected["classId"])==
                 (original["gamePatch"],original["gameBuild"],original["classId"]),
                 "REGISTRY_SELECTION_PATCH_CLASS_MISMATCH")
    graph.reject(selected["catalogSha256"]==source_sha and
                 selected["fixtureFingerprint"]==original["sourceFixtureFingerprint"],
                 "REGISTRY_SELECTION_SOURCE_MISMATCH")
    graph.reject(type(selected["registrySnapshotSha256"])==str and
                 bool(graph.SHA64.fullmatch(selected["registrySnapshotSha256"])),
                 "REGISTRY_SNAPSHOT_HASH_MISSING")
    graph.reject(selected["selectionSha256"]==graph.digest({
        k:v for k,v in selected.items() if k!="selectionSha256"}),
                 "REGISTRY_SELECTION_HASH_MISMATCH")
    graph.reject(selected["sourceOfExpectedGolden"]=="NOT_INCLUDED"
                 and selected["executableRules"]==[]
                 and selected["simulationContext"] is None
                 and selected["publishAllowed"] is False,
                 "REGISTRY_ATTEMPTED_GOLDEN_OR_RULE_EXECUTION")
    coverage=selected["coverage"]
    graph.reject(type(coverage)==dict and set(coverage)==COVERAGE_KEYS,
                 "REGISTRY_SELECTION_COVERAGE_INVALID")
    graph.reject(coverage["denominator"]==50 and
                 coverage["activeRules"]==0 and
                 coverage["verifiedGameFormulas"]==0 and
                 coverage["approvedGoldens"]==0 and
                 coverage["realMaxrollParity"]=="NOT_RUN",
                 "REGISTRY_FALSE_VERIFIED_PROMOTION")
    source={x["metricId"]:x for x in cat["metrics"]}
    rows=selected["metrics"]
    graph.reject(type(rows)==list and len(rows)==50
                 and all(type(x)==dict and set(x)==ROW_KEYS for x in rows),
                 "REGISTRY_SELECTION_ROWS_INCOMPLETE")
    seen=set()
    index={}
    for row in rows:
        mid=row["metricId"]
        graph.reject(type(mid)==str and mid not in seen and mid in source,
                     "REGISTRY_SELECTION_UNKNOWN_OR_DUPLICATE_METRIC")
        seen.add(mid)
        graph.reject(row["group"]==source[mid]["group"],
                     "REGISTRY_SELECTION_METRIC_GROUP_MISMATCH")
        graph.reject(row["sourceGrade"] in GRADES and
                     row["sourceGrade"]==source[mid]["formulaVerificationStatus"],
                     "REGISTRY_SOURCE_RESEARCH_GRADE_MISMATCH")
        state=row["state"]
        graph.reject(state in ("UNKNOWN","UNVERIFIED"),
                     "UNAPPROVED_REAL_EXECUTABLE_RULE")
        graph.reject(row["value"] is None and row["executableRule"] is None,
                     "UNAPPROVED_NUMERIC_RULE_INJECTION")
        if state=="UNVERIFIED":
            graph.reject(mid=="maxroll.heroDetails.446" and
                         type(row["candidateId"])==str and
                         len(row["candidateId"])>0 and
                         row["reason"]=="CANDIDATE_G2_G3_G4_NOT_VERIFIED",
                         "UNEXPECTED_SOURCE_CANDIDATE")
        else:
            graph.reject(row["candidateId"] is None and
                         row["reason"]=="NO_APPROVED_FORMULA_RULE",
                         "UNKNOWN_METRIC_FALSE_CANDIDATE")
        index[mid]=row
    graph.reject(len(seen)==50 and seen==set(source),
                 "REGISTRY_SELECTION_CATALOG_ID_SET_MISMATCH")
    unknown=sum(x["state"]=="UNKNOWN" for x in rows)
    candidate=sum(x["state"]=="UNVERIFIED" for x in rows)
    graph.reject(coverage["missing"]==unknown and
                 coverage["candidateUnverified"]==candidate,
                 "REGISTRY_SELECTION_COVERAGE_MISMATCH")
    outputRows=[]
    for m in original["characterMetrics"]:
        row=index[m["metricId"]]
        graph.reject(not m["computed"] and m["raw"] is None
                     and m["display"] is None,"REGISTRY_REAL_ACTUAL_LEAK")
        outputRows.append({
            **m,
            "sourceRuleStatus":row["state"],
            "unverifiedCandidateId":row["candidateId"],
            "ruleSelectionReason":row["reason"],
            "activeRule":None,
        })
    result={
        "artifactType":"INTERNAL_GRAPH_REGISTRY_SELECTION_BRIDGE_NOT_PUBLIC_BE",
        "status":"BLOCKED_NO_APPROVED_EXECUTABLE_RULES",
        "patch":original["gamePatch"],"gameBuild":original["gameBuild"],
        "classId":original["classId"],
        "registrySnapshotSha256":selected["registrySnapshotSha256"],
        "selectionSha256":selected["selectionSha256"],
        "sourceGraphSha256":original["graphSha256"],
        "catalogSha256":source_sha,
        "fixtureFingerprint":original["sourceFixtureFingerprint"],
        "ruleCoverage":{"unknown":unknown,"candidateUnverified":candidate,
                        "activeRules":0,"verifiedGameFormulas":0},
        "characterMetrics":outputRows,
        "characterMetricsComputed":0,
        "approvedGoldenCount":0,
        "simulationContext":None,
        "realMaxrollParity":"BLOCKED_NOT_RUN",
        "publishAllowed":False,
    }
    result["graphSha256"]=graph.digest(result)
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description="Read-only registry-selection -> internal Graph bridge")
    p.add_argument("--overlay",type=Path,required=True)
    p.add_argument("--selection",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args(argv)
    try:
        out=bind(graph.read_json(a.overlay),graph.read_json(a.selection))
        rc=0
    except (graph.GraphError,OSError,TypeError,ValueError,UnicodeError,KeyError) as err:
        out={"status":"BLOCKED","errors":[str(err)],
             "realMaxrollParity":"BLOCKED_NOT_RUN","publishAllowed":False}
        rc=2
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
    print(json.dumps({k:v for k,v in out.items() if k!="characterMetrics"},sort_keys=True))
    return rc

if __name__=="__main__":
    sys.exit(main())
