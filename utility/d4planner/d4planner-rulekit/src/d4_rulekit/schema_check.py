"""Deterministic, fail-closed JSON Schema (G1) checks for D4 Rule DSL.

G1 never certifies in-game semantics, patch correctness, or DPS.
"""
from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    source = files("d4_rulekit.schemas").joinpath("rule-v1.schema.json")
    schema = json.loads(source.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    return Draft202012Validator(load_schema())


def _pointer(parts: Any) -> str:
    return "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def validate_rule(data: Any) -> list[dict[str, str]]:
    """Return stable, JSON-serializable errors. Empty errors means G1 only PASS."""
    errors: list[dict[str, str]] = []
    for err in _validator().iter_errors(data):
        errors.append({"path": _pointer(err.absolute_path), "message": err.message})
    return sorted(errors, key=lambda item: (item["path"], item["message"]))


def validate_path(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    try:
        with path.open(encoding="utf-8") as stream:
            data = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {
            "file": str(path),
            "status": "BLOCKED",
            "errors": [{"path": "/", "message": f"Cannot read JSON: {exc}"}],
        }
    errors = validate_rule(data)
    return {
        "file": str(path),
        "status": "PASS" if not errors else "FAIL",
        "ruleId": data.get("ruleId") if isinstance(data, dict) else None,
        "errors": errors,
    }


def schema_self_check() -> dict[str, Any]:
    try:
        schema = load_schema()
    except (OSError, ValueError, SchemaError) as exc:
        return {"status": "FAIL", "errors": [str(exc)]}
    return {
        "status": "PASS",
        "draft": schema.get("$schema"),
        "id": schema.get("$id"),
        "actionVariants": len(schema["$defs"]["action"]["oneOf"]),
        "errors": [],
    }
