"""Opt-in existing capture evidence. No capture, resolver or Equipment DB mutations.
Native invokes this bounded helper with owner-controlled paths, never WebView paths.
"""

from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sqlite3
import time

MAX = 32_000_000


def safe(path):
    return all(
        not p.is_symlink()
        and not (
            getattr(p.stat(follow_symlinks=False), "st_file_attributes", 0) & 0x400
        )
        for p in [path, *path.parents]
        if p.exists()
    )


def export(root: Path, session: str, destination: Path, consent: bool):
    if not consent:
        raise ValueError("EVIDENCE_CONSENT_REQUIRED")
    if (
        not session
        or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for c in session
        )
        or len(session) > 128
    ):
        raise ValueError("INVALID_SESSION")
    if (
        not root.is_absolute()
        or not destination.is_absolute()
        or not safe(root)
        or not safe(destination)
        or destination.exists()
    ):
        raise ValueError("INVALID_PATH")
    destination.mkdir(mode=0o700)
    files = []
    sources = [
        ("events.db", root / "state" / "events.db"),
        (
            "equipment-projector.jsonl",
            root / "sessions" / session / "equipment-projector.jsonl",
        ),
    ]
    for name, src in sources:
        dst = destination / name
        result = {"name": name, "sessionId": session, "status": "UNAVAILABLE"}
        try:
            if not safe(src) or not src.is_file() or src.stat().st_size > MAX:
                raise ValueError("SOURCE_UNAVAILABLE")
            if name == "events.db":
                # Read-only SQLite connection includes committed WAL pages. No hot-file copying.
                started = time.monotonic()

                def progress(status, remaining, total):
                    if total * page_size > MAX or time.monotonic() - started > 10:
                        raise ValueError("BACKUP_BUDGET")

                with sqlite3.connect(
                    src.as_uri() + "?mode=ro", uri=True, timeout=1
                ) as source:
                    page_size = source.execute("PRAGMA page_size").fetchone()[0]
                    with sqlite3.connect(dst) as target:
                        source.backup(target, pages=128, progress=progress, sleep=0.01)
                        if target.execute("PRAGMA quick_check").fetchone() != ("ok",):
                            raise ValueError("CORRUPT_DB")
            else:
                with src.open("rb") as stream:
                    raw = stream.read(MAX + 1)
                if len(raw) > MAX:
                    raise ValueError("SIZE_LIMIT")
                # Preserve only complete existing JSONL records; never fabricate a partial line.
                cut = raw.rfind(b"\n") + 1
                raw = raw[:cut]
                for line in raw.splitlines():
                    json.loads(line)
                dst.write_bytes(raw)
            if dst.stat().st_size > MAX:
                raise ValueError("SIZE_LIMIT")
            dst.chmod(0o600)
            result["status"] = "BEST_EFFORT"
        except (OSError, ValueError, sqlite3.Error):
            if dst.exists():
                dst.unlink()
        files.append(result)
    return {
        "schemaVersion": "d4planner-evidence-export/v1",
        "files": files,
        "completeness": "BEST_EFFORT",
        "sessionId": session,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--destination", type=Path, required=True)
    p.add_argument("--consent", action="store_true")
    a = p.parse_args()
    try:
        result = export(
            Path(os.environ["D4PLANNER_CAPTURE_DATA_ROOT"]),
            os.environ["D4PLANNER_CAPTURE_SESSION_ID"],
            a.destination,
            a.consent,
        )
    except Exception:
        result = {
            "schemaVersion": "d4planner-evidence-export/v1",
            "files": [
                {"name": "events.db", "status": "UNAVAILABLE"},
                {"name": "equipment-projector.jsonl", "status": "UNAVAILABLE"},
            ],
            "completeness": "UNAVAILABLE",
        }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
