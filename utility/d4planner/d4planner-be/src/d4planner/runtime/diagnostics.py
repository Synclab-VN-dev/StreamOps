"""Fail-open semantic diagnostics for D4Planner components."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def _record(component: str, event: str, fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "emittedAt": _now(),
        "component": component,
        "event": event,
        **fields,
    }


class JsonlDiagnosticsSink:
    """Append-only diagnostics sink. Failures never escape into runtime logic."""

    def __init__(self, path: Path, *, component: str):
        self.path = path
        self.component = component
        self._lock = threading.Lock()

    def emit(self, event: str, **fields: Any) -> bool:
        payload = _record(self.component, event, fields)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            with self._lock:
                with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(line)
                    handle.write("\n")
                    handle.flush()
            return True
        except (OSError, TypeError, ValueError):
            return False


class MemoryDiagnosticsSink:
    """In-memory sink used by offline replay and tests."""

    def __init__(self, *, component: str):
        self.component = component
        self.records: list[dict[str, Any]] = []

    def emit(self, event: str, **fields: Any) -> bool:
        try:
            self.records.append(_record(self.component, event, fields))
            return True
        except (TypeError, ValueError):
            return False
