"""Replay archived #106 F4/F5 evidence arithmetic. Not a formula or Graph parity gate."""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

F4_COMMIT = "3ae928e5701d2de9ac995973b39e9b91d789f4bb"
F5_COMMIT = "8fdf59a988b0425e789248a5f1898ef67b27314d"
AUDIT_KINDS = {"F4_BOUNDED_CONTROLLED": 22, "F4_F5_BOUNDED_MIXED": 3,
               "F5_OBSERVED_INVARIANT_NONCAUSAL": 1}
F5_COUNTS = {"allDamage": 9, "allDamageReduction": 6,
             "criticalStrikeChance": 9, "pvpDamageReduction": 9}
FLOAT_EPS = 1e-8
ROUNDING_HALF_STEP_PP = 0.05


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def tooltip_formula(kind, inputs):
    additive = sum(i["pct"] / 100 for i in inputs if not i["multiplicative"])
    multiplier = math.prod((1 + i["pct"] / 100) for i in inputs if i["multiplicative"])
    if kind == "allDamage":
        return (1 + additive) * multiplier - 1
    if kind == "criticalStrikeChance":
        return sum(i["pct"] / 100 for i in inputs)
    if kind == "allDamageReduction":
        # Frozen F5 vectors contain either all-negative multiplicative sources,
        # or additive sources. An unmodelled mixed mode must fail closed.
        mixed = any(i["multiplicative"] for i in inputs) and any(
            not i["multiplicative"] for i in inputs)
        if mixed:
            raise ValueError("unresolved mixed DR-source order")
        return 1 - multiplier if any(i["multiplicative"] for i in inputs) else additive
    raise ValueError("unknown F5 vector group")


