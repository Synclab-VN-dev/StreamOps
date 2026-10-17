"""#110 bound scenario-state reconciliation without public schema or numeric leakage."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import graph
import scenario_state as scene


def build(overlay,scenario):
    catalog,catalog_sha=graph.source_catalog()
    base=graph.build_graph(catalog,catalog_sha,overlay)
    guards=scene.gate_trace(scenario,scene.REFERENCE_GATES)
    graph.reject(base["sourceFixtureFingerprint"]==
                 guards["sourceFixtureFingerprint"],
                 "SCENARIO_GRAPH_FIXTURE_MISMATCH")
    nodes=[
        {"id":"scenario:"+name,"sourceTruth":"UNOBSERVED_STATIC_PLANNER" if
         scenario["fields"][name]["state"]=="UNKNOWN" else
         "SYNTHETIC_TEST_CASE_ONLY",
         "runtimeState":scenario["fields"][name]["state"],
         "valueKnownInRealSource":False}
        for name in scene.FIELDS
    ]
    # The source catalog does not support true formulas for ANY of these
    # 50 metrics. Test-only scenario known values therefore NEVER compute them.
    graph.reject(len(base["characterMetrics"])==50 and
                 base["coverage"]["computed"]==0 and
                 all(row["raw"] is None and row["display"] is None for row
                     in base["characterMetrics"]),
                 "UNTRUSTED_CONTEXT_PROMOTED_NUMERIC_STAT")
    result={
        "artifactType":"INTERNAL_GRAPH_SCENARIO_STATE_PROOF_ONLY",
        "status":"BLOCKED_NO_VERIFIED_MAXROLL_RULES",
        "patch":base["gamePatch"],"build":base["gameBuild"],
        "classId":base["classId"],
        "sourceCatalogSha256":catalog_sha,
        "sourceFixtureFingerprint":base["sourceFixtureFingerprint"],
        "sourceGraphSha256":base["graphSha256"],
        "scenarioSha256":guards["scenarioSha256"],
        "scenarioNodes":nodes,
        "conditionTrace":guards["trace"],
        "scenarioTruthCoverage":guards["truthCoverage"],
        "characterMetrics":base["characterMetrics"],
        "characterMetricsComputed":0,
        "characterMetricsUnknown":50,
        "simulationContext":None,
        "realMaxrollParity":"BLOCKED_NOT_RUN",
        "approvedGoldenCount":0,
        "executableRealRulesCount":0,
        "approvedScenario":False,
        "publishAllowed":False,
    }
    result["graphSha256"]=graph.digest(result)
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description="#110 internal scenario source-UNKNOWN graph")
    p.add_argument("--overlay",type=Path,required=True)
    p.add_argument("--scenario",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    args=p.parse_args(argv)
    try:
        result=build(graph.read_json(args.overlay),graph.read_json(args.scenario))
        rc=0
    except (graph.GraphError,OSError,ValueError,KeyError,UnicodeError,TypeError) as err:
        result={"status":"BLOCKED","errors":[str(err)],
                "realMaxrollParity":"BLOCKED_NOT_RUN",
                "publishAllowed":False}
        rc=2
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="characterMetrics"},sort_keys=True))
    return rc


if __name__=="__main__":
    sys.exit(main())
