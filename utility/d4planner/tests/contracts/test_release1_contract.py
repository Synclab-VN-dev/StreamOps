from __future__ import annotations

import copy
import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
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
RULEKIT_BUILD_SCHEMA = D4PLANNER.parent / "d4-rulekit" / "providers" / "maxroll" / "d4-build-v1.schema.json"


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


def canonical_modifiers(item: dict[str, Any], group: str, entity_id: str) -> list[dict[str, Any]]:
    group_key = {
        "AFFIXES": "affixes", "IMPLICITS": "implicits", "ASPECTS": "aspects", "TEMPERS": "tempers"
    }[group]
    return [modifier for modifier in item[group_key] if modifier["entityId"] == entity_id]


def validate_target_semantics(target: dict[str, Any]) -> None:
    validator(TARGET_SCHEMA).validate(target)
    criteria = target["assessmentPolicy"]["criteria"]
    ids = [criterion["criterionId"] for criterion in criteria]
    if len(ids) != len(set(ids)):
        raise ValueError("criterionId must be unique")
    orders = [criterion["targetOrder"] for criterion in criteria]
    if len(orders) != len(set(orders)):
        raise ValueError("targetOrder must be unique")
    links = [
        (criterion["slotId"], criterion["kind"], criterion["entityId"], criterion["source"]["group"], criterion["source"]["occurrence"])
        for criterion in criteria
    ]
    if len(links) != len(set(links)):
        raise ValueError("criterion source binding must be unique")
    slots = {slot["slotId"]: slot["item"] for slot in target["canonicalBuild"]["equipment"]["slots"]}
    for criterion in criteria:
        item = slots.get(criterion["slotId"])
        if item is None:
            raise ValueError("criterion slotId must link to canonical target equipment")
        matches = canonical_modifiers(item, criterion["source"]["group"], criterion["entityId"])
        occurrence = criterion["source"]["occurrence"]
        if occurrence >= len(matches):
            raise ValueError("criterion occurrence must link to canonical target equipment")
        modifier = matches[occurrence]
        parameter_ids = [parameter["parameterId"] for parameter in criterion["parameters"]]
        parameter_indices = [parameter["index"] for parameter in criterion["parameters"]]
        if len(parameter_ids) != len(set(parameter_ids)) or len(parameter_indices) != len(set(parameter_indices)):
            raise ValueError("criterion parameter id/index must be unique")
        for parameter in criterion["parameters"]:
            expected = parameter["expected"]
            if expected["type"] == "NUMBER_RANGE" and expected["minimum"] > expected["maximum"]:
                raise ValueError("BETWEEN minimum must not exceed maximum")
            if parameter["comparator"] != "PRESENT" and parameter["index"] >= len(modifier["values"]):
                raise ValueError("criterion parameter must link to a canonical modifier value")


