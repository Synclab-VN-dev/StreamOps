"""Command-line interface for the D4Planner runtime."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any, Iterator

from .runtime.model import RuntimeState
from .runtime.pathing import UserPathManager, WindowsRegistryPathBackend
from .runtime.store import RuntimePaths, read_json
from .runtime.windows import WindowsRuntime


TERMINAL_STATES = {
    RuntimeState.RUNNING.value,
    RuntimeState.WAITING_FOR_GAME.value,
    RuntimeState.RESTART_REQUIRED.value,
    RuntimeState.BLOCKED.value,
    RuntimeState.DEGRADED.value,
}


def _paths() -> RuntimePaths:
    override = os.environ.get("D4PLANNER_HOME")
    return RuntimePaths(Path(override)) if override else RuntimePaths.default()


def _pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _state(paths: RuntimePaths) -> dict[str, Any]:
    return read_json(paths.runtime_state) or {
        "state": RuntimeState.STOPPED.value,
        "captureActive": False,
    }


def _spawn_daemon(*, speech: bool, isolated: bool) -> int:
    cmd = [sys.executable, "-m", "d4planner.daemon"]
    if speech:
        cmd.append("--speech")
    if isolated:
        cmd.append("--isolated")
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(cmd, **kwargs)
    return int(process.pid)


def _wait_start(paths: RuntimePaths, pid: int, timeout: float = 120.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_state = None
    while time.monotonic() < deadline:
        status = _state(paths)
        current = str(status.get("state") or "")
        if current != last_state and current:
            detail = str(status.get("detail") or "")
            print(f"[{current}] {detail}".rstrip())
            last_state = current
        if current in TERMINAL_STATES:
            return status
        if not _pid_alive(pid):
            return status
        time.sleep(0.25)
    return _state(paths)


def _event_lines(path: Path, *, follow: bool, from_end: bool) -> Iterator[str]:
    while follow and not path.exists():
        time.sleep(0.2)
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        if from_end:
            handle.seek(0, os.SEEK_END)
        while True:
            line = handle.readline()
            if line:
                yield line
                continue
            if not follow:
                return
            time.sleep(0.15)


def _pretty_event(event: dict[str, Any]) -> str | None:
    event_type = str(event.get("type") or "")
    timestamp = str(event.get("timestamp") or "")
    stamp = timestamp[11:23] if len(timestamp) >= 23 else timestamp
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    if event_type == "speech.raw":
        text = str(data.get("text") or "").strip()
        return f"[{stamp}] {text}" if text else None
    detail = str(data.get("detail") or "")
    return f"[{stamp}] {event_type} {detail}".rstrip()


def command_logs(paths: RuntimePaths, *, follow: bool, raw: bool, from_end: bool = False) -> int:
    status = _state(paths)
    session_dir = status.get("sessionDir")
    if not session_dir:
        print("No active/recent D4Planner session.", file=sys.stderr)
        return 2
    path = Path(str(session_dir)) / "events.jsonl"
    try:
        for line in _event_lines(path, follow=follow, from_end=from_end):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if raw:
                print(json.dumps(event, ensure_ascii=False, separators=(",", ":")), flush=True)
            else:
                rendered = _pretty_event(event)
                if rendered:
                    print(rendered, flush=True)
    except KeyboardInterrupt:
        return 0
    return 0


def command_status(paths: RuntimePaths, *, raw_json: bool) -> int:
    status = _state(paths)
    if raw_json:
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0
    tolk = status.get("tolk") or {}
    nvda = status.get("nvda") or {}
    steam = status.get("steam") or {}
    game = status.get("game") or {}
    rows = [
        ("Runtime", status.get("state")),
        ("Detail", status.get("detail")),
        ("Supervisor PID", status.get("supervisorPid")),
        ("NVDA", f"PID {nvda.get('pid')} / Session {nvda.get('session_id') or nvda.get('sessionId')}" if nvda else "STOPPED"),
        ("Tolk backend", tolk.get("reader") if tolk else "UNKNOWN"),
        ("Steam", f"PID {steam.get('pid')}" if steam else "STOPPED"),
        ("Diablo IV", f"PID {game.get('pid')}" if game else "STOPPED"),
        ("Capture", "ACTIVE" if status.get("captureActive") else "INACTIVE"),
        ("Mode", "silent" if status.get("silent", True) else "speech"),
        ("Session", status.get("sessionId") or "-"),
        ("Last event", status.get("lastEventAt") or "-"),
    ]
    width = max(len(key) for key, _ in rows)
    for key, value in rows:
        print(f"{key:<{width}}  {value}")
    state = str(status.get("state") or "")
    if state == RuntimeState.BLOCKED.value:
        return 2
    if state == RuntimeState.RESTART_REQUIRED.value:
        return 3
    return 0


def command_start(
    paths: RuntimePaths,
    *,
    speech: bool,
    isolated: bool,
    detached: bool,
    timeout: float,
) -> int:
    paths.ensure()
    previous = _state(paths)
    previous_pid = previous.get("supervisorPid")
    if _pid_alive(int(previous_pid)) if previous_pid else False:
        state = str(previous.get("state") or "")
        if state != RuntimeState.STOPPED.value:
            print(f"D4Planner already running (PID {previous_pid}, state {state}).")
            if detached:
                return 0
            return command_logs(paths, follow=True, raw=False, from_end=True)

    try:
        paths.stop_request.unlink()
    except FileNotFoundError:
        pass

    pid = _spawn_daemon(speech=speech, isolated=isolated)
    print(f"D4Planner supervisor PID {pid}")
    status = _wait_start(paths, pid, timeout=timeout)
    state = str(status.get("state") or "")
    if state == RuntimeState.BLOCKED.value:
        print(status.get("lastError") or status.get("detail"), file=sys.stderr)
        return 2
    if state == RuntimeState.RESTART_REQUIRED.value:
        print(status.get("detail"), file=sys.stderr)
        return 3
    if state not in {RuntimeState.RUNNING.value, RuntimeState.WAITING_FOR_GAME.value, RuntimeState.DEGRADED.value}:
        print(f"D4Planner did not become ready (state={state or 'UNKNOWN'}).", file=sys.stderr)
        return 4
    if detached:
        return 0
    print("\n── D4Planner live events (Ctrl+C = detach only) ──")
    return command_logs(paths, follow=True, raw=False, from_end=True)


def command_stop(paths: RuntimePaths, *, timeout: float = 10.0) -> int:
    status = _state(paths)
    pid = status.get("supervisorPid")
    if not pid or not _pid_alive(int(pid)):
        print("D4Planner supervisor is not running.")
        return 0
    paths.stop_request.parent.mkdir(parents=True, exist_ok=True)
    paths.stop_request.write_text("stop\n", encoding="utf-8")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = _state(paths)
        if current.get("state") == RuntimeState.STOPPED.value or not _pid_alive(int(pid)):
            print("D4Planner stopped. Diablo IV and Steam were left untouched.")
            return 0
        time.sleep(0.2)
    print("Stop request sent; supervisor has not exited yet.", file=sys.stderr)
    return 1


def command_doctor(paths: RuntimePaths, *, raw_json: bool) -> int:
    runtime = WindowsRuntime(paths)
    report = runtime.doctor()
    checks = report.checks
    if raw_json:
        print(json.dumps(checks, ensure_ascii=False, indent=2))
    else:
        for name, item in checks.items():
            print(f"{str(item.get('status')):4}  {name:<18} {item.get('detail')}")
        steam = runtime.steam_process() if os.name == "nt" else None
        manager = UserPathManager(paths, WindowsRegistryPathBackend()) if os.name == "nt" else None
        updated = manager.managed_updated_at() if manager else None
        if steam and updated and runtime.process_started_before(steam, updated):
            print("WARN  steam_environment  Steam started before D4Planner PATH update; restart required")
    return 0 if report.ok else 1


def command_path(paths: RuntimePaths, action: str) -> int:
    if os.name != "nt":
        print("PATH management requires Windows.", file=sys.stderr)
        return 2
    manager = UserPathManager(paths, WindowsRegistryPathBackend())
    if action == "status":
        print("managed" if manager.is_present(paths.controller) else "not-managed")
        return 0
    change = manager.restore()
    print("User PATH restored." if change.changed else "User PATH already clean.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="d4planner")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start")
    start.add_argument("-d", "--detach", action="store_true")
    start.add_argument("--speech", action="store_true")
    start.add_argument("--isolated", action="store_true")
    start.add_argument("--timeout", type=float, default=120.0)

    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")

    logs = sub.add_parser("logs")
    logs.add_argument("-f", "--follow", action="store_true")
    logs.add_argument("--raw", action="store_true")
    logs.add_argument("--from-end", action="store_true")

    stop = sub.add_parser("stop")
    stop.add_argument("--timeout", type=float, default=10.0)

    doctor = sub.add_parser("doctor")
    doctor.add_argument("--json", action="store_true")

    path = sub.add_parser("path")
    path.add_argument("action", choices=("status", "restore"))

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = _paths()
    if args.command == "start":
        return command_start(
            paths,
            speech=args.speech,
            isolated=args.isolated,
            detached=args.detach,
            timeout=args.timeout,
        )
    if args.command == "status":
        return command_status(paths, raw_json=args.json)
    if args.command == "logs":
        return command_logs(paths, follow=args.follow, raw=args.raw, from_end=args.from_end)
    if args.command == "stop":
        return command_stop(paths, timeout=args.timeout)
    if args.command == "doctor":
        return command_doctor(paths, raw_json=args.json)
    if args.command == "path":
        return command_path(paths, args.action)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
