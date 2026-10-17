"""20-stat source-scoped Golden verification ledger for Issue #105.

No Golden Expected enters the Graph. When private full DEV capture is supplied,
validate its immutable Git blob and compare actual for all 20 separately.
Default public CI uses only the already-pinned public Level Golden subset.
Every missing formula is BLOCKED, never a synthetic VERIFIED stat.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import graph
import golden_candidate_eval as engine
import scoped_golden_verifier as verifier

EXPECTED_CAPTURE={"DEV-00":{
    "sha":"6220f636f66c9d113c0b41f13480d09d7bed4dc0",
    "commit":"bb4c5cc6b2135583eb708f0a3f374060675b6c0b",
    "class":"rogue","count":50,"unique":50}}
TARGET=20

def require(ok,error): graph.reject(ok,error)

def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def validate_manifest(manifest,inventory):
    require(type(manifest)==dict and manifest.get("schema")==
            "maxroll-stat-verification-target-v1" and
            manifest.get("goalUniqueMetricIds")==TARGET and
            manifest.get("initialFixture")=="DEV-00" and
            manifest.get("initialClassId")=="rogue" and
            manifest.get("patch")=="3.2.1.73552","INVALID_20_TARGET_SCOPE")
    targets=manifest.get("metrics")
    require(type(targets)==list and len(targets)==TARGET and
            len({x["metricId"] for x in targets})==TARGET,
            "INVALID_20_TARGET_DENOMINATOR")
    positions={r["metricId"]:r for r in inventory["metrics"]}
    require(inventory["fixtureId"]=="DEV-00" and inventory["classId"]=="rogue" and
            len(inventory["metrics"])==50 and len(positions)==50,
            "INCOMPLETE_ROGUE_CAPTURED_METRIC_INVENTORY")
    for t in targets:
        require(type(t)==dict and set(t)=={"metricId","label","priority","blockerHint"}
                and t["metricId"] in positions and
                positions[t["metricId"]]["label"]==t["label"] and
                t["priority"] in ("P0","P1") and
                type(t["blockerHint"])==str and bool(t["blockerHint"]),
                "TARGET_NOT_IN_IMMUTABLE_MAXROLL_INVENTORY")
    return targets

def load_private_capture(path,manifest,actual):
    """Read capture *bytes* and verify immutable Git blob, NOT just metadata."""
    raw=Path(path).read_bytes()
    blob=hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
    pinned=EXPECTED_CAPTURE[manifest["initialFixture"]]
    require(blob==pinned["sha"],"PRIVATE_GOLDEN_CAPTURE_BLOB_MISMATCH")
    data=json.loads(raw)
    f=data.get("fixture",{})
    require(data.get("origin")=="MAXROLL_BROWSER_CAPTURE" and
            f.get("classId")==pinned["class"] and
            f.get("gamePatch")+"."+f.get("gameBuild")==actual["gamePatch"] and
            f.get("inputSnapshotSha256")==actual["sourceInputFingerprint"] and
            len(data.get("metrics",[]))==pinned["count"] and
            len({m["metricId"] for m in data["metrics"]})==pinned["unique"],
            "PRIVATE_GOLDEN_CAPTURE_SCOPE_MISMATCH")
    return data

def run(source,inventory,rules,manifest,level_golden,private_path=None):
    targets=validate_manifest(manifest,inventory)
    # Formula evaluation MUST occur before reading independent Expected data.
    actual=engine.build(source,inventory,rules)
    require(actual["fixtureId"]=="DEV-00" and actual["classId"]=="rogue"
            and actual["uniqueMetricCount"]==50 and
            actual["sourceRowCount"]==50,
            "GRAPH_OUTSIDE_ROGUE_TARGET_SCOPE")
    level_verified=verifier.verify(actual,level_golden)
    require(level_verified["fixtureId"]==actual["fixtureId"] and
            level_verified["classId"]==actual["classId"] and
            level_verified["verifiedScoped"]==1 and
            level_verified["metrics"][0]["metricId"]=="maxroll.heroDetails.279" and
            level_verified["metrics"][0]["status"]=="VERIFIED",
            "BASELINE_GOLDEN_LEVEL_REGRESSION")
    indexed={(x["group"].casefold(),x["metricId"]):x
             for x in actual["characterMetrics"]}
    private_capture=load_private_capture(private_path,manifest,actual) if private_path else None
    full_ref=({m["metricId"]:m for m in private_capture["metrics"]}
              if private_capture else {})
    count={"VERIFIED":0,"FAIL":0,"BLOCKED":0}
    records=[]
    for target in targets:
        metric_id=target["metricId"]
        group=next(r["group"] for r in inventory["metrics"] if r["metricId"]==metric_id)
        row=indexed[(group.casefold(),metric_id)]
        observed=full_ref.get(metric_id)
        if private_capture:
            require(observed is not None and observed["group"].casefold()==group.casefold()
                    and observed["originalMaxrollLabel"]==target["label"]
                    and observed["rawOrigin"]=="MAXROLL_CDP_RUNTIME_DIRECT"
                    and observed["displayOrigin"]=="MAXROLL_BROWSER_UI_DIRECT"
                    and observed["inputFingerprintSha256"]==actual["sourceInputFingerprint"],
                    "PRIVATE_GOLDEN_METRIC_INVALID")
        if not row["computed"]:
            state="BLOCKED";reason="NO_SOURCE_DERIVED_FORMULA_ACTUAL"
        elif metric_id=="maxroll.heroDetails.279":
            state="VERIFIED";reason="REAL_SCOPED_GOLDEN_RAW_DISPLAY_PASS"
        elif not private_capture:
            state="BLOCKED";reason="NO_PRIVATE_GOLDEN_IN_PUBLIC_CI"
        elif (type(row.get("raw")) in (int,float) and
              row["raw"]==observed["expectedRawValue"] and
              row["display"]==observed["expectedDisplayValue"]):
            state="VERIFIED";reason="REAL_SCOPED_GOLDEN_RAW_DISPLAY_PASS"
        else:
            state="FAIL";reason="INDEPENDENT_GOLDEN_MISMATCH"
        count[state]+=1
        records.append({
          "metricId":metric_id,"label":target["label"],"group":group,
          "fixtureId":"DEV-00","classId":"rogue",
          "state":state,"reason":reason,"priority":target["priority"],
          "sourceFormulaBlocker":None if state=="VERIFIED" else target["blockerHint"],
          "candidateHasActual":bool(row["computed"]),
          "goldenMode":"IMMUTABLE_FULL_CAPTURE" if private_capture else
                       "PUBLIC_LEVEL_ONLY",
          "actualIsIndependentOfExpected":True,
        })
    require(sum(count.values())==TARGET,"TARGET_20_ROW_ACCOUNTING_FAILED")
    report={"schema":"maxroll-20-stat-scope-progress-v1",
            "target":TARGET,"fixtureId":actual["fixtureId"],
            "classId":actual["classId"],"gamePatch":actual["gamePatch"],
            "inputFingerprintSha256":actual["sourceInputFingerprint"],
            "actualGraphSha256":actual["graphSha256"],
            "candidateRuleSetSha256":actual["candidateRuleSetSha256"],
            "verificationType":"PER_METRIC_INDEPENDENT_CAPTURED_GOLDEN",
            "verifiedUniqueMetricIds":count["VERIFIED"],
            "failedMetricIds":count["FAIL"],
            "blockedMetricIds":count["BLOCKED"],
            "remainingToTarget":TARGET-count["VERIFIED"],
            "captureComplete":private_capture is not None,
            "allTargetVerified":count["VERIFIED"]==TARGET,
            "holdoutOpened":False,"productionRulePromoted":False,
            "records":records}
    report["reportSha256"]=graph.digest(report)
    return report

def main(argv=None):
    p=argparse.ArgumentParser()
    for k in ("source","inventory","rules","manifest","level-golden","report"):
        p.add_argument("--"+k,type=Path,required=True)
    p.add_argument("--private-expected",type=Path)
    a=p.parse_args(argv)
    try:
        report=run(read(a.source),read(a.inventory),read(a.rules),
                   read(a.manifest),read(a.level_golden),a.private_expected)
        rc=0
    except (OSError,ValueError,KeyError,TypeError,graph.GraphError) as e:
        report={"status":"BLOCKED_INVALID_VERIFICATION_EVIDENCE",
                "reason":str(e),"verifiedUniqueMetricIds":0}
        rc=2
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps({k:v for k,v in report.items() if k!="records"},sort_keys=True))
    return rc

if __name__=="__main__":
    sys.exit(main())
