"""CI-03 machine-checkable contract and sourced reference regression.

This is NOT the game simulator or G2/G3/DPS verifier. No external network access.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
import sys
from typing import Any

from d4_rulekit.schema_check import load_schema


def _error(errors: list[str], condition: bool, label: str) -> None:
    if not condition:
        errors.append(label)


def check_contract(document: Any) -> list[str]:
    """Check consistency with the *actual* Rule DSL schema, never a copied operator list."""
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["contract must be a JSON object"]
    schema = load_schema()
    known_ops = {
        variant["properties"]["op"]["const"]
        for variant in schema["$defs"]["action"]["oneOf"]
    }
    actual_ops = document.get("operators")
    _error(errors, document.get("contractVersion") == "1.0.0", "contractVersion mismatch")
    _error(errors, document.get("ruleSchemaVersion") == "1.0.0", "rule schema version mismatch")
    _error(errors, isinstance(actual_ops, dict), "operators not a map")
    if isinstance(actual_ops, dict):
        _error(errors, set(actual_ops) == known_ops, "operators mismatch schema action discriminators")
        allowed_classes = set(document.get("eventModel", {}).get("actionCategories", []))
        for op, payload in actual_ops.items():
            _error(errors, isinstance(payload, dict) and payload.get("class") in allowed_classes,
                   f"operator {op}: unknown action class")
            _error(errors, isinstance(payload, dict) and bool(payload.get("semantics")),
                   f"operator {op}: missing semantics")
            _error(errors, isinstance(payload, dict) and payload.get("gameBehavior") ==
                   "requires_verified_rule_data", f"operator {op}: missing evidence guard")
        _error(errors, actual_ops.get("modify_stat", {}).get("class") !=
               actual_ops.get("deal_damage", {}).get("class"),
               "modifier and damage event MUST be different action classes")

    known_phases = set(schema["$defs"]["mechanic"]["properties"]["phase"]["enum"])
    phases = document.get("phaseOrder", [])
    _error(errors, isinstance(phases, list) and len(phases) == len(known_phases) and
           len(set(phases)) == len(phases) and set(phases) == known_phases,
           "phaseOrder must include every schema phase exactly once")

    event_model = document.get("eventModel", {})
    if not isinstance(event_model, dict):
        return errors + ["eventModel must be a map"]
    _error(errors, event_model.get("orderingEvidence") ==
           "ENGINE_DETERMINISM_ONLY_NOT_BLIZZARD_INTERNAL_ORDER",
           "ordering convention must not claim Blizzard event accuracy")
    _error(errors, event_model.get("collisionPolicy") ==
           "modify_stat_does_not_emit_damage;deal_damage_schedules_damage_event",
           "missing non-collision contract")
    _error(errors, event_model.get("priorityConflict") ==
           "REJECT_EQUAL_PRIORITY_INCOMPATIBLE_OVERRIDE",
           "override conflicts must fail closed")
    _error(errors, "DENY_UNDECLARED_RECURSION" in event_model.get("recursion", ""),
           "recursive triggering must deny by default")
    _error(errors, event_model.get("triggeredInheritance") == "EXPLICIT_PER_RULE_ELSE_UNVERIFIED",
           "trigger inheritance must not silently default")
    _error(errors, event_model.get("snapshotTiming") == "EXPLICIT_PER_RULE_ELSE_UNVERIFIED",
           "snapshot timing must not silently default")
    distinct = event_model.get("distinctEvents", [])
    _error(errors, isinstance(distinct, list) and
           {"SKILL_CAST", "SKILL_TRIGGERED", "DAMAGE_HIT", "PERIODIC_TICK"} <= set(distinct),
           "cast, triggered, hit and tick events must remain distinct")

    refs = document.get("provenance", {}).get("sourceRegistry", [])
    refs_valid = isinstance(refs, list) and all(isinstance(x, dict) for x in refs)
    _error(errors, refs_valid, "provenance registry invalid")
    source_ids = set()
    if refs_valid:
        source_ids = {x.get("id") for x in refs}
        _error(errors, len(source_ids) == len(refs), "duplicate source IDs")
        for ref in refs:
            _error(errors, ref.get("kind") == "official" and
                   isinstance(ref.get("url"), str) and
                   ref["url"].startswith("https://news.blizzard.com/en-us/article/") and
                   bool(ref.get("claim")) and bool(ref.get("scope")),
                   f"invalid evidence record {ref.get('id')}")
    _error(errors, document.get("patchBaseline", {}).get("gameVersion") == "3.2.3",
           "patch baseline mismatch")
    _error(errors, document.get("patchBaseline", {}).get("sourceId") in source_ids,
           "patch baseline missing source evidence")

    policies = document.get("aggregationPolicies")
    _error(errors, isinstance(policies, dict), "aggregationPolicies must be a map")
    if isinstance(policies, dict):
        _error(errors, policies.get("gear_damage_multiplier", {}).get("kind") ==
               "sum_then_factor", "gear multipliers must use sourced additive grouping")
        for key, value in policies.items():
            _error(errors, isinstance(value, dict) and
                   value.get("kind") in {"sum_then_factor", "product_of_factors",
                                        "additive_times_baseline"},
                   f"unsupported aggregation: {key}")
            ids = value.get("sourceIds", []) if isinstance(value, dict) else []
            _error(errors, bool(ids) and all(r in source_ids for r in ids),
                   f"aggregation {key} lacks source")
            if key.startswith("historical_"):
                _error(errors, value.get("status") == "HISTORICAL_ONLY_DO_NOT_APPLY_TO_3_2_3",
                       f"historical policy incorrectly promoted: {key}")
    interactions = document.get("interactions", {})
    if isinstance(interactions, dict):
        item = interactions.get("storm_shephard_2p_5p", {})
        _error(errors, item.get("mode") == "coexist_not_override" and
               item.get("sourceIds") == ["blizzard-storm-3-0-4"],
               "Storm Shephard effect requires specific sourced coexistence policy")
        _error(errors, interactions.get("generic_stack", {}).get("mode") ==
               "REQUIRES_RULE_EVIDENCE", "generic stack must not invent a default")
    else:
        errors.append("interactions must be a map")

    unknown = document.get("unknownPolicy", {})
    _error(errors, isinstance(unknown, dict) and
           unknown.get("missingEvidence") == "UNVERIFIED" and
           unknown.get("unverifiedSnapshot") == "UNVERIFIED" and
           unknown.get("unverifiedProcInheritance") == "UNVERIFIED" and
           unknown.get("numericFallback") == "FORBIDDEN" and
           unknown.get("ambiguousOverride") == "CONTRACT_FAIL",
           "unknown mechanic fallback must be fail-closed")
    return sorted(set(errors))


def evaluate_reference(vector: dict, contract: dict) -> tuple[str, str | None]:
    """Reference *contract* arithmetic, not actual in-game DPS calculation."""
    kind = vector["testType"]
    if kind == "unverified":
        return "UNVERIFIED", None
    if kind == "aggregation":
        policy = contract["aggregationPolicies"][vector["policyId"]]
        if policy["kind"] != "sum_then_factor" or vector["patch"] != "3.2.3":
            raise ValueError("unsupported patch/policy for this fixture")
        factor = Decimal(1) + sum((Decimal(x) for x in vector["values"]), Decimal(0))
        return "PASS_CONTRACT_ONLY", str(factor)
    if kind == "historical_arithmetic":
        policy = contract["aggregationPolicies"][vector["policyId"]]
        if policy["kind"] != "additive_times_baseline" or vector["patch"] != "1.2.0":
            raise ValueError("historical fixture must not be interpreted for 3.x")
        factor = (Decimal(1) + Decimal(vector["additive"])) * (
            Decimal(1) + Decimal(vector["baseline"]))
        return "PASS_HISTORICAL_ONLY", str(factor)
    if kind == "interaction":
        item = contract["interactions"][vector["interactionId"]]
        if item["mode"] != "coexist_not_override" or vector["patch"] != "3.0.4":
            raise ValueError("unverified interaction applicability")
        if sorted(vector["activeBonuses"]) != sorted(vector["expectedActive"]):
            raise ValueError("expected coexistence mismatch")
        return "PASS_RULE_SPECIFIC", None
    raise ValueError("unsupported testType; cannot produce numerical result")


def check_references(document: Any, contract: dict) -> list[str]:
    errors = []
    if not isinstance(document, dict) or document.get("baseline") != "3.2.3":
        return ["reference baseline mismatch"]
    if document.get("referenceSetVersion") != "1.0.0":
        return ["referenceSetVersion invalid"]
    vectors = document.get("vectors", [])
    if not isinstance(vectors, list) or len(vectors) < 4:
        return ["reference vector matrix incomplete"]
    names = [v.get("caseId") for v in vectors if isinstance(v, dict)]
    if len(set(names)) != len(vectors):
        errors.append("duplicate or malformed reference case")
    sources = {x["id"] for x in contract["provenance"]["sourceRegistry"]}
    for vector in vectors:
        if not isinstance(vector, dict):
            errors.append("malformed reference case")
            continue
        case = vector.get("caseId", "<unknown>")
        if not vector.get("sourceIds") or not set(vector["sourceIds"]) <= sources:
            errors.append(f"{case}: missing independent source")
        try:
            status, value = evaluate_reference(vector, contract)
            if status != vector.get("expectedStatus"):
                errors.append(f"{case}: expected status mismatch")
            expected = vector.get("expectedFactor")
            if expected is not None:
                if value is None or Decimal(value) != Decimal(expected):
                    errors.append(f"{case}: expected factor mismatch")
            elif value is not None:
                errors.append(f"{case}: a nonnumeric case generated a factor")
            if status == "UNVERIFIED" and value is not None:
                errors.append(f"{case}: unverified case leaked numeric result")
            if vector["testType"] == "aggregation":
                if not str(vector.get("coefficientsProvenance", "")).startswith("SYNTHETIC"):
                    errors.append(f"{case}: illustrative coefficients misrepresented")
        except (KeyError, ValueError, TypeError, ArithmeticError) as exc:
            errors.append(f"{case}: {exc}")
    return sorted(set(errors))


def report_files(contract_path: Path, references_path: Path) -> dict:
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        references = json.loads(references_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        return {"gate": "CI-03", "status": "BLOCKED", "errors": [str(exc)]}
    errors = check_contract(contract)
    if not errors:
        errors += check_references(references, contract)
    return {
        "gate": "CI-03_EXECUTION_CONTRACT_NOT_GAME_SIMULATION",
        "status": "PASS" if not errors else "FAIL",
        "contractVersion": contract.get("contractVersion"),
        "baselinePatch": contract.get("patchBaseline", {}).get("gameVersion"),
        "sourceCount": len(contract.get("provenance", {}).get("sourceRegistry", [])),
        "referenceCount": len(references.get("vectors", [])),
        "errors": errors,
        "gameAccuracy": "NOT_VERIFIED_BY_CI03",
    }


def main(argv: list[str] | None = None) -> int:
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
