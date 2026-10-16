"""#110 proof-of-composition graph artifact for three fake G1 DSL families.

Never insert synthetic mechanic totals into the source-catalog characterMetrics.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import graph
import synthetic_compiler

HERE=Path(__file__).resolve().parent


def build(overlay,synthetic):
    catalog,catalog_sha=graph.source_catalog()
    base=graph.build_graph(catalog,catalog_sha,overlay)
    case=synthetic_compiler.compose(synthetic)
    graph.reject(base["gamePatch"]==synthetic["gamePatch"]
                 and base["gameBuild"]==synthetic["gameBuild"]
                 and base["classId"]==synthetic["classId"],
                 "COMPOSED_GRAPH_PATCH_MISMATCH")
    graph.reject(base["coverage"]["computed"]==0 and
                 base["coverage"]["unknown"]==50
                 and all(x["raw"] is None and x["display"] is None
                         for x in base["characterMetrics"]),
                 "SYNTHETIC_OUTPUT_CONTAMINATED_CHARACTER_STATS")
    source=[t for t in case["trace"] if t["status"]=="SYNTHETIC_APPLIED"]
    nodes=[{"id":"synthetic:"+row["ruleId"],"kind":"SYNTHETIC_MECHANIC_ONLY",
            "sourceFamily":row["sourceFamily"],"notMaxroll":True} for row in source]
    out={
        "status":"PASS_SYNTHETIC_COMPOSITION_GRAPH_ONLY_REAL_MAXROLL_BLOCKED",
        "artifactType":"INTERNAL_GRAPH_PROOF_NOT_PUBLIC_BE_CONTRACT",
        "sourceGraphSha256":base["graphSha256"],
        "syntheticRulesetSha256":case["rulesetSha256"],
        "syntheticManifestSha256":case["manifestSha256"],
        "gamePatch":base["gamePatch"],
        "gameBuild":base["gameBuild"],"classId":base["classId"],
        "sourceCatalogSha256":base["sourceCatalogSha256"],
        "sourceFixtureFingerprint":base["sourceFixtureFingerprint"],
        "syntheticMechanicNodes":nodes,
        "syntheticOutputOnly":{"stats":case["stats"],"skills":case["skills"],
                               "trace":case["trace"]},
        "characterMetrics":base["characterMetrics"],
        "realCharacterComputed":0,
        "unknownCharacterMetrics":50,
        "simulationContext":None,
        "realParity":"BLOCKED_NOT_RUN",
        "approvedGoldens":0,
        "publishedRules":False,
    }
    out["graphSha256"]=graph.digest(out)
    return out


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--overlay",type=Path,required=True)
    p.add_argument("--synthetic",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args(argv)
    try:
        v=build(graph.read_json(a.overlay),graph.read_json(a.synthetic))
        code=0
    except (graph.GraphError,ValueError,KeyError,TypeError,OSError,
            UnicodeError,ImportError) as e:
        v={"status":"BLOCKED","errors":[str(e)],
           "realParity":"BLOCKED_NOT_RUN","publishedRules":False}
        code=2
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(v,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in v.items() if k!="characterMetrics"},sort_keys=True))
    return code
if __name__=="__main__":
    sys.exit(main())
