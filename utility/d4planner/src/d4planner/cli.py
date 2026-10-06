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
from .runtime.store import RuntimePaths, read_json, write_capture_config
from .runtime.windows import WindowsRuntime


TERMINAL_STATES = {
    RuntimeState.RUNNING.value,
    RuntimeState.WAITING_FOR_GAME.value,
    RuntimeState.RESTART_REQUIRED.value,
    RuntimeState.BLOCKED.value,
    RuntimeState.DEGRADED.value,
}

ACTIVE_STATES = {
    RuntimeState.BOOTSTRAPPING.value,
    RuntimeState.NVDA_READY.value,
    RuntimeState.TOLK_READY.value,
    RuntimeState.GAME_STARTING.value,
    RuntimeState.GAME_ATTACHED.value,
    RuntimeState.CAPTURE_READY.value,
    RuntimeState.RUNNING.value,
    RuntimeState.WAITING_FOR_GAME.value,
    RuntimeState.DEGRADED.value,
}


def _paths() -> RuntimePaths:
    override = os.environ.get("D4PLANNER_HOME")
    return RuntimePaths(Path(override)) if override else RuntimePaths.default()


def _pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) is not a harmless existence probe on Windows.
        # Query the process handle instead so status/singleton checks can never
        # terminate the process being inspected.
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            int(pid),
        )
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return int(exit_code.value) == STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _capture_effective(paths: RuntimePaths) -> bool:
    config = read_json(paths.capture_state) or {}
    if not config.get("enabled"):
        return False
    try:
        lease_until = float(config.get("leaseUntilUnix") or 0)
    except (TypeError, ValueError):
        return False
    return lease_until > time.time()


def _state(paths: RuntimePaths) -> dict[str, Any]:
    state = dict(
        read_json(paths.runtime_state)
        or {
            "state": RuntimeState.STOPPED.value,
            "captureActive": False,
        }
    )
    pid = state.get("supervisorPid")
    alive = _pid_alive(int(pid)) if pid else False
    state["supervisorAlive"] = alive
    state["captureEffective"] = _capture_effective(paths)
    return state


def _spawn_daemon(paths: RuntimePaths, *, speech: bool, isolated: bool) -> int:
    if os.name == "nt":
        previous = read_json(paths.runtime_state) or {}
        previous_pid = previous.get("supervisorPid")
        runtime = WindowsRuntime(paths)
        runtime.launch_supervisor_task(speech=speech, isolated=isolated)
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            current = read_json(paths.runtime_state) or {}
            pid = current.get("supervisorPid")
            if pid and pid != previous_pid and _pid_alive(int(pid)):
                return int(pid)
            time.sleep(0.1)
        raise RuntimeError("scheduled supervisor did not publish a live PID within 15s")

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
        owner_pid = status.get("supervisorPid")
        try:
            owned_by_new_daemon = int(owner_pid) == int(pid)
        except (TypeError, ValueError):
            owned_by_new_daemon = False

        if owned_by_new_daemon:
            current = str(status.get("state") or "")
            if current != last_state and current:
                detail = str(status.get("detail") or "")
                print(f"[{current}] {detail}".rstrip())
                last_state = current
            if current in TERMINAL_STATES:
                return status

        if not _pid_alive(pid):
            return {
                "state": RuntimeState.BLOCKED.value,
                "detail": "supervisor exited before publishing a terminal runtime state",
                "lastError": f"supervisor PID {pid} exited during bootstrap",
                "supervisorPid": pid,
                "captureActive": False,
            }
        time.sleep(0.25)

    status = _state(paths)
    if status.get("supervisorPid") == pid:
        return status
    return {
        "state": RuntimeState.BLOCKED.value,
        "detail": "timed out waiting for the new supervisor runtime state",
        "lastError": f"supervisor PID {pid} did not publish state within {timeout:g}s",
        "supervisorPid": pid,
        "captureActive": False,
    }


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
    except (KeyboardInterrupt, BrokenPipeError):
        # SSH/stdout disconnect detaches this viewer only; the supervisor owns
        # capture state independently and must keep running.
        return 0
    return 0


def command_status(paths: RuntimePaths, *, raw_json: bool) -> int:
    status = _state(paths)
    if raw_json:
        print(json.dumps(status, ensure_ascii=False, indent=2))
        state = str(status.get("state") or "")
        if state in ACTIVE_STATES and not status.get("supervisorAlive"):
            return 2
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
        (
            "Capture",
            "ACTIVE"
            if status.get("captureEffective")
            else ("STALE" if status.get("captureActive") else "INACTIVE"),
        ),
        ("Mode", "silent" if status.get("silent", True) else "speech"),
        ("Session", status.get("sessionId") or "-"),
        ("Last event", status.get("lastEventAt") or "-"),
    ]
    width = max(len(key) for key, _ in rows)
    for key, value in rows:
        print(f"{key:<{width}}  {value}")
    state = str(status.get("state") or "")
    if state in ACTIVE_STATES and not status.get("supervisorAlive"):
        print("Warning: runtime state is stale; supervisor process is not running.", file=sys.stderr)
        return 2
    if state == RuntimeState.BLOCKED.value:
        return 2
    if state == RuntimeState.RESTART_REQUIRED.value:
        return 3
    return 0


