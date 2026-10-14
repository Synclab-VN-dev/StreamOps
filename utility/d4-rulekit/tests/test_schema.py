import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from d4_rulekit.schema_check import load_schema, schema_self_check, validate_path, validate_rule


ROOT = Path(__file__).resolve().parents[1]
VALID = sorted((ROOT / "fixtures" / "valid").glob("*.json"))


def test_schema_is_valid_draft_2020_12():
    Draft202012Validator.check_schema(load_schema())
    assert schema_self_check()["status"] == "PASS"
    assert schema_self_check()["actionVariants"] == 15


def test_schema_is_packaged_and_has_all_contract_sections():
    data = load_schema()
    assert data["$schema"].endswith("draft/2020-12/schema")
    assert {"expr", "action", "mechanic", "source", "patch", "verification"} <= set(data["$defs"])


@pytest.mark.parametrize("fixture", VALID, ids=lambda p: p.stem)
def test_four_synthetic_valid_fixtures(fixture: Path):
    assert len(VALID) == 4, "Expected four checked-in positive specimens"
    assert not validate_rule(json.loads(fixture.read_text(encoding="utf-8")))
    assert validate_path(fixture)["status"] == "PASS"
