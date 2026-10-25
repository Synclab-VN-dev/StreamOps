from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource


D4PLANNER = Path(__file__).resolve().parents[2]
CONTRACT = D4PLANNER / "contracts" / "release1" / "v1"
SCHEMAS = CONTRACT / "schemas"
FIXTURES = CONTRACT / "fixtures"
RULEKIT_BUILD_SCHEMA = (
    D4PLANNER.parent
    / "d4-rulekit"
    / "providers"
    / "maxroll"
    / "d4-build-v1.schema.json"
)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


TARGET_SCHEMA = load(SCHEMAS / "target.schema.json")
HUD_SCHEMA = load(SCHEMAS / "hud.schema.json")
WS_SCHEMA = load(SCHEMAS / "ws.schema.json")
PROCESS_SCHEMA = load(SCHEMAS / "process-event.schema.json")
BUILD_SCHEMA = load(RULEKIT_BUILD_SCHEMA)
REGISTRY = (
    Registry()
    .with_resource(BUILD_SCHEMA["$id"], Resource.from_contents(BUILD_SCHEMA))
    .with_resource(HUD_SCHEMA["$id"], Resource.from_contents(HUD_SCHEMA))
)


def validator(schema: dict[str, Any]) -> Draft202012Validator:
    return Draft202012Validator(schema, registry=REGISTRY, format_checker=FormatChecker())


def validate_target_semantics(target: dict[str, Any]) -> None:
    validator(TARGET_SCHEMA).validate(target)
    profile = target["assessmentPolicy"]["weightProfile"]
    if profile["coreWeight"] <= profile["nonCoreWeight"]:
        raise ValueError("coreWeight must be greater than nonCoreWeight")
    ids = [c["criterionId"] for c in target["assessmentPolicy"]["criteria"]]
    if len(ids) != len(set(ids)):
        raise ValueError("criterionId must be unique")
    links = [(c["slotId"], c["kind"], c["entityId"]) for c in target["assessmentPolicy"]["criteria"]]
    if len(links) != len(set(links)):
        raise ValueError("criterion target link must be unique")
    slots = {
        slot["slotId"]: slot["item"]
        for slot in target["canonicalBuild"]["equipment"]["slots"]
    }
    for criterion in target["assessmentPolicy"]["criteria"]:
        expected = criterion["expected"]
        if criterion["comparator"] == "BETWEEN" and expected["minimum"] > expected["maximum"]:
            raise ValueError("BETWEEN minimum must not exceed maximum")
        item = slots.get(criterion["slotId"])
        if item is None:
            raise ValueError("criterion slotId must link to canonical target equipment")
        groups = (
            ("affixes", "implicits", "tempers")
            if criterion["kind"] == "AFFIX"
            else ("aspects",)
        )
        entity_ids = {modifier["entityId"] for group in groups for modifier in item[group]}
        if criterion["entityId"] not in entity_ids:
            raise ValueError("criterion entityId must link to canonical target equipment")


