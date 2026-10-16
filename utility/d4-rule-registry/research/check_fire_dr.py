"""F7.2 Fire DR bounded DISPLAY source arithmetic replay. Not a #108 Golden parity gate."""
from __future__ import annotations
import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sys

FIXTURE = Path(__file__).with_name("fire-dr-f7-2.json")
EXPECTED_SOURCE = "918aa4b0e1845d34909a8b847a324b445e3805a7"
REVIEW = "https://github.com/Synclab-VN-dev/StreamOps/issues/106#issuecomment-6212668905"
POINTS = [(50,22), (50,422), (50,2822), (50,3222), (50,3544)]


def compare(doc):
    assert doc["fixtureVersion"] == "f7.2-v1"
    assert doc["sourceKind"] == "INDEPENDENTLY_REVIEWED_MAXROLL_DISPLAY_SOURCE_ONLY"
    assert doc["sourceCommit"] == EXPECTED_SOURCE and doc["sourceReview"] == REVIEW
    assert doc["patch"] == "3.2.1.73552" and doc["classId"] == "rogue"
    assert doc["metricId"] == "maxroll.heroDetails.446"
    assert doc["oracle"] == "MAXROLL_ONLY"
    assert doc["candidate"] == "DR_display_percent = 90 * R / (R + 15 * Level)"
    assert doc["status"] == "BOUNDED_VERIFIED_DISPLAY_ONLY"
    assert doc["exactRawHelperVerified"] is False
    assert doc["explicitCapVerified"] is False
    assert doc["sourceInputsKnownFully"] is False
    assert doc["approvedGolden"] is False and doc["graphParity"] == "NOT_RUN"
    tol = Decimal(doc["displayTolerancePercentagePoints"])
    assert tol == Decimal("0.05")
    vectors = doc["vectors"]
    assert len(vectors) == 5 and [(x["level"], x["R"]) for x in vectors] == POINTS
    report = []
    for vector in vectors:
        level, resistance = vector["level"], vector["R"]
        assert isinstance(level,int) and isinstance(resistance,int) and resistance >= 0
        predicted = Decimal(90)*Decimal(resistance)/(Decimal(resistance)+Decimal(15)*Decimal(level))
        source_display = Decimal(vector["maxrollDisplayPercent"])
        delta = abs(predicted-source_display)
        assert delta < tol, "F7.2_DISPLAY_MISMATCH: %s" % (vector,)
        report.append({
            "level": level, "R": resistance,
            "maxrollSourceDisplayPercent": vector["maxrollDisplayPercent"],
            "computedBoundedCurvePercent": str(predicted),
            "absErrorPercentagePoints": str(delta),
            "status": "PASS_BOUNDED_DISPLAY",
        })
    return {
        "status": "PASS_BOUNDED_RESEARCH_REPLAY_ONLY",
        "sourceMatch": len(report),
        "sourceTotal": 5,
        "sampleRows": report,
        "provenance": EXPECTED_SOURCE,
        "verifiedExactRawHelper": False,
        "verifiedExplicitCap": False,
        "approvedGolden": False,
        "graphParity": "BLOCKED_NOT_RUN",
        "promotableToActiveRule": False,
    }


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--fixture",type=Path,default=FIXTURE)
    p.add_argument("--report",type=Path,required=True)
    args=p.parse_args(argv)
    try:
        result=compare(json.loads(args.fixture.read_text(encoding="utf-8")))
        code=0
    except (AssertionError, ValueError, KeyError, OSError, InvalidOperation, ZeroDivisionError, TypeError) as exc:
        result={"status":"BLOCKED","errors":[str(exc)],"approvedGolden":False,
                "graphParity":"NOT_TESTED","promotableToActiveRule":False}
        code=2
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="sampleRows"},sort_keys=True))
    return code


if __name__=="__main__":
    sys.exit(main())
