"""#110: class/fixture-scoped working-model evaluator, independent of Golden.

A numeric partial subtotal is useful for debugging, but is never silently
promoted to a full Character Stat Actual. Unseen effects are not treated as
zero. The registry is open for future contributor strategies without changing
the aggregator, metric rule list, or independent Golden comparator.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol
import argparse
import json
import math
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import graph
import golden_candidate_eval as existing
import primary_paragon_source
import source_roll_index

PRIMARY = {
    "Strength": "maxroll.heroDetails.108",
    "Intelligence": "maxroll.heroDetails.109",
    "Willpower": "maxroll.heroDetails.110",
    "Dexterity": "maxroll.heroDetails.111",
}
LEVEL = "maxroll.heroDetails.279"
PRIMARY_GAPS = (
    "CLASS_BASE_AND_LEVEL", "ALTARS", "ITEM_NID_TO_CORE_STAT",
    "SOCKET_CHARM_AND_SKILL", "PARAGON_STACKING_AND_GLYPH_INTERACTIONS",
)
F3_PRIMARY = {name: "Floor(" + name + "_Total)" for name in PRIMARY}
PERCENT_DAMAGE_IDS = ("maxroll.heroDetails.2", "maxroll.heroDetails.25")


from contributor_contract import SourceContribution


class ContributorStrategy(Protocol):
    family: str
    def produce(self, source: dict, paragon: dict, rolls: dict) -> tuple[SourceContribution, ...]: ...


class ProfileLevel:
    family = "BUILD_LEVEL"

    def produce(self, source, paragon, rolls):
        # Reads independent build input and verifies patch/class/fingerprint.
        # No Expected / Golden reference is accessible here.
        profile = source["currentReadOnlyPublicProfile"]
        return (SourceContribution(LEVEL, self.family, profile["level"],
                                   "build.level", "MAXROLL_PUBLIC_BUILD_INPUT"),)


class ParagonFlatTooltip:
    family = "PARAGON_UI_FLAT"

    def produce(self, source, paragon, rolls):
        return tuple(SourceContribution(
            PRIMARY[row["stat"]], self.family, row["flat"],
            "paragon/active-node/%d/line/%d" % (row["nodeIndex"], row["line"]),
            row["grade"]) for row in paragon["contributions"])


class ModelRegistry:
    """Pure and injectable; strategies have no DB, Golden, or output IO."""

    def __init__(self, strategies):
        self._strategies = {}
        for strategy in strategies:
            family = strategy.family
            graph.reject(type(family) is str and family and family not in self._strategies,
                         "DUPLICATE_OR_EMPTY_CONTRIBUTOR_FAMILY")
            self._strategies[family] = strategy

    def contributions(self, source, paragon, rolls, allowed_ids):
        bucket = {}
        for family, strategy in self._strategies.items():
            result = strategy.produce(source, paragon, rolls)
            graph.reject(type(result) is tuple, "STRATEGY_RESULT_NOT_IMMUTABLE")
            for row in result:
                graph.reject(isinstance(row, SourceContribution) and
                    row.family == family and row.metric_id in allowed_ids and
                    type(row.value) in (int, float) and math.isfinite(row.value) and
                    type(row.source_id) is str and bool(row.source_id) and
                    type(row.provenance) is str and bool(row.provenance),
                    "CONTRIBUTOR_PROTOCOL_VIOLATION")
                key = (family, row.source_id)
                graph.reject(key not in bucket, "DUPLICATE_CONTRIBUTOR_SOURCE")
                bucket[key] = row
        by_metric = {}
        for row in bucket.values():
            by_metric.setdefault(row.metric_id, []).append(row)
        return by_metric


def evaluate(source, inventory, targets, f3map, paragon_witness, roll_witness,
             registry=None):
    """Compute as far as captured evidence permits, without loading Expected."""
    existing.metadata_fixture(inventory)
    env = existing.normalized_source(source, inventory)
    graph.reject(inventory["fixtureId"] == "DEV-00" and
        inventory["classId"] == "rogue" and inventory["gamePatch"] == "3.2.1.73552",
        "WORKING_MODEL_ROGUE_DEV00_ONLY")
    existing.reject_expected(targets)
    existing.reject_expected(f3map)
    paragon = primary_paragon_source.capture(paragon_witness)
    rolls = source_roll_index.index(roll_witness)
    for w in (paragon, rolls):
        graph.reject(w["fixtureId"] == inventory["fixtureId"] and
            w["classId"] == inventory["classId"] and
            w.get("patch") == inventory["gamePatch"] and
            w.get("inputFingerprintSha256", w.get("sourceFingerprint")) ==
            inventory["inputFingerprintSha256"],
            "MIXED_SOURCE_SCOPE_OR_PATCH")
    graph.reject(targets.get("schema") == "maxroll-stat-verification-target-v1"
                 and targets.get("goalUniqueMetricIds") == 20
                 and targets.get("initialFixture") == "DEV-00"
                 and targets.get("initialClassId") == "rogue"
                 and targets.get("patch") == inventory["gamePatch"],
                 "INVALID_TARGET_MANIFEST")
    desired = targets["metrics"]
    source_rules = f3map.get("formulas")
    graph.reject(type(desired) is list and len(desired) == 20 and
                 type(source_rules) is list and len(source_rules) >= 20 and
                 len({x["metricId"] for x in desired}) == 20,
                 "INVALID_TARGET20_RULE_COVERAGE")
    rules = {r["metricId"]: r for r in source_rules}
    known = {r["metricId"]: r for r in inventory["metrics"]}
    for record in desired:
        mid = record["metricId"]
        graph.reject(mid in rules and mid in known and
                     record["label"] == known[mid]["label"] ==
                     rules[mid]["label"], "TARGET_SOURCE_RULE_ID_MISMATCH")
    graph.reject(rules[LEVEL]["sourceExpression"] == "Level", "LEVEL_RULE_DRIFT")
    for name, mid in PRIMARY.items():
        graph.reject(rules[mid]["sourceExpression"] == F3_PRIMARY[name],
                     "PRIMARY_FORMULA_SOURCE_DRIFT")
    # Registry is the OCP extension seam. No downstream case switch per strategy.
    from paragon_damage_contributors import ParagonPercentDamage
    registry = registry if registry is not None else ModelRegistry(
        (ProfileLevel(), ParagonFlatTooltip(), ParagonPercentDamage()))
    paragon_source_view = {**paragon, "sourceActiveNodes":tuple(paragon_witness["nodes"])}
    contributions = registry.contributions(source, paragon_source_view, rolls, set(known))
    rows = []
    for entry in desired:
        mid = entry["metricId"]
        observed = contributions.get(mid, [])
        families = {c.family for c in observed}
        gap = [] if mid == LEVEL else (
            [g for g in PRIMARY_GAPS if g not in families]
            if mid in PRIMARY.values() else
            ["PARAGON_PERCENT_NOT_FULL_RUNTIME_BUCKET",
             "EQUIPMENT_SKILL_CHARM_EFFECTS_UNMAPPED",
             "MULTIPLICATIVE_OR_CONDITIONAL_STACKING_UNKNOWN"]
            if mid in PERCENT_DAMAGE_IDS else
            ["NO_MAPPED_RUNTIME_CONTRIBUTOR:" + d for d in
             rules[mid]["intermediateVariables"]] or
            ["NO_EXECUTABLE_RUNTIME_FUNCTION"])
        if observed:
            subtotal = sum(c.value for c in observed)
            candidate = int(math.floor(subtotal)) if mid in PRIMARY.values() else subtotal
            if mid == LEVEL:
                graph.reject(type(candidate) is int and candidate == env["level"],
                             "LEVEL_SOURCE_CONFLICT")
                state = "SOURCE_DERIVED_BASELINE_CANDIDATE"
            else:
                state = "PROVISIONAL_PARTIAL_CONTRIBUTOR_SUBTOTAL"
            display = (f"{candidate * 100:.1f}%" if mid in PERCENT_DAMAGE_IDS
                       else f"{candidate:,}" if isinstance(candidate, int)
                       else str(candidate))
        else:
            candidate = None
            display = None
            state = "BLOCKED_NO_OBSERVED_CONTRIBUTOR"
        rows.append({
            "metricId": mid, "label": entry["label"],
            "group": known[mid]["group"],
            "modelStatus": state,
            "candidateRaw": candidate, "candidateDisplay": display,
            "candidateIsCompleteActual": mid == LEVEL and bool(observed),
            "goldenVerified": False,
            "missingContributorFamilies": gap,
            "sourceExpression": rules[mid]["sourceExpression"],
            "runtimeDependencies": rules[mid]["intermediateVariables"],
            "assumption": (
                "PARTIAL_OBSERVED_SUBTOTAL_EXCLUDES_UNMAPPED_CONTRIBUTORS"
                if mid in PRIMARY.values() else
                "ADDITIVE_PARAGON_PERCENT_ONLY_NO_STACKING_OR_OTHER_FAMILIES"
                if mid in PERCENT_DAMAGE_IDS else
                "UNAVAILABLE_RUNTIME_DEPENDENCIES_NOT_DEFAULTED"
                if not observed else "NONE_FOR_LEVEL_INPUT"),
            "contributions": [{
                "family": c.family, "sourceId": c.source_id,
                "value": c.value, "provenance": c.provenance}
                for c in observed],
        })
    report = {
        "schema": "d4-working-model-candidates-v1",
        "fixtureId": inventory["fixtureId"], "classId": inventory["classId"],
        "gamePatch": inventory["gamePatch"],
        "inputFingerprintSha256": inventory["inputFingerprintSha256"],
        "runtimeSourceSha256": inventory["runtimeSourceSha256"],
        "sourceInputSha256": graph.digest(source),
        "paragonReportSha256": paragon["reportSha256"],
        "rollIndexSha256": rolls["indexSha256"],
        "observedRollsWithoutTrustedMetricMapping": rolls["rollCount"],
        "targetUniqueMetricIds": 20,
        "numericCandidates": sum(r["candidateRaw"] is not None for r in rows),
        "provisionalCandidates": sum(
            r["modelStatus"] == "PROVISIONAL_PARTIAL_CONTRIBUTOR_SUBTOTAL" for r in rows),
        "newGoldenVerified": 0,
        "goldenExpectedLoaded": False,
        "holdoutOpened": False,
        "productionRulePromoted": False,
        "publishAllowed": False,
        "metrics": rows,
    }
    report["reportSha256"] = graph.digest(report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser()
    for key in ("source", "inventory", "targets", "f3map", "paragon",
                "rolls", "report"):
        parser.add_argument("--" + key, type=Path, required=True)
    a = parser.parse_args(argv)
    try:
        read = graph.read_json
        report = evaluate(read(a.source), read(a.inventory),
                          read(a.targets), read(a.f3map),
                          read(a.paragon), read(a.rolls))
        code = 0
    except (graph.GraphError, KeyError, ValueError, TypeError, OSError) as exc:
        report = {"status":"BLOCKED_INVALID_WORKING_MODEL_INPUT",
                  "reason":str(exc), "newGoldenVerified":0,"publishAllowed":False}
        code = 2
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n",
                        encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k != "metrics"},
                     sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
