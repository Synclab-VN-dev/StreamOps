"""#108 Maxroll 50-Character-Stat Golden parity gate (no formula evaluator).

Expected samples must be captured independently from Maxroll; actual samples
must come from #110 Graph. Until BOTH exist, report BLOCKED, never PASS.
"""
from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re

SHA = re.compile(r"^[0-9a-f]{64}$")
GROUPS = {"summary": 2, "core": 5, "resistances": 8, "offensive": 20,
          "defensive": 7, "utility": 7, "pvp": 1}
MISSING = object()


def compare_metric(expected, actual):
    """One display-pinned metric. Raw values are tested ONLY if observed at source."""
    if actual.get("display") != expected.get("display"):
        return "FAIL", "DISPLAY_MISMATCH"
    if expected.get("rawOrigin") == "MAXROLL_RUNTIME":
        if actual.get("raw") is None:
            return "BLOCKED", "ACTUAL_RAW_UNAVAILABLE"
        try:
            e, a = Decimal(str(expected["raw"])), Decimal(str(actual["raw"]))
        except (InvalidOperation, KeyError, ValueError):
            return "BLOCKED", "INVALID_RAW_NUMBER"
        if not e.is_finite() or not a.is_finite():
            return "BLOCKED", "NONFINITE_RAW"
        if a != e:
            return "FAIL", "RAW_MISMATCH_NO_UNAPPROVED_TOLERANCE"
    return "PASS", "EXACT_MATCH"


def _identity(obj, f):
    fields = ("classId", "level", "variant", "gamePatch", "gameBuild",
              "inputSnapshotSha256")
    data = obj.get("fixture", {})
    return isinstance(data, dict) and all(data.get(k) == f.get(k) for k in fields)


def _rows(rows, name, errors, *, expected=False):
    if not isinstance(rows, list) or len(rows) != 50:
        errors.append(name + ": missing exactly 50 stat rows")
        return {}
    keys = set()
    counts = Counter()
    result = {}
    for m in rows:
        if not isinstance(m, dict):
            errors.append(name + ": malformed metric")
            continue
        key, group = m.get("id"), m.get("group")
        if not isinstance(key, str) or not key or not isinstance(group, str):
            errors.append(name + ": missing metric ID/group")
            continue
        if not key.startswith(group + "."):
            errors.append(name + ": metric ID does not match group " + key)
        if key in keys:
            errors.append(name + ": duplicate metric ID " + key)
        keys.add(key)
        counts[group] += 1
        if not isinstance(m.get("display"), str):
            errors.append(name + ": display not captured/computed for " + key)
        if expected:
            if m.get("source") != "MAXROLL_BROWSER_CAPTURE" or not m.get("evidenceRef"):
                errors.append(name + ": missing independent Maxroll evidence for " + key)
            if m.get("rawOrigin") not in ("MAXROLL_RUNTIME", "NOT_OBSERVED"):
                errors.append(name + ": invalid raw origin for " + key)
            if m.get("rawOrigin") == "NOT_OBSERVED" and m.get("raw") is not None:
                errors.append(name + ": fabricated raw for " + key)
            if m.get("rawOrigin") == "MAXROLL_RUNTIME" and m.get("raw") is None:
                errors.append(name + ": raw missing for " + key)
        result[key] = m
    if dict(counts) != GROUPS:
        errors.append(name + ": group coverage != 50 pinned visible stats")
    return result


