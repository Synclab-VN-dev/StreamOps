from d4_rulekit.schema_check import load_schema

EXPECTED = {
    "modify_stat", "modify_skill", "transform_tags", "deal_damage",
    "spawn_projectile", "trigger_skill", "apply_state", "remove_state",
    "modify_resource", "modify_cooldown", "spawn_entity", "heal",
    "grant_barrier", "emit_event", "override_rule",
}


def test_action_discriminator_is_unique_and_exact():
    variants = load_schema()["$defs"]["action"]["oneOf"]
    ops = [case["properties"]["op"]["const"] for case in variants]
    assert len(ops) == len(set(ops)) == 15
    assert set(ops) == EXPECTED
    for case in variants:
        assert case.get("additionalProperties") is False
        assert "op" in case["required"]


def test_expression_ast_is_typed_and_closed():
    variants = load_schema()["$defs"]["expr"]["oneOf"]
    assert {v["properties"]["kind"]["const"] for v in variants} == {"literal", "ref", "call"}
    for case in variants:
        assert case.get("additionalProperties") is False
    # Free-form script expression is deliberately NOT an accepted AST primitive.
    calls = next(v for v in variants if v["properties"]["kind"]["const"] == "call")
    assert "eval" not in calls["properties"]["fn"]["enum"]
    assert "exec" not in calls["properties"]["fn"]["enum"]
