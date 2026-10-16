"""#107 CI-03: Maxroll-only structural contract gate. NOT a game formula evaluator."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

from d4_rulekit.schema_check import load_schema

PATCH = "3.2.1"
BUILD = "73552"
BASELINE = PATCH + "." + BUILD
SOURCE_ID = "maxroll-f1-rogue-3-2-1-73552"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _require(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def check_contract(document: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["contract must be a JSON object"]

    schema = load_schema()
    known_ops = {
        variant["properties"]["op"]["const"]
        for variant in schema["$defs"]["action"]["oneOf"]
    }
    _require(errors, document.get("contractVersion") == "1.0.0", "contractVersion mismatch")
    _require(errors, document.get("ruleSchemaVersion") == "1.0.0", "rule schema version mismatch")
    ops = document.get("operators")
    _require(errors, isinstance(ops, dict), "operators not a map")
    if isinstance(ops, dict):
        _require(errors, set(ops) == known_ops, "operators mismatch schema action discriminators")
        classes = set(document.get("eventModel", {}).get("actionCategories", []))
        for op, payload in ops.items():
            _require(errors, isinstance(payload, dict), f"operator {op}: malformed")
            if not isinstance(payload, dict):
                continue
            _require(errors, payload.get("class") in classes, f"operator {op}: invalid class")
            _require(errors, bool(payload.get("semantics")), f"operator {op}: semantics missing")
            _require(errors, payload.get("gameBehavior") == "requires_verified_rule_data",
                     f"operator {op}: unsourced behavior default")
        if isinstance(ops.get("modify_stat"), dict) and isinstance(ops.get("deal_damage"), dict):
            _require(errors, ops["modify_stat"]["class"] != ops["deal_damage"]["class"],
                     "modifier and damage event MUST be different action classes")

    known_phases = set(schema["$defs"]["mechanic"]["properties"]["phase"]["enum"])
    phases = document.get("phaseOrder")
    _require(errors, isinstance(phases, list) and len(phases) == len(known_phases) and
             len(set(phases)) == len(phases) and set(phases) == known_phases,
             "phase order mismatch")

    event = document.get("eventModel")
    _require(errors, isinstance(event, dict), "event model missing")
    if isinstance(event, dict):
        _require(errors, event.get("orderingEvidence") == "ENGINE_DETERMINISM_ONLY_NOT_MAXROLL_VERIFIED",
                 "event ordering not verified by Maxroll")
        _require(errors, event.get("collisionPolicy") ==
                 "modify_stat_does_not_emit_damage;deal_damage_schedules_damage_event",
                 "modifier and damage must remain distinct")
        _require(errors, event.get("priorityConflict") == "REJECT_EQUAL_PRIORITY_INCOMPATIBLE_OVERRIDE",
                 "conflicting overrides must fail closed")
        _require(errors, "DENY_UNDECLARED_RECURSION" in event.get("recursion", ""),
                 "unbounded recursion")
        _require(errors, event.get("triggeredInheritance") == "EXPLICIT_PER_RULE_ELSE_UNVERIFIED",
                 "unsupported trigger inheritance default")
        _require(errors, event.get("snapshotTiming") == "EXPLICIT_PER_RULE_ELSE_UNVERIFIED",
                 "unsupported snapshot default")
        _require(errors, {"SKILL_CAST", "SKILL_TRIGGERED", "DAMAGE_HIT", "PERIODIC_TICK"}
                 <= set(event.get("distinctEvents", [])), "event identities missing")

    baseline = document.get("patchBaseline", {})
    _require(errors, isinstance(baseline, dict), "patch baseline missing")
    if isinstance(baseline, dict):
        _require(errors, baseline.get("gameVersion") == PATCH and baseline.get("buildNumber") == BUILD,
                 "owner pinned Maxroll baseline mismatch")
        _require(errors, baseline.get("sourceId") == SOURCE_ID, "baseline source mismatch")
        _require(errors, baseline.get("policy") == "exact_patch_rule_selection",
                 "exact patch selection required")
        _require(errors, baseline.get("authority") == "OWNER_APPROVED_MAXROLL_BASELINE_2026_10_16",
                 "baseline approval missing")

    registry = document.get("provenance", {}).get("sourceRegistry")
    _require(errors, isinstance(registry, list) and bool(registry), "source registry missing")
    if isinstance(registry, list):
        ids = [v.get("id") for v in registry if isinstance(v, dict)]
        _require(errors, len(ids) == len(registry) and len(ids) == len(set(ids)),
                 "duplicate/malformed sources")
        for item in registry:
            if not isinstance(item, dict):
                continue
            _require(errors, item.get("kind") == "maxroll_ui_observation" and
                     item.get("id") == SOURCE_ID and
                     item.get("gameVersion") == PATCH and item.get("buildNumber") == BUILD and
                     isinstance(item.get("url"), str) and
                     item["url"].startswith("https://maxroll.gg/d4/planner/") and
                     item.get("status") == "UI_OBSERVED_ONLY" and
                     item.get("formulaEvidence") == "NONE_F1_READ_ONLY" and
                     bool(item.get("captureEvidence")),
                     "source must be bounded Maxroll F1 UI observation (not official formula)")

    _require(errors, document.get("aggregationPolicies") == {},
             "active calculation formula requires separate Maxroll causal evidence; no synthetic/legacy promotions")
    _require(errors, document.get("interactions") ==
             {"generic_stack": {"mode": "REQUIRES_RULE_EVIDENCE", "status": "UNVERIFIED"}},
             "unverified legacy interactions must not be active")

    policy = document.get("referencePolicy")
    _require(errors, isinstance(policy, dict), "Maxroll reference policy missing")
    if isinstance(policy, dict):
        _require(errors, policy.get("oracle") == "MAXROLL_ONLY", "oracle must be Maxroll")
        _require(errors, policy.get("pinnedGamePatch") == PATCH and
                 policy.get("pinnedGameBuild") == BUILD, "Maxroll policy patch mismatch")
        _require(errors, policy.get("approvedGoldenCount") == 0 and
                 policy.get("maxrollParity") == "BLOCKED_PENDING_COMPLETE_INPUT_AND_INDEPENDENT_GOLDEN",
                 "fake golden/parity promotion")
        _require(errors, policy.get("historicalSources") == "NOT_ACTIVE" and
                 policy.get("numericFallback") == "FORBIDDEN", "historical source or numeric fallback enabled")

    unknown = document.get("unknownPolicy")
    _require(errors, isinstance(unknown, dict) and
             unknown.get("missingEvidence") == "UNVERIFIED" and
             unknown.get("ambiguousOverride") == "CONTRACT_FAIL" and
             unknown.get("unverifiedSnapshot") == "UNVERIFIED" and
             unknown.get("unverifiedProcInheritance") == "UNVERIFIED" and
             unknown.get("numericFallback") == "FORBIDDEN",
             "fail closed unknown policy violated")
    return sorted(set(errors))


def evaluate_reference(vector: dict, contract: dict):
    """Fail closed. A candidate Maxroll UI value is not an approved numeric formula."""
    raise ValueError("numeric Maxroll references require independently reviewed golden and #108 parity gate")


def check_references(document: Any, contract: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["reference manifest must be object"]
    _require(errors, document.get("referenceSetVersion") == "2.0.0",
             "reference version mismatch")
    _require(errors, document.get("oracle") == "MAXROLL_ONLY", "reference is not Maxroll")
    _require(errors, document.get("baseline") == BASELINE and
             document.get("gamePatch") == PATCH and document.get("gameBuild") == BUILD,
             "reference patch/build mismatch")
    _require(errors, document.get("sourceId") == SOURCE_ID, "reference source mismatch")
    _require(errors, document.get("sourceEvidence") ==
             "https://github.com/Synclab-VN-dev/StreamOps/issues/106#issuecomment-6196291714",
             "independent capture evidence missing")
    _require(errors, document.get("fixtureUrl") == "https://maxroll.gg/d4/planner/1g1any0x#3",
             "fixture URL mismatch")
    fingerprint = document.get("fixtureFingerprint")
    _require(errors, isinstance(fingerprint, str) and bool(_SHA256.fullmatch(fingerprint)),
             "invalid fixture fingerprint")
    _require(errors, document.get("candidateVisibleMetricCount") == 50 and
             document.get("candidateVisibleMetricCount") ==
             contract.get("referencePolicy", {}).get("candidateMetrics"),
             "captured fixture count mismatch")
    _require(errors, document.get("approvedGoldenCount") == 0 and
             document.get("referenceStatus") == "CANDIDATE_ONLY_INPUT_PARTIAL" and
             document.get("maxrollParity") == "BLOCKED_NO_APPROVED_GOLDEN" and
             document.get("vectors") == [],
             "unreviewed candidate was promoted into active Maxroll golden")
    return sorted(set(errors))


def report_files(contract_path: Path, references_path: Path) -> dict:
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        references = json.loads(references_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        return {"status": "BLOCKED", "errors": [str(exc)], "maxrollParity": "NOT_TESTED"}
    errors = check_contract(contract)
    if not errors:
        errors += check_references(references, contract)
    return {
        "gate": "CI-03_EXECUTION_CONTRACT_ONLY",
        "status": "PASS" if not errors else "FAIL",
        "contractVersion": contract.get("contractVersion"),
        "baselinePatch": contract.get("patchBaseline", {}).get("gameVersion"),
        "baselineBuild": contract.get("patchBaseline", {}).get("buildNumber"),
        "oracle": "MAXROLL_ONLY",
        "sourceCount": len(contract.get("provenance", {}).get("sourceRegistry", [])),
        "candidateVisibleMetricCount": references.get("candidateVisibleMetricCount"),
        "approvedGoldenCount": references.get("approvedGoldenCount"),
        "referenceCount": len(references.get("vectors", [])),
        "maxrollParity": "BLOCKED_NO_APPROVED_GOLDEN",
        "gameAccuracy": "NOT_VERIFIED_BY_CI03",
        "errors": sorted(set(errors)),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="d4-rulekit-execution-check")
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--references", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    result = report_files(args.contract, args.references)
    content = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(content, encoding="utf-8")
    print(content, end="")
    return {"PASS": 0, "FAIL": 1, "BLOCKED": 2}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