def verify(fixture_doc, golden=MISSING, actual=MISSING, formulas=MISSING):
    errors, blocks, comparisons = [], [], []
    f = fixture_doc.get("fixture", {}) if isinstance(fixture_doc, dict) else {}
    if (not isinstance(f, dict) or fixture_doc.get("oracle") != "MAXROLL_ONLY"
            or f.get("metricDenominator") != 50
            or f.get("metricGroups") != GROUPS
            or f.get("classId") != "rogue"
            or (f.get("gamePatch"), f.get("gameBuild")) != ("3.2.1", "73552")
            or not SHA.fullmatch(str(f.get("inputSnapshotSha256", "")))):
        blocks.append("INVALID_PINNED_ROGUE_FIXTURE")
    if f.get("inputCompleteness") != "COMPLETE":
        blocks.append("FIXTURE_INPUTS_INCOMPLETE")
    for name, data in (("golden", golden), ("actual", actual), ("formulas", formulas)):
        if data is MISSING or not isinstance(data, dict):
            blocks.append("MISSING_" + name.upper() + "_ARTIFACT")
    if blocks:
        return _report(errors, blocks, comparisons)
    for name, data in (("golden", golden), ("actual", actual)):
        if not _identity(data, f):
            blocks.append("MISMATCH_" + name.upper() + "_FIXTURE_IDENTITY")
    if golden.get("source") != "MAXROLL_BROWSER_CAPTURE" or golden.get("review") != "INDEPENDENTLY_APPROVED":
        blocks.append("GOLDEN_NOT_INDEPENDENTLY_APPROVED")
    if not golden.get("evidenceManifestSha256") or not SHA.fullmatch(str(golden["evidenceManifestSha256"])):
        blocks.append("INVALID_GOLDEN_MANIFEST")
    # Ensure the captured metric payload has not changed since independent review.
    payload = {"fixture": golden.get("fixture"), "metrics": golden.get("metrics"),
               "vectors": golden.get("vectors")}
    digest = hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if golden.get("capturedPayloadSha256") != digest:
        blocks.append("GOLDEN_CAPTURE_PAYLOAD_HASH_MISMATCH")
    if actual.get("source") != "FORMULA_GRAPH":
        blocks.append("ACTUAL_NOT_FROM_FORMULA_GRAPH")
    for key in ("graphSha256", "ruleSetSha256"):
        if not SHA.fullmatch(str(actual.get(key, ""))):
            blocks.append("ACTUAL_" + key + "_MISSING")
    if formulas.get("patchBuild") != "3.2.1.73552":
        blocks.append("RULES_PATCH_MISMATCH")
    expected = _rows(golden.get("metrics"), "golden", blocks, expected=True)
    observed = _rows(actual.get("metrics"), "actual", blocks)
    rules = formulas.get("metrics")
    if not isinstance(rules, list) or len(rules) != 50:
        blocks.append("NOT_ALL_50_FORMULAS_PRESENT")
        rule_map = {}
    else:
        rule_map = {}
        for rule in rules:
            if not isinstance(rule, dict) or not isinstance(rule.get("id"), str):
                blocks.append("BAD_FORMULA_RECORD")
                continue
            if rule["id"] in rule_map:
                blocks.append("DUPLICATE_FORMULA_ID")
            rule_map[rule["id"]] = rule
            if (rule.get("status") != "CAUSALLY_VERIFIED"
                    or not rule.get("expressionRef")
                    or len(rule.get("independentVectorRefs", [])) < 2):
                blocks.append("UNVERIFIED_FORMULA_" + rule["id"])
    if set(expected) != set(observed) or set(expected) != set(rule_map):
        blocks.append("METRIC_ID_COVERAGE_INCOMPLETE_OR_MISMATCHED")
    # An actual match cannot validate a formula unless it also passes independent
    # changed-input reference samples. Check these with the same strict comparator.
    gold_vectors = golden.get("vectors")
    actual_vectors = actual.get("vectors")
    if not isinstance(gold_vectors, list) or not isinstance(actual_vectors, list):
        blocks.append("MISSING_CHANGED_INPUT_GOLDEN_VECTORS")
    else:
        if len(gold_vectors) < 2 or len(actual_vectors) != len(gold_vectors):
            blocks.append("INSUFFICIENT_INDEPENDENT_CHANGED_INPUT_VECTORS")
        fingerprints = set()
        source_vector_ids = {v.get("id") for v in gold_vectors if isinstance(v, dict)}
        if len(source_vector_ids) != len(gold_vectors):
            blocks.append("DUPLICATE_GOLDEN_VECTOR_IDS")
        for rule in rule_map.values():
            refs = rule.get("independentVectorRefs", [])
            if len(set(refs)) < 2 or not set(refs).issubset(source_vector_ids):
                blocks.append("FORMULA_VECTOR_PROVENANCE_UNMATCHED_" + rule["id"])
        for i, (g, a) in enumerate(zip(gold_vectors, actual_vectors)):
            stamp = g.get("inputSnapshotSha256", "")
            if (not SHA.fullmatch(str(stamp)) or stamp == f.get("inputSnapshotSha256")
                    or stamp in fingerprints or stamp != a.get("inputSnapshotSha256")):
                blocks.append("VECTOR_FINGERPRINT_MISMATCH_" + str(i))
            fingerprints.add(stamp)
            if (g.get("source") != "MAXROLL_BROWSER_CAPTURE"
                    or g.get("inputCompleteness") != "COMPLETE"
                    or not g.get("captureEvidenceRef")):
                blocks.append("VECTOR_EXPECTED_SOURCE_OR_INPUT_INVALID_" + str(i))
            if a.get("source") != "FORMULA_GRAPH":
                blocks.append("VECTOR_ACTUAL_NOT_FROM_GRAPH_" + str(i))
            gx = _rows(g.get("metrics"), "golden-vector-" + str(i), blocks, expected=True)
            ax = _rows(a.get("metrics"), "actual-vector-" + str(i), blocks)
            if set(gx) != set(ax) or set(gx) != set(expected):
                blocks.append("VECTOR_METRIC_COVERAGE_INVALID_" + str(i))
            for key in set(gx) & set(ax):
                result, reason = compare_metric(gx[key], ax[key])
                comparisons.append({"vector": i, "metricId": key,
                                    "result": result, "reason": reason})
                if result == "FAIL":
                    errors.append("VECTOR_" + str(i) + "_" + key + "_" + reason)
                if result == "BLOCKED":
                    blocks.append("VECTOR_" + str(i) + "_" + key + "_" + reason)
    for key in set(expected) & set(observed):
        result, reason = compare_metric(expected[key], observed[key])
        comparisons.append({"vector": "baseline", "metricId": key,
                            "result": result, "reason": reason})
        if result == "FAIL":
            errors.append("BASELINE_" + key + "_" + reason)
        if result == "BLOCKED":
            blocks.append("BASELINE_" + key + "_" + reason)
    return _report(errors, blocks, comparisons)