def pointer(document: Any, path: str) -> Any:
    value = document
    for part in path.strip("/").split("/"):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def apply_mutation(document: dict[str, Any], mutation: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(document)
    parts = mutation["path"].strip("/").split("/")
    parent: Any = result
    for part in parts[:-1]:
        parent = parent[int(part)] if isinstance(parent, list) else parent[part]
    if mutation["operation"] == "replace":
        parent[parts[-1]] = mutation["value"]
    elif mutation["operation"] == "append-copy":
        pointer(result, mutation["path"]).append(copy.deepcopy(pointer(result, mutation["from"])))
    elif mutation["operation"] == "append-copy-with-id":
        copied = copy.deepcopy(pointer(result, mutation["from"]))
        copied["criterionId"] = mutation["value"]
        pointer(result, mutation["path"]).append(copied)
    else:  # pragma: no cover - a bad test vector is a contract authoring failure
        raise AssertionError(f"unknown mutation {mutation['operation']}")
    return result


def assess_truth(criteria: list[dict[str, Any]], weights: dict[str, float]) -> dict[str, Any]:
    statuses: list[str] = []
    for criterion in criteria:
        if criterion["evidence"] != "COMPLETE" or criterion["identity"] == "UNKNOWN":
            status = "UNKNOWN"
        elif criterion["identity"] in {"WRONG", "ABSENT"}:
            status = "FAIL" if criterion["core"] else "WARN"
        elif criterion["valueRelation"] in {"MEETS", "ABOVE"}:
            status = "PASS"
        else:
            status = "WARN"
        statuses.append(status)

    criterion_weights = [weights["core"] if c["core"] else weights["nonCore"] for c in criteria]
    evaluable = sum(w for w, status in zip(criterion_weights, statuses) if status != "UNKNOWN")
    passed = sum(w for w, status in zip(criterion_weights, statuses) if status == "PASS")
    return {
        "statuses": statuses,
        "scoreStatus": "NO_DATA" if evaluable == 0 else "SCORED",
        "score": None if evaluable == 0 else 100 * passed / evaluable,
        "passedWeight": passed,
        "evaluableWeight": evaluable,
        "evaluatedCriteria": sum(status != "UNKNOWN" for status in statuses),
        "totalCriteria": len(criteria),
        "failIssues": statuses.count("FAIL"),
        "warnings": statuses.count("WARN"),
    }


@pytest.mark.parametrize("schema", [TARGET_SCHEMA, HUD_SCHEMA, WS_SCHEMA, PROCESS_SCHEMA, BUILD_SCHEMA])
def test_json_schemas_are_real_draft_2020_12(schema: dict[str, Any]) -> None:
    Draft202012Validator.check_schema(schema)


def test_valid_target_and_canonical_build_validate() -> None:
    target = load(FIXTURES / "target.valid.synthetic.json")
    validate_target_semantics(target)
    assert target["assessmentPolicy"]["weightProfile"]["approval"] == "TEST_ONLY"
    assert target["canonicalBuild"]["schemaVersion"] == "d4-build/v1"


def test_invalid_target_policy_and_duplicate_criteria_are_rejected() -> None:
    base = load(FIXTURES / "target.valid.synthetic.json")
    mutations = load(FIXTURES / "target-mutations.synthetic.json")["cases"]
    observed: dict[str, str] = {}
    for mutation in mutations:
        changed = apply_mutation(base, mutation)
        try:
            validate_target_semantics(changed)
        except ValidationError:
            observed[mutation["id"]] = "SCHEMA_INVALID"
        except ValueError as exc:
            observed[mutation["id"]] = (
                "DUPLICATE_CRITERION_ID" if "criterionId" in str(exc) else "POLICY_INVALID"
            )
        else:
            observed[mutation["id"]] = "VALID"
    assert observed == {case["id"]: case["expected"] for case in mutations}


def test_selection_rechecks_exact_bytes_hash_and_validity() -> None:
    fixture = load(FIXTURES / "target-selection.synthetic.json")
    listed = fixture["listed"]

    def outcome(case: dict[str, Any]) -> str:
        if "/" in case["selectTargetId"] or "\\" in case["selectTargetId"] or ".." in case["selectTargetId"]:
            return "INVALID_MESSAGE"
        if not case["exists"]:
            return "TARGET_NOT_FOUND"
        if case["actualSha256"] != listed["contentSha256"]:
            return "TARGET_CHANGED"
        if not case["validNow"]:
            return "TARGET_INVALID"
        return "ACTIVATED"

    assert {case["id"]: outcome(case) for case in fixture["cases"]} == {
        case["id"]: case["expected"] for case in fixture["cases"]
    }


@pytest.mark.parametrize("fixture_name", ["hud.partial.synthetic.json", "hud.no-data.synthetic.json"])
def test_hud_fixtures_validate_and_keep_metrics_distinct(fixture_name: str) -> None:
    hud = load(FIXTURES / fixture_name)
    validator(HUD_SCHEMA).validate(hud)
    score = hud["score"]
    assert set(("value", "coverage", "itemsPassing", "itemsTargeted")) <= score.keys()
    assert score["coverage"]["denominator"] != score["itemsTargeted"]
    assert hud["binding"]["targetSha256"] == hud["selectedTarget"]["contentSha256"]


def test_no_data_is_not_zero_score_and_rulekit_health_is_independent() -> None:
    hud = load(FIXTURES / "hud.no-data.synthetic.json")
    assert hud["score"]["status"] == "NO_DATA"
    assert hud["score"]["value"] is None
    assert hud["health"]["ruleKit"] == "READY"
    invalid = copy.deepcopy(hud)
    invalid["score"]["value"] = 0
    with pytest.raises(ValidationError):
        validator(HUD_SCHEMA).validate(invalid)


def test_truth_table_status_score_coverage_and_issue_rules() -> None:
    fixture = load(FIXTURES / "assessment-truth.synthetic.json")
    assert fixture["weightProfile"]["approval"] == "TEST_ONLY"
    weights = fixture["weightProfile"]
    for case in fixture["cases"]:
        result = assess_truth(case["criteria"], weights)
        assert result["statuses"] == [c["expectedStatus"] for c in case["criteria"]], case["id"]
        assert {key: result[key] for key in case["expected"]} == case["expected"], case["id"]


def test_non_equipment_target_changes_do_not_change_equipment_contract_input() -> None:
    original = load(FIXTURES / "target.valid.synthetic.json")
    changed = copy.deepcopy(original)
    changed["canonicalBuild"]["skills"] = {"allocations": [], "bar": []}
    changed["canonicalBuild"]["paragon"] = {
        "boards": [{"boardId": "different-synthetic-board", "rotation": 2, "allocations": []}]
    }
    changed["preservedSections"]["charms"] = [
        {"id": "different-synthetic-charm", "rank": 99}
    ]

    def equipment_contract_input(target: dict[str, Any]) -> str:
        projected = {
            "equipment": target["canonicalBuild"]["equipment"],
            "policy": target["assessmentPolicy"],
        }
        return hashlib.sha256(
            json.dumps(projected, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    validate_target_semantics(changed)
    assert equipment_contract_input(changed) == equipment_contract_input(original)


def test_all_sample_ws_messages_validate() -> None:
    messages = load(FIXTURES / "ws-messages.synthetic.json")["messages"]
    for message in messages:
        validator(WS_SCHEMA).validate(message)

    arbitrary_path = copy.deepcopy(next(m for m in messages if m["type"] == "target.select.request"))
    arbitrary_path["targetId"] = "../../secrets.json"
    with pytest.raises(ValidationError):
        validator(WS_SCHEMA).validate(arbitrary_path)

    hud = load(FIXTURES / "hud.partial.synthetic.json")
    for message_type in ("hud.snapshot", "hud.update"):
        message = {
            "protocolVersion": "d4planner-ws/v1",
            "messageId": f"m-{message_type}",
            "type": message_type,
            "correlationId": "m-snapshot-request" if message_type == "hud.snapshot" else None,
            "backendGeneration": 3,
            "previousHudRevision": None if message_type == "hud.snapshot" else 11,
            "hud": hud,
        }
        validator(WS_SCHEMA).validate(message)


def test_ws_duplicate_out_of_order_gap_target_switch_and_reconnect_vectors() -> None:
    fixture = load(FIXTURES / "ws-sequences.synthetic.json")
    for case in fixture["cases"]:
        state = copy.deepcopy(case["initial"])
        for event in case["events"]:
            if event["generation"] < state["generation"]:
                actual = "IGNORE_OLD_GENERATION"
            elif event["generation"] > state["generation"]:
                actual = "RESET_AND_APPLY_SNAPSHOT" if event["previous"] is None else "RESYNC_GAP"
            elif event["revision"] == state["hudRevision"]:
                actual = "IGNORE_DUPLICATE"
            elif event["revision"] < state["hudRevision"]:
                actual = "IGNORE_OLD"
            elif event["previous"] != state["hudRevision"]:
                actual = "RESYNC_GAP"
            elif event["selectionRevision"] < state["selectionRevision"] or (
                event["selectionRevision"] == state["selectionRevision"]
                and event["targetId"] != state["targetId"]
            ):
                actual = "RESYNC_BINDING_MISMATCH"
            else:
                actual = "APPLY"

            assert actual == event["expected"], (case["id"], event)
            if actual in {"APPLY", "RESET_AND_APPLY_SNAPSHOT"}:
                state.update(
                    generation=event["generation"],
                    hudRevision=event["revision"],
                    selectionRevision=event["selectionRevision"],
                    targetId=event["targetId"],
                )


def test_lifecycle_sequences_validate_ownership_generation_and_ready_health() -> None:
    cases = load(FIXTURES / "lifecycle-sequences.synthetic.json")["cases"]
    for case in cases:
        events = case["events"]
        for event in events:
            validator(PROCESS_SCHEMA).validate(event)
        assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
        assert len({event["ownerInstanceId"] for event in events}) == 1
        for event in events:
            if event["event"] == "READY":
                assert event["healthVerified"] is True
                assert event["protocolVersion"]
        spawned_by_generation = [
            (event["generation"], event["childInstanceId"])
            for event in events
            if event["event"] == "SPAWNED"
        ]
        assert len(spawned_by_generation) == len({generation for generation, _ in spawned_by_generation})


def test_lifecycle_restart_invalidates_old_worker_sessions_before_new_ready() -> None:
    cases = load(FIXTURES / "lifecycle-sequences.synthetic.json")["cases"]
    crash = next(case for case in cases if case["id"] == "crash-bounded-restart")["events"]
    names = [event["event"] for event in crash]
    assert names.index("CRASHED") < names.index("SESSIONS_INVALIDATED") < names.index("RESTART_SCHEDULED")
    assert crash[-1]["generation"] > crash[0]["generation"]
    assert crash[-1]["childInstanceId"] != crash[0]["childInstanceId"]
