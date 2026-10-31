import copy
import json
from pathlib import Path

import pytest

from d4_rulekit.schema_check import validate_path, validate_rule


ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / "fixtures/valid/skill.json").read_text(encoding="utf-8"))
INVALID = sorted((ROOT / "fixtures/invalid").glob("*.json"))


@pytest.mark.parametrize("fixture", INVALID, ids=lambda p: p.stem)
def test_checked_in_invalid_fixtures_fail_closed(fixture):
    assert len(INVALID) >= 3
    result = validate_path(fixture)
    assert result["status"] == "FAIL"
    assert result["errors"]


@pytest.mark.parametrize("mutation", [
    lambda d: d.update({"surprise": "not allowed"}),
    lambda d: d.pop("game"),
    lambda d: d["mechanics"][0]["actions"][0].update({"op": "execute_python"}),
    lambda d: d["mechanics"][0]["actions"][0]["value"].update({"unit": "untrusted_unit"}),
    lambda d: d["mechanics"][0].update({"phase": "some_new_phase"}),
])
def test_schema_rejects_unknown_operations_units_and_fields(mutation):
    data = copy.deepcopy(BASE)
    mutation(data)
    assert validate_rule(data)


def test_input_type_is_checked_not_implicitly_coerced():
    assert validate_rule([BASE])


def test_schema_pass_is_not_semantic_pass():
    data = copy.deepcopy(BASE)
    data["verification"]["status"] = "unverified"
    assert validate_rule(data) == []
    # G1 cannot assert the game coefficient, proc probability or physical hit rate.
