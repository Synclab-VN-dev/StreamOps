"""Standalone CLI: syntax/schema checks only; no D4 game or runtime required."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .schema_check import schema_self_check, validate_path


def _write_json(document: dict, report: str | None) -> None:
    result = json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if report:
        target = Path(report)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(result, encoding="utf-8")
    print(result, end="")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="d4-rulekit", description="D4 DSL G1 schema validation")
    cmd = parser.add_subparsers(dest="command", required=True)
    verify = cmd.add_parser("schema-check", help="Check embedded JSON Schema Draft 2020-12")
    verify.add_argument("--report", help="Write deterministic JSON report")
    check = cmd.add_parser("validate", help="Check Rule DSL JSON files (G1 only)")
    check.add_argument("files", nargs="+", help="Input JSON paths")
    check.add_argument("--report", help="Write deterministic JSON report")
    args = parser.parse_args(argv)
    if args.command == "schema-check":
        result = schema_self_check()
        _write_json(result, args.report)
        return 0 if result["status"] == "PASS" else 1

    results = [validate_path(p) for p in args.files]
    if any(item["status"] == "BLOCKED" for item in results):
        outcome = "BLOCKED"
        exit_code = 2
    elif any(item["status"] == "FAIL" for item in results):
        outcome = "FAIL"
        exit_code = 1
    else:
        outcome = "PASS"
        exit_code = 0
    _write_json({
        "gate": "G1_SCHEMA_ONLY",
        "status": outcome,
        "count": len(results),
        "results": results,
    }, args.report)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
