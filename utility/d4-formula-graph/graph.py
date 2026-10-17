"""#110 preliminary typed metric graph, strict no-formula fallback, internal-only interface.

This is NOT an approved FormulaGraphResult serialized contract. It only consumes
the #106 pinned source catalog. It never evaluates research candidates, never
copies Maxroll expected values, and never substitutes zero for unknown values.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

BASE=Path(__file__).resolve().parents[1]
CATALOG=BASE/"d4-maxroll-reference"/"f8-character-metric-catalog.json"
CATALOG_GIT_BLOB="ebf17a0e64e249448609145b89753fec3709ae7d"
BASELINE=("3.2.1","73552","rogue")
EXPECTED_GROUPS={"summary":2,"core":5,"resistances":8,"offensive":20,
                 "defensive":7,"utility":7,"pvp":1}
SHA64=re.compile(r"^[0-9a-f]{64}$")


class GraphError(ValueError):
    pass


def reject(condition,message):
    if not condition:raise GraphError(message)


def canonical(obj):
    return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":"),
                      allow_nan=False).encode("utf-8")


def digest(obj):
    return hashlib.sha256(canonical(obj)).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def source_catalog(path=CATALOG):
    b=Path(path).read_bytes()
    blob=hashlib.sha1(b"blob "+str(len(b)).encode("ascii")+b"\0"+b).hexdigest()
    reject(blob==CATALOG_GIT_BLOB,"SOURCE_CATALOG_CHANGED_WITHOUT_APPROVAL")
    cat=json.loads(b)
    reject(cat.get("scope")=="SOURCE_EVIDENCE_INVENTORY_ONLY"
           and cat.get("oracle")=="MAXROLL_ONLY","UNTRUSTED_SOURCE_CATALOG")
    v=cat.get("baseline",{})
    reject((v.get("gamePatch"),v.get("gameBuild"),v.get("classId"))==BASELINE,
           "CATALOG_PATCH_CLASS_MISMATCH")
    f=cat.get("fixture",{})
    reject(f.get("inputCompleteness")=="PARTIAL" and
           bool(SHA64.fullmatch(f.get("inputSnapshotSha256",""))),
           "FALSE_SOURCE_INPUT_COMPLETENESS")
    m=cat.get("metrics")
    reject(isinstance(m,list) and len(m)==50 and
           len({x.get("metricId") for x in m})==50,
           "INCOMPLETE_SOURCE_METRIC_CATALOG")
    reject(Counter(x.get("group") for x in m)==EXPECTED_GROUPS,
           "INVALID_MAXROLL_METRIC_DENOMINATOR")
    reject(all(x.get("goldenStatus")=="NOT_APPROVED"
               and x.get("maxrollGraphParity")=="NOT_RUN" for x in m),
           "FALSE_GOLDEN_SOURCE_PROMOTION")
    return cat,hashlib.sha256(b).hexdigest()


def validate_overlay(overlay,cat):
    reject(isinstance(overlay,dict) and
           set(overlay)=={"mode","gamePatch","gameBuild","classId",
                          "sourceFixtureFingerprint","variant","equipment",
                          "skills","charms","context"},"INVALID_BUILD_FIELDS")
    reject(overlay["mode"]=="SYNTHETIC_OVERLAY_ONLY","UNCERTIFIED_REAL_BUILD_INPUT")
    reject((overlay["gamePatch"],overlay["gameBuild"],overlay["classId"])==BASELINE,
           "GRAPH_PATCH_CLASS_MISMATCH")
    reject(overlay["sourceFixtureFingerprint"]==
           cat["fixture"]["inputSnapshotSha256"],"GRAPH_FIXTURE_SOURCE_MISMATCH")
    reject(isinstance(overlay["variant"],str) and bool(overlay["variant"]),
           "INVALID_VARIANT")
    for field in ("equipment","charms","context"):
        data=overlay[field]
        reject(isinstance(data,dict) and
               all(isinstance(k,str) and k for k in data),"INVALID_"+field.upper())
        # Only structural hash/diff input; never numeric calculator defaults.
        reject(all(isinstance(v,(str,int,float,bool,type(None))) for v in data.values()),
               "UNSUPPORTED_OVERLAY_VALUE_"+field.upper())
    skills=overlay["skills"]
    reject(isinstance(skills,dict) and
           all(isinstance(k,str) and k and isinstance(v,int) and not isinstance(v,bool)
               and v>=0 for k,v in skills.items()),"INVALID_SYNTHETIC_SKILL_RANK")
    reject(not any(k in overlay["context"] for k in
                   ("maxrollExpected","golden","verifiedFormula","computedStats")),
           "SOURCE_EXPECTED_AS_ACTUAL_FORBIDDEN")
    return digest(overlay)


def build_graph(cat,catalog_sha,overlay):
    build_sha=validate_overlay(overlay,cat)
    rows=[]; nodes=[]; edges=[]
    for item in sorted(cat["metrics"],key=lambda x:x["metricId"]):
        metric_id=item["metricId"]
        f4=item.get("f4ObservedDependencies",{})
        source_deps=f4.get("directDependencies",[])
        reject(isinstance(source_deps,list)
               and all(isinstance(x,str) for x in source_deps),
               "UNTRUSTED_DEPENDENCY_EVIDENCE")
        node_id="stat:"+metric_id
        nodes.append({
            "id":node_id,
            "kind":"METRIC_UNRESOLVED_SOURCE_OBSERVATION",
            "group":item["group"],
            "sourceDependencyNames":source_deps,
            "inputSnapshotHash":build_sha,
            "evaluationState":"BLOCKED_NO_APPROVED_FORMULA",
        })
        # f4 dependencies are source observations and NOT trustworthy executable edges.
        rows.append({
            "metricId":metric_id,"group":item["group"],"label":item["label"],
            "status":"UNKNOWN",
            "raw":None,"display":None,
            "unit":None,"roundingPolicy":None,
            "sourceGrade":item["formulaVerificationStatus"],
            "computed":False,
            "contributors":[],
            "sourceObservedDependencies":source_deps,
            "sourceDependenciesExecutionStatus":"NOT_COMPILED",
            "trace":[node_id],
            "reason":"FORMULA_RULE_NOT_FULLY_VERIFIED",
        })
    reject(len(rows)==50 and len(nodes)==50,"GRAPH_INCOMPLETE")
    data={
        "artifactType":"INTERNAL_GRAPH_EXPERIMENT_NOT_PUBLIC_FORMULAGRAPHRESULT",
        "status":"BLOCKED_NO_VERIFIED_MAXROLL_RULES",
        "gamePatch":BASELINE[0],"gameBuild":BASELINE[1],
        "classId":BASELINE[2],
        "sourceCatalogSha256":catalog_sha,
        "sourceCatalogGitBlobSha1":CATALOG_GIT_BLOB,
        "sourceFixtureFingerprint":cat["fixture"]["inputSnapshotSha256"],
        "sourceInputCompleteness":"PARTIAL",
        "syntheticOverlaySha256":build_sha,
        "metricNodes":nodes,"observedDependencyEdges":edges,
        "characterMetrics":rows,"skillMetrics":[],
        "simulationContext":None,
        "coverage":{
            "identified":50,"computed":0,"unknown":50,
            "sourceBounded":27,"sourcePartial":23,
            "approvedGolden":0,"realMaxrollParity":"BLOCKED_NOT_RUN",
        },
        "expectedMaxrollValuesIncluded":False,
        "runExecutableCandidates":False,
        "reportIsNotGameTruth":True,
    }
    data["graphSha256"]=digest(data)
    return data


def topological_sort(nodes,edges):
    """Synthetic/structural DAG check; source-f4 observed names NEVER enter this DAG."""
    reject(isinstance(nodes,list) and len(nodes)==len(set(nodes))
           and all(isinstance(n,str) and n for n in nodes),"INVALID_GRAPH_NODES")
    reject(isinstance(edges,list),"INVALID_GRAPH_EDGES")
    graph={n:set() for n in nodes}
    for edge in edges:
        reject(isinstance(edge,(tuple,list)) and len(edge)==2,
               "INVALID_GRAPH_EDGE")
        source,target=edge
        reject(source in graph and target in graph,"UNRESOLVED_GRAPH_REFERENCE")
        reject(source!=target,"GRAPH_DEPENDENCY_CYCLE")
        graph[target].add(source)
    state={}; order=[]
    def visit(n):
        reject(state.get(n)!=1,"GRAPH_DEPENDENCY_CYCLE")
        if state.get(n)==2:return
        state[n]=1
        for dep in sorted(graph[n]):visit(dep)
        state[n]=2
        order.append(n)
    for n in sorted(graph):visit(n)
    return order


def main(argv=None):
    p=argparse.ArgumentParser(description="Internal #110 UNKNOWN-preserving graph contract smoke")
    p.add_argument("--overlay",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    args=p.parse_args(argv)
    try:
        c,sha=source_catalog()
        report=build_graph(c,sha,read_json(args.overlay))
        code=0
    except (GraphError,OSError,UnicodeError,KeyError,TypeError,ValueError,
            json.JSONDecodeError) as exc:
        report={"status":"BLOCKED","errors":[str(exc)],
                "realMaxrollParity":"BLOCKED_NOT_RUN",
                "expectedMaxrollValuesIncluded":False}
        code=2
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in
                      ("characterMetrics","metricNodes")},sort_keys=True))
    return code


if __name__=="__main__":
    sys.exit(main())