def _print_start_summary(status: dict[str, Any]) -> None:
    nvda = status.get("nvda") if isinstance(status.get("nvda"), dict) else {}
    steam = status.get("steam") if isinstance(status.get("steam"), dict) else {}
    game = status.get("game") if isinstance(status.get("game"), dict) else {}
    tolk = status.get("tolk") if isinstance(status.get("tolk"), dict) else {}
    checks = [
        ("Runtime", status.get("state") in {"RUNNING", "WAITING_FOR_GAME", "DEGRADED"}, status.get("state")),
        ("NVDA", bool(nvda), f"PID {nvda.get('pid')}" if nvda else "not running"),
        ("Tolk backend", str(tolk.get("reader") or "").casefold() == "nvda", tolk.get("reader") or "unknown"),
        ("Steam", bool(steam), f"PID {steam.get('pid')}" if steam else "not running"),
        ("Diablo IV", bool(game), f"PID {game.get('pid')}" if game else "waiting"),
        ("Capture", bool(status.get("captureActive")), "ACTIVE" if status.get("captureActive") else "INACTIVE"),
    ]
    for name, ok, detail in checks:
        # SSH/non-TTY Windows shells commonly expose CP1252. Keep lifecycle
        # summaries ASCII so a successful start cannot fail while printing.
        mark = "[OK]" if ok else "[--]"
        print(f"{mark} {name}: {detail}")


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
            current_silent = bool(previous.get("silent", True))
            requested_silent = not speech
            if current_silent != requested_silent:
                current_mode = "silent" if current_silent else "speech"
                requested_mode = "silent" if requested_silent else "speech"
                print(
                    f"D4Planner is already running in {current_mode} mode; "
                    f"requested {requested_mode}. Run 'd4planner stop' first.",
                    file=sys.stderr,
                )
                return 4
            print(f"D4Planner already running (PID {previous_pid}, state {state}).")
            if detached:
                return 0
            return command_logs(paths, follow=True, raw=False, from_end=True)

    try:
        paths.stop_request.unlink()
    except FileNotFoundError:
        pass

    try:
        pid = _spawn_daemon(paths=paths, speech=speech, isolated=isolated)
    except (RuntimeError, OSError) as exc:
        print(f"Unable to start D4Planner supervisor: {exc}", file=sys.stderr)
        return 4
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
    print()
    _print_start_summary(status)
    if detached:
        return 0
    print("\n── D4Planner live events (Ctrl+C = detach only) ──")
    return command_logs(paths, follow=True, raw=False, from_end=True)


def command_stop(paths: RuntimePaths, *, timeout: float = 10.0) -> int:
    status = _state(paths)
    pid = status.get("supervisorPid")
    if not pid or not _pid_alive(int(pid)):
        # A crashed supervisor may have left a still-valid short capture lease.
        # Disable it explicitly so NVDA immediately returns to passthrough.
        write_capture_config(paths, enabled=False)
        print("D4Planner supervisor is not running; capture is disabled.")
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
    checks = dict(report.checks)

    status = _state(paths)
    state = str(status.get("state") or RuntimeState.STOPPED.value)
    alive = bool(status.get("supervisorAlive"))
    capture_effective = bool(status.get("captureEffective"))
    active = state in ACTIVE_STATES

    checks["supervisor"] = {
        "status": "PASS" if (alive or not active) else "FAIL",
        "detail": {
            "state": state,
            "pid": status.get("supervisorPid"),
            "alive": alive,
        },
    }

    session_dir = status.get("sessionDir")
    session_exists = bool(session_dir and Path(str(session_dir)).is_dir())
    checks["session"] = {
        "status": "PASS" if session_exists else ("FAIL" if active else "WARN"),
        "detail": session_dir or "no active/recent session",
    }

    requires_capture = state in {
        RuntimeState.CAPTURE_READY.value,
        RuntimeState.RUNNING.value,
        RuntimeState.WAITING_FOR_GAME.value,
        RuntimeState.DEGRADED.value,
    }
    checks["capture_lease"] = {
        "status": "PASS" if capture_effective else ("FAIL" if requires_capture else "WARN"),
        "detail": {
            "effective": capture_effective,
            "configuredActive": bool(status.get("captureActive")),
        },
    }

    last_event = status.get("lastEventAt")
    checks["last_event"] = {
        "status": "PASS" if last_event else "WARN",
        "detail": last_event or "no speech event captured in this session yet",
    }

    stale = False
    if os.name == "nt":
        steam = runtime.steam_process()
        manager = UserPathManager(paths, WindowsRegistryPathBackend())
        updated = manager.managed_updated_at()
        stale = bool(steam and updated and runtime.process_started_before(steam, updated))
        checks["steam_environment"] = {
            "status": "FAIL" if stale else "PASS",
            "detail": (
                "Steam started before D4Planner PATH update; exit Steam normally and retry"
                if stale
                else "environment generation is current"
            ),
        }

    if raw_json:
        print(json.dumps(checks, ensure_ascii=False, indent=2))
    else:
        for name, item in checks.items():
            print(f"{str(item.get('status')):4}  {name:<18} {item.get('detail')}")

    overall_ok = all(item.get("status") != "FAIL" for item in checks.values())
    return 0 if overall_ok else 1


def command_path(paths: RuntimePaths, action: str) -> int:
    if os.name != "nt":
        print("PATH management requires Windows.", file=sys.stderr)
        return 2
    manager = UserPathManager(paths, WindowsRegistryPathBackend())
    if action == "status":
        print("managed" if manager.is_present(paths.controller) else "not-managed")
        return 0

    status = _state(paths)
    if status.get("supervisorAlive") and str(status.get("state") or "") in ACTIVE_STATES:
        print(
            "Refusing to restore User PATH while D4Planner is active. "
            "Run 'd4planner stop' first.",
            file=sys.stderr,
        )
        return 4

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


def _configure_console_streams() -> None:
    """Keep non-TTY Windows shells from crashing on non-CP1252 speech text."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(errors="backslashreplace")
            except (OSError, ValueError):
                pass


def main(argv: list[str] | None = None) -> int:
    _configure_console_streams()
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
