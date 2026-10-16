"""Read-only issue #119 NVDA + controller marker evidence collector.

Never changes D4Planner, injects gameplay input, or infers inventory ownership.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import sys

ITEM_TYPES = ("Helm", "Chest Armor", "Gloves", "Pants", "Boots", "Wand", "Focus", "Ring", "Amulet", "Sword")
ITEM_POWER = re.compile(r"^(\d[\d,]*) Item Power$")


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"expected JSON object in {path}")
    return data


def reader(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise RuntimeError(f"canonical events.db missing: {path}")
    uri = path.resolve().as_uri() + "?mode=ro"
    db = sqlite3.connect(uri, uri=True, timeout=3.0)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    db.execute("PRAGMA busy_timeout=3000")
    return db


def snapshot(home: Path) -> dict:
    state = read_json(home / "state" / "runtime.json")
    session = state.get("sessionId")
    if not isinstance(session, str) or not session:
        raise RuntimeError("no active/recent D4Planner capture session")
    with closing(reader(home / "state" / "events.db")) as db:
        seq = db.execute("SELECT COALESCE(MAX(event_seq),0) FROM event_log WHERE session_id=?", (session,)).fetchone()[0]
    marker = ((state.get("extras") or {}).get("inputMarker") or {})
    return {
        "schemaVersion": 1, "sessionId": session, "eventSeq": int(seq),
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        "runtimeState": state.get("state"), "supervisorPid": state.get("supervisorPid"),
        "captureActive": state.get("captureActive"),
        "marker": {key: marker.get(key) for key in (
            "state", "layoutId", "mode", "configuredDigitalCount", "backend", "sessionId",
            "droppedCount", "overflow", "error")},
    }


def fetch_events(home: Path, session: str, start: int, end: int) -> list[dict]:
    rows = []
    with closing(reader(home / "state" / "events.db")) as db:
        for row in db.execute(
            "SELECT event_seq,timestamp,type,data_json FROM event_log "
            "WHERE session_id=? AND event_seq>? AND event_seq<=? ORDER BY event_seq",
            (session, start, end),
        ):
            try:
                data = json.loads(row["data_json"])
            except (ValueError, TypeError) as exc:
                raise RuntimeError(f"invalid data_json eventSeq={row['event_seq']}: {exc}") from exc
            if not isinstance(data, dict):
                raise RuntimeError(f"non-object data_json eventSeq={row['event_seq']}")
            rows.append({"eventSeq": row["event_seq"], "sessionId": session,
                         "timestamp": row["timestamp"], "type": row["type"], "data": data})
    return rows


def anchors(events: list[dict]) -> list[dict]:
    # Anchor is an *observation*, never proof the item is owned or picked up.
    lines = [(event["eventSeq"], event["timestamp"], str(event["data"].get("text") or "").strip())
             for event in events if event["type"] == "speech.raw"]
    found = []
    for idx in range(2, len(lines)):
        name_seq, time, name = lines[idx-2]
        _, _, kind = lines[idx-1]
        power_seq, _, power = lines[idx]
        match = ITEM_POWER.fullmatch(power)
        if not name or not match:
            continue
        matched_type = next((t for t in ITEM_TYPES if kind.endswith(" " + t) or kind == t), None)
        if matched_type is None:
            continue
        found.append({"name": name, "itemType": matched_type,
                      "itemPower": int(match[1].replace(",", "")),
                      "sourceSeqStart": name_seq, "sourceSeqEnd": power_seq,
                      "timestamp": time, "location": "UNKNOWN", "ownership": "UNVERIFIED"})
    return found


def write_json(path: Path, data: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, data: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as dest:
        for event in data:
            dest.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def finish(home: Path, baseline_file: Path, outdir: Path) -> dict:
    baseline = read_json(baseline_file)
    after = snapshot(home)
    if baseline.get("sessionId") != after["sessionId"]:
        raise RuntimeError("session changed during capture; refuse to splice distinct sessions")
    start, end = int(baseline["eventSeq"]), int(after["eventSeq"])
    if end < start:
        raise RuntimeError("event sequence regressed during capture")
    events = fetch_events(home, after["sessionId"], start, end)
    speech = [v for v in events if v["type"] == "speech.raw"]
    inputs = [v for v in events if v["type"] == "input.marker.raw"]
    observed = anchors(events)
    keys = Counter(str(v["data"].get("controlId") or v["data"].get("key") or "UNKNOWN") for v in inputs)
    edges = Counter(str(v["data"].get("state") or "").lower() for v in inputs)
    gaps = [seq for seq in range(start+1, end+1)] if end - start <= 100000 else []
    if gaps:
        present = {int(e["eventSeq"]) for e in events}
        gaps = [seq for seq in gaps if seq not in present]
    missing_count = (end - start) - len(events)
    marker = after["marker"]
    checks = {
        "session_continuity": "PASS",
        "canonical_events_complete": "PASS" if missing_count == 0 else "FAIL",
        "nvda_speech_observed": "PASS" if speech else "BLOCKED",
        "configured_input_edges_observed": "PASS" if inputs else "BLOCKED",
        "controller_16_key_profile": "PASS" if marker.get("layoutId") == "xbox-steaminput-18-v1" and marker.get("configuredDigitalCount") == 16 and marker.get("state") == "ACTIVE" else "BLOCKED",
        "input_queue_health": "PASS" if marker.get("droppedCount") == 0 and marker.get("overflow") is False else "BLOCKED",
        "inventory_stash_completeness": "BLOCKED",
    }
    summary = {"schemaVersion": 1, "sessionId": after["sessionId"], "eventRange": [start+1,end],
               "speechCount": len(speech), "inputCount": len(inputs),
               "inputEdges": dict(edges), "observedMappedKeys": dict(sorted(keys.items())),
               "anchorCount": len(observed), "missingEvents": missing_count,
               "missingEventExamples": gaps[:20], "coverage": {"inventory": "UNVERIFIED", "stash": "UNVERIFIED"},
               "checks": checks, "before": baseline, "after": after,
               "warning": "Mapped keyboard edges are not proof of physical controller provenance. Tooltip anchors do not prove ownership, pickup or complete scans."}
    write_jsonl(outdir / "events.jsonl", events)
    write_jsonl(outdir / "speech.jsonl", speech)
    write_jsonl(outdir / "input.jsonl", inputs)
    write_json(outdir / "item-anchors-unverified.json", observed)
    write_json(outdir / "summary.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("begin", "finish"))
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--out", type=Path, help="begin baseline.json output file")
    parser.add_argument("--baseline", type=Path, help="finish baseline.json input file")
    parser.add_argument("--outdir", type=Path, help="finish output directory")
    args = parser.parse_args(argv)
    try:
        if args.action == "begin":
            if args.out is None: parser.error("begin requires --out")
            report = snapshot(args.home)
            write_json(args.out, report)
            print(json.dumps({"baseline": str(args.out), "sessionId": report["sessionId"], "eventSeq": report["eventSeq"]}))
            return 0
        if args.baseline is None or args.outdir is None: parser.error("finish requires --baseline and --outdir")
        report = finish(args.home, args.baseline, args.outdir)
        print(json.dumps({"output": str(args.outdir), "checks": report["checks"], "speechCount": report["speechCount"], "inputCount": report["inputCount"]}))
        return 1 if "FAIL" in report["checks"].values() else 0
    except (OSError, ValueError, RuntimeError, sqlite3.DatabaseError) as exc:
        print(f"BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
