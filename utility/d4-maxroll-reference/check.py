"""Validate a Maxroll read-only captured Character Stats fixture (not a parity engine)."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
from typing import Any

VERSION = "1.0.0"
SHA = re.compile(r"^[0-9a-f]{64}$")
PATCH = re.compile(r"^[0-9]+(?:\.[0-9]+){1,4}$")
STATUSES = {"OBSERVED", "UNKNOWN", "UNVERIFIED", "UNSUPPORTED", "NOT_APPLICABLE"}


def validate(obj: Any, *, golden: bool = False) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(obj, dict):
        return {"status": "FAIL", "errors": ["root must be an object"], "warnings": [], "metricCounts": {}}
    def need(cond: bool, message: str):
        if not cond:
            errors.append(message)
    need(obj.get("contractVersion") == VERSION, "wrong contractVersion")
    need(obj.get("source") == "MAXROLL", "source must be MAXROLL")
    v = obj.get("versionEvidence") or {}
    need(isinstance(v, dict), "versionEvidence must be object")
    if not isinstance(v, dict): v = {}
    need(v.get("status") in ("VERIFIED", "UNVERIFIED"), "missing explicit version status")
    need(isinstance(v.get("capturedAtUtc"), str) and v.get("capturedAtUtc", "").endswith("Z"), "missing UTC capture timestamp")
    need(isinstance(v.get("url"), str) and v.get("url", "").startswith("https://maxroll.gg/d4/planner/"), "missing Maxroll fixture URL")
    for key in ("appVersion", "gamePatch", "gameBuild"):
        value = v.get(key)
        need(value is None or isinstance(value, str), f"versionEvidence.{key} must be string or null")
    if v.get("gamePatch") is not None:
        need(bool(PATCH.fullmatch(v["gamePatch"])), "invalid gamePatch shape")
    f = obj.get("fixture") or {}
    if not isinstance(f, dict): f = {}; errors.append("fixture must be object")
    for key in ("id", "classId", "buildFingerprint", "inputSnapshotSha256"):
        need(isinstance(f.get(key), str) and bool(f.get(key)), f"fixture.{key} required")
    need(isinstance(f.get("level"), int) and not isinstance(f.get("level"), bool) and f.get("level", 0) > 0, "fixture.level must be positive integer")
    need(f.get("inputCompleteness") in ("COMPLETE", "PARTIAL"), "fixture.inputCompleteness required")
    if isinstance(f.get("inputSnapshotSha256"), str):
        need(bool(SHA.fullmatch(f["inputSnapshotSha256"])), "inputSnapshotSha256 invalid")
    groups = obj.get("groups")
    need(isinstance(groups, list) and len(groups) > 0, "groups must be non-empty array")
    all_ids = set()
    counts: dict[str, int] = {}
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, dict):
                errors.append("malformed group"); continue
            category = group.get("id")
            if not isinstance(category, str) or not category:
                errors.append("group id missing"); continue
            need(category not in counts, f"duplicate group {category}")
            rows = group.get("metrics")
            need(isinstance(rows, list), f"{category}: metrics must be array")
            if not isinstance(rows, list): continue
            counts[category] = len(rows)
            need(len(rows) == group.get("visibleCount"), f"{category}: visibleCount mismatch")
            for row in rows:
                if not isinstance(row, dict): errors.append(f"{category}: malformed metric"); continue
                key = row.get("id")
                need(isinstance(key, str) and bool(key), f"{category}: metric id missing")
                if isinstance(key, str):
                    need(key not in all_ids, f"duplicate metric id: {key}"); all_ids.add(key)
                need(isinstance(row.get("label"), str) and bool(row.get("label")), f"{key}: label missing")
                need(isinstance(row.get("displayValue"), str), f"{key}: displayValue must be captured text")
                need(isinstance(row.get("unit"), str), f"{key}: unit must be string (can be empty)")
                need(row.get("evidenceStatus") in STATUSES, f"{key}: unknown evidenceStatus")
                need(row.get("rawOrigin") in ("MAXROLL_RUNTIME", "NOT_OBSERVED"), f"{key}: rawOrigin invalid")
                if row.get("rawOrigin") == "NOT_OBSERVED":
                    need(row.get("rawValue") is None, f"{key}: fabricated rawValue")
                else:
                    need(isinstance(row.get("rawValue"), (int, float, str)) and row.get("rawValue") != "", f"{key}: raw value absent")
                need(isinstance(row.get("evidenceRef"), str) and bool(row.get("evidenceRef")), f"{key}: capture evidenceRef required")
                need(row.get("formulaStatus") in ("UNKNOWN", "SOURCE_OBSERVED", "CAUSALLY_VERIFIED"), f"{key}: formulaStatus invalid")
    need(obj.get("totalVisibleMetrics") == sum(counts.values()), "totalVisibleMetrics != enumerated count")
    # A capture is not a claim that every game's metric exists in the known set.
    need(obj.get("globalGameCoverage") is None, "globalGameCoverage must remain null")
    if v.get("status") != "VERIFIED" or not all(v.get(k) for k in ("appVersion", "gamePatch", "gameBuild")):
        warnings.append("version NOT independently pinned")
    if f.get("inputCompleteness") != "COMPLETE": warnings.append("fixture inputs PARTIAL")
    if any(row.get("formulaStatus") != "CAUSALLY_VERIFIED" for g in groups or [] if isinstance(g, dict) for row in g.get("metrics", []) if isinstance(row, dict)):
        warnings.append("one or more formulas NOT causally verified (normal F1)")
    if golden:
        # Golden promotion is a separate step: even syntax-correct captured UI is only a candidate.
        need(v.get("status") == "VERIFIED" and all(v.get(k) for k in ("appVersion", "gamePatch", "gameBuild")), "golden requires verified exact Maxroll version/build")
        need(f.get("inputCompleteness") == "COMPLETE", "golden requires complete fixture inputs")
        need(obj.get("referenceApproval") == "INDEPENDENTLY_REVIEWED", "golden requires independent review record")
        need(isinstance(obj.get("referenceManifestSha256"), str) and bool(SHA.fullmatch(obj.get("referenceManifestSha256", ""))), "golden requires immutable manifest hash")
        need(obj.get("fixtureOrigin") == "CAPTURED_MAXROLL_INDEPENDENTLY", "golden must not derive from StreamOps or synthetic outputs")
    status = "FAIL" if errors else ("PASS_GOLDEN_RECORD_INTEGRITY" if golden else "PASS_CANDIDATE_ONLY")
    return {"status": status, "contractVersion": VERSION, "metricCounts": counts, "totalVisibleMetrics": sum(counts.values()), "errors": sorted(set(errors)), "warnings": warnings, "maxrollParity": "NOT_TESTED"}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("capture", type=Path)
    p.add_argument("--golden", action="store_true")
    p.add_argument("--report", type=Path)
    args = p.parse_args(argv)
    try:
        out = validate(json.loads(args.capture.read_text(encoding="utf-8")), golden=args.golden)
    except (OSError, UnicodeError, ValueError) as exc:
        out = {"status": "BLOCKED", "errors": [str(exc)], "warnings": [], "metricCounts": {}}
    formatted = json.dumps(out, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(formatted, encoding="utf-8")
    print(formatted, end="")
    return 1 if out["status"] == "FAIL" else 2 if out["status"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
