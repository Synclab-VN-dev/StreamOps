"""Issue #87 read-only physical marker evidence analyzer.

This tool never starts/stops Steam, Diablo IV or D4Planner, installs a keyboard
hook, changes the runtime config, or claims that a keyboard event proves a
physical controller press. Call from the PR95 acceptance wrapper.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from d4planner.controller import load_profile
from d4planner.runtime.events.repository import EventLogReader
from d4planner.runtime.store import RuntimePaths, read_json


def snapshot(paths: RuntimePaths) -> dict:
    status = read_json(paths.runtime_state) or {}
    marker = ((status.get("extras") or {}).get("inputMarker") or {})
    session = str(status.get("sessionId") or "")
    reader = EventLogReader(paths.events_db)
    try:
        current = reader.max_sequence(session) if session else 0
    finally:
        reader.close()
    valid = (
        status.get("state") == "RUNNING"
        and marker.get("state") == "ACTIVE"
        and marker.get("layoutId") == "xbox-steaminput-18-v1"
        and marker.get("mode") == "BLOCK"
        and marker.get("backend") == "keyboardHook"
        and marker.get("configuredDigitalCount") == 16
        and marker.get("analogDisabledCount") == 2
        and int(marker.get("droppedCount") or 0) == 0
        and not marker.get("overflow", False)
        and not marker.get("error")
    )
    return {
        "sessionId": session,
        "maxSeq": current,
        "runtimeState": status.get("state", "UNKNOWN"),
        "markerState": marker.get("state", "UNKNOWN"),
        "mode": marker.get("mode", "UNKNOWN"),
        "layoutId": marker.get("layoutId"),
        "backend": marker.get("backend"),
        "hookSessionId": marker.get("sessionId"),
        "droppedCount": marker.get("droppedCount", 0),
        "overflow": marker.get("overflow", False),
        "lastError": marker.get("error") or status.get("lastError"),
        "validForReview": valid,
        "capturedAt": datetime.now(timezone.utc).isoformat(),
    }


def analyze(
    *, events: list[dict], start: dict, end: dict,
    quick_check: str, profile=None,
) -> dict:
    """Pure evidence matrix: observed markers, not physical provenance."""
    profile = profile or load_profile("xbox16")
    same_session = bool(start["sessionId"]) and (
        start["sessionId"] == end["sessionId"]
    )
    valid = bool(start["validForReview"] and end["validForReview"] and same_session)
    by_control: dict[str, list[dict]] = {item.control_id: [] for item in profile.digital}
    unknown: list[dict] = []
    speech_count = 0
    event_seq: list[int] = []
    for event in events:
        seq = int(event["eventSeq"])
        event_seq.append(seq)
        if event.get("type") == "speech.raw":
            speech_count += 1
        if event.get("type") != "input.marker.raw":
            continue
        data = event.get("data") or {}
        control = data.get("controlId")
        if control not in by_control:
            unknown.append({"eventSeq": seq, "controlId": control,
                            "key": data.get("key"), "virtualKey": data.get("virtualKey")})
        else:
            by_control[control].append({"eventSeq": seq, **data})

    matrix = []
    for item in profile.digital:
        observed = by_control[item.control_id]
        actual_states = [str(row.get("state") or "").lower() for row in observed]
        correct = (
            valid and len(observed) == 2
            and actual_states == ["down", "up"]
            and all(
                row.get("virtualKey") == item.virtual_key
                and str(row.get("key") or "").upper() == item.key
                and row.get("layoutId") == profile.layout_id
                and row.get("mappingSource") == "configuredLayout"
                and row.get("suppressed") is True
                for row in observed
            )
        )
        matrix.append({
            "id": f"DF-06-{item.control_id}",
            "controlId": item.control_id,
            "expected": {"key": item.key, "virtualKey": item.virtual_key,
                         "states": ["down", "up"], "suppressed": True},
            "actual": {
                "states": actual_states,
                "virtualKeys": [row.get("virtualKey") for row in observed],
                "scanCodes": [row.get("scanCode") for row in observed],
                "seq": [row["eventSeq"] for row in observed],
            },
            "result": "PASS" if correct else ("BLOCKED" if not valid else "FAIL"),
            "physicalVerified": False,
            "note": "Observed keyboard marker only; owner must verify physical C/controller and gameplay.",
        })
    monotonic = (
        event_seq == sorted(event_seq)
        and len(event_seq) == len(set(event_seq))
        and all(start["maxSeq"] < seq <= end["maxSeq"] for seq in event_seq)
    )
    checks = [
        {"id":"ENV-01", "expected":"RUNNING + BLOCK Xbox16 hook, same session",
         "actual":{"start":start,"end":end}, "result":"PASS" if valid else "BLOCKED"},
        {"id":"DB-01", "expected":"PRAGMA quick_check=ok",
         "actual":quick_check, "result":"PASS" if quick_check=="ok" else "FAIL"},
        {"id":"DB-02", "expected":"strict unique monotonic sequence within snapshot",
         "actual":{"events":len(event_seq), "monotonic":monotonic},
         "result":"PASS" if monotonic else "FAIL"},
        {"id":"DB-03", "expected":"no unmapped input marker",
         "actual":{"unknownCount":len(unknown), "unknown":unknown},
         "result":"PASS" if not unknown else "FAIL"},
        {"id":"DB-04", "expected":"speech preserved in canonical SQLite",
         "actual":{"observedSpeechCount":speech_count},
         "result":"PASS" if speech_count else "SKIP"},
        {"id":"OWNER-01", "expected":"Owner confirms 16 physical presses, no cursor blink, gameplay",
         "actual":"not observable from keyboard events", "result":"BLOCKED"},
        {"id":"OWNER-02", "expected":"Owner reviews F10/F11 overlay and keyboard tradeoff",
         "actual":"not observable from keyboard events", "result":"BLOCKED"},
    ]
    combined = matrix + checks
    counts = dict(Counter(row["result"] for row in combined))
    return {
        "schemaVersion":1, "ticket":87, "pr":95,
        "mode":"readOnlyEvidence", "layoutId":profile.layout_id,
        "configured":16, "physicallyVerified":0,
        "status": "BLOCKED" if not valid else (
            "FAIL" if counts.get("FAIL", 0) else "PENDING_OWNER_REVIEW"
        ),
        "summary":{key:counts.get(key,0) for key in ("PASS","FAIL","BLOCKED","SKIP")},
        "checks": checks, "matrix":matrix,
        "eventCount":len(events), "speechEvents":speech_count,
        "range":{"fromExclusive":start["maxSeq"],"toInclusive":end["maxSeq"]},
    }


def read_evidence(paths: RuntimePaths, session: str, after: int, max_seq: int) -> tuple[list[dict], str]:
    reader = EventLogReader(paths.events_db)
    events = []
    try:
        # Snapshot maxSeq at end, do not chase a live writer indefinitely.
        cursor = after
        while cursor < max_seq:
            batch = reader.read_after(session, cursor, limit=1000)
            if not batch:
                break
            for row in batch:
                if row.event_seq > max_seq:
                    break
                events.append(row.as_dict())
            cursor = batch[-1].event_seq
        check = "missing database"
        if reader._db is not None:
            row = reader._db.execute("PRAGMA quick_check").fetchone()
            check = str(row[0]) if row else "no result"
        return events, check
    finally:
        reader.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--mode", choices=("snapshot", "analyze"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--start", type=Path)
    args = parser.parse_args(argv)
    paths = RuntimePaths(args.home)
    try:
        end = snapshot(paths)
        if args.mode == "snapshot":
            output = end
            code = 0 if output["validForReview"] else 2
        else:
            if args.start is None:
                parser.error("--start is required for analyze")
            start = json.loads(args.start.read_text(encoding="utf-8"))
            if not start.get("sessionId") or start.get("sessionId") != end["sessionId"]:
                events, integrity = [], "session changed"
            else:
                events, integrity = read_evidence(
                    paths, start["sessionId"], int(start["maxSeq"]), int(end["maxSeq"])
                )
            output = analyze(events=events, start=start, end=end, quick_check=integrity)
            events_path = args.out.with_name(args.out.stem + "-events.jsonl")
            events_path.parent.mkdir(parents=True, exist_ok=True)
            events_path.write_text(
                "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
                encoding="utf-8",
            )
            output["eventsFile"] = str(events_path)
            # MAN remains BLOCKED by design. A failed marker mapping is nonzero.
            code = 2 if output["status"] in ("BLOCKED", "FAIL") else 0
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({
            "status": output.get("status", "READY" if code == 0 else "BLOCKED"),
            "output":str(args.out), "summary":output.get("summary"),
        }, ensure_ascii=False))
        return code
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"ISSUE87_EVIDENCE_ERROR: {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
