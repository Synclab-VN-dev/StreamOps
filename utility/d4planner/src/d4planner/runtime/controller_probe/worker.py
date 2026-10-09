"""Probe worker and diagnostic payload; never imports production EventStore."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from d4planner.runtime.store import atomic_write_json, read_json
from d4planner.runtime.windows import WindowsRuntime

from .rawinput import RawInputBackend
from .runner import run_backends


def probe_payload(runtime: WindowsRuntime, seconds: float) -> dict[str, Any]:
    """Executed only when process session equals the active desktop session."""
    current = runtime.current_process_session_id()
    active = runtime.active_console_session_id()
    if active is None or current != active:
        raise RuntimeError(
            f"wrong interactive session: probe={current!r}, active={active!r}"
        )
    return {
        "probeProcessSession": current,
        "activeConsoleSession": active,
        "backends": [r.as_dict() for r in run_backends(seconds, [RawInputBackend()])],
    }


def execute_request(
    runtime: WindowsRuntime, request_path: Path, output_path: Path
) -> int:
    request = read_json(request_path)
    if not isinstance(request, dict) or not isinstance(request.get("requestId"), str):
        raise ValueError("invalid controller probe request")
    seconds = float(request.get("seconds", 0))
    payload: dict[str, Any] = {"requestId": request["requestId"]}
    try:
        if not 0 < seconds <= 300:
            raise ValueError("seconds must be between 0 and 300")
        payload.update(probe_payload(runtime, seconds))
    except Exception as exc:
        payload["error"] = f"{type(exc).__name__}: {exc}"
    atomic_write_json(output_path, payload)
    return 2 if "error" in payload else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="d4planner-controller-worker")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if os.name != "nt":
        parser.error("controller probe worker requires Windows")
    from d4planner.runtime.store import RuntimePaths

    return execute_request(WindowsRuntime(RuntimePaths.default()), args.request, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
