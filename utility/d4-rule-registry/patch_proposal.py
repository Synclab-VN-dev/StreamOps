"""#109 on-demand synthetic patch evidence-to-candidate diff. Never publishes game rules."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import registry

SOURCE = HERE / "fixtures" / "synthetic-patch-cycle.json"
EVIDENCE = HERE / "fixtures" / "synthetic-patch-evidence.json"
SOURCE_BLOB = "d5cc70811475eda18b06a7a7fbd4e58724d9ab59"
SOURCE_SHA256 = "74d7e394dd18798cb20c0938a2f98e94ea8adf03d01fb810540be2a73d4e6d82"
CATEGORIES = ("added", "removed", "buffed", "nerfed")
GATES = {"G1":"NOT_APPLICABLE_SYNTHETIC_DATA_ONLY","G2":"NOT_RUN","G3":"NOT_RUN","G4":"NOT_RUN"}


def _require(condition, reason):
    registry.require(condition, reason)


def _check_source(source_bytes):
    blob = hashlib.sha1(b"blob " + str(len(source_bytes)).encode() + b"\0" + source_bytes).hexdigest()
    digest = hashlib.sha256(source_bytes).hexdigest()
    _require(blob == SOURCE_BLOB and digest == SOURCE_SHA256, "UNAPPROVED_SOURCE_MUTATION")
    fixture = json.loads(source_bytes)
    _require(isinstance(fixture,dict) and fixture.get("synthetic") is True,
             "REAL_PATCH_INPUT_FORBIDDEN")
    for name in ("old","new"):
        state = fixture.get(name)
        _require(isinstance(state,dict) and set(state)=={"patch","rules"}
                 and isinstance(state["patch"],str) and state["patch"].startswith("synthetic-")
                 and isinstance(state["rules"],dict), "INVALID_PATCH_STATE")
        for mid,val in state["rules"].items():
            _require(isinstance(mid,str) and mid.startswith("fake.")
                     and type(val) in (int,float) and math.isfinite(val),
                     "UNSAFE_SYNTHETIC_METRIC")
    _require(fixture["old"]["patch"]!=fixture["new"]["patch"],"NO_PATCH_CHANGE")
    return fixture


def build(source_bytes, evidence):
    fixture = _check_source(source_bytes)
    _require(isinstance(evidence,dict) and
             set(evidence)=={"manifestVersion","sourceGitBlobSha1","sourceSha256",
                             "synthetic","sourceKind","gameFormulaVerification","records"},
             "MANIFEST_SCHEMA_INVALID")
    _require(evidence["manifestVersion"]=="1.0.0"
             and evidence["sourceGitBlobSha1"]==SOURCE_BLOB
             and evidence["sourceSha256"]==SOURCE_SHA256
             and evidence["synthetic"] is True
             and evidence["sourceKind"]=="synthetic_fixture"
             and evidence["gameFormulaVerification"]=="NOT_VERIFIED",
             "UNSOURCED_OR_REAL_FORMULA_CLAIM")
    delta = registry.simulate_synthetic_patch_cycle(fixture)["diff"]
    old,new = fixture["old"]["rules"],fixture["new"]["rules"]
    changed = {mid:cat for cat in CATEGORIES for mid in delta[cat]}
    records = evidence["records"]
    _require(isinstance(records,list) and len(records)==len(changed),
             "MISSING_OR_EXTRA_SOURCE_EVIDENCE")
    seen=set()
    for row in records:
        _require(isinstance(row,dict) and
                 set(row)=={"metricId","category","sourcePointer","sourceKind",
                            "sourceGitBlobSha1","scope"},
                 "INVALID_SOURCE_RECORD")
        mid=row["metricId"]
        _require(isinstance(mid,str) and mid in changed and mid not in seen,
                 "DUPLICATE_OR_UNKNOWN_SOURCE")
        seen.add(mid)
        _require(row["category"]==changed[mid]
                 and row["sourcePointer"]=="fixtures/synthetic-patch-cycle.json#/new/rules/"+mid
                 and row["sourceKind"]=="synthetic_fixture"
                 and row["sourceGitBlobSha1"]==SOURCE_BLOB
                 and row["scope"]=="SYNTHETIC_ONLY",
                 "EVIDENCE_POINTER_OR_CATEGORY_MISMATCH")
    _require(seen==set(changed),"SOURCE_COVERAGE_GAP")
    candidates=[{
        "id":"synthetic."+mid, "metricId":mid, "changeType":changed[mid],
        "oldValue":old.get(mid),"newValue":new.get(mid),
        "sourcePointer":"fixtures/synthetic-patch-cycle.json#/new/rules/"+mid,
        "sourceGitBlobSha1":SOURCE_BLOB,"patch":fixture["new"]["patch"],
        "schemaVersion":"1.0.0","state":"SYNTHETIC_CANDIDATE_UNVERIFIED",
        "verificationGates":dict(GATES),"active":False,
    } for mid in sorted(changed)]
    report={
        "status":"PASS_SYNTHETIC_CANDIDATE_GENERATION_ONLY",
        "fixtureKind":"synthetic_fixture","sourceSha256":SOURCE_SHA256,
        "sourceGitBlobSha1":SOURCE_BLOB,
        "baselinePatch":fixture["old"]["patch"],"targetPatch":fixture["new"]["patch"],
        "schemaVersion":"1.0.0","sourceChangeCoverage":
            {"changed":len(changed),"sourced":len(candidates),"gameVerified":0},
        "diff":delta,"candidates":candidates,"autoPublish":False,
        "schemaChanged":False,"realPatchCompatibility":"NOT_TESTED",
        "maxrollParity":"NOT_TESTED",
    }
    report["reportSha256"]=registry.sha256(report)
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description="Source-pinned synthetic patch candidate/diff generator")
    p.add_argument("--source",type=Path,default=SOURCE)
    p.add_argument("--evidence",type=Path,default=EVIDENCE)
    p.add_argument("--report",type=Path,required=True)
    args=p.parse_args(argv)
    try:
        report=build(args.source.read_bytes(),registry.load(args.evidence))
        code=0
    except (ValueError,TypeError,KeyError,OSError,UnicodeError,registry.RegistryError) as exc:
        report={"status":"BLOCKED","errors":[str(exc)],
                "autoPublish":False,"maxrollParity":"NOT_TESTED"}
        code=2
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k!="candidates"},sort_keys=True))
    return code

if __name__=="__main__":
    sys.exit(main())
