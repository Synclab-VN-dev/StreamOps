"""#108 independent DEV-only metric comparator against #110 candidate graph.

Loads independently captured DEVELOPMENT expected separately, never imports them
into graph evaluator. No production parity PASS, no holdout access or approval.
"""
from __future__ import annotations
import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import graph

def guard(p,why):
    graph.reject(p,why)

def key(r):
    return (r["group"].strip().casefold(),r["metricId"])

def finite(v):
    if type(v) not in (float,int):return False
    try:return Decimal(str(v)).is_finite()
    except InvalidOperation:return False

def canonical_rows(expected):
    """Accept two real frozen DEV source schemas; never infer omitted values."""
    fixture=expected.get("fixtureId") or expected.get("fixture",{}).get("fixtureId")
    guard(type(fixture)==str and fixture.startswith("DEV-"),"HOLDOUT_EXPECTED_PROHIBITED")
    origin=expected.get("origin")
    guard(origin=="MAXROLL_BROWSER_CAPTURE","INVALID_EXPECTED_SOURCE")
    if expected.get("schema")=="F-GOLDEN-01-maxroll-expected-v1":
        guard(expected.get("partition")=="DEVELOPMENT","HOLDOUT_EXPECTED_PROHIBITED")
        rows=expected.get("metrics")
        guard(type(rows)==list and len(rows)==expected.get("metricCount"),
              "EXPECTED_ROW_DENOMINATOR_MISMATCH")
        result=[{"metricId":x["metricId"],"group":x["group"],"label":x["label"],
                 "raw":x["raw"],"display":x["display"],
                 "rawOrigin":x["provenance"]["raw"],
                 "displayOrigin":x["provenance"]["display"]} for x in rows]
        fingerprint=expected.get("inputFingerprintSha256")
        patch=expected.get("patch")
    else:
        guard(expected.get("artifact") in {"rogue-50-maxroll-golden-candidate",
                                           "rogue-frozen-maxroll-golden-candidate"}
              or expected.get("schemaVersion")==1,
              "UNKNOWN_EXPECTED_CAPTURE_SCHEMA")
        guard(expected.get("referenceApproval")!="APPROVED",
              "OWNER_GOLDEN_APPROVAL_NOT_GRANTED")
        rows=expected.get("metrics")
        guard(type(rows)==list and len(rows)>0,"EXPECTED_ROWS_MISSING")
        result=[{"metricId":x["metricId"],"group":x["group"],
                 "label":x["originalMaxrollLabel"],"raw":x["expectedRawValue"],
                 "display":x["expectedDisplayValue"],"rawOrigin":x["rawOrigin"],
                 "displayOrigin":x["displayOrigin"]} for x in rows]
        fingerprint=expected["metrics"][0].get("inputFingerprintSha256")
        patch=expected["metrics"][0].get("patch")
    guard(all(type(x["metricId"])==str and type(x["group"])==str and
              type(x["label"])==str and type(x["display"])==str and
              finite(x["raw"]) and
              x["rawOrigin"]=="MAXROLL_CDP_RUNTIME_DIRECT" and
              x["displayOrigin"]=="MAXROLL_BROWSER_UI_DIRECT" for x in result),
          "EXPECTED_MUST_BE_INDEPENDENTLY_OBSERVED")
    guard(len({key(x) for x in result})==len(result),"DUPLICATE_EXPECTED_DISPLAY_ROW")
    duplicates={}
    for row in result:
        a=duplicates.setdefault(row["metricId"],(row["raw"],row["display"],row["label"]))
        guard(Decimal(str(a[0]))==Decimal(str(row["raw"])) and
              a[1]==row["display"] and a[2].casefold()==row["label"].casefold(),
              "CONFLICTING_DUPLICATE_EXPECTED_METRIC")
    return fixture,fingerprint,patch,result

