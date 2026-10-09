"""SSH control-to-interactive-desktop relay for #77; diagnostics only."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import time
import uuid

from d4planner.runtime.store import atomic_write_json, read_json
from d4planner.runtime.windows import RuntimeBlocked, WindowsRuntime

from .worker import probe_payload


TASK_NAME = "D4Planner-Controller-Probe-V2"


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def run_or_relay(runtime: WindowsRuntime, seconds: float) -> dict:
    if not 0 < seconds <= 300:
        raise ValueError("--seconds must be between 0 and 300")
    runtime.require_windows()
    current = runtime.current_process_session_id()
    active = runtime.active_console_session_id()
    if active is None:
        raise RuntimeBlocked("no active interactive console session")
    if current == active:
        return {
            "controlSession": current, "relayed": False,
            **probe_payload(runtime, seconds),
        }
    request_id = uuid.uuid4().hex
    directory = runtime.paths.runtime / "probes" / "controller-v2" / request_id
    directory.mkdir(parents=True, exist_ok=True)
    request = directory / "request.json"
    result_path = directory / "result.json"
    helper = directory / "run-probe.ps1"
    atomic_write_json(request, {"requestId": request_id, "seconds": seconds})
    helper.write_text(
        "$ErrorActionPreference='Stop'\n"
        f"& {_ps_quote(str(Path(sys.executable)))} -m "
        "d4planner.runtime.controller_probe.worker "
        f"--request {_ps_quote(str(request))} --output {_ps_quote(str(result_path))}\n",
        encoding="utf-8",
    )
    runtime._prepare_interactive_task(TASK_NAME, helper)
    runtime.run_task(TASK_NAME)
    deadline = time.monotonic() + seconds + 20
    while time.monotonic() < deadline:
        result = read_json(result_path)
        if isinstance(result, dict) and result.get("requestId") == request_id:
            if result.get("error"):
                raise RuntimeBlocked(str(result["error"]))
            if result.get("probeProcessSession") != active or result.get("activeConsoleSession") != active:
                raise RuntimeBlocked("interactive relay returned a wrong-session result")
            return {"controlSession": current, "relayed": True, **result}
        time.sleep(0.1)
    raise RuntimeBlocked(
        f"interactive controller probe did not return within {seconds + 20:g}s; "
        f"request={request_id} (worker is time-bounded)"
    )
