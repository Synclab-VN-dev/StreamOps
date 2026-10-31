"""Structural G1 nested-expression, state and recursion guard cases.

These tests intentionally do NOT claim to validate runtime cycle semantics (G2).
"""
import copy
import json
from pathlib import Path

from d4_rulekit.schema_check import validate_rule

ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / "fixtures/valid/skill.json").read_text(encoding="utf-8"))


def test_nested_expr_rejects_unlisted_function_even_inside_valid_outer_ast():
    data = copy.deepcopy(BASE)
    data["mechanics"][0]["actions"][0]["value"] = {
        "kind": "call", "fn": "add", "args": [
            {"kind": "literal", "value": 1, "unit": "count"},
            {"kind": "call", "fn": "unsafe_eval", "args": [
                {"kind": "literal", "value": 2, "unit": "count"}
            ]},
        ],
    }
    assert validate_rule(data)


def test_state_stack_rules_accept_known_enum_and_reject_unknown():
    data = copy.deepcopy(BASE)
    action = {"op": "apply_state", "who": "actor", "state": {
        "stateId": "example.state.a", "stacking": "refresh", "expiration": "all_at_once",
    }}
    data["mechanics"][0]["actions"] = [action]
    assert validate_rule(data) == []
    action["state"]["stacking"] = "invented_stack_mode"
    assert validate_rule(data)


def test_proc_recursion_bounds_fail_closed_structurally():
    data = copy.deepcopy(BASE)
    proc = {
        "chanceModel": "direct",
        "triggeredEventsCanProc": True,
        "maxChainDepth": 64,
    }
    data["mechanics"][0]["proc"] = proc
    assert validate_rule(data) == []
    proc["maxChainDepth"] = 65
    assert validate_rule(data)
    proc["maxChainDepth"] = -1
    assert validate_rule(data)


def test_g1_cannot_detect_valid_type_but_unknown_runtime_cycles():
    data = copy.deepcopy(BASE)
    data["dependencies"] = [data["ruleId"]]
    assert validate_rule(data) == []
    # A self-referential dependency must be rejected by #108 G2, not certified by G1.
