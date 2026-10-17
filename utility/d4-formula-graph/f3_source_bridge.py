"""Capture roll-index → F3 runtime dependency evidence bridge, fail-closed.

This deliberately DOES NOT map affix nid to a runtime variable without
evidence. Source presence != contributor semantics or metric computation.
"""
from __future__ import annotations
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import graph
import source_roll_index
import f3_dependency_eval

def bridge(witness,formula_catalog):
    indexed=source_roll_index.index(witness)
    graph.reject(indexed["fixtureId"]=="DEV-00","F3_RESEARCH_SCOPE_ROGUE_ONLY")
    formulas=f3_dependency_eval.run(formula_catalog,
             {"mode":"SOURCE_UNKNOWN","values":{}},fixture="DEV-00")
    missing=set()
    detail=[]
    for x in formulas["results"]:
        need=list(x["missingRuntimeVariables"])
        missing.update(need)
        detail.append({
            "metricId":x["metricId"],
            "f3Expression":x["f3Expression"],
            "evidenceGrade":x["sourceGrade"],
            "unresolvedRuntimeVariables":need,
            "affixSourceNidMappingCount":0,
            "actual":None,
            "status":"BLOCKED_UNPROVEN_NID_TO_RUNTIME_VARIABLE_MAPPING",
        })
    result={
        "artifactType":"CAPTURED_ROLL_TO_F3_DEPENDENCY_GAP_REPORT",
        "fixtureId":indexed["fixtureId"],"patch":indexed["patch"],
        "inputFingerprintSha256":indexed["sourceFingerprint"],
        "sourceRollIndexSha256":indexed["indexSha256"],
        "f3TraceSha256":formulas["traceSha256"],
        "observedRolls":indexed["rollCount"],
        "observedUniqueNids":indexed["uniqueNidCount"],
        "f3Formulas":len(detail),
        "unmappedIntermediateDependencies":sorted(missing),
        "statFormulaMappingVerified":0,
        "computedMetricValues":0,
        "contributorsCrossMapped":0,
        "details":detail,
        "goldenExpectedLoaded":False,
        "holdoutExpectedLoaded":False,
        "publishAllowed":False,
    }
    result["reportSha256"]=graph.digest(result)
    return result
