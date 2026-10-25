from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable

from .target_repository import ActivatedTarget


@dataclass(frozen=True, slots=True)
class ObservedValue:
    type: str
    value: int | float | str | bool
    unit: str = "NONE"
    evidence: str = "OBSERVED"

    def as_dict(self) -> dict[str, Any]:
        return {"type": self.type, "value": self.value, "unit": self.unit}


@dataclass(frozen=True, slots=True)
class ObservedEntity:
    kind: str
    group: str
    entity_id: str
    occurrence: int
    label: str
    values: tuple[ObservedValue | None, ...]


@dataclass(frozen=True, slots=True)
class ObservedItem:
    slot_id: str
    item_id: str
    display_name: str
    observed_at: str
    source: str = "CAPTURE"
    entities: tuple[ObservedEntity, ...] = ()


@dataclass(frozen=True, slots=True)
class EquipmentSnapshot:
    character_id: str
    character_display_name: str
    current_revision: int
    captured_at: str
    items: tuple[ObservedItem, ...]
    # Evidence tokens are PRESENT_VALUE, COMPLETE_CATEGORY and COMPLETE_SLOT.
    slot_evidence: dict[str, frozenset[str]] = field(default_factory=dict)
    capture_health: str = "HEALTHY"


@dataclass(frozen=True, slots=True)
class AssessmentResult:
    score_status: str
    score: float | None
    passed_weight: int
    evaluable_weight: int
    evaluated_criteria: int
    total_criteria: int
    total_weight: int
    fail_issues: int
    warnings: int
    items_passing: int
    items_targeted: int
    rows: tuple[dict[str, Any], ...]
    recommendation: dict[str, Any] | None

    @property
    def display_score_half_up(self) -> int | None:
        if self.score is None:
            return None
        return int(Decimal(str(self.score)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    def score_payload(self) -> dict[str, Any]:
        return {
            "status": self.score_status,
            "value": self.score,
            "passedWeight": self.passed_weight,
            "evaluableWeight": self.evaluable_weight,
            "evaluationCounts": {
                "evaluatedCriteria": self.evaluated_criteria,
                "totalCriteria": self.total_criteria,
                "evaluatedWeight": self.evaluable_weight,
                "totalWeight": self.total_weight,
            },
            "failIssueCount": self.fail_issues,
            "warnCount": self.warnings,
            "itemsPassing": self.items_passing,
            "itemsTargeted": self.items_targeted,
        }


def _typed_expected(parameter: dict[str, Any]) -> dict[str, Any]:
    expected = dict(parameter["expected"])
    expected["unit"] = parameter["unit"]
    return expected


def _parameter_passes(parameter: dict[str, Any], actual: ObservedValue | None) -> bool | None:
    comparator = parameter["comparator"]
    if comparator == "PRESENT":
        return actual is not None
    if actual is None or actual.unit != parameter["unit"]:
        return None
    expected = parameter["expected"]
    expected_actual_type = "NUMBER" if comparator == "BETWEEN" else expected["type"]
    if actual.type != expected_actual_type:
        return None
    value_has_type = (
        (actual.type == "NUMBER" and isinstance(actual.value, (int, float)) and not isinstance(actual.value, bool))
        or (actual.type == "TEXT" and isinstance(actual.value, str))
        or (actual.type == "BOOLEAN" and isinstance(actual.value, bool))
    )
    if not value_has_type:
        return None
    if comparator == "EQUAL":
        return actual.value == expected["value"]
    if actual.type != "NUMBER":
        return None
    if comparator == "AT_LEAST":
        return actual.value >= expected["value"]
    if comparator == "AT_MOST":
        return actual.value <= expected["value"]
    if comparator == "BETWEEN":
        return expected["minimum"] <= actual.value <= expected["maximum"]
    raise ValueError(f"unsupported comparator: {comparator}")


class EquipmentAssessmentService:
    """Pure Equipment-only scorer; it never calls Rule Kit or fills Current from Target."""

    def assess(self, current: EquipmentSnapshot, target: ActivatedTarget) -> AssessmentResult:
        policy = target.document["assessmentPolicy"]
        criteria = policy["criteria"]
        weights = policy["weightProfile"]
        item_by_slot = {item.slot_id: item for item in current.items}
        canonical_slots = {
            slot["slotId"]: slot["item"]
            for slot in target.document["canonicalBuild"]["equipment"]["slots"]
        }
        results: list[dict[str, Any]] = []
        for criterion in criteria:
            item = item_by_slot.get(criterion["slotId"])
            evidence = current.slot_evidence.get(criterion["slotId"], frozenset())
            required = criterion["evidenceRequirement"]
            complete = required in evidence or "COMPLETE_SLOT" in evidence
            entity = None
            if item is not None:
                entity = next((
                    candidate for candidate in item.entities
                    if candidate.kind == criterion["kind"]
                    and candidate.group == criterion["source"]["group"]
                    and candidate.entity_id == criterion["entityId"]
                    and candidate.occurrence == criterion["source"]["occurrence"]
                ), None)
            parameter_rows: list[dict[str, Any]] = []
            parameter_values: list[bool | None] = []
            for parameter in criterion["parameters"]:
                actual = None
                if entity is not None and parameter["index"] < len(entity.values):
                    actual = entity.values[parameter["index"]]
                passed = _parameter_passes(parameter, actual)
                parameter_values.append(passed)
                if passed is True:
                    status, reason, observed = "PASS", "VALUE_MEETS_TARGET", "OBSERVED"
                elif passed is False:
                    status, reason, observed = "WARN", "VALUE_BELOW_OR_DIFFERENT", "OBSERVED"
                elif actual is not None and actual.unit != parameter["unit"]:
                    status, reason, observed = "UNKNOWN", "UNIT_MISMATCH", "UNIT_MISMATCH"
                elif actual is not None:
                    status, reason, observed = "UNKNOWN", "TYPE_MISMATCH", "UNAVAILABLE"
                else:
                    status, reason = "UNKNOWN", "PARAMETER_NOT_OBSERVED"
                    observed = "INCOMPLETE" if not complete else "CONFIRMED_ABSENT"
                parameter_rows.append({
                    "parameterId": parameter["parameterId"],
                    "label": parameter["parameterId"],
                    "index": parameter["index"],
                    "comparator": parameter["comparator"],
                    "expected": _typed_expected(parameter),
                    "actual": (
                        {"type": "BOOLEAN", "value": True, "unit": "NONE"}
                        if parameter["comparator"] == "PRESENT" and actual is not None
                        else actual.as_dict() if actual is not None else None
                    ),
                    "evidence": observed,
                    "status": status,
                    "reasonCode": reason,
                })
            if item is None or entity is None:
                if not complete:
                    status, reason = "UNKNOWN", "EVIDENCE_INCOMPLETE"
                elif criterion["core"]:
                    status, reason = "FAIL", "CORE_IDENTITY_MISSING_CONFIRMED"
                else:
                    status, reason = "WARN", "NON_CORE_IDENTITY_MISSING_CONFIRMED"
            elif any(value is None for value in parameter_values):
                status, reason = "UNKNOWN", "PARAMETER_INCOMPARABLE"
            elif all(parameter_values):
                status, reason = "PASS", "CRITERION_MEETS_TARGET"
            else:
                status = "WARN"
                reason = "CORE_ROLL_BELOW_TARGET" if criterion["core"] else "NON_CORE_BELOW_TARGET"
            weight = weights["coreWeight"] if criterion["core"] else weights["nonCoreWeight"]
            target_item = canonical_slots[criterion["slotId"]]
            results.append({
                "criterion": criterion,
                "status": status,
                "reason": reason,
                "weight": weight,
                "item": item,
                "entity": entity,
                "parameters": parameter_rows,
                "targetItem": target_item,
            })

        evaluable = [result for result in results if result["status"] != "UNKNOWN"]
        passed_weight = sum(result["weight"] for result in evaluable if result["status"] == "PASS")
        evaluable_weight = sum(result["weight"] for result in evaluable)
        score = 100 * passed_weight / evaluable_weight if evaluable_weight else None
        score_status = "SCORED" if evaluable_weight else "NO_DATA"
        slots = list(dict.fromkeys(criterion["slotId"] for criterion in criteria))
        rows: list[dict[str, Any]] = []
        for slot_id in slots:
            slot_results = [result for result in results if result["criterion"]["slotId"] == slot_id]
            statuses = [result["status"] for result in slot_results]
            row_status = "PASS" if statuses and all(s == "PASS" for s in statuses) else (
                "FAIL" if "FAIL" in statuses else "WARN" if "WARN" in statuses else "UNKNOWN"
            )
            item = item_by_slot.get(slot_id)
            target_item = canonical_slots[slot_id]
            rows.append({
                "slotId": slot_id,
                "slotLabel": slot_id.replace("-", " ").title(),
                "targetItem": {
                    "itemId": target_item["baseItemId"],
                    "displayName": target_item["baseItemId"],
                },
                "currentItem": None if item is None else {
                    "itemId": item.item_id, "displayName": item.display_name,
                    "observedAt": item.observed_at, "source": item.source,
                },
                "currentPresence": (
                    "OBSERVED" if item is not None else
                    "CONFIRMED_ABSENT" if "COMPLETE_SLOT" in current.slot_evidence.get(slot_id, ())
                    else "UNKNOWN"
                ),
                "status": row_status,
                "reasonCode": next((r["reason"] for r in slot_results if r["status"] == row_status), "NO_CRITERIA"),
                "comparisons": [self._comparison_payload(result) for result in slot_results],
            })
        item_passes = sum(1 for row in rows if row["status"] == "PASS")
        recommendation = self._recommendation(results)
        return AssessmentResult(
            score_status, score, passed_weight, evaluable_weight, len(evaluable),
            len(results), sum(result["weight"] for result in results),
            len({r["criterion"]["criterionId"] for r in results if r["status"] == "FAIL"}),
            sum(1 for r in results if r["status"] == "WARN"), item_passes,
            len(rows), tuple(rows), recommendation,
        )

    @staticmethod
    def _comparison_payload(result: dict[str, Any]) -> dict[str, Any]:
        criterion = result["criterion"]
        entity = result["entity"]
        label = entity.label if entity is not None else criterion["entityId"]
        return {
            "criterionId": criterion["criterionId"],
            "targetOrder": criterion["targetOrder"],
            "kind": criterion["kind"],
            "source": criterion["source"],
            "entityId": criterion["entityId"],
            "label": label,
            "displayText": f"{label}: {result['reason']}",
            "core": criterion["core"],
            "status": result["status"],
            "reasonCode": result["reason"],
            "parameters": result["parameters"],
        }

    @staticmethod
    def _recommendation(results: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
        priority = {("FAIL", True): 0, ("WARN", True): 1, ("WARN", False): 2}
        candidates = [r for r in results if (r["status"], r["criterion"]["core"]) in priority]
        if not candidates:
            return None
        selected = min(candidates, key=lambda r: (
            priority[(r["status"], r["criterion"]["core"])],
            r["criterion"]["targetOrder"], r["criterion"]["criterionId"],
        ))
        action = "REPLACE" if selected["status"] == "FAIL" else "IMPROVE_ROLL"
        return {
            "action": action,
            "displayText": f"Improve {selected['criterion']['entityId']}",
            "reasonCodes": [selected["reason"]],
            "criterionIds": [selected["criterion"]["criterionId"]],
        }
