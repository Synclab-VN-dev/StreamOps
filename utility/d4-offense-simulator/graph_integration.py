"""Pinned #110 source graph -> #111 fail-closed integration, no real DPS.

Loads the independently captured DEV-00 and DEV-01 input-only witness from
a separate read-only checkout of PR #121 at the EXACT pinned SHA. It never
reads a private/synthetic Golden Expected or a HOLDOUT input.
"""
from __future__ import annotations
from copy import deepcopy
import argparse
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import simulator

GRAPH_SHA="2b2b38defca182e0034a0d9907e1f828254bba0f"
GRAPH_HOME=Path(os.environ.get("D4_SOURCE_GRAPH_ROOT","")).resolve()

def require(ok:bool,why:str):
    if not ok:raise simulator.Blocked(why)

def sha_source(root:Path)->None:
    """Validate the source checkout before importing code, not only fixtures."""
    require(root.is_dir() and (root/".git").exists(),"MISSING_SOURCE_GRAPH_CHECKOUT")
    import subprocess
    result=subprocess.run(["git","-C",str(root),"rev-parse","HEAD"],
                          text=True,capture_output=True,check=True)
    require(result.stdout.strip()==GRAPH_SHA,"STALE_OR_WRONG_GRAPH_COMMIT")

def read(path:Path)->dict[str,Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def run(source_root:Path)->dict[str,Any]:
    sha_source(source_root)
    graph_base=source_root/"utility"/"d4-formula-graph"
    require((graph_base/"dev_source_graph.py").exists(),"GRAPH_CODE_MISSING")
    sys.path.insert(0,str(graph_base))
    import dev_source_graph
    import graph
    rules=graph.read_json(graph_base/"fixtures"/"candidate-source-level.json")
    synthetic_context=read(HERE/"fixtures"/"synthetic-context.json")
    sandbox_trace=simulator.simulate(synthetic_context)
    require(sandbox_trace["realDps"] is None and
            sandbox_trace["publishAllowed"] is False,
            "SYNTHETIC_SANDBOX_CANNOT_PROVE_GAME_DPS")
    reports=[]
    t0=time.perf_counter()
    for n,clas,expected_rows,expected_ids in (
        ("dev00","rogue",50,50),("dev01","sorcerer",49,47)):
        fixture=graph_base/"fixtures"
        mechanics=graph.read_json(fixture/(n+"-mechanics.json"))
        rolls=graph.read_json(fixture/(n+"-source-rolls.json"))
        inventory=graph.read_json(fixture/(n+"-visible-inventory.json"))
        start=time.perf_counter()
        observed=dev_source_graph.build(mechanics,rolls,inventory,rules)
        gate=simulator.require_graph(observed,["maxroll.heroDetails.3"])
        elapsed=(time.perf_counter()-start)*1000
        require(observed["classId"]==clas and
                observed["visibleMetricRows"]==expected_rows and
                observed["uniqueMetricIds"]==expected_ids and
                observed["candidateComputedUnique"]==1 and
                len(observed["sourceStatActual"])==expected_rows,
                "SOURCE_GRAPH_METRIC_DENOMINATOR_MISMATCH")
        require(gate["status"]=="BLOCKED" and
                "maxroll.heroDetails.3" in gate["unverifiedRequiredMetrics"] and
                gate["realDps"] is None and gate["syntheticDps"] is None and
                gate["statRecalculation"] is False and
                gate["completeCharacterStatParity"] is False,
                "CRITICAL_UNKNOWN_WAS_WRONGLY_PUBLISHED")
        changed=deepcopy(rolls)
        changed["slots"][0]["fields"]["explicits"][0]["values"][0]+=1
        after=dev_source_graph.build(mechanics,changed,inventory,rules)
        change=dev_source_graph.diff(observed,after)
        gate_changed=simulator.require_graph(after,["maxroll.heroDetails.3"])
        require(change["sourceChanges"]["changed"] and
                observed["graphSha256"]!=after["graphSha256"] and
                gate_changed["status"]=="BLOCKED" and
                gate_changed["realDps"] is None,
                "ALTERED_REAL_SOURCE_WRONGLY_PUBLISHED")
        tampered=deepcopy(observed)
        tampered["gamePatch"]="3.2.3"
        guard_stale=simulator.require_graph(tampered,["maxroll.heroDetails.3"])
        require(guard_stale["stalePatch"] and guard_stale["status"]=="BLOCKED",
                "WRONG_PATCH_NOT_BLOCKED")
        tampered=deepcopy(observed)
        tampered["graphSha256"]="0"*64
        guard_sha=simulator.require_graph(tampered,["maxroll.heroDetails.3"])
        require(guard_sha["invalidGraphIdentity"] and
                guard_sha["status"]=="BLOCKED",
                "GRAPH_HASH_TAMPERING_NOT_DETECTED")
        # Hash tampering of even one metric body field must not be accepted.
        falsified=deepcopy(observed)
        falsified["sourceStatActual"][0]["status"]="VERIFIED_INDEPENDENT_MAXROLL_PARITY"
        falsified_gate=simulator.require_graph(
            falsified,["maxroll.heroDetails.3"])
        require(falsified_gate["status"]=="BLOCKED" and
                falsified_gate["invalidGraphIdentity"],
                "GRAPH_BODY_TAMPERING_NOT_DETECTED")
        unsupported=deepcopy(observed)
        critical=next(x for x in unsupported["sourceStatActual"]
                      if x["metricId"]=="maxroll.heroDetails.3")
        critical["status"]="UNSUPPORTED"
        critical["reason"]="SOURCE_CAPTURE_DOES_NOT_PROVE_EFFECT_SEMANTICS"
        unsupported["graphSha256"]=graph.digest({
             k:v for k,v in unsupported.items() if k!="graphSha256"})
        guard_unsupported=simulator.require_graph(
            unsupported,["maxroll.heroDetails.3"])
        require(guard_unsupported["status"]=="BLOCKED" and
                "maxroll.heroDetails.3" in guard_unsupported["unverifiedRequiredMetrics"]
                and guard_unsupported["realDps"] is None,
                "UNSUPPORTED_CRITICAL_STAT_NOT_BLOCKED")
        missing=deepcopy(observed)
        missing["sourceStatActual"]=[x for x in missing["sourceStatActual"]
                                     if x["metricId"]!="maxroll.heroDetails.3"]
        missing["graphSha256"]=graph.digest({
             k:v for k,v in missing.items() if k!="graphSha256"})
        guard_missing=simulator.require_graph(
            missing,["maxroll.heroDetails.3"])
        require(guard_missing["status"]=="BLOCKED" and
                guard_missing["realDps"] is None and
                "maxroll.heroDetails.3" in guard_missing["unverifiedRequiredMetrics"],
                "ABSENT_CRITICAL_STAT_NOT_BLOCKED")
        reports.append({
          "expected":{"sourceRows":expected_rows,
                      "distinctMetricIds":expected_ids,
                      "requiredOffenseState":"BLOCKED",
                      "realDps":None},
          "actual":{"sourceRows":observed["visibleMetricRows"],
                    "distinctMetricIds":observed["uniqueMetricIds"],
                    "requiredOffenseState":gate["status"],
                    "realDps":gate["realDps"]},
          "fixtureId":observed["fixtureId"],"classId":clas,
          "inputFingerprintSha256":observed["fixtureInputFingerprint"],
          "sourceGraphSha256":observed["graphSha256"],
          "mutatedGraphSha256":after["graphSha256"],
          "visibleMetricRows":expected_rows,"uniqueMetricIds":expected_ids,
          "unverifiedCriticalMetricIds":gate["unverifiedRequiredMetrics"],
          "realDps":gate["realDps"],
          "graphPassedStatsWithoutRecomputation":True,
          "sourceDelta":change["sourceChanges"],
          "patchMismatchGate":"BLOCKED",
          "unsupportedCriticalMetricGate":"BLOCKED",
          "absentCriticalMetricGate":"BLOCKED",
          "graphBodyTamperGate":"BLOCKED",
          "graphHashTamperGate":"BLOCKED",
          "unknownCombatState":gate["unknownScenarioTruths"],
          "elapsedMs":round(elapsed,3),
          "caseStatus":"PASS_REAL_SOURCE_FAIL_CLOSED_NOT_GAME_DPS",
        })
    output={
      "artifactType":"CROSS_PR_TWO_CLASS_GRAPH_TO_OFFENSE_GATE",
      "graphSourceCommit":GRAPH_SHA,
      "replayMode":"PINNED_DEVELOPMENT_OFFLINE_CI",
      "syntheticSandboxSeed":synthetic_context["seed"],
      "syntheticSandboxInputSha256":sandbox_trace["inputSha256"],
      "syntheticSandboxReportedSeparately":True,
      "scope":"REAL_CAPTURED_DEVELOPMENT_INPUTS_UNKNOWN_METRICS",
      "cases":reports,"fixtureCount":len(reports),
      "durationMs":round((time.perf_counter()-t0)*1000,3),
      "totalVisibleMetricRows":sum(r["visibleMetricRows"] for r in reports),
      "totalDistinctIdsAcrossBuilds":sum(r["uniqueMetricIds"] for r in reports),
      "allRealDpsBlocked":True,
      "expectedVsActualAllCasesMatch":all(
         r["expected"]==r["actual"] for r in reports),
      "deterministicEvidenceSha256":simulator.digest({
          "source":GRAPH_SHA,"seed":synthetic_context["seed"],
          "cases":[{"fixture":r["fixtureId"],
                    "graph":r["sourceGraphSha256"],
                    "mutated":r["mutatedGraphSha256"],
                    "delta":r["sourceDelta"],
                    "expected":r["expected"],
                    "actual":r["actual"]} for r in reports],
      }),"gameplayGoldenParity":"NOT_RUN",
      "holdoutOpened":False,"publishAllowed":False,
    }
    output["sha256"]=simulator.digest(output)
    return output

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source-root",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    args=p.parse_args()
    try:
        report=run(args.source_root)
        code=0
    except (simulator.Blocked,ValueError,KeyError,TypeError,
            OSError,ImportError) as e:
        report={"status":"BLOCKED","error":str(e),
                "allRealDpsBlocked":True,"publishAllowed":False}
        code=2
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",
                           encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k!="cases"},sort_keys=True))
    return code

if __name__=="__main__":sys.exit(main())