def _report(errors, blocks, comparisons):
    status = "BLOCKED" if blocks else "FAIL" if errors else "PASS"
    return {"status": status, "gate": "MAXROLL_50_STAT_GRAPH_PARITY",
            "numeratorMatched": sum(x["result"] == "PASS" and x["vector"] == "baseline"
                                    for x in comparisons),
            "denominator": 50, "errors": sorted(set(errors)),
            "blockers": sorted(set(blocks)),
            "comparisons": sorted(comparisons, key=lambda x: (str(x["vector"]), x["metricId"])),
            "scope": "ONE_PINNED_ROGUE_FIXTURE_NOT_ALL_GAME"}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--fixture", type=Path, required=True)
    p.add_argument("--golden", type=Path)
    p.add_argument("--actual", type=Path)
    p.add_argument("--formulas", type=Path)
    p.add_argument("--report", type=Path)
    args = p.parse_args()
    try:
        read = lambda path: json.loads(path.read_text(encoding="utf-8"))
        report = verify(read(args.fixture),
                        read(args.golden) if args.golden else MISSING,
                        read(args.actual) if args.actual else MISSING,
                        read(args.formulas) if args.formulas else MISSING)
    except (OSError, ValueError, UnicodeError) as exc:
        report = {"status": "BLOCKED", "blockers": ["UNREADABLE_ARTIFACT:" + str(exc)]}
    out = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(out, encoding="utf-8")
    print(out, end="")
    return {"PASS": 0, "FAIL": 1, "BLOCKED": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