def compare(actual,expected):
    guard(type(actual)==dict and actual.get("artifactType")==
          "INTERNAL_GOLDEN_DRIVEN_CANDIDATE_ACTUAL_NOT_PUBLIC_BE",
          "NOT_GOLDEN_CANDIDATE_ACTUAL")
    guard(actual.get("partition")=="DEVELOPMENT","HOLDOUT_EVALUATION_NOT_ALLOWED")
    guard(actual.get("sourceExpectedImported") is False and
          actual.get("maxrollParity")=="NOT_RUN" and
          actual.get("approvedGoldens")==0 and
          actual.get("verifiedMetrics")==0 and
          actual.get("publishAllowed") is False,
          "FALSE_GOLDEN_OR_PRODUCTION_PROMOTION")
    guard(actual.get("graphSha256")==graph.digest({
        k:v for k,v in actual.items() if k!="graphSha256"}),
        "GRAPH_MANIFEST_SHA_MISMATCH")
    fid,input_sha,patch,expected_rows=canonical_rows(expected)
    guard(actual["fixtureId"]==fid and actual["gamePatch"]==patch and
          actual["sourceInputFingerprint"]==input_sha,
          "EXPECTED_ACTUAL_PATCH_OR_FIXTURE_MISMATCH")
    rows=actual.get("characterMetrics")
    guard(type(rows)==list and len(rows)==actual.get("sourceRowCount"),
          "ACTUAL_DENOMINATOR_MISMATCH")
    guard(len({key(x) for x in rows})==len(rows),"DUPLICATE_ACTUAL_ROW")
    guard(actual["uniqueMetricCount"]==len({x["metricId"] for x in rows}),
          "UNIQUE_METRIC_DENOMINATOR_MISMATCH")
    actualidx={key(x):x for x in rows}
    guard(set(actualidx)=={key(x) for x in expected_rows},
          "EXPECTED_ACTUAL_VISIBLE_ROW_SET_MISMATCH")
    projection={}
    report=[]
    for exp in expected_rows:
        item=actualidx[key(exp)]
        guard(item["label"].casefold()==exp["label"].casefold(),
              "DISPLAY_LABEL_SOURCE_MISMATCH")
        if not item["computed"]:
            guard(item["raw"] is None and item["display"] is None,
                  "UNKNOWN_METRIC_MUST_BE_NULL")
            st="BLOCKED_UNKNOWN_FORMULA"
            raw_diff=None
        else:
            guard(item["status"]=="CANDIDATE_COMPUTED_UNVERIFIED" and
                  finite(item["raw"]) and
                  item["display"] is None and len(item["trace"])>0,
                  "FALSE_VERIFIED_OR_DISPLAY_READY")
            delta=Decimal(str(item["raw"]))-Decimal(str(exp["raw"]))
            raw_diff=str(delta)
            st="MATCH_UNVERIFIED_CANDIDATE" if delta==0 else "MISMATCH_UNVERIFIED_CANDIDATE"
        if item["metricId"] in projection:
            prev=projection[item["metricId"]]
            guard(prev==(item["raw"],item["status"],tuple(
                json.dumps(x,sort_keys=True) for x in item["trace"])),
                "CONFLICTING_ACTUAL_DUPLICATE_PROJECTIONS")
        else:
            projection[item["metricId"]]=(item["raw"],item["status"],tuple(
                json.dumps(x,sort_keys=True) for x in item["trace"]))
        report.append({"metricId":exp["metricId"],"group":exp["group"],
                       "label":exp["label"],"state":st,
                       "expectedRaw":exp["raw"],"actualRaw":item["raw"],
                       "rawDiff":raw_diff,"expectedDisplay":exp["display"],
                       "actualDisplay":None,"displayState":"NOT_EVALUATED",
                       "trace":item["trace"]})
    counts=dict(Counter(r["state"] for r in report))
    output={
        "artifactType":"INTERNAL_DEV_GOLDEN_DIFF_NO_APPROVAL",
        "status":"DEVELOPMENT_PARTIAL_BLOCKED" if
                 counts.get("MISMATCH_UNVERIFIED_CANDIDATE",0)==0 else
                 "DEVELOPMENT_CANDIDATE_MISMATCH",
        "fixtureId":fid,"graphSha256":actual["graphSha256"],
        "expectedCaptureSha256":graph.digest(expected),
        "gamePatch":patch,"sourceInputFingerprint":input_sha,
        "sourceRows":len(report),"uniqueMetricIds":len(projection),
        "candidateComputedUnique":sum(x[1]=="CANDIDATE_COMPUTED_UNVERIFIED"
                                       for x in projection.values()),
        "matchedUnverifiedRows":counts.get("MATCH_UNVERIFIED_CANDIDATE",0),
        "mismatchedUnverifiedRows":counts.get("MISMATCH_UNVERIFIED_CANDIDATE",0),
        "blockedRows":counts.get("BLOCKED_UNKNOWN_FORMULA",0),
        "allMetricsVerified":False,"approvedGolden":False,
        "holdoutEvaluated":False,"fullMaxrollParity":"BLOCKED_NOT_RUN",
        "details":report,
    }
    output["reportSha256"]=graph.digest(output)
    return output

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--actual",type=Path,required=True)
    p.add_argument("--development-expected",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args(argv)
    try:
        result=compare(graph.read_json(a.actual),graph.read_json(a.development_expected))
        code=0
    except (graph.GraphError,KeyError,TypeError,ValueError,OSError,UnicodeError,
            InvalidOperation) as err:
        result={"status":"BLOCKED","errors":[str(err)],
                "fullMaxrollParity":"BLOCKED_NOT_RUN","approvedGolden":False}
        code=2
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="details"},sort_keys=True))
    return code

if __name__=="__main__":sys.exit(main())
