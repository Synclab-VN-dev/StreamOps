"""Independent DEVELOPMENT Golden diagnostic for M20 working-model candidates.

This module alone reads the immutable expected capture, after the source-only
working model has been evaluated and serialized. A sample match of a provisional
subtotal is NOT a Golden VERIFIED stat and cannot promote production rules.
"""
from __future__ import annotations
from decimal import Decimal
from pathlib import Path
import argparse
import hashlib
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import graph

GOLDEN_BLOB = "6220f636f66c9d113c0b41f13480d09d7bed4dc0"
GOLDEN_SOURCE_COMMIT = "bb4c5cc6b2135583eb708f0a3f374060675b6c0b"


def compare(model, raw_expected):
    graph.reject(model.get("schema") == "d4-working-model-candidates-v1" and
                 model.get("reportSha256") ==
                 graph.digest({k:v for k,v in model.items() if k != "reportSha256"}) and
                 model.get("goldenExpectedLoaded") is False and
                 model.get("publishAllowed") is False and
                 model.get("newGoldenVerified") == 0,
                 "UNTRUSTED_INDEPENDENT_WORKING_MODEL")
    sha = hashlib.sha1(b"blob " + str(len(raw_expected)).encode() + b"\0" +
                       raw_expected).hexdigest()
    graph.reject(sha == GOLDEN_BLOB, "GOLDEN_CAPTURE_BLOB_MISMATCH")
    expected = json.loads(raw_expected)
    fixture = expected["fixture"]
    graph.reject(expected.get("origin") == "MAXROLL_BROWSER_CAPTURE" and
                 fixture.get("classId") == model["classId"] == "rogue" and
                 fixture.get("gamePatch") + "." + fixture.get("gameBuild") ==
                 model["gamePatch"] == "3.2.1.73552" and
                 fixture.get("inputSnapshotSha256") ==
                 model["inputFingerprintSha256"] and
                 len(expected["metrics"]) == 50 and
                 len({r["metricId"] for r in expected["metrics"]}) == 50,
                 "GOLDEN_CAPTURE_FIXTURE_MISMATCH")
    source = {r["metricId"]:r for r in expected["metrics"]}
    metrics = model["metrics"]
    graph.reject(len(metrics) == 20 and
                 len({m["metricId"] for m in metrics}) == 20,
                 "INCOMPLETE_WORKING_MODEL_TARGET20")
    result = []
    counts = {"PROVISIONAL_MISMATCH":0,
              "PROVISIONAL_SAMPLE_MATCH_NOT_VERIFIED":0,
              "BLOCKED_NO_CANDIDATE":0,
              "SOURCE_LEVEL_SAMPLE_MATCH_NEEDS_ORIGINAL_GATE":0,
              "SOURCE_LEVEL_MISMATCH":0}
    for row in metrics:
        mid = row["metricId"]
        item = source[mid]
        graph.reject(item["originalMaxrollLabel"] == row["label"] and
                     item["group"].casefold() == row["group"].casefold() and
                     item["rawOrigin"] == "MAXROLL_CDP_RUNTIME_DIRECT" and
                     item["displayOrigin"] == "MAXROLL_BROWSER_UI_DIRECT" and
                     item["inputFingerprintSha256"] ==
                     model["inputFingerprintSha256"],
                     "GOLDEN_ID_LABEL_GROUP_OR_ORIGIN_MISMATCH")
        actual = row["candidateRaw"]
        reference = item["expectedRawValue"]
        diff = (str(Decimal(str(actual)) - Decimal(str(reference)))
                if actual is not None else None)
        matches = (actual is not None and diff in ("0", "0.0") and
                   row["candidateDisplay"] == item["expectedDisplayValue"])
        if actual is None:
            status = "BLOCKED_NO_CANDIDATE"
        elif row["metricId"] == "maxroll.heroDetails.279":
            status = ("SOURCE_LEVEL_SAMPLE_MATCH_NEEDS_ORIGINAL_GATE" if matches
                      else "SOURCE_LEVEL_MISMATCH")
        else:
            status = ("PROVISIONAL_SAMPLE_MATCH_NOT_VERIFIED" if matches else
                      "PROVISIONAL_MISMATCH")
        counts[status] += 1
        result.append({
            "metricId":mid, "label":row["label"], "status":status,
            "actualCandidateRaw":actual,"actualCandidateDisplay":row["candidateDisplay"],
            "expectedRaw":reference,"expectedDisplay":item["expectedDisplayValue"],
            "rawDiffActualMinusExpected":diff,
            "missingContributorFamilies":row["missingContributorFamilies"],
            "assumption":row["assumption"],
            "verificationClaim":"NONE_FROM_THIS_DIAGNOSTIC",
        })
    report = {
        "schema":"d4-working-model-golden-diagnostics-v1",
        "fixtureId":model["fixtureId"],"classId":model["classId"],
        "gamePatch":model["gamePatch"],
        "goldenOriginalCommit":GOLDEN_SOURCE_COMMIT,
        "goldenOriginalBlob":GOLDEN_BLOB,
        "modelReportSha256":model["reportSha256"],
        "comparedMetricIds":len(result),"counts":counts,
        "newGoldenVerified":0,
        "goldenStatus":"DIAGNOSTIC_NOT_A_PROMOTION_GATE",
        "holdoutOpened":False,"publishAllowed":False,
        "metrics":result,
    }
    report["reportSha256"] = graph.digest(report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser()
    for k in ("model", "golden", "report"):
        parser.add_argument("--" + k, type=Path, required=True)
    a = parser.parse_args(argv)
    try:
        report = compare(graph.read_json(a.model), a.golden.read_bytes())
        code = 0
    except (KeyError, ValueError, TypeError, OSError, graph.GraphError) as exc:
        report = {"status":"BLOCKED_INVALID_GOLDEN_DIAGNOSTIC",
                  "reason":str(exc),"newGoldenVerified":0,"publishAllowed":False}
        code = 2
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(report,sort_keys=True,indent=2) + "\n",
                        encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k != "metrics"},
                     sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
