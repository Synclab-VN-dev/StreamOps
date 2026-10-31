"""Generate a reviewable report from a raw NVDA JSONL capture."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from d4planner.capture.core import read_jsonl, validate_event_order

FIELDS = (
    "Item name",
    "Item type / slot",
    "Rarity",
    "Item Power",
    "Affix name",
    "Affix value",
    "Roll range",
    "Equipped marker",
    "Unique power",
    "Aspect name/effect",
    "Temper",
    "Masterwork",
    "Greater Affix marker",
    "Charm",
    "Seal",
)


def render_report(events: list[dict[str, object]]) -> str:
    order_errors = validate_event_order(events)
    processes = Counter(str(e.get("process") or "<unknown>") for e in events)
    d4_events = [
        e
        for e in events
        if "diablo" in f"{e.get('process') or ''} {e.get('windowTitle') or ''}".lower()
    ]

    lines = [
        "# D4 NVDA POC report",
        "",
        "## Capture summary",
        "",
        f"- Total speech events: **{len(events)}**",
        f"- Diablo-context events: **{len(d4_events)}**",
        f"- Event ordering: **{'PASS' if not order_errors else 'FAIL'}**",
        "",
        "### Processes observed",
        "",
    ]
    for process, count in sorted(processes.items()):
        lines.append(f"- {process}: {count}")

    if order_errors:
        lines.extend(["", "### Ordering errors", ""])
        lines.extend(f"- {error}" for error in order_errors)

    lines.extend(
        [
            "",
            "## Field evaluation",
            "",
            "The generator does not infer gameplay semantics. Review raw evidence manually.",
            "",
            "| Field | Result | Raw evidence / note |",
            "|---|---|---|",
        ]
    )
    for field in FIELDS:
        lines.append(f"| {field} | NOT_EVALUATED | |")

    lines.extend(
        [
            "",
            "## POC conclusion",
            "",
            "**Status: NOT_EVALUATED**",
            "",
            "- GO: NVDA is sufficient as the primary source for gear capture.",
            "- PARTIAL: core gear is available, but OCR/vision is needed for missing fields.",
            "- NO-GO: data is too incomplete or unstable for NVDA to be the primary source.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("jsonl", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args(argv)

    events = read_jsonl(args.jsonl)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_report(events), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
