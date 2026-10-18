"""Issue #119 PR #120: read-only one-shot CLI snapshot acceptance on Windows A.

Does NOT start/stop D4Planner or interact with NVDA/Game/Steam. Never clears DB.
Current item --attach live changes and game truth require separate Owner MAN.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys


def run(repo_root: Path, home: Path, expected_head: str, evidence_dir: Path) -> dict:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    report = {
        "schemaVersion": 1, "issue": 119, "pr": 120,
        "expectedHead": expected_head, "homeDir": str(home),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cases": results, "status": "BLOCKED",
    }

    def record(case: str, status: str, expected: str, actual: str) -> None:
        results.append({"id": case, "status": status,
                        "expected": expected, "actual": actual})

    try:
        head = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=15)
        actual_head = head.stdout.strip()
        if head.returncode or actual_head != expected_head:
            raise RuntimeError(f"ENVIRONMENT HEAD expected {expected_head}; actual {actual_head}")
        record("UC-00-HEAD", "PASS", expected_head, actual_head)
        src = repo_root / "utility" / "d4planner" / "src"
        db = home / "state" / "character.db"
        if not src.is_dir() or not db.is_file():
            raise RuntimeError(f"ENVIRONMENT missing PR source or database: {src}, {db}")
        env = dict(os.environ, D4PLANNER_HOME=str(home),
                   PYTHONPATH=str(src) + os.pathsep + os.environ.get("PYTHONPATH", ""))
        snapshots = {}
        for location in ("all", "inventory", "equipment", "stash"):
            args = [sys.executable, "-m", "d4planner.cli", "item", "--json"]
            if location != "all":
                args += ["--location", location]
            completed = subprocess.run(args, cwd=repo_root, env=env,
                                       capture_output=True, text=True,
                                       timeout=30, encoding="utf-8")
            (evidence_dir / f"{location}.stdout.json").write_text(
                completed.stdout, encoding="utf-8")
            (evidence_dir / f"{location}.stderr.txt").write_text(
                completed.stderr, encoding="utf-8")
            if completed.returncode:
                raise RuntimeError(
                    f"PRODUCT {location} exit={completed.returncode}; "
                    f"stderr={completed.stderr[:300]}")
            snapshots[location] = json.loads(completed.stdout)
        all_items = snapshots["all"]["items"]
        revision = snapshots["all"]["revision"]
        for location in ("inventory", "equipment", "stash"):
            filtered = snapshots[location]
            if filtered["revision"] != revision:
                record(f"UC-03-{location}", "BLOCKED",
                       f"revision={revision}", f"revision={filtered['revision']}")
                continue
            expected = sorted(str(x["id"]) for x in all_items
                              if x["location"]["type"] == location)
            actual = sorted(str(x["id"]) for x in filtered["items"])
            record(f"UC-03-{location}",
                   "PASS" if expected == actual else "FAIL",
                   repr(expected), repr(actual))
        statuses = {r["status"] for r in results}
        report["status"] = ("FAIL" if "FAIL" in statuses else
                            "BLOCKED" if "BLOCKED" in statuses else
                            "PASS_SNAPSHOT_ONLY")
        record("UC-04-ATTACH-DELTA", "PENDING_MAN",
               "Real change appears after commit", "No game action performed")
        record("UC-07-REAL-A", "PENDING_MAN",
               "Current items match visible game", "Manual checkpoint required")
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        record("PREFLIGHT_OR_PRODUCT", "BLOCKED",
               "Valid HEAD, read-only CLI, consistent SQLite snapshot", str(exc))
        report["status"] = "BLOCKED"
    finally:
        (evidence_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--home-dir", type=Path, required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.repo_root.resolve(), args.home_dir.resolve(),
                 args.expected_head, args.evidence_dir.resolve())
    print(json.dumps({"status": report["status"],
                      "evidence": str(args.evidence_dir)},
                     ensure_ascii=False))
    return {"PASS_SNAPSHOT_ONLY": 0, "FAIL": 1}.get(report["status"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