def pointer(document: Any, path: str) -> Any:
    value = document
    for part in path.strip("/").split("/"):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def apply_mutation(document: dict[str, Any], mutation: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(document)
    operation = mutation["operation"]
    if operation == "append-distinct-occurrence":
        item = result["canonicalBuild"]["equipment"]["slots"][0]["item"]
        item["affixes"].append(copy.deepcopy(item["affixes"][0]))
        copied = copy.deepcopy(result["assessmentPolicy"]["criteria"][0])
        copied.update(criterionId="gloves.attack-speed-second", targetOrder=99)
        copied["source"]["occurrence"] = 1
        result["assessmentPolicy"]["criteria"].append(copied)
        return result
    parts = mutation["path"].strip("/").split("/")
    parent: Any = result
    for part in parts[:-1]:
        parent = parent[int(part)] if isinstance(parent, list) else parent[part]
    if operation == "replace":
        if isinstance(parent, list):
            parent[int(parts[-1])] = mutation["value"]
        else:
            parent[parts[-1]] = mutation["value"]
    elif operation == "append-copy":
        pointer(result, mutation["path"]).append(copy.deepcopy(pointer(result, mutation["from"])))
    elif operation == "append-copy-with-id":
        copied = copy.deepcopy(pointer(result, mutation["from"]))
        copied.update(criterionId=mutation["value"], targetOrder=99)
        pointer(result, mutation["path"]).append(copied)
    elif operation == "append-parameter-copy":
        copied = copy.deepcopy(pointer(result, mutation["from"]))
        copied["parameterId"] = mutation["value"]
        pointer(result, mutation["path"]).append(copied)
    else:  # pragma: no cover
        raise AssertionError(f"unknown mutation {operation}")
    return result


def parameter_passes(parameter: dict[str, Any]) -> bool | None:
    expected, actual = parameter["expected"], parameter["actual"]
    if parameter["comparator"] == "PRESENT":
        return True
    if actual is None or expected["unit"] != actual["unit"]:
        return None
    comparator = parameter["comparator"]
    if comparator == "EQUAL" and actual["type"] != expected["type"]:
        # Python considers True == 1; contract equality never crosses value types.
        return None
    if comparator == "AT_LEAST":
        return actual["value"] >= expected["value"]
    if comparator == "AT_MOST":
        return actual["value"] <= expected["value"]
    if comparator == "BETWEEN":
        return expected["minimum"] <= actual["value"] <= expected["maximum"]
    if comparator == "EQUAL":
        return actual["value"] == expected["value"]
    raise AssertionError(comparator)


def assess_truth(criteria: list[dict[str, Any]], weights: dict[str, float]) -> dict[str, Any]:
    statuses: list[str] = []
    for criterion in criteria:
        if criterion["evidence"] != "COMPLETE" or criterion["identity"] == "UNKNOWN":
            status = "UNKNOWN"
        elif criterion["identity"] in {"WRONG", "ABSENT"}:
            status = "FAIL" if criterion["core"] else "WARN"
        else:
            parameter_results = [parameter_passes(parameter) for parameter in criterion["parameters"]]
            status = "UNKNOWN" if any(result is None for result in parameter_results) else ("PASS" if all(parameter_results) else "WARN")
        statuses.append(status)
    criterion_weights = [weights["core"] if criterion["core"] else weights["nonCore"] for criterion in criteria]
    evaluable = sum(weight for weight, status in zip(criterion_weights, statuses) if status != "UNKNOWN")
    passed = sum(weight for weight, status in zip(criterion_weights, statuses) if status == "PASS")
    return {
        "statuses": statuses, "scoreStatus": "NO_DATA" if evaluable == 0 else "SCORED",
        "score": None if evaluable == 0 else 100 * passed / evaluable,
        "passedWeight": passed, "evaluableWeight": evaluable,
        "evaluatedCriteria": sum(status != "UNKNOWN" for status in statuses), "totalCriteria": len(criteria),
        "failIssues": len({criterion["criterionId"] for criterion, status in zip(criteria, statuses) if status == "FAIL"}),
        "warnings": statuses.count("WARN"), "itemPass": bool(statuses) and all(status == "PASS" for status in statuses),
    }


def validate_hud_semantics(hud: dict[str, Any]) -> None:
    validator(HUD_SCHEMA).validate(hud)
    context, score = hud["context"], hud["score"]
    if context["state"] == "BOUND":
        binding, character, target = context["binding"], context["character"], context["target"]
        assert binding["runtimeInstanceId"] == hud["backend"]["runtimeInstanceId"]
        assert (binding["characterId"], binding["currentRevision"]) == (character["characterId"], character["currentRevision"])
        assert (binding["targetId"], binding["targetSha256"], binding["selectionRevision"]) == (target["targetId"], target["contentSha256"], target["selectionRevision"])
    else:
        assert context["binding"] is None
    if context["state"] in {"STARTUP", "TARGET_ONLY", "CHARACTER_ONLY", "TARGET_UNAVAILABLE"}:
        assert score["status"] == "NO_DATA" and not hud["equipment"]
    if score["status"] == "SCORED":
        assert score["value"] == 100 * score["passedWeight"] / score["evaluableWeight"]


@pytest.mark.parametrize("schema", [TARGET_SCHEMA, HUD_SCHEMA, WS_SCHEMA, PROCESS_SCHEMA, BUILD_SCHEMA])
def test_json_schemas_are_real_draft_2020_12(schema: dict[str, Any]) -> None:
    Draft202012Validator.check_schema(schema)


def test_approved_policy_and_valid_multi_parameter_target() -> None:
    target = load(FIXTURES / "target.valid.synthetic.json")
    validate_target_semantics(target)
    profile = target["assessmentPolicy"]["weightProfile"]
    assert (profile["coreWeight"], profile["nonCoreWeight"], profile["approval"]["status"]) == (3, 1, "APPROVED")
    effect = target["assessmentPolicy"]["criteria"][2]
    assert [parameter["index"] for parameter in effect["parameters"]] == [0, 1]


def test_invalid_types_ranges_units_duplicates_and_missing_parameters_are_rejected() -> None:
    base = load(FIXTURES / "target.valid.synthetic.json")
    mutations = load(FIXTURES / "target-mutations.synthetic.json")["cases"]
    observed: dict[str, str] = {}
    for mutation in mutations:
        try:
            validate_target_semantics(apply_mutation(base, mutation))
        except ValidationError:
            observed[mutation["id"]] = "SCHEMA_INVALID"
        except ValueError as exc:
            observed[mutation["id"]] = "DUPLICATE_CRITERION_ID" if "criterionId" in str(exc) else "POLICY_INVALID"
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
        return "TARGET_INVALID" if not case["validNow"] else "ACTIVATED"

    assert {case["id"]: outcome(case) for case in fixture["cases"]} == {case["id"]: case["expected"] for case in fixture["cases"]}


@pytest.mark.parametrize("fixture_name", [
    "hud.no-data.synthetic.json", "hud.target-only.synthetic.json", "hud.character-only.synthetic.json",
    "hud.target-unavailable.synthetic.json", "hud.partial.synthetic.json",
])
def test_discriminated_hud_states_validate_without_fake_ids(fixture_name: str) -> None:
    hud = load(FIXTURES / fixture_name)
    validate_hud_semantics(hud)
    assert hud["provenance"]["assessmentVersion"] == "d4planner-r1-contract/1.0.0-candidate.3"


def test_no_data_is_not_zero_and_backend_can_be_ready_before_context() -> None:
    hud = load(FIXTURES / "hud.no-data.synthetic.json")
    assert hud["context"] == {"state": "STARTUP", "character": None, "target": None, "binding": None, "selectionError": None}
    assert hud["score"]["value"] is None and hud["health"]["ruleKit"] == "READY"
    invalid = copy.deepcopy(hud)
    invalid["score"]["value"] = 0
    with pytest.raises(ValidationError):
        validator(HUD_SCHEMA).validate(invalid)


def test_hud_context_discriminator_rejects_mixed_or_fake_contexts() -> None:
    startup = load(FIXTURES / "hud.no-data.synthetic.json")
    target_only = load(FIXTURES / "hud.target-only.synthetic.json")
    partial = load(FIXTURES / "hud.partial.synthetic.json")
    mixed_startup = copy.deepcopy(startup)
    mixed_startup["context"]["target"] = target_only["context"]["target"]
    with pytest.raises(ValidationError):
        validator(HUD_SCHEMA).validate(mixed_startup)
    unbound = copy.deepcopy(partial)
    unbound["context"]["binding"] = None
    with pytest.raises(ValidationError):
        validator(HUD_SCHEMA).validate(unbound)


def test_startup_target_character_capture_and_invalidation_transitions() -> None:
    fixture = load(FIXTURES / "hud-transitions.synthetic.json")
    startup_case = fixture["cases"][0]
    startup = load(FIXTURES / startup_case["states"][0]["fixture"])
    target_only = load(FIXTURES / startup_case["states"][1]["fixture"])
    bound_no_capture = copy.deepcopy(target_only)
    bound_no_capture["hudRevision"] = 2
    bound_no_capture["context"].update(
        state="BOUND",
        character={"characterId": "character-synthetic-a", "displayName": "Synthetic Character", "currentRevision": 0},
        binding={"runtimeInstanceId": "backend-synthetic-a", "characterId": "character-synthetic-a", "currentRevision": 0,
                 "targetId": "synthetic-charge-bolt", "targetSha256": "a" * 64, "selectionRevision": 1,
                 "policyVersion": "d4planner-equipment-policy/v1+r1-equipment-weights/1.0.0"},
    )
    partial = load(FIXTURES / startup_case["states"][3]["fixture"])
    for hud, expected_state, expected_score in [
        (startup, "STARTUP", "NO_DATA"), (target_only, "TARGET_ONLY", "NO_DATA"),
        (bound_no_capture, "BOUND", "NO_DATA"), (partial, "BOUND", "SCORED"),
    ]:
        validate_hud_semantics(hud)
        assert (hud["context"]["state"], hud["score"]["status"]) == (expected_state, expected_score)

    character_change = copy.deepcopy(partial)
    character_change["hudRevision"] += 1
    character_change["context"]["character"].update(characterId="character-synthetic-b", currentRevision=0)
    character_change["context"]["binding"].update(characterId="character-synthetic-b", currentRevision=0)
    character_change["score"] = copy.deepcopy(target_only["score"])
    character_change["equipment"] = []
    character_change["recommendation"] = None
    validate_hud_semantics(character_change)
    assert character_change["context"]["binding"]["characterId"] != partial["context"]["binding"]["characterId"]

    unavailable = load(FIXTURES / fixture["cases"][3]["expectedFixture"])
    validate_hud_semantics(unavailable)
    assert unavailable["context"]["target"] is None and unavailable["score"]["status"] == "NO_DATA"


def test_failed_selection_preserves_active_target_label_and_score_binding() -> None:
    hud = load(FIXTURES / "hud.partial.synthetic.json")
    old_target = copy.deepcopy(hud["context"]["target"])
    old_binding = copy.deepcopy(hud["context"]["binding"])
    old_score = copy.deepcopy(hud["score"])
    hud["context"]["selectionError"] = {"code": "TARGET_NOT_FOUND", "attemptedTargetId": "synthetic-missing-target", "occurredAt": "2026-10-25T05:00:10Z"}
    validate_hud_semantics(hud)
    assert hud["context"]["target"] == old_target
    assert hud["context"]["binding"] == old_binding
    assert hud["score"] == old_score
    assert hud["context"]["selectionError"]["attemptedTargetId"] != old_target["targetId"]


def test_raw_truth_vectors_score_once_per_criterion_and_item_requires_all_pass() -> None:
    fixture = load(FIXTURES / "assessment-truth.synthetic.json")
    assert fixture["policy"] == {"profileId": "r1-equipment-weights/1.0.0", "approval": "APPROVED", "core": 3, "nonCore": 1, "parameterAggregation": "ALL"}
    for case in fixture["cases"]:
        result = assess_truth(case["criteria"], fixture["policy"])
        assert result["statuses"] == [criterion["expectedStatus"] for criterion in case["criteria"]], case["id"]
        assert {key: result[key] for key in case["expected"]} == case["expected"], case["id"]


@pytest.mark.parametrize("case_id,expected_status,expected_score", [
    ("equal-number-vs-boolean-is-unknown", "UNKNOWN", None),
    ("equal-number-vs-text-is-unknown", "UNKNOWN", None),
    ("equal-unit-mismatch-is-unknown", "UNKNOWN", None),
    ("equal-same-type-unit-different-value-is-warn", "WARN", 0),
    ("equal-same-type-unit-value-is-pass", "PASS", 100),
])
def test_equal_type_and_unit_semantics(case_id: str, expected_status: str, expected_score: float | None) -> None:
    fixture = load(FIXTURES / "assessment-truth.synthetic.json")
    case = next(item for item in fixture["cases"] if item["id"] == case_id)
    result = assess_truth(case["criteria"], fixture["policy"])
    assert result["statuses"] == [expected_status]
    assert result["score"] == expected_score
    if expected_status == "UNKNOWN":
        assert (result["scoreStatus"], result["evaluableWeight"], result["warnings"], result["failIssues"]) == (
            "NO_DATA", 0, 0, 0,
        )


def test_half_up_is_display_only_and_recommendation_order_is_stable() -> None:
    transport_score = 100 * 2 / 3
    assert transport_score != 67
    assert Decimal(str(transport_score)).quantize(Decimal("1"), rounding=ROUND_HALF_UP) == Decimal("67")
    candidates = [
        {"id": "z", "severity": "NON_CORE_WARN", "targetOrder": 0},
        {"id": "b", "severity": "CORE_WARN", "targetOrder": 2},
        {"id": "a", "severity": "CORE_WARN", "targetOrder": 2},
        {"id": "c", "severity": "CORE_FAIL", "targetOrder": 9},
    ]
    priority = {"CORE_FAIL": 0, "CORE_WARN": 1, "NON_CORE_WARN": 2}
    ordered = sorted(candidates, key=lambda item: (priority[item["severity"]], item["targetOrder"], item["id"]))
    assert [item["id"] for item in ordered] == ["c", "a", "b", "z"]


def test_non_equipment_target_changes_do_not_change_equipment_contract_input() -> None:
    original = load(FIXTURES / "target.valid.synthetic.json")
    changed = copy.deepcopy(original)
    changed["canonicalBuild"]["skills"] = {"allocations": [], "bar": []}
    changed["canonicalBuild"]["paragon"] = {"boards": [{"boardId": "different-synthetic-board", "rotation": 2, "allocations": []}]}
    changed["preservedSections"]["charms"] = [{"id": "different-synthetic-charm", "rank": 99}]

    def equipment_input(target: dict[str, Any]) -> str:
        projected = {"equipment": target["canonicalBuild"]["equipment"], "policy": target["assessmentPolicy"]}
        return hashlib.sha256(json.dumps(projected, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    validate_target_semantics(changed)
    assert equipment_input(changed) == equipment_input(original)


def test_hud_fixture_contains_complete_display_model_without_external_lookup() -> None:
    hud = load(FIXTURES / "hud.partial.synthetic.json")
    validate_hud_semantics(hud)
    row = hud["equipment"][0]
    assert row["slotLabel"] and row["currentItem"]["displayName"] and row["targetItem"]["displayName"]
    assert all(comparison["label"] and comparison["displayText"] for comparison in row["comparisons"])
    assert all(parameter["label"] for comparison in row["comparisons"] for parameter in comparison["parameters"])
    assert hud["provenance"]["lastObservedAt"] == row["currentItem"]["observedAt"]
    assert "coverage" not in hud["score"]
    assert "| Coverage |" not in (CONTRACT / "ui-data-dictionary.md").read_text(encoding="utf-8")


def test_hud_rejects_missing_display_metadata_and_untyped_numeric_comparisons() -> None:
    hud = load(FIXTURES / "hud.partial.synthetic.json")
    missing_label = copy.deepcopy(hud)
    del missing_label["equipment"][0]["currentItem"]["displayName"]
    with pytest.raises(ValidationError):
        validator(HUD_SCHEMA).validate(missing_label)
    string_number = copy.deepcopy(hud)
    string_number["equipment"][0]["comparisons"][0]["parameters"][0]["expected"]["value"] = "8"
    with pytest.raises(ValidationError):
        validator(HUD_SCHEMA).validate(string_number)
    wrong_actual_type = copy.deepcopy(hud)
    wrong_actual_type["equipment"][0]["comparisons"][0]["parameters"][0]["actual"] = {
        "type": "TEXT", "value": "9.4", "unit": "NONE"
    }
    with pytest.raises(ValidationError):
        validator(HUD_SCHEMA).validate(wrong_actual_type)


def test_all_sample_ws_messages_and_startup_snapshot_validate() -> None:
    messages = load(FIXTURES / "ws-messages.synthetic.json")["messages"]
    for message in messages:
        validator(WS_SCHEMA).validate(message)
    arbitrary_path = copy.deepcopy(next(message for message in messages if message["type"] == "target.select.request"))
    arbitrary_path["targetId"] = "../../secrets.json"
    with pytest.raises(ValidationError):
        validator(WS_SCHEMA).validate(arbitrary_path)

    request = next(message for message in messages if message["type"] == "hud.snapshot.request")
    for hud_name in ("hud.no-data.synthetic.json", "hud.partial.synthetic.json"):
        hud = load(FIXTURES / hud_name)
        snapshot = {
            "protocolVersion": "d4planner-ws/v1", "messageId": f"snapshot-{hud_name}", "type": "hud.snapshot",
            "correlationId": request["messageId"], "backendGeneration": 3, "authoritative": True,
            "subscriptionId": "sub-synthetic", "subscriptionAfterRevision": hud["hudRevision"],
            "requestContext": request["requestContext"], "hud": hud,
        }
        validator(WS_SCHEMA).validate(snapshot)

    ambiguous_old_request = copy.deepcopy(request)
    ambiguous_old_request["requestContext"] = {
        "runtimeInstanceId": "backend-synthetic-a", "minimumHudRevision": 0,
        "expectedCharacterId": None, "expectedTargetId": None, "expectedSelectionRevision": None,
    }
    with pytest.raises(ValidationError):
        validator(WS_SCHEMA).validate(ambiguous_old_request)


def test_schema_request_to_reducer_initial_context_discovery() -> None:
    messages = load(FIXTURES / "ws-messages.synthetic.json")["messages"]
    hello = next(message for message in messages if message["type"] == "hello.accepted")
    request = next(
        message for message in messages
        if message["type"] == "hud.snapshot.request"
        and message["requestContext"]["mode"] == "DISCOVER_ACTIVE_CONTEXT"
    )
    hud = load(FIXTURES / "hud.partial.synthetic.json")
    snapshot = {
        "protocolVersion": "d4planner-ws/v1", "messageId": "snapshot-discovery-bound", "type": "hud.snapshot",
        "correlationId": request["messageId"], "backendGeneration": hello["backendGeneration"], "authoritative": True,
        "subscriptionId": "sub-discovered", "subscriptionAfterRevision": hud["hudRevision"],
        "requestContext": request["requestContext"], "hud": hud,
    }
    validator(WS_SCHEMA).validate(request)
    validator(WS_SCHEMA).validate(snapshot)
    state = {
        "runtimeInstanceId": hello["runtimeInstanceId"], "generation": hello["backendGeneration"],
        "hudRevision": -1, "contextState": None, "selectionRevision": None, "targetId": None,
        "characterId": None, "subscriptionId": None, "pendingRequestId": None,
    }
    assert apply_ws_event(state, {
        "kind": "REQUEST", "mode": request["requestContext"]["mode"], "requestId": request["messageId"],
        "minimumRevision": request["requestContext"]["minimumHudRevision"],
    }) == "REQUEST_RECORDED"
    context = hud["context"]
    assert apply_ws_event(state, {
        "kind": "SNAPSHOT", "requestId": snapshot["correlationId"], "runtimeInstanceId": hud["backend"]["runtimeInstanceId"],
        "generation": snapshot["backendGeneration"], "subscriptionId": snapshot["subscriptionId"], "revision": hud["hudRevision"],
        "contextState": context["state"], "selectionRevision": context["target"]["selectionRevision"],
        "targetId": context["target"]["targetId"], "characterId": context["character"]["characterId"],
    }) == "APPLY_DISCOVERY_SNAPSHOT"
    assert (state["characterId"], state["targetId"], state["hudRevision"]) == (
        "character-synthetic-a", "synthetic-charge-bolt", 12,
    )


def apply_ws_event(state: dict[str, Any], event: dict[str, Any]) -> str:
    kind = event["kind"]
    if kind == "HELLO_ACCEPTED":
        state.update(runtimeInstanceId=event["runtimeInstanceId"], generation=event["generation"], hudRevision=-1,
                     subscriptionId=None, pendingRequestId=None, pendingMode=None, contextState=None,
                     targetId=None, characterId=None, selectionRevision=None)
        return "RESET_GENERATION"
    if kind == "REQUEST":
        state.update(pendingRequestId=event["requestId"], pendingMode=event["mode"],
                     minimumRevision=event["minimumRevision"], expectedContext=event.get("expectedContext"))
        return "REQUEST_RECORDED"
    if event["runtimeInstanceId"] != state["runtimeInstanceId"]:
        return "REJECT_RUNTIME_INSTANCE"
    if event["generation"] != state["generation"]:
        return "REJECT_GENERATION"
    if kind == "SNAPSHOT":
        if event["requestId"] != state["pendingRequestId"]:
            return "REJECT_UNEXPECTED_SNAPSHOT"
        actual_context = {
            "state": event["contextState"], "targetId": event["targetId"],
            "characterId": event["characterId"], "selectionRevision": event["selectionRevision"],
        }
        if state["pendingMode"] == "RESYNC_KNOWN_CONTEXT" and actual_context != state["expectedContext"]:
            return "REJECT_CONTEXT"
        if event["revision"] < state["hudRevision"] or event["revision"] < state["minimumRevision"]:
            return "IGNORE_STALE_SNAPSHOT"
        if state["pendingMode"] == "DISCOVER_ACTIVE_CONTEXT":
            outcome = "APPLY_DISCOVERY_SNAPSHOT"
        else:
            outcome = "CONFIRM_EQUAL_SNAPSHOT" if event["revision"] == state["hudRevision"] else "APPLY_SNAPSHOT"
        state.update(hudRevision=event["revision"], subscriptionId=event["subscriptionId"],
                     contextState=event["contextState"], targetId=event["targetId"],
                     characterId=event["characterId"], selectionRevision=event["selectionRevision"],
                     pendingRequestId=None, pendingMode=None, expectedContext=None)
        return outcome
    if event["subscriptionId"] != state["subscriptionId"]:
        return "REJECT_SUBSCRIPTION"
    if event["revision"] <= state["hudRevision"]:
        return "IGNORE_OLD_UPDATE"
    if event["previous"] != state["hudRevision"]:
        return "RESYNC_GAP"
    context_changed = (event["contextState"], event["targetId"], event["characterId"], event["selectionRevision"]) != (
        state["contextState"], state["targetId"], state["characterId"], state["selectionRevision"]
    )
    state.update(hudRevision=event["revision"], contextState=event["contextState"], targetId=event["targetId"],
                 characterId=event["characterId"], selectionRevision=event["selectionRevision"])
    return "APPLY_CONTEXT_UPDATE" if context_changed else "APPLY_UPDATE"


def test_ws_authoritative_snapshot_resync_reconnect_and_anti_rollback_vectors() -> None:
    fixture = load(FIXTURES / "ws-sequences.synthetic.json")
    for case in fixture["cases"]:
        state = copy.deepcopy(case["initial"])
        for event in case["events"]:
            assert apply_ws_event(state, event) == event["expected"], (case["id"], event, state)


def test_lifecycle_sequences_validate_ownership_generation_and_ready_health() -> None:
    cases = load(FIXTURES / "lifecycle-sequences.synthetic.json")["cases"]
    for case in cases:
        events = case["events"]
        for event in events:
            validator(PROCESS_SCHEMA).validate(event)
        assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
        assert len({event["ownerInstanceId"] for event in events}) == 1
        assert all(event["healthVerified"] is True and event["protocolVersion"] for event in events if event["event"] == "READY")
        spawned = [(event["generation"], event["childInstanceId"]) for event in events if event["event"] == "SPAWNED"]
        assert len(spawned) == len({generation for generation, _ in spawned})


def test_lifecycle_restart_invalidates_old_worker_sessions_before_new_ready() -> None:
    cases = load(FIXTURES / "lifecycle-sequences.synthetic.json")["cases"]
    crash = next(case for case in cases if case["id"] == "crash-bounded-restart")["events"]
    names = [event["event"] for event in crash]
    assert names.index("CRASHED") < names.index("SESSIONS_INVALIDATED") < names.index("RESTART_SCHEDULED")
    assert crash[-1]["generation"] > crash[0]["generation"] and crash[-1]["childInstanceId"] != crash[0]["childInstanceId"]
