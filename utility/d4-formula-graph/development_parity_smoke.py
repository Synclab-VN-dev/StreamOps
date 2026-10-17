"""CI smoke: mock development expected in memory only, NEVER claim Maxroll parity."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import graph
import golden_candidate_eval as ev
import development_parity as gate

def synthetic_expected(actual):
    return {
        "schema":"F-GOLDEN-01-maxroll-expected-v1",
        "fixtureId":actual["fixtureId"],
        "partition":"DEVELOPMENT",
        "origin":"SYNTHETIC_TEST_ONLY",
        "patch":actual["gamePatch"],
        "inputFingerprintSha256":actual["sourceInputFingerprint"],
        "metricCount":actual["sourceRowCount"],
        "metrics":[{
            "metricId":r["metricId"],"group":r["group"],"label":r["label"],
            "raw":70 if r["metricId"]==ev.LEVEL_ID else 1,
            "display":"70" if r["metricId"]==ev.LEVEL_ID else "1",
            "provenance":{"raw":"SYNTHETIC_TEST_ONLY",
                          "display":"SYNTHETIC_TEST_ONLY"},
        } for r in actual["characterMetrics"]],
    }

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--report-dir",type=Path,required=True)
    a=p.parse_args(argv)
    a.report_dir.mkdir(parents=True,exist_ok=True)
    for fid in ("dev00","dev01"):
        actual=graph.read_json(a.report_dir/(fid+"-candidate-actual.json"))
        result=gate.compare(actual,synthetic_expected(actual),test_only=True)
        graph.reject(result["sourceRows"]==actual["sourceRowCount"]
                     and result["matchedUnverifiedRows"]==1 and
                     result["blockedRows"]==actual["sourceRowCount"]-1 and
                     result["fullMaxrollParity"]=="BLOCKED_NOT_RUN"
                     and result["referenceMode"]=="SYNTHETIC_TEST_ONLY",
                     "SYNTHETIC_COMPARATOR_BROKEN")
        # Never persist mock Expected to an artifact.
        out=a.report_dir/(fid+"-synthetic-dev-diff.json")
        out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
        print(fid,result["sourceRows"],result["uniqueMetricIds"],
              result["matchedUnverifiedRows"],result["blockedRows"])
    return 0
if __name__=="__main__":sys.exit(main())
