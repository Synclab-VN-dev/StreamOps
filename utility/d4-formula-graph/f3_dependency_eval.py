"""Bounded F3 *runtime expression* compiler; NOT executable production game rules.

Missing dependency inputs produce UNKNOWN, never zero. Synthetic test bindings
exercise arithmetic only and MUST NOT generate Graph Actual or Golden PASS.
"""
from __future__ import annotations
import json
import math
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import graph

OPS={"add":2,"subtract":2,"min":2,"floor":1}
SOURCE_STATES={"UNKNOWN_UNMAPPED_EFFECT","KNOWN_SYNTHETIC_TEST_ONLY"}

def require(ok,code):graph.reject(ok,code)

def walk(expr,deps,depth=0):
    require(depth<=20 and type(expr)==dict,"INVALID_FORMULA_TREE")
    if "ref" in expr:
        require(set(expr)=={"ref"} and expr["ref"] in deps,
                "FORMULA_SOURCE_REF_NOT_OBSERVED")
        return {expr["ref"]}
    if "const" in expr:
        require(set(expr)=={"const"} and type(expr["const"]) in (int,float)
                and math.isfinite(expr["const"]),"INVALID_F3_FORMULA_CONST")
        return set()
    require(set(expr)=={"op","args"} and expr["op"] in OPS and
            type(expr["args"])==list and len(expr["args"])==OPS[expr["op"]],
            "UNSUPPORTED_F3_FORMULA_AST")
    return set().union(*(walk(e,deps,depth+1) for e in expr["args"]))

def evaluate_expression(expr,values):
    if "ref" in expr:return values[expr["ref"]]
    if "const" in expr:return expr["const"]
    a=[evaluate_expression(x,values) for x in expr["args"]]
    op=expr["op"]
    if op=="add":return a[0]+a[1]
    if op=="subtract":return a[0]-a[1]
    if op=="min":return min(a)
    if op=="floor":return math.floor(a[0])
    raise graph.GraphError("UNSUPPORTED_F3_MATH")

def run(formula_catalog,bindings,fixture="DEV-00"):
    require(type(formula_catalog)==dict and
            formula_catalog.get("schema")=="F3_BOUNDED_RESEARCH_FORMULAS_V1" and
            formula_catalog.get("origin")=="F3_BROWSER_RUNTIME_EXPRESSION_OBSERVED_NOT_FULL_FORMULA_VERIFIED" and
            formula_catalog.get("sourceCommit")=="1a4ecec" and
            formula_catalog.get("mode")=="RESEARCH_CANDIDATE_SANDBOX_ONLY" and
            formula_catalog.get("patch")=="3.2.1.73552" and
            formula_catalog.get("classId")=="rogue",
            "F3_SOURCE_PROVENANCE_OR_PATCH_INVALID")
    require(fixture=="DEV-00","F3_CLASS_FIXTURE_SCOPE_MISMATCH")
    require(type(bindings)==dict and set(bindings)=={"mode","values"} and
            bindings["mode"] in ("SOURCE_UNKNOWN","SYNTHETIC_TEST_ONLY") and
            type(bindings["values"])==dict,
            "INVALID_F3_BINDING_SOURCE")
    if bindings["mode"]=="SOURCE_UNKNOWN":
        require(not bindings["values"],"REAL_VARIABLE_VALUES_NOT_PROVEN_FROM_SOURCE")
    formulas=formula_catalog.get("formulas")
    require(type(formulas)==list and 0<len(formulas)<=10,"INVALID_F3_FORMULAS")
    union_deps=set()
    for f in formulas:
        require(type(f)==dict and type(f.get("dependencyNames"))==list,
                "INVALID_F3_FORMULA_DEPENDENCIES")
        union_deps.update(f["dependencyNames"])
    require(set(bindings["values"])<=union_deps,
            "UNRECOGNIZED_F3_SYNTHETIC_VARIABLE")
    results=[];seen=set()
    for f in formulas:
        require(type(f)==dict and set(f)=={"metricId","label","f3Expression","f3EvidenceStatus","dependencyNames","ast"} and
                f["metricId"] not in seen and
                f["f3EvidenceStatus"]=="CAUSALLY_VERIFIED_BOUNDED" and
                type(f["f3Expression"])==str and f["f3Expression"] and
                type(f["label"])==str and f["label"] and
                type(f["dependencyNames"])==list and
                len(f["dependencyNames"])==len(set(f["dependencyNames"])),
                "INVALID_BOUNDED_F3_RULE")
        seen.add(f["metricId"])
        deps=set(f["dependencyNames"]);observed=walk(f["ast"],deps)
        require(deps==observed,"F3_FORMULA_DEPENDENCY_SET_MISMATCH")
        current=bindings["values"]
        for key,value in current.items():
            require(type(value) in (float,int) and math.isfinite(value),
                    "NONFINITE_SYNTHETIC_TEST_VALUE")
        missing=sorted(deps-set(current))
        known=sorted(deps&set(current))
        if missing:
            val=None;status="UNKNOWN_MISSING_F3_INTERMEDIATE_VARIABLES"
        else:
            val=evaluate_expression(f["ast"],current)
            require(type(val) in (float,int) and math.isfinite(val),
                    "UNSAFE_FORMULA_RESULT")
            status="SYNTHETIC_ARITHMETIC_ONLY_NOT_GAME_ACTUAL"
        results.append({
            "metricId":f["metricId"],"label":f["label"],
            "sourceGrade":"CAUSALLY_VERIFIED_BOUNDED_NOT_FULL_FORMULA",
            "f3Expression":f["f3Expression"],
            "knownRuntimeVariables":known,"missingRuntimeVariables":missing,
            "status":status,"trialOnly":val,"characterStatActual":None,
            "productionRuleActivated":False,
        })
    out={
        "artifactType":"INTERNAL_F3_BOUNDED_FORMULA_DEPENDENCY_TRACE",
        "fixtureId":fixture,"patch":"3.2.1.73552",
        "sourceEvidenceCommit":"1a4ecec",
        "formulaCatalogSha256":graph.digest(formula_catalog),
        "bindingMode":bindings["mode"],"results":results,
        "sourceKnown":sum(not x["missingRuntimeVariables"] for x in results)
                       if bindings["mode"]=="SOURCE_UNKNOWN" else 0,
        "formulaFullVerified":0,"realMaxrollActualComputed":0,
        "goldenParity":"NOT_RUN","publishAllowed":False,
    }
    out["traceSha256"]=graph.digest(out)
    return out
