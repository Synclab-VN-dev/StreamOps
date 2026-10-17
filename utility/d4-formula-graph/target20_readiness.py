"""Milestone M20: report independently Golden-VERIFIED distinct Character Stats.

No numerical formulas live here. We only consume actual computed earlier by
#110 and separately run real Golden verification reports. Uncomputed -> BLOCKED.
Class/fixture-specific PASS never becomes global approval or a production rule.
"""
from __future__ import annotations
from pathlib import Path
import argparse,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import graph

SCHEMA="openstream-maxroll-target20-v1"
REAL_REPORT="scoped-character-stat-verification-v1"
EXPECTED_SOURCE_COMMIT="1a4ecec"

def guard(ok,why):graph.reject(ok,why)
def checked_hash(x,key):
    guard(type(x)==dict and x.get(key)==graph.digest({k:v for k,v in x.items() if k!=key}),
          "INTEGRITY_MISMATCH_"+key)

def audit(targets,actual,verification_reports):
    guard(type(targets)==dict and targets.get("schema")==SCHEMA and
          targets.get("targetUniqueMetricIds")==20 and
          targets.get("source",{}).get("commit")==EXPECTED_SOURCE_COMMIT and
          targets.get("source",{}).get("sourcePatch")=="3.2.1.73552",
          "INVALID_F3_TARGET20_MANIFEST")
    entries=targets.get("metricSources")
    guard(type(entries)==list and len(entries)==20,"NOT_EXACTLY_20_TARGET_IDS")
    mids=[x.get("metricId") for x in entries]
    guard(len(set(mids))==20 and
          all(type(x)==str and x.startswith("maxroll.heroDetails.") for x in mids),
          "DUPLICATE_OR_BAD_TARGET_METRIC_ID")
    for entry in entries:
        guard(entry.get("classScope")=="rogue" and
              entry.get("fixtureScope")=="DEV-00" and
              entry.get("grade")=="CANDIDATE_SOURCE_EXPRESSION_NOT_COMPUTED" and
              type(entry.get("label"))==str and
              type(entry.get("sourceExpression"))==str and
              bool(entry["sourceExpression"]) and
              type(entry.get("reportedRuntimeDependencies"))==list and
              type(entry.get("runtimeFunctionCalls"))==list,
              "INVALID_F3_TARGET_ENTRY")
    guard(type(actual)==dict and
          actual.get("artifactType")=="INTERNAL_GOLDEN_DRIVEN_CANDIDATE_ACTUAL_NOT_PUBLIC_BE" and
          actual.get("fixtureId")=="DEV-00" and
          actual.get("classId")=="rogue" and
          actual.get("gamePatch")=="3.2.1.73552" and
          actual.get("partition")=="DEVELOPMENT" and
          actual.get("sourceExpectedImported") is False and
          actual.get("publishAllowed") is False,
          "NOT_REAL_ROGUE_GRAPH_ACTUAL")
    checked_hash(actual,"graphSha256")
    source_rows=actual.get("characterMetrics")
    guard(type(source_rows)==list and len(source_rows)==actual.get("sourceRowCount")
          and actual.get("uniqueMetricCount")==len({r["metricId"] for r in source_rows}),
          "INVALID_SOURCE_METRIC_INVENTORY")
    by_id={}
    for row in source_rows:
        mid=row["metricId"]
        if mid in by_id:
            other=by_id[mid]
            guard((other.get("raw"),other.get("status"),other.get("display"))==
                  (row.get("raw"),row.get("status"),row.get("display")),
                  "CONFLICTING_SOURCE_UI_PROJECTIONS")
        else:by_id[mid]=row
    guard(set(mids)<=set(by_id),"TARGET_NOT_IN_SOURCE_INVENTORY")
    guard(type(verification_reports)==list and len(verification_reports)>=1,
          "NO_INDEPENDENT_GOLDEN_VERIFICATION_REPORT")
    pass_rows={}
    scopes=set()
    for report in verification_reports:
        checked_hash(report,"reportSha256")
        guard(report.get("schema")==REAL_REPORT and
              report.get("fixtureId")=="DEV-00" and
              report.get("classId")=="rogue" and
              report.get("gamePatch")=="3.2.1.73552" and
              report.get("inputFingerprintSha256")==actual["sourceInputFingerprint"] and
              report.get("runtimeSourceSha256")==actual["runtimeSourceSha256"] and
              report.get("actualSha256")==actual["graphSha256"] and
              report.get("ruleSetSha256")==actual["candidateRuleSetSha256"] and
              report.get("holdoutUsed") is False and
              report.get("productionRulePromoted") is False and
              report.get("fullCharacterStatsParity") is False and
              report.get("verifiedAcrossAllClasses") is False,
              "FOREIGN_OR_PROMOTED_GOLDEN_VERIFICATION_REPORT")
        scope=(report["fixtureId"],report["classId"],report["gamePatch"],
               report["inputFingerprintSha256"],report["goldenSubsetSha256"])
        guard(scope not in scopes,"DUPLICATE_GOLDEN_VERIFICATION_REPORT")
        scopes.add(scope)
        rows=report.get("metrics",[])
        guard(type(rows)==list and
              report.get("verifiedScoped")==sum(r.get("status")=="VERIFIED" for r in rows) and
              report.get("status")=="PASS_SCOPED" if rows and all(r.get("status")=="VERIFIED" for r in rows)
              else report.get("status")!="PASS_SCOPED",
              "FAKE_VERIFIED_REPORT_COUNT_OR_STATUS")
        for row in rows:
            mid=row.get("metricId")
            if row.get("status")=="VERIFIED":
                guard(mid in mids and mid not in pass_rows and
                      row.get("testResult")=="PASS" and
                      mid in by_id and by_id[mid].get("computed") is True and
                      by_id[mid].get("raw")==row.get("actualRaw") and
                      by_id[mid].get("display")==row.get("actualDisplay") and
                      row.get("rawDiff") in ("0","0.0"),
                      "GOLDEN_PASS_NOT_SUPPORTED_BY_ACTUAL")
                pass_rows[mid]=row
    details=[]
    for target in entries:
        mid=target["metricId"]
        row=by_id[mid]
        passed=mid in pass_rows
        status="VERIFIED" if passed else (
            "BLOCKED_NO_REAL_COMPUTED_ACTUAL" if row.get("computed") is not True
            else "BLOCKED_NO_PASSING_INDEPENDENT_GOLDEN_TEST")
        details.append({
          "metricId":mid,"label":target["label"],
          "classId":"rogue","fixtureId":"DEV-00","gamePatch":actual["gamePatch"],
          "status":status,
          "formulaCandidateFromF3":target["sourceExpression"],
          "runtimeDependencies":target["reportedRuntimeDependencies"],
          "runtimeFunctionCalls":target["runtimeFunctionCalls"],
          "computedActualExists":row.get("computed") is True,
          "goldenTestPassed":passed,
          "actualRaw":row.get("raw"),
          "verifiedGoldenRaw":pass_rows[mid]["expectedRaw"] if passed else None,
          "actualDisplay":row.get("display"),
          "verifiedGoldenDisplay":pass_rows[mid]["expectedDisplay"] if passed else None,
          "reason":"CI_REAL_GOLDEN_PASS_FROZEN_SCOPE" if passed else
                   "SOURCE_CONTRIBUTORS_OR_INDEPENDENT_GOLDEN_PASS_MISSING"
        })
    n=len(pass_rows)
    out={
      "artifactType":"M20_GOLDEN_VERIFIED_UNIQUE_METRIC_MILESTONE_REPORT",
      "targetUniqueMetricIds":20,"verifiedUniqueMetricIds":n,
      "remainingUniqueMetricIds":20-n,
      "verifiedScopedCases":len(pass_rows),
      "status":"TARGET_MET" if n>=20 else "IN_PROGRESS",
      "classScope":"rogue","fixtureScope":"DEV-00",
      "gamePatch":actual["gamePatch"],
      "actualGraphSha256":actual["graphSha256"],
      "candidateRuleSetSha256":actual["candidateRuleSetSha256"],
      "f3CandidateManifestSha256":graph.digest(targets),
      "goldenExpectedInjectedIntoGraph":False,
      "fullFixtureParity":False,"holdoutUsed":False,
      "productionRulePromoted":False,"metrics":details
    }
    out["reportSha256"]=graph.digest(out)
    return out

def main(argv=None):
    p=argparse.ArgumentParser()
    for name in ("targets","actual","verification","report"):
        p.add_argument("--"+name,required=True,type=Path)
    a=p.parse_args(argv)
    try:
        result=audit(graph.read_json(a.targets),graph.read_json(a.actual),
                     [graph.read_json(a.verification)])
        rc=0
    except (graph.GraphError,OSError,ValueError,KeyError,TypeError) as e:
        result={"status":"BLOCKED_INVALID_EVIDENCE","error":str(e),
                "verifiedUniqueMetricIds":0}
        rc=2
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="metrics"},sort_keys=True))
    return rc
if __name__=="__main__":
    sys.exit(main())
