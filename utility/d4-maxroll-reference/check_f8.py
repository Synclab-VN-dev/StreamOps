"""#106 source-inventory integrity gate. Never certifies a formula or Maxroll Graph parity."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

GROUP_IDS = {
    "summary": "900 901",
    "core": "279 108 109 110 111",
    "resistances": "2036494626 480 439 446 453 460 467 474",
    "offensive": "93 46 114 3 4 347 349 1 49 50 51 52 71041540 53 251 2 25 56 166 299",
    "defensive": "58 78 180 431 357 104 61",
    "utility": "81 286 80 92 152 181 367",
    "pvp": "70",
}
EXPECTED = {
    "maxroll.heroDetails." + suffix: group
    for group, suffixes in GROUP_IDS.items()
    for suffix in suffixes.split()
}
F5_VERIFIED = set(
    "900 279 108 109 110 111 480 93 46 114 3 4 1 58 180 431 357 104 61 "
    "81 286 80 92 181 367 70".split()
)
SHA = re.compile(r"^[0-9a-f]{64}$")


def validate(obj):
    errors = []

    def check(condition, message):
        if not condition:
            errors.append(message)

    if not isinstance(obj, dict):
        return {"status": "FAIL", "errors": ["catalog must be an object"]}

    check(obj.get("catalogVersion") == "1.1.0", "wrong inventory version")
    check(obj.get("scope") == "SOURCE_EVIDENCE_INVENTORY_ONLY", "not source-only")
    check(obj.get("oracle") == "MAXROLL_ONLY", "wrong oracle")
    baseline = obj.get("baseline") or {}
    check((baseline.get("gamePatch"), baseline.get("gameBuild"),
           baseline.get("classId"), baseline.get("ownerPinned"))
          == ("3.2.1", "73552", "rogue", True), "patch/class pin mismatch")
    fixture = obj.get("fixture") or {}
    for field in ("inputSnapshotSha256", "snapshotFingerprintSha256",
                  "snapshotOutputSha256"):
        check(bool(SHA.fullmatch(str(fixture.get(field, "")))),
              "invalid fixture hash: " + field)
    check(fixture.get("inputCompleteness") == "PARTIAL",
          "cannot promote incomplete F1 inputs")
    check(fixture.get("referenceUrl") == "https://maxroll.gg/d4/planner/1g1any0x#3",
          "fixture reference changed")
    check(fixture.get("sourceRawCount") == 50 and
          fixture.get("sourceRenderedCount") == 50, "source rows not full")
    provenance = obj.get("provenance") or {}
    check(provenance.get("sourceRepository") == "Synclab-VN-dev/synclab-agent" and
          provenance.get("sourceCommit") ==
          "8fdf59a988b0425e789248a5f1898ef67b27314d",
          "source evidence pin changed")
    check(provenance.get("sourceReview") == "PROVISIONAL_UNTIL_PER_METRIC_AUDIT",
          "unapproved audit promotion")
    check(provenance.get("sourceF4Commit") ==
          "3ae928e5701d2de9ac995973b39e9b91d789f4bb",
          "F4 dependency source pin changed")
    coverage = obj.get("coverage") or {}
    check(coverage.get("denominator") == 50 and
          coverage.get("metricRowsCataloged") == 50, "bad denominator")
    check(coverage.get("sourceGroupCounts") ==
          {group: len(ids.split()) for group, ids in GROUP_IDS.items()},
          "group denominator changed")
    check(coverage.get("fullFormulaVerified") == 0 and
          coverage.get("boundedVerified") == 27 and
          coverage.get("partial") == 23, "unreviewed formula promotion")
    check(coverage.get("fullMaxrollParity") == "NOT_RUN" and
          coverage.get("approvedGoldenCount") == 0, "false parity/golden")
    policy = obj.get("policy") or {}
    check(policy.get("sourceFormulaStatusSeparateFromGraphParity") is True and
          policy.get("unknownNeverZero") is True, "unsafe policy")

    metrics = obj.get("metrics")
    check(isinstance(metrics, list), "metrics must be list")
    metrics = metrics if isinstance(metrics, list) else []
    ids = [m.get("metricId") for m in metrics if isinstance(m, dict)]
    check(len(metrics) == 50 and len(ids) == 50, "50 distinct metrics required")
    check(len(set(ids)) == len(ids), "duplicate metricId")
    check(set(ids) == set(EXPECTED), "missing/extra canonical F5 IDs")
    statuses = Counter()
    legacy = Counter()
    per_group = Counter()
    source_mechanic_count = 0
    f4_counts = Counter()
    for m in metrics:
        if not isinstance(m, dict):
            errors.append("malformed metric"); continue
        mid = m.get("metricId")
        group = m.get("group")
        check(group == EXPECTED.get(mid), f"{mid}: ID/group mismatch")
        check(isinstance(m.get("label"), str) and bool(m.get("label")),
              f"{mid}: no label")
        per_group[group] += 1
        old = m.get("legacyF5Status")
        legacy[old] += 1
        suffix = str(mid).removeprefix("maxroll.heroDetails.")
        check(old == ("VERIFIED" if suffix in F5_VERIFIED else "PARTIAL"),
              f"{mid}: historical status overwritten")
        check(bool(m.get("legacyEvidenceBasis")), f"{mid}: missing F5 basis")
        status = m.get("formulaVerificationStatus")
        statuses[status] += 1
        check(status == ("BOUNDED_VERIFIED" if
                          (suffix in F5_VERIFIED or suffix == "446") else "PARTIAL"),
              f"{mid}: not supported by bounded evidence")
        expected_review = ("F7_2_INDEPENDENTLY_REVIEWED_DISPLAY_BOUNDED"
                           if suffix == "446"
                           else "PROVISIONAL_PENDING_PER_METRIC_AUDIT")
        check(m.get("reviewStatus") == expected_review,
              f"{mid}: review status false promotion")
        check(m.get("sourceObservation") == "F5_AGENT_CDP_REPORTED_NOT_GOLDEN",
              f"{mid}: missing source origin")
        raw = m.get("sourceReportedRaw")
        check(raw is None or (isinstance(raw, str) and bool(raw)),
              f"{mid}: invalid source raw")
        display = m.get("sourceReportedDisplay")
        check(display is None or isinstance(display, str),
              f"{mid}: invalid display")
        check(m.get("knownInputs") == [] and m.get("applicableEffects") == []
              and m.get("dependencies") == [] and m.get("orderStatus") == "UNKNOWN",
              f"{mid}: invented inputs, dependencies, or ordering")
        check(m.get("goldenStatus") == "NOT_APPROVED" and
              m.get("maxrollGraphParity") == "NOT_RUN",
              f"{mid}: unsupported golden/parity promotion")
        check(isinstance(m.get("openGaps"), list) and bool(m.get("openGaps")),
              f"{mid}: unresolved branches hidden")
        source_mechanic = m.get("sourceReportedMechanic")
        if source_mechanic is not None:
            source_mechanic_count += 1
            check(isinstance(source_mechanic, dict) and
                  source_mechanic.get("kind") ==
                  "F5_AGENT_HYPOTHESIS_NOT_RULE_DATA" and
                  isinstance(source_mechanic.get("runtimeExpression"), str) and
                  isinstance(source_mechanic.get("candidateExpression"), str) and
                  isinstance(source_mechanic.get("verificationMode"), str),
                  f"{mid}: unreviewed source mechanic misrepresented")
        f4 = m.get("f4ObservedDependencies")
        check(isinstance(f4, dict), f"{mid}: missing F4 dependency trace")
        if isinstance(f4, dict):
            old_f4 = f4.get("f4HistoricalStatus")
            f4_counts[old_f4] += 1
            check(old_f4 in {"VERIFIED", "PARTIAL", "BLOCKED"},
                  f"{mid}: invalid F4 history")
            check(f4.get("provenance") ==
                  "F4_DISPOSABLE_ROGUE_FIXTURE_SOURCE_OBSERVED_NOT_GOLDEN" and
                  f4.get("sourceReview") ==
                  "https://github.com/Synclab-VN-dev/StreamOps/issues/106#issuecomment-6208057744",
                  f"{mid}: unsupported F4 source promotion")
            check(isinstance(f4.get("runtimeExpression"), (str, type(None))) and
                  isinstance(f4.get("reportedFormulaCandidate"), (str, type(None))) and
                  isinstance(f4.get("directDependencies"), list) and
                  isinstance(f4.get("functionNodes"), list) and
                  isinstance(f4.get("contributorDomains"), list) and
                  isinstance(f4.get("unresolved"), list) and
                  isinstance(f4.get("discriminatingVectorCount"), int),
                  f"{mid}: missing F4 dependency evidence")
            if m.get("legacyEvidenceBasis") == "PRESERVED_F4_BOUNDED_EVIDENCE":
                check(old_f4 == "VERIFIED", f"{mid}: lost F4 bounded path proof")
        candidate = m.get("formulaCandidate")
        if suffix == "446":
            check(isinstance(candidate, dict) and
                  candidate.get("testedPatch") == "3.2.1.73552" and
                  candidate.get("testedClass") == "rogue" and
                  candidate.get("testedLevels") == [50, 60, 70] and
                  candidate.get("observedDisplayMatches") == 67 and
                  candidate.get("verifiedExactHelper") is False and
                  candidate.get("provenExplicitCap") is False,
                  "Fire DR hypothesis promoted beyond F7.2 evidence")
        else:
            check(candidate is None, f"{mid}: unsupported formula candidate")
    check(source_mechanic_count == 28, "F5 candidate inventory lost")
    check(f4_counts == {"VERIFIED": 22, "PARTIAL": 16, "BLOCKED": 12},
          "F4 historical coverage changed")
    check(legacy == {"VERIFIED": 26, "PARTIAL": 24}, "F5 history changed")
    check(statuses == {"BOUNDED_VERIFIED": 27, "PARTIAL": 23},
          "taxonomy counts changed")
    check(dict(per_group) == coverage.get("sourceGroupCounts"),
          "metric group counts diverge")
    return {
        "status": "FAIL" if errors else "PASS_SOURCE_INVENTORY_ONLY",
        "errors": sorted(set(errors)),
        "catalogedMetricIds": len(set(ids)),
        "legacyF5Counts": dict(legacy),
        "proposedFormulaStatusCounts": dict(statuses),
        "groupCounts": dict(per_group),
        "independentGraphParity": "NOT_RUN",
        "approvedGoldenCount": 0,
        "independentPerMetricAudit": "PENDING_FOR_26_LEGACY_BOUNDED",
        "sourceMechanicAnnotationsNotVerified": source_mechanic_count,
        "sourceF4DependencyRowsNotGolden": sum(f4_counts.values()),
        "f4LegacyEvidenceCounts": dict(f4_counts),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        result = validate(json.loads(args.catalog.read_text(encoding="utf-8")))
    except (OSError, ValueError, UnicodeError) as exc:
        result = {"status": "BLOCKED", "errors": [str(exc)]}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                               encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS_SOURCE_INVENTORY_ONLY" else 2 if result["status"] == "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
