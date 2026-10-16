"""Offline F2 Maxroll research catalog gate; never reports numeric parity PASS."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re

SHA = re.compile(r"^[0-9a-f]{64}$")
GRADES = {"RUNTIME_REPORTED", "CAUSAL_BOUNDED_REUSED_VECTORS",
          "ADDITIVE_BOUNDED_MULTIPLICATIVE_UNVERIFIED"}

def validate(c):
    errors = []
    def need(ok, why):
        if not ok:
            errors.append(why)
    if not isinstance(c, dict):
        return {"status": "FAIL", "errors": ["not an object"]}
    need(c.get("catalogVersion") == "1.0.0", "catalogVersion mismatch")
    need(c.get("oracle") == "MAXROLL_ONLY", "non-Maxroll reference")
    need(c.get("status") == "F2_RESEARCH_CANDIDATES_NOT_GOLDEN", "candidate promotion")
    baseline = c.get("baseline") or {}
    need(baseline.get("gamePatch") == "3.2.1" and
         baseline.get("gameBuild") == "73552" and
         baseline.get("ownerPinned") is True, "baseline mismatch")
    fixture = c.get("fixture") or {}
    need(fixture.get("classId") == "rogue" and
         fixture.get("variant") == "#3", "fixture mismatch")
    need(bool(SHA.fullmatch(str(fixture.get("inputSnapshotSha256", "")))), "fixture hash invalid")
    need(fixture.get("inputCompleteness") == "PARTIAL", "unsupported COMPLETE promotion")
    need(fixture.get("socketsResolved") == 4 and fixture.get("socketsTotal") == 13,
         "socket completeness mismatch")
    inv = c.get("inventory") or {}
    groups = inv.get("groups") or {}
    expected = {"summary": 2, "core": 5, "resistances": 8,
                "offensive": 20, "defensive": 7, "utility": 7, "pvp": 1}
    need(groups == expected and inv.get("visibleTotal") == 50
         and sum(groups.values()) == 50, "invented fixture denominator")
    policy = c.get("parity") or {}
    need(policy.get("approvedGoldenCount") == 0 and
         policy.get("maxrollParity") == "NOT_TESTED" and
         policy.get("numericFallback") == "FORBIDDEN", "false Golden/parity claim")
    sources = c.get("evidenceRegistry") or {}
    need("F2_106" in sources and
         sources.get("F2_106", {}).get("url") == c.get("f2Source") and
         sources.get("F2_106", {}).get("rawTraceIndependentlyReviewed") is False,
         "unreviewed trace misrepresented")
    rows = c.get("metrics")
    need(isinstance(rows, list) and len(rows) > 0, "no catalog metrics")
    seen = set()
    counts = {}
    for item in rows if isinstance(rows, list) else []:
        if not isinstance(item, dict):
            errors.append("invalid metric"); continue
        mid = item.get("id")
        group = item.get("group")
        need(isinstance(mid, str) and mid.startswith(str(group) + "."),
             "invalid metric ID/group")
        need(mid not in seen, "duplicate metric ID")
        seen.add(mid)
        counts[group] = counts.get(group, 0) + 1
        need(group in expected and counts[group] <= expected.get(group, 0),
             "metric exceeds fixture group count")
        need(item.get("rawOrigin") == "MAXROLL_CDP_AGENT_REPORT" and
             isinstance(item.get("rawValue"), str), "invalid raw origin/value")
        need(isinstance(item.get("displayValue"), str) and
             item.get("formatPolicy") == "OBSERVED_SAMPLE_ONLY", "unverified format promotion")
        need(item.get("evidenceGrade") in GRADES and
             item.get("evidenceId") == "F2_106", "unreviewed source promotion")
        need(item.get("formulaStatus") == "UNKNOWN" and
             item.get("goldenStatus") == "NOT_APPROVED", "unsupported formula/golden promotion")
        for key in ("inputs", "effects", "dependencies"):
            need(item.get(key) == [], "invented dependency or effect")
        need(item.get("ordering") == "UNKNOWN", "unverified ordering")
        candidate = item.get("formulaCandidate")
        if candidate is not None:
            need(isinstance(candidate, dict) and
                 candidate.get("status") in {
                     "SINGLE_FIXTURE_EQUALITY_NOT_CAUSAL",
                     "ONE_FIXTURE_ARITHMETIC_EXPLANATION_NOT_CAUSAL"},
                 "candidate promoted to causal formula")
    need(len(seen) < 50, "partial F2 research presented as full fixture formula coverage")
    return {"status": "FAIL" if errors else "PASS_RESEARCH_CATALOG_ONLY",
            "errors": sorted(set(errors)), "catalogedMetrics": len(seen),
            "visibleFixtureMetrics": 50, "approvedGoldenCount": 0,
            "maxrollParity": "NOT_TESTED", "formulaParity": "NOT_TESTED",
            "counts": counts}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        result = validate(json.loads(args.catalog.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, ValueError) as exc:
        result = {"status": "BLOCKED", "errors": [str(exc)]}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS_RESEARCH_CATALOG_ONLY" else 1

if __name__ == "__main__":
    raise SystemExit(main())