def validate(audit, catalog):
    errors = []
    def need(ok, why):
        if not ok:
            errors.append(why)

    if not isinstance(audit, dict) or not isinstance(catalog, dict):
        return {"status": "FAIL", "errors": ["root must be an object"]}
    need(audit.get("auditVersion") == "1.0.0", "audit schema mismatch")
    need(audit.get("auditScope") == "LEGACY_26_SOURCE_EVIDENCE_REPLAY_NOT_GRAPH_PARITY",
         "source audit scope promoted")
    need(audit.get("referencePatch") == "3.2.1.73552" and
         audit.get("classId") == "rogue", "unsupported patch/class")
    evidence = audit.get("immutableEvidence") or {}
    need(evidence.get("f4Commit") == F4_COMMIT and
         evidence.get("f5Commit") == F5_COMMIT and
         evidence.get("currentCatalog") == "f8-character-metric-catalog.json",
         "source commits/catalog changed")
    need(evidence.get("f4BlobSha") == "5f5a04ebec5073d32151d3ea2cdc6ac54c6e9b17" and
         evidence.get("f5BlobSha") == "2d1ce8120663a883b3fd923344dca48ec6b955a5",
         "source blob identity changed")
    counts = audit.get("classification") or {}
    need(counts.get("metricCount") == 26 and counts.get("fullyVerified") == 0 and
         counts.get("graphParityPass") == 0 and counts.get("approvedGoldenCount") == 0,
         "false formula/golden/Graph promotion")
    need(counts.get("boundedControlledF4") == 22 and
         counts.get("boundedF4F5") == 3 and
         counts.get("observedInvariantNonCausal") == 1 and
         counts.get("f4NumericDeltas") == 209 and
         counts.get("f5TooltipVectors") == 33,
         "unsupported evidence denominator")
    rounding = audit.get("mathPolicy") or {}
    need(rounding.get("floatAbsEpsilon") == FLOAT_EPS and
         rounding.get("displayTooltipRoundingHalfStepPp") == ROUNDING_HALF_STEP_PP,
         "predeclared numeric tolerance changed")
    approval = audit.get("approval") or {}
    need(approval.get("formulaDesign") == "PENDING_OWNER_MAN_01" and
         approval.get("referenceGolden") == "NOT_APPROVED" and
         approval.get("merge") == "NOT_AUTHORIZED", "false owner/merge approval")
    source = catalog.get("metrics") or []
    expected = {m.get("metricId"): m for m in source if
                isinstance(m, dict) and m.get("legacyF5Status") == "VERIFIED"}
    need(len(source) == 50 and len(expected) == 26 and
         len({m.get("metricId") for m in source if isinstance(m, dict)}) == 50,
         "F8 source denominator wrong")
    metrics = audit.get("metrics")
    need(isinstance(metrics, list), "audit metrics must be a list")
    metrics = metrics if isinstance(metrics, list) else []
    seen, kind_counts = set(), Counter()
    delta_checks = 0
    noncausal_ids = []
    for row in metrics:
        if not isinstance(row, dict):
            errors.append("non-object audit metric"); continue
        mid = row.get("metricId")
        need(isinstance(mid, str) and mid not in seen and mid in expected,
             f"{mid}: extra/duplicate/unexpected legacy metric")
        seen.add(mid)
        src = expected.get(mid) or {}
        need(row.get("group") == src.get("group") and
             row.get("label") == src.get("label"), f"{mid}: F8 identity drift")
        need(row.get("formulaVerificationStatus") == "BOUNDED_VERIFIED" and
             row.get("fullFormulaVerified") is False and
             row.get("maxrollGraphParity") == "NOT_RUN" and
             row.get("promotionDecision") == "RETAIN_BOUNDED_SOURCE_ONLY",
             f"{mid}: unsupported formula/parity promotion")
        need(row.get("f5HistoricalStatus") == "VERIFIED" and
             row.get("f4HistoricalStatus") ==
             (src.get("f4ObservedDependencies") or {}).get("f4HistoricalStatus"),
             f"{mid}: historical proof changed")
        kind = row.get("evidenceKind")
        kind_counts[kind] += 1
        need(kind in AUDIT_KINDS, f"{mid}: invalid evidence category")
        need(row.get("causalIsolation") ==
             ("NOT_ESTABLISHED" if kind == "F5_OBSERVED_INVARIANT_NONCAUSAL"
              else "BOUNDED_ONLY"), f"{mid}: causality incorrectly claimed")
        basis = src.get("legacyEvidenceBasis")
        expected_kind = ("F4_BOUNDED_CONTROLLED"
                         if basis == "PRESERVED_F4_BOUNDED_EVIDENCE"
                         else "F5_OBSERVED_INVARIANT_NONCAUSAL"
                         if mid == "maxroll.heroDetails.70"
                         else "F4_F5_BOUNDED_MIXED")
        need(kind == expected_kind, f"{mid}: evidence basis mismatch")
        if kind == "F5_OBSERVED_INVARIANT_NONCAUSAL":
            noncausal_ids.append(mid)
        f4 = src.get("f4ObservedDependencies") or {}
        need(row.get("sourceFormulaCandidate") == f4.get("reportedFormulaCandidate") and
             row.get("sourceRuntimeExpression") == f4.get("runtimeExpression") and
             row.get("sourceDependencies") == f4.get("directDependencies") and
             row.get("sourceFunctionNodes") == f4.get("functionNodes") and
             row.get("sourceUnresolved") == f4.get("unresolved"),
             f"{mid}: F4 source formula/dependency drift")
        need(isinstance(row.get("requiredForFullVerification"), str) and
             bool(row.get("requiredForFullVerification")),
             f"{mid}: unsupported branches hidden")
        vectors = row.get("f4SourceVectors")
        need(isinstance(vectors, list), f"{mid}: F4 vectors absent")
        vectors = vectors if isinstance(vectors, list) else []
        need(len(vectors) == row.get("f4VectorDeclaredCount") ==
             f4.get("discriminatingVectorCount"), f"{mid}: vector count drift")
        ids = set()
        for v in vectors:
            if not isinstance(v, dict):
                errors.append(f"{mid}: malformed vector"); continue
            label = v.get("id")
            need(isinstance(label, str) and bool(label) and label not in ids,
                 f"{mid}: vector ID malformed/duplicate")
            ids.add(label)
            nums = [v.get(k) for k in ("before", "after", "reportedDelta")]
            if not all(finite_number(n) for n in nums):
                errors.append(f"{mid}: non-finite F4 values"); continue
            delta_checks += 1
            need(math.isclose(nums[1] - nums[0], nums[2], rel_tol=0,
                              abs_tol=FLOAT_EPS), f"{mid}/{label}: F4 delta mismatch")
    need(len(metrics) == 26 and seen == set(expected),
         "unreviewed/missing legacy metrics")
    need(dict(kind_counts) == AUDIT_KINDS, "evidence classes miscounted")
    need(noncausal_ids == ["maxroll.heroDetails.70"],
         "PvP invariant misrepresented as causal")
    need(delta_checks == 209, "did not check all 209 archived deltas")

    sets = audit.get("f5RoundingVectors")
    need(isinstance(sets, dict) and set(sets) == set(F5_COUNTS),
         "incomplete F5 vectors")
    source_tooltip_checks = 0
    source_interval_checks = 0
    pvp_observations = []
    for family, count in F5_COUNTS.items():
        entries = sets.get(family, []) if isinstance(sets, dict) else []
        need(isinstance(entries, list) and len(entries) == count,
             f"{family}: F5 group denominator mismatch")
        seen_ids = set()
        for v in entries if isinstance(entries, list) else []:
            if not isinstance(v, dict):
                errors.append(f"{family}: non-object F5 vector"); continue
            fixture = v.get("candidateId")
            need(isinstance(fixture, str) and bool(fixture) and
                 fixture not in seen_ids, f"{family}: duplicate fixture ID")
            seen_ids.add(fixture)
            if family == "pvpDamageReduction":
                raw = v.get("sourceRaw")
                display = v.get("sourceDisplay")
                need(finite_number(raw) and math.isclose(raw, 0.9199219,
                     abs_tol=1e-10) and display == "92.0%",
                     f"{fixture}: noncausal PvP reference changed")
                pvp_observations.append(raw)
                continue
            inputs = v.get("inputs")
            if not isinstance(inputs, list) or not inputs:
                errors.append(f"{family}/{fixture}: input vectors missing")
                continue
            if not all(isinstance(i, dict) and finite_number(i.get("pct"))
                       and isinstance(i.get("multiplicative"), bool)
                       and isinstance(i.get("source"), str) for i in inputs):
                errors.append(f"{family}/{fixture}: malformed tooltip inputs")
                continue
            try:
                value = tooltip_formula(family, inputs)
                expected_reported = v.get("reportedExpectedFromRoundedTooltips")
                actual = v.get("sourceRaw")
                if not finite_number(expected_reported) or not finite_number(actual):
                    errors.append(f"{family}/{fixture}: non-finite expected/actual")
                    continue
                need(math.isclose(value, expected_reported, rel_tol=0,
                                  abs_tol=FLOAT_EPS),
                     f"{family}/{fixture}: F5 reported tooltip arithmetic wrong")
                source_tooltip_checks += 1
                # A one-decimal tooltip value p represents [p-0.05, p+0.05] pp.
                # Compute conservative value bounds by evaluating both endpoints.
                half = ROUNDING_HALF_STEP_PP
                low = tooltip_formula(family, [
                    {**i, "pct": i["pct"] - half} for i in inputs])
                high = tooltip_formula(family, [
                    {**i, "pct": i["pct"] + half} for i in inputs])
                lo, hi = min(low, high), max(low, high)
                need(lo - FLOAT_EPS <= actual <= hi + FLOAT_EPS,
                     f"{family}/{fixture}: actual outside tooltip rounding bounds")
                source_interval_checks += 1
                need(finite_number(v.get("reportAbsoluteError")) and
                     math.isclose(abs(expected_reported - actual),
                                  v["reportAbsoluteError"], rel_tol=0,
                                  abs_tol=FLOAT_EPS),
                     f"{family}/{fixture}: F5 source error field inconsistent")
            except (TypeError, ValueError, ZeroDivisionError) as exc:
                errors.append(f"{family}/{fixture}: {exc}")
    need(source_tooltip_checks == 24 and source_interval_checks == 24 and
         len(pvp_observations) == 9, "incomplete F5 cross-checks")
    return {
        "status": "FAIL" if errors else "PASS_BOUNDED_SOURCE_AUDIT_ONLY",
        "errors": sorted(set(errors)),
        "legacyMetricsAudited": len(seen),
        "controlledF4": kind_counts.get("F4_BOUNDED_CONTROLLED", 0),
        "boundedF4F5": kind_counts.get("F4_F5_BOUNDED_MIXED", 0),
        "pvpNoncausalInvariant": kind_counts.get("F5_OBSERVED_INVARIANT_NONCAUSAL", 0),
        "f4ArithmeticDeltasChecked": delta_checks,
        "f5TooltipArithmeticChecked": source_tooltip_checks,
        "f5RawWithinTooltipRoundingInterval": source_interval_checks,
        "pvpInvarianceObservations": len(pvp_observations),
        "fullyVerified": 0,
        "maxrollGraphParity": "NOT_RUN",
        "approvedGoldenCount": 0,
        "unresolvedCausalBranches": "EXPLICIT_BY_METRIC",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("audit", type=Path)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        result = validate(json.loads(args.audit.read_text(encoding="utf-8")),
                          json.loads(args.catalog.read_text(encoding="utf-8")))
    except (ValueError, OSError, UnicodeError) as exc:
        result = {"status": "BLOCKED", "errors": [str(exc)]}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                               encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS_BOUNDED_SOURCE_AUDIT_ONLY" else (
        2 if result["status"] == "BLOCKED" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
