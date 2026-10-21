#!/usr/bin/env python3
"""Offline local-browser Maxroll calculation PoC.

The runtime package must be provisioned separately and is never stored in this
repository. This CLI validates the bounded build contract, starts Chromium in
offline mode through maxroll_adapter.js, and writes only calculated stats.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from maxroll_poc import ValidationError, canonical_sha256, require, validate_build


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--runtime-dir", type=Path,
                        default=os.environ.get("MAXROLL_RUNTIME_DIR"))
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()

    if args.runtime_dir is None:
        print("validation error: --runtime-dir or MAXROLL_RUNTIME_DIR is required",
              file=sys.stderr)
        return 2
    runtime_dir = Path(args.runtime_dir).resolve()
    manifest = runtime_dir / "runtime-package.json"
    if not manifest.is_file():
        print(f"validation error: runtime package not found: {manifest}",
              file=sys.stderr)
        return 2

    output = args.output.resolve()
    output.unlink(missing_ok=True)
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
                    (script_dir.parent / "evidence" / "offline-poc" /
                     "standalone-runs")).resolve()
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
        "--runtime-dir", str(runtime_dir),
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
        runtime_evidence = result.get("evidence", {}).get("runtimePackage")
        require(isinstance(runtime_evidence, dict),
                "adapter did not report local runtime evidence")
        require(runtime_evidence.get("explicitUnarchivedFetch") ==
                "FAILED_AS_EXPECTED",
                "adapter did not prove fail-closed outbound behavior")
        os.replace(temporary_path, output)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        temporary_path.unlink(missing_ok=True)
        print(f"adapter output error: {error}", file=sys.stderr)
        return 3

    if completed.stdout.strip():
        print(completed.stdout.rstrip())
    print(json.dumps({
        "status": "PASS",
        "mode": "LOCAL_RUNTIME_PACKAGE_OFFLINE",
        "inputSha256": input_sha,
        "output": str(args.output),
        "metricCoverage": result.get("coverage"),
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
