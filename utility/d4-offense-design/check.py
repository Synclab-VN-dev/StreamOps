"""Issue #106: versioned Offensive design CI gate (not a Diablo IV combat engine).

All numerical fixtures are synthetic. Maxroll trace claims are inventory/provenance
only; no synthetic output is promoted as verified in-game DPS.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent

ALLOWED_STATUSES = {
    "VERIFIED_VECTOR_SCOPED", "RUNTIME_OBSERVED", "SOURCE_OBSERVED",
    "OFFICIAL_RULE_SPECIFIC", "HISTORICAL_ONLY", "SYNTHETIC_ONLY",
    "UNKNOWN", "BLOCKED_INVALID_FIXTURE"
}
REQUIRED_GROUPS = {
    "direct", "buckets", "skill", "critical", "trigger",
    "periodic", "state", "timing", "target"
}
NUMERIC_OPERATIONS = {
    "additive_factor", "multiply_factors", "crit_expected",
    "multihit_expected", "proc_expected", "periodic_ticks",
    "duration_weighted", "stack_factor", "mitigated_damage"
}
REQUIRED_VECTOR_OPERATIONS = NUMERIC_OPERATIONS | {"event_order", "guard"}
GUARD_RESULTS = {
    "UNBOUNDED_TRIGGER_RECURSION": "BLOCKED",
    "PATCH_MISMATCH": "BLOCKED",
    "UNKNOWN_SNAPSHOT": "UNVERIFIED",
    "MISSING_DPS_ORACLE": "UNVERIFIED"
}

def dec(value):
    if isinstance(value, bool):
        raise ValueError("booleans are not numeric coefficients")
    d = Decimal(str(value))
    if not d.is_finite():
        raise ValueError("non-finite coefficient")
    return d

def fail(errors, test, message):
    if not test:
        errors.append(message)

def source_ids(document):
    return {entry["id"] for entry in document["sources"]}

def check_inventory(document):
    errors = []
    fail(errors, document.get("inventoryVersion") == "0.1.0", "inventory version")
    fail(errors, document.get("issue") == 106, "issue identity")
    fail(errors, document.get("scope") == "OFFENSIVE_DESIGN_ONLY_NO_SIMULATOR", "scope changed")
    policy = document.get("patchPolicy", {})
    fail(errors, policy.get("designReference") == "3.2.3", "baseline patch")
    fail(errors, policy.get("maxrollObserved") == "3.2.1.73552", "Maxroll evidence patch")
    fail(errors, policy.get("crossPatchPromotion") == "BLOCKED", "cross-patch guard")
    fail(errors, policy.get("missingMechanic") == "UNKNOWN_NO_NUMERIC_FALLBACK",
         "unknown mechanic must fail closed")
    sources = document.get("sources", [])
    mechanics = document.get("mechanics", [])
    fail(errors, isinstance(sources, list) and len(sources) >= 5, "sources incomplete")
    fail(errors, isinstance(mechanics, list) and len(mechanics) >= 15, "mechanic inventory incomplete")
    if not isinstance(sources, list) or not isinstance(mechanics, list):
        return errors
    ids = [x.get("id") for x in sources if isinstance(x, dict)]
    fail(errors, len(ids) == len(sources) and len(set(ids)) == len(ids), "source ids malformed/duplicate")
    lookup = {x.get("id"): x for x in sources if isinstance(x, dict)}
    for source in sources:
        if not isinstance(source, dict):
            errors.append("invalid source record")
            continue
        fail(errors, bool(source.get("kind")) and bool(source.get("scope")) and
             isinstance(source.get("url"), str) and source["url"].startswith("https://"),
             "source without kind/scope/HTTPS URL: " + str(source.get("id")))
        fail(errors, source.get("kind") == "SYNTHETIC_DESIGN" or
             isinstance(source.get("patch"), str),
             "source without patch: " + str(source.get("id")))
    seen = set()
    groups = set()
    for item in mechanics:
        if not isinstance(item, dict):
            errors.append("invalid mechanic record")
            continue
        mid = item.get("id")
        fail(errors, isinstance(mid, str) and bool(mid) and mid not in seen, "duplicate/empty mechanic ID")
        seen.add(mid)
        groups.add(item.get("group"))
        status = item.get("status")
        fail(errors, status in ALLOWED_STATUSES, "invalid status " + str(mid))
        links = item.get("sourceIds")
        fail(errors, isinstance(links, list) and bool(links) and
             all(x in lookup for x in links), "missing source for " + str(mid))
        fail(errors, bool(item.get("designMeaning")) and bool(item.get("gap")) and
             item.get("downstream") in {"#108", "#109", "#110", "#111"},
             "missing limits or downstream owner: " + str(mid))
        if status in {"VERIFIED_VECTOR_SCOPED", "RUNTIME_OBSERVED", "SOURCE_OBSERVED",
                      "BLOCKED_INVALID_FIXTURE"}:
            fail(errors, item.get("patch") == "3.2.1.73552",
                 "runtime evidence wrongly promoted across patches: " + str(mid))
            fail(errors, isinstance(links, list) and any(
                lookup.get(x, {}).get("kind", "").startswith("AGENT_REPORTED") for x in links
            ), "runtime claim lacks actual trace reference: " + str(mid))
        if status == "SYNTHETIC_ONLY":
            fail(errors, item.get("patch") is None and "synthetic-design-106" in (links or []),
                 "synthetic item promoted as game policy: " + str(mid))
        if status == "HISTORICAL_ONLY":
            fail(errors, item.get("patch") not in {None, "3.2.3"},
                 "historical mechanics wrongly tagged 3.2.3: " + str(mid))
    fail(errors, groups >= REQUIRED_GROUPS, "missing mechanic taxonomy groups")
    return errors

def calculate(op, data):
    if op == "additive_factor":
        return Decimal(1) + sum((dec(v) for v in data["bonuses"]), Decimal(0))
    if op == "multiply_factors":
        out = Decimal(1)
        for value in data["factors"]:
            out *= dec(value)
        return out
    if op == "crit_expected":
        chance = dec(data["chance"])
        cap = dec(data["cap"])
        if cap < 0 or cap > 1 or chance < 0:
            raise ValueError("invalid crit cap/chance")
        return dec(data["base"]) * (Decimal(1) + min(chance, cap) * dec(data["extra"]))
    if op == "multihit_expected":
        chance = dec(data["hitChance"])
        if not 0 <= chance <= 1:
            raise ValueError("invalid hit chance")
        return dec(data["perHit"]) * dec(data["hits"]) * chance
    if op == "proc_expected":
        chance = dec(data["chance"])
        if not 0 <= chance <= 1:
            raise ValueError("invalid proc chance")
        return dec(data["base"]) + chance * dec(data["triggerDamage"])
    if op == "periodic_ticks":
        return dec(data["damagePerTick"]) * dec(data["ticks"])
    if op == "duration_weighted":
        uptime = dec(data["uptime"])
        if not 0 <= uptime <= 1:
            raise ValueError("invalid uptime")
        return dec(data["base"]) * (Decimal(1) + (dec(data["factor"]) - 1) * uptime)
    if op == "stack_factor":
        cap = dec(data["cap"])
        count = dec(data["stacks"])
        if min(cap, count) < 0:
            raise ValueError("negative stack count")
        return Decimal(1) + min(cap, count) * dec(data["perStack"])
    if op == "mitigated_damage":
        mitigation = dec(data["mitigation"])
        if not 0 <= mitigation <= 1:
            raise ValueError("invalid mitigation")
        return Decimal(0) if data["immune"] is True else dec(data["base"]) * (1 - mitigation)
    if op == "event_order":
        events = data["events"]
        if any(not isinstance(e["id"], str) for e in events):
            raise ValueError("invalid event id")
        return [x["id"] for x in sorted(events,
                key=lambda x: (dec(x["time"]), int(x["phase"]), x["id"]))]
    if op == "guard":
        guard = data["guard"]
        if guard not in GUARD_RESULTS:
            raise ValueError("unknown fail-closed guard")
        if guard == "PATCH_MISMATCH" and data.get("patch") == data.get("baseline"):
            raise ValueError("patch guard has matching versions")
        return None
    raise ValueError("unsupported vector op " + str(op))

def check_vectors(document):
    errors = []
    fail(errors, document.get("vectorSetVersion") == "0.1.0", "vector set version")
    fail(errors, document.get("patch") == "SYNTHETIC_UNVERSIONED", "synthetic version guard")
    fail(errors, document.get("gameAccuracy") == "NOT_GAME_VERIFIED", "numeric game truth overclaim")
    vectors = document.get("vectors", [])
    if not isinstance(vectors, list):
        return ["vectors must be list"]
    fail(errors, len(vectors) >= 20, "incomplete reference matrix")
    names = [x.get("id") for x in vectors if isinstance(x, dict)]
    fail(errors, len(names) == len(vectors) and len(set(names)) == len(names),
         "vector identifiers malformed or duplicated")
    ops = {v.get("op") for v in vectors if isinstance(v, dict)}
    fail(errors, ops >= REQUIRED_VECTOR_OPERATIONS, "missing required mechanics test groups")
    for v in vectors:
        if not isinstance(v, dict):
            errors.append("invalid vector")
            continue
        name = v.get("id")
        op = v.get("op")
        try:
            got = calculate(op, v["inputs"])
            status = (GUARD_RESULTS[v["inputs"]["guard"]] if op == "guard"
                      else "PASS_SYNTHETIC")
            if v.get("status") != status:
                errors.append(str(name) + ": status mismatch")
            if got is None:
                if v.get("expected") is not None:
                    errors.append(str(name) + ": fail-closed case has numeric expected")
            elif op == "event_order":
                if got != v.get("expected"):
                    errors.append(str(name) + ": event ordering mismatch")
            elif dec(v["expected"]) != got:
                errors.append(str(name) + ": independent arithmetic mismatch " +
                              str(got) + " != " + str(v.get("expected")))
        except (ValueError, KeyError, TypeError, InvalidOperation,
                ArithmeticError, IndexError) as exc:
            errors.append(str(name) + ": " + str(exc))
    return errors

def check_fixtures(document, source_ids_known):
    errors = []
    fail(errors, document.get("fixtureSetVersion") == "0.1.0", "fixture set version")
    fail(errors, document.get("patch") == "SYNTHETIC_UNVERSIONED", "fixture patch overclaim")
    fail(errors, document.get("gameAccuracy") == "NOT_GAME_VERIFIED", "fixture accuracy overclaim")
    fixtures = document.get("fixtures", [])
    if not isinstance(fixtures, list):
        return ["fixture list invalid"]
    expected_families = {"direct_skill", "proc_trigger", "buff_stack"}
    fail(errors, len(fixtures) >= 3, "too few fixtures")
    fail(errors, {x.get("family") for x in fixtures if isinstance(x, dict)} >=
         expected_families, "missing independent scenario family")
    for f in fixtures:
        if not isinstance(f, dict):
            errors.append("invalid fixture object")
            continue
        name = f.get("id")
        fail(errors, f.get("synthetic") is True and f.get("sourceIds") ==
             ["synthetic-design-106"] and "synthetic-design-106" in source_ids_known,
             str(name) + ": synthetic provenance mismatch")
        fail(errors, f.get("scenario") == "single-target" and
             isinstance(f.get("assumptions"), list) and bool(f["assumptions"]),
             str(name) + ": missing scenario/assumptions")
        try:
            p = f["input"]
            if f["family"] == "direct_skill":
                expected = dec(p["weaponAverage"]) * dec(p["rankCoefficient"]) * (
                    1 + dec(p["additive"]))
                for mult in p["multipliers"]:
                    expected *= dec(mult)
                observed = dec(f["expectedEventDamage"])
            elif f["family"] == "proc_trigger":
                if p["maxDepth"] != 1:
                    raise ValueError("proc fixture must bound depth")
                expected = dec(p["baseDamage"]) + dec(p["procChance"]) * dec(p["triggerDamage"])
                observed = dec(f["expectedDamageMean"])
            elif f["family"] == "buff_stack":
                effective = min(dec(p["stacks"]), dec(p["stackCap"]))
                on = 1 + effective * dec(p["perStackRatio"])
                uptime = dec(p["activeFraction"])
                expected = (dec(p["baseDamage"]) * dec(p["hitsPerSecond"]) *
                    dec(f["timeHorizonSeconds"]) * ((1 - uptime) + uptime * on))
                observed = dec(f["expectedDamageTotal"])
            else:
                raise ValueError("unsupported fixture family")
            if observed != expected:
                errors.append(str(name) + ": fixture arithmetic mismatch")
        except (KeyError, ValueError, TypeError, InvalidOperation, ArithmeticError) as exc:
            errors.append(str(name) + ": " + str(exc))
    return errors

def audit(inventory, fixtures, vectors):
    inventory_errors = check_inventory(inventory)
    source_refs = source_ids(inventory) if not inventory_errors else set()
    fixture_errors = check_fixtures(fixtures, source_refs)
    vector_errors = check_vectors(vectors)
    gates = {
        "CI-01": {"status": "PASS" if not inventory_errors else "FAIL",
                  "errors": inventory_errors},
        "CI-02": {"status": "PASS" if not (fixture_errors or vector_errors) else "FAIL",
                  "errors": sorted(fixture_errors + vector_errors)},
        "CI-03": {"status": "PASS" if not inventory_errors and not fixture_errors
                               and not vector_errors else "FAIL",
                  "errors": sorted(inventory_errors + fixture_errors + vector_errors)}
    }
    return {
        "issue": 106,
        "scope": "DESIGN_CONSISTENCY_ONLY_NOT_GAME_ACCURACY",
        "status": "PASS" if all(g["status"] == "PASS" for g in gates.values()) else "FAIL",
        "gates": gates,
        "counts": {"mechanicsEnumerated": len(inventory.get("mechanics", [])),
                   "syntheticFixtures": len(fixtures.get("fixtures", [])),
                   "syntheticVectors": len(vectors.get("vectors", [])),
                   "globalCoverageDenominator": "UNKNOWN",
                   "globalCoveragePercent": None},
        "ownerDesignApproval": "PENDING_MAN_01",
        "maxrollCrossPatchPromotion": "BLOCKED",
        "independentGameAccuracy": "NOT_VERIFIED"
    }

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def main(argv=None):
    parser = argparse.ArgumentParser(description="Issue 106 design-only consistency checker")
    parser.add_argument("--inventory", type=Path, default=HERE / "mechanics.json")
    parser.add_argument("--fixtures", type=Path, default=HERE / "fixtures.json")
    parser.add_argument("--vectors", type=Path, default=HERE / "vectors.json")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        report = audit(load(args.inventory), load(args.fixtures), load(args.vectors))
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        report = {"issue": 106, "status": "BLOCKED", "errors": [str(exc)],
                  "ownerDesignApproval": "PENDING_MAN_01"}
    message = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(message, encoding="utf-8")
    print(message, end="")
    return {"PASS": 0, "FAIL": 1, "BLOCKED": 2}[report["status"]]

if __name__ == "__main__":
    sys.exit(main())
