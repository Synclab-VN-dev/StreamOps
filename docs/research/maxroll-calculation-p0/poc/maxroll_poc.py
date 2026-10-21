#!/usr/bin/env python3
"""Minimal JSON-to-Maxroll-Character-Stats PoC CLI.

The Python entry point validates the bounded PoC contract and delegates only
browser/UI/CDP interaction to maxroll_adapter.js. It contains no Diablo IV
formula implementation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


CONTRACT_VERSION = "maxroll-build-poc/1"
SUPPORTED_PATCH = "3.2.1.73552"


class ValidationError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def require_exact_keys(value: dict[str, Any], expected: set[str], name: str) -> None:
    actual = set(value)
    require(actual == expected,
            f"{name} keys must be {sorted(expected)!r}; got {sorted(actual)!r}")


def validate_build(value: Any) -> dict[str, Any]:
    require(isinstance(value, dict), "input root must be an object")
    require_exact_keys(value, {
        "contractVersion", "provider", "game", "profile", "items",
        "calculationContext",
    }, "root")
    require(value.get("contractVersion") == CONTRACT_VERSION,
            f"contractVersion must be {CONTRACT_VERSION!r}")
    require(value.get("provider") == "maxroll", "provider must be 'maxroll'")

    game = value.get("game")
    require(isinstance(game, dict), "game must be an object")
    require_exact_keys(game, {"id", "patch"}, "game")
    require(game.get("id") == "d4", "game.id must be 'd4'")
    require(game.get("patch") == SUPPORTED_PATCH,
            f"game.patch must be {SUPPORTED_PATCH!r} for this PoC")

    profile = value.get("profile")
    require(isinstance(profile, dict), "profile must be an object")
    require_exact_keys(profile, {
        "class", "level", "worldTier", "items", "skills", "paragon",
    }, "profile")
    require(profile.get("class") == "Rogue", "profile.class must be 'Rogue'")
    require(isinstance(profile.get("level"), int) and 1 <= profile["level"] <= 70,
            "profile.level must be an integer from 1 through 70")
    require(profile.get("worldTier") == "Torment I",
            "profile.worldTier must be 'Torment I'")
    require(profile.get("skills") == {}, "only an empty skills object is supported")
    require(profile.get("paragon") == {}, "only an empty paragon object is supported")
    require(isinstance(profile.get("items"), dict), "profile.items must be an object")
    require(set(profile["items"]) == {"Helm"}, "exactly the Helm slot is supported")

    items = value.get("items")
    require(isinstance(items, dict) and len(items) == 1,
            "items must contain exactly one item")
    item_key = profile["items"]["Helm"]
    require(item_key in items, "profile.items.Helm must reference items entry")
    item = items[item_key]
    require(isinstance(item, dict), "referenced Helm item must be an object")
    require_exact_keys(item, {"slot", "baseName", "explicitModifiers"},
                       "item")
    require(item.get("slot") == "Helm", "item.slot must be 'Helm'")
    require(item.get("baseName") == "Runic Skullcap",
            "item.baseName must be 'Runic Skullcap'")
    modifiers = item.get("explicitModifiers")
    require(isinstance(modifiers, list) and len(modifiers) <= 1,
            "explicitModifiers must contain zero or one modifier")
    for index, modifier in enumerate(modifiers):
        require(isinstance(modifier, dict), f"modifier {index} must be an object")
        require_exact_keys(modifier,
                           {"identity", "pickerLabel", "expectedEffect"},
                           f"modifier {index}")
        require(modifier.get("identity") == "Dampening / Of Dampening",
                f"modifier {index} identity is unsupported")
        require(modifier.get("pickerLabel") == "Dampening / Of Dampening",
                f"modifier {index} pickerLabel is unsupported")
        require(modifier.get("expectedEffect") == "+2800 Fire Resistance",
                f"modifier {index} expectedEffect is unsupported")

    context = value.get("calculationContext")
    require(isinstance(context, dict), "calculationContext must be an object")
    require_exact_keys(context, {"fixture", "conditions"},
                       "calculationContext")
    require(context.get("fixture") == "NEW_PROFILE_LOCAL",
            "calculationContext.fixture must be 'NEW_PROFILE_LOCAL'")
    require(context.get("conditions") == {},
            "only an empty calculationContext.conditions object is supported")
    return value


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()

    output = args.output.resolve()
    try:
        output.unlink(missing_ok=True)
    except OSError as error:
        print(f"output preparation error: {error}", file=sys.stderr)
        return 2

    try:
        source = json.loads(args.input.read_text(encoding="utf-8"))
        build = validate_build(source)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        print(f"validation error: {error}", file=sys.stderr)
        return 2

    input_sha = canonical_sha256(build)
    script_dir = Path(__file__).resolve().parent
    adapter = script_dir / "maxroll_adapter.js"
    output.parent.mkdir(parents=True, exist_ok=True)
    evidence_dir = (args.evidence_dir or
                    (script_dir.parent / "evidence" / "poc-runs")).resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent,
        delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)

    command = [
        "node", str(adapter),
        "--input", str(args.input.resolve()),
        "--output", str(temporary_path),
        "--input-sha256", input_sha,
        "--evidence-dir", str(evidence_dir),
    ]
    environment = os.environ.copy()
    environment.setdefault("NODE_PATH", "/tmp/issue106-f4.Z3XkXq/node_modules")
    completed = subprocess.run(command, text=True, capture_output=True,
                               env=environment, check=False)
    if completed.returncode != 0:
        temporary_path.unlink(missing_ok=True)
        print(completed.stderr.rstrip(), file=sys.stderr)
        return completed.returncode

    try:
        result = json.loads(temporary_path.read_text(encoding="utf-8"))
        require(result.get("inputBuildSha256") == input_sha,
                "adapter returned the wrong input SHA-256")
        require(result.get("provider") == "maxroll",
                "adapter returned the wrong provider")
        os.replace(temporary_path, output)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        temporary_path.unlink(missing_ok=True)
        print(f"adapter output error: {error}", file=sys.stderr)
        return 3

    if completed.stdout.strip():
        print(completed.stdout.rstrip())
    print(json.dumps({
        "status": "PASS",
        "input": str(args.input),
        "inputSha256": input_sha,
        "output": str(args.output),
        "metricCoverage": result.get("coverage"),
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
