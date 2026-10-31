import copy
import json
from pathlib import Path

from d4_rulekit.contract_check import (
    check_contract,
    check_references,
    evaluate_reference,
    report_files,
)

ROOT = Path(__file__).resolve().parents[1]
CFILE = ROOT / "contracts" / "execution-v1.json"
RFILE = ROOT / "references" / "3.2.3" / "ci03-reference-vectors.json"
CONTRACT = json.loads(CFILE.read_text(encoding="utf-8"))
REFERENCES = json.loads(RFILE.read_text(encoding="utf-8"))


def test_ci03_real_contract_and_sourced_vectors():
    report = report_files(CFILE, RFILE)
    assert report["status"] == "PASS", report
    assert report["referenceCount"] == 4
    assert report["sourceCount"] >= 4
    assert report["gameAccuracy"] == "NOT_VERIFIED_BY_CI03"


def test_all_fifteen_discriminated_actions_have_distinct_semantics():
    assert not check_contract(CONTRACT)
    assert len(CONTRACT["operators"]) == 15
    assert CONTRACT["operators"]["modify_stat"]["class"] != (
        CONTRACT["operators"]["deal_damage"]["class"]
    )
    assert CONTRACT["eventModel"]["priorityConflict"] == (
        "REJECT_EQUAL_PRIORITY_INCOMPATIBLE_OVERRIDE"
    )


def test_missing_action_fails_closed():
    mutated = copy.deepcopy(CONTRACT)
    del mutated["operators"]["emit_event"]
    assert any("operators mismatch" in x for x in check_contract(mutated))


def test_modifier_damage_collision_fails_closed():
    mutated = copy.deepcopy(CONTRACT)
    mutated["operators"]["deal_damage"]["class"] = (
        mutated["operators"]["modify_stat"]["class"]
    )
    assert any("different action classes" in x for x in check_contract(mutated))


def test_unverified_snapshot_and_inheritance_no_numeric_default():
    mutated = copy.deepcopy(CONTRACT)
    mutated["unknownPolicy"]["numericFallback"] = "0"
    assert check_contract(mutated)
    mutated = copy.deepcopy(CONTRACT)
    mutated["eventModel"]["triggeredInheritance"] = "INHERIT_ALL"
    assert check_contract(mutated)
    status, number = evaluate_reference(REFERENCES["vectors"][-1], CONTRACT)
    assert status == "UNVERIFIED" and number is None


def test_game_patch_is_exact_not_historical_implicit_backport():
    v = copy.deepcopy(REFERENCES["vectors"][1])
    v["patch"] = "3.2.3"
    try:
        evaluate_reference(v, CONTRACT)
    except ValueError as exc:
        assert "historical" in str(exc)
    else:
        raise AssertionError("historical 1.2 formula was silently promoted to patch 3.2.3")


def test_gear_multiplier_is_additive_with_itself_not_product():
    status, factor = evaluate_reference(REFERENCES["vectors"][0], CONTRACT)
    assert status == "PASS_CONTRACT_ONLY"
    assert factor == "1.35"
    assert factor != "1.3800"


def test_storm_set_coexists_only_with_explicit_item_rule():
    status, value = evaluate_reference(REFERENCES["vectors"][2], CONTRACT)
    assert (status, value) == ("PASS_RULE_SPECIFIC", None)
    mutated = copy.deepcopy(CONTRACT)
    mutated["interactions"]["storm_shephard_2p_5p"]["mode"] = "override"
    assert check_contract(mutated)


def test_source_provenance_is_mandatory_for_aggregations():
    mutated = copy.deepcopy(CONTRACT)
    mutated["aggregationPolicies"]["gear_damage_multiplier"]["sourceIds"] = []
    assert any("lacks source" in x for x in check_contract(mutated))


def test_reference_golden_must_be_independent_and_unchanged():
    corrupted = copy.deepcopy(REFERENCES)
    corrupted["vectors"][0]["expectedFactor"] = "1.38"
    assert any("expected factor mismatch" in x for x in check_references(corrupted, CONTRACT))
    corrupted = copy.deepcopy(REFERENCES)
    corrupted["vectors"][0]["coefficientsProvenance"] = "verified_blizzard_roll"
    assert any("misrepresented" in x for x in check_references(corrupted, CONTRACT))


def test_missing_inputs_produce_blocked_not_false_pass(tmp_path):
    status = report_files(tmp_path / "missing.json", RFILE)
    assert status["status"] == "BLOCKED"


def test_missing_patch_or_conflicting_override_policy_fails_closed():
    mutated = copy.deepcopy(CONTRACT)
    mutated["patchBaseline"]["sourceId"] = "made-up"
    assert check_contract(mutated)
    mutated = copy.deepcopy(CONTRACT)
    mutated["eventModel"]["priorityConflict"] = "LAST_ONE_WINS"
    assert check_contract(mutated)
