"""#107 Maxroll rebaseline safety tests. No fake golden PASS."""
import copy
import json
from pathlib import Path

import pytest

from d4_rulekit.contract_check import (
    check_contract,
    check_references,
    evaluate_reference,
    report_files,
)

ROOT = Path(__file__).resolve().parents[1]
CFILE = ROOT / "contracts" / "execution-v1.json"
RFILE = ROOT / "references" / "3.2.1.73552" / "ci03-reference-vectors.json"
CONTRACT = json.loads(CFILE.read_text(encoding="utf-8"))
REFERENCES = json.loads(RFILE.read_text(encoding="utf-8"))


def test_baseline_is_owner_pinned_maxroll_not_blizzard():
    report = report_files(CFILE, RFILE)
    assert report["status"] == "PASS", report
    assert report["baselinePatch"] == "3.2.1"
    assert report["baselineBuild"] == "73552"
    assert report["oracle"] == "MAXROLL_ONLY"
    assert report["approvedGoldenCount"] == 0
    assert report["referenceCount"] == 0
    assert report["candidateVisibleMetricCount"] == 50
    assert report["maxrollParity"] == "BLOCKED_NO_APPROVED_GOLDEN"
    assert report["gameAccuracy"] == "NOT_VERIFIED_BY_CI03"


def test_same_fifteen_schema_operators():
    assert not check_contract(CONTRACT)
    assert len(CONTRACT["operators"]) == 15
    assert CONTRACT["operators"]["modify_stat"]["class"] != CONTRACT["operators"]["deal_damage"]["class"]


def test_missing_operator_is_rejected():
    doc = copy.deepcopy(CONTRACT)
    doc["operators"].pop("emit_event")
    assert any("operators mismatch" in e for e in check_contract(doc))


def test_modifier_damage_collision_rejected():
    doc = copy.deepcopy(CONTRACT)
    doc["operators"]["deal_damage"]["class"] = doc["operators"]["modify_stat"]["class"]
    assert any("different action classes" in e for e in check_contract(doc))


def test_invalid_event_priority_rejected():
    doc = copy.deepcopy(CONTRACT)
    doc["eventModel"]["priorityConflict"] = "LAST_WINS"
    assert check_contract(doc)


def test_missing_snapshot_or_recursion_guard_rejected():
    doc = copy.deepcopy(CONTRACT)
    doc["eventModel"]["triggeredInheritance"] = "INHERIT_ALL"
    assert check_contract(doc)
    doc = copy.deepcopy(CONTRACT)
    doc["eventModel"]["recursion"] = "ALLOW"
    assert check_contract(doc)


def test_fail_closed_unknown_and_numeric_default():
    doc = copy.deepcopy(CONTRACT)
    doc["unknownPolicy"]["numericFallback"] = "0"
    assert any("fail closed" in e for e in check_contract(doc))


def test_wrong_patch_or_build_rejected():
    for name, value in [("gameVersion", "3.2.3"), ("buildNumber", "73883")]:
        doc = copy.deepcopy(CONTRACT)
        doc["patchBaseline"][name] = value
        assert any("baseline mismatch" in e for e in check_contract(doc))


def test_legacy_blizzard_cannot_be_active_reference_source():
    doc = copy.deepcopy(CONTRACT)
    doc["provenance"]["sourceRegistry"][0]["kind"] = "official"
    assert any("bounded Maxroll" in e for e in check_contract(doc))
    doc = copy.deepcopy(CONTRACT)
    doc["provenance"]["sourceRegistry"][0]["url"] = "https://news.blizzard.com/"
    assert check_contract(doc)


def test_legacy_or_synthetic_formula_cannot_be_promoted():
    doc = copy.deepcopy(CONTRACT)
    doc["aggregationPolicies"]["gear_damage_multiplier"] = {
        "kind": "sum_then_factor", "status": "OFFICIAL_MECHANIC_WITH_SYNTHETIC_VALUES"
    }
    assert any("active calculation formula" in e for e in check_contract(doc))
    doc = copy.deepcopy(CONTRACT)
    doc["interactions"]["storm_shephard_2p_5p"] = {"mode": "coexist_not_override"}
    assert check_contract(doc)


def test_candidate_only_never_becomes_golden():
    reference = copy.deepcopy(REFERENCES)
    reference["approvedGoldenCount"] = 50
    assert any("promoted" in e for e in check_references(reference, CONTRACT))
    reference = copy.deepcopy(REFERENCES)
    reference["vectors"].append({"expectedFactor": "1.35", "source": "AI"})
    assert check_references(reference, CONTRACT)


def test_cannot_fake_reference_patch_or_input_fingerprint():
    reference = copy.deepcopy(REFERENCES)
    reference["gamePatch"] = "3.2.3"
    assert any("patch/build" in e for e in check_references(reference, CONTRACT))
    reference = copy.deepcopy(REFERENCES)
    reference["fixtureFingerprint"] = "fake"
    assert any("fingerprint" in e for e in check_references(reference, CONTRACT))


def test_captured_50_not_global_coverage_or_parity():
    reference = copy.deepcopy(REFERENCES)
    reference["candidateVisibleMetricCount"] = 51
    assert check_references(reference, CONTRACT)
    doc = copy.deepcopy(CONTRACT)
    doc["referencePolicy"]["maxrollParity"] = "PASS"
    assert check_contract(doc)


def test_missing_evidence_yields_blocked(tmp_path):
    report = report_files(tmp_path / "missing-contract.json", RFILE)
    assert report["status"] == "BLOCKED"


def test_no_numeric_reference_evaluator_without_independent_golden():
    with pytest.raises(ValueError, match="independently reviewed"):
        evaluate_reference({"testType": "aggregation", "expectedFactor": "1.35"}, CONTRACT)


def test_missing_app_semver_does_not_block_owner_patch_choice():
    assert CONTRACT["patchBaseline"]["appVersion"] == "UNKNOWN_NOT_REQUIRED_FOR_PATCH_PIN"
    assert not check_contract(CONTRACT)
