"""Standalone Windows diagnostic: observe and optionally suppress the F11 Steam Input marker.

Invocations from SSH automatically relay into the interactive game session.
This module does not change production InputMarkerCapture or write to SQLite.

Important: WH_KEYBOARD_LL cannot authenticate the source of F11. In --block
mode *physical* F11 is also suppressed while the selected game owns foreground.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import ctypes
from ctypes import wintypes
import json
import os
import re
import subprocess
from pathlib import Path
import sys
import time
import uuid

# Absolute import also works when invoked via the script path from SSH.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from d4planner.runtime.keyboard_hook import (
    BoundedSamples, Decision, F11Sample, HC_ACTION, KEY_STATES,
    VK_F11, WH_KEYBOARD_LL, WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP,
    WindowsF11Hook, capture_or_pass, decide_f11, require_game_pid,
    safe_capture_or_pass,
)


def run_diagnostic(*, pid: int, seconds: float, block: bool,
            jsonl: bool, diagnose: bool = False) -> int:
    if seconds <= 0 or seconds > 300:
        raise ValueError("--seconds must be > 0 and <= 300")
    require_game_pid(pid)
    if process_session_id(os.getpid()) != process_session_id(pid):
        raise RuntimeError("keyboard hook must run in the same interactive session as Diablo IV")
    print(f"F11 DIAGNOSTIC: PID={pid} mode={'BLOCK' if block else 'OBSERVE'} "
          f"duration={seconds:g}s; Ctrl+C stops", flush=True)
    print("WARNING: --block also intercepts physical F11 while D4 is foreground; "
          "Steam Input provenance is not verified.", flush=True)
    with WindowsF11Hook(game_pid=pid, block=block, diagnose=diagnose) as hook:
        end = time.monotonic() + seconds
        try:
            while time.monotonic() < end:
                if not hook.pump():
                    break
                for sample in hook.samples.drain():
                    item = sample.as_dict()
                    if jsonl:
                        print(json.dumps(item, ensure_ascii=False), flush=True)
                    else:
                        print(f"[{item['timestamp']}] F11 {sample.state.upper()}"
                              f" injected={item['injected']} suppressed={sample.suppressed}"
                              f" foregroundPid={item['foregroundPid']}"
                              f" targetMatch={item['targetMatch']}", flush=True)
                time.sleep(0.01)
        except KeyboardInterrupt:
            print("Ctrl+C: stopping hook", flush=True)
        finally:
            hook.pump()
            for sample in hook.samples.drain():
                print(json.dumps(sample.as_dict(), ensure_ascii=False), flush=True)
            print(f"SUMMARY: keyboard_seen={hook.keyboard_seen} "
                  f"f11_seen={hook.f11_seen} "
                  f"f11_target={hook.f11_target} "
                  f"f11_other_foreground={hook.f11_other_foreground} "
                  f"queue_dropped={hook.samples.dropped} "
                  f"hook_errors={hook.hook_errors}", flush=True)
    return 0



# Control plane for SSH -> interactive Windows session.
# This uses the same Task Scheduler interactive principal approach as the
# D4Planner supervisor/input-marker-probe, but keeps all changes inside keyboard diagnostics.
REMOTE_FINISHED = "F11_DIAGNOSTIC_COMPLETE"


def process_session_id(pid: int) -> int:
    """Retrieve the real Windows session for PID, not the SSH session."""
    if os.name != "nt":
        raise OSError("remote F11 diagnostic requires Windows")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = kernel32.ProcessIdToSessionId
    fn.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    fn.restype = wintypes.BOOL
    session = wintypes.DWORD()
    if not fn(int(pid), ctypes.byref(session)):
        raise OSError(ctypes.get_last_error(), f"ProcessIdToSessionId({pid}) failed")
    return int(session.value)


def active_console_session_id() -> int:
    if os.name != "nt":
        raise OSError("remote F11 diagnostic requires Windows")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = kernel32.WTSGetActiveConsoleSessionId
    fn.argtypes = []
    fn.restype = wintypes.DWORD
    session = int(fn())
    if session == 0xFFFFFFFF:
        raise RuntimeError("no active Windows console session; cannot launch keyboard hook")
    return session


def remote_log_path(request_id: str) -> Path:
    root = os.environ.get("LOCALAPPDATA")
    if not root:
        raise RuntimeError("LOCALAPPDATA is not set; cannot safely store diagnostic logs")
    return Path(root) / "d4planner" / "state" / "keyboard-diagnostic" / f"f11-{request_id}.log"


def _powershell_quote(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def _run_powershell(code: str, *, timeout: float = 25.0) -> None:
    process = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", code],
        text=True, capture_output=True, timeout=timeout, check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(
            "Windows Scheduled Task failed: "
            + (process.stderr.strip() or process.stdout.strip())[:500]
        )


def scheduled_task_script(
    *, task_name: str, python_exe: str, script_path: str,
    game_pid: int, seconds: float, block: bool, jsonl: bool,
    diagnose: bool, log_path: Path,
) -> str:
    """Build one safely escaped interactive-task PowerShell invocation."""
    cmd = [
        script_path, "--pid", str(int(game_pid)), "--seconds", str(float(seconds)),
        "--interactive-worker", "--output", str(log_path),
    ]
    if block:
        cmd.append("--block")
    if jsonl:
        cmd.append("--jsonl")
    if diagnose:
        cmd.append("--diagnose")
    args = subprocess.list2cmdline(cmd)
    return (
        "$ErrorActionPreference='Stop';"
        f"$a=New-ScheduledTaskAction -Execute {_powershell_quote(python_exe)} "
        f"-Argument {_powershell_quote(args)} "
        f"-WorkingDirectory {_powershell_quote(str(Path(script_path).parent))};"
        "$u=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name;"
        "$p=New-ScheduledTaskPrincipal -UserId $u -LogonType Interactive -RunLevel Limited;"
        "$s=New-ScheduledTaskSettingsSet -Priority 4 "
        "-ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew "
        "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries;"
        "$d=New-ScheduledTask -Action $a -Principal $p -Settings $s;"
        f"Register-ScheduledTask -TaskName {_powershell_quote(task_name)} "
        "-InputObject $d -Force | Out-Null;"
        f"Start-ScheduledTask -TaskName {_powershell_quote(task_name)} "
        "-ErrorAction Stop;"
    )


def _remove_task(task_name: str) -> None:
    """Always stop a runaway hook on remote cancel, then unregister task."""
    name = _powershell_quote(task_name)
    script = (
        "$ErrorActionPreference='Stop';"
        f"$t=Get-ScheduledTask -TaskName {name} -ErrorAction SilentlyContinue;"
        "if($null -ne $t){"
        f" Stop-ScheduledTask -TaskName {name} -ErrorAction SilentlyContinue;"
        f" Unregister-ScheduledTask -TaskName {name} -Confirm:$false -ErrorAction Stop;"
        "}"
    )
    _run_powershell(script)


def _run_interactive_worker(*, pid: int, seconds: float, block: bool,
                            jsonl: bool, diagnose: bool, output: Path) -> int:
    """Executed by Task Scheduler under logged-on user; log is sole IPC."""
    output.parent.mkdir(parents=True, exist_ok=True)
    rc = 2
    with output.open("w", encoding="utf-8", buffering=1) as handle:
        with redirect_stdout(handle), redirect_stderr(handle):
            try:
                game_session = process_session_id(pid)
                worker_session = process_session_id(os.getpid())
                active_session = active_console_session_id()
                print(
                    f"DIAGNOSTIC_SESSION worker={worker_session} game={game_session} "
                    f"active={active_session}", flush=True
                )
                if worker_session != game_session or active_session != game_session:
                    raise RuntimeError("interactive task did not start on game's active desktop")
                rc = run_diagnostic(pid=pid, seconds=seconds, block=block,
                             jsonl=jsonl, diagnose=diagnose)
            except Exception as exc:
                print(f"DIAGNOSTIC ERROR: {type(exc).__name__}: {exc}", flush=True)
                rc = 2
            finally:
                # run_diagnostic unhooks before this completion marker is printed.
                print(f"{REMOTE_FINISHED} status={rc}", flush=True)
    return rc


def _relay_ssh_to_interactive(*, pid: int, seconds: float, block: bool,
                              jsonl: bool, diagnose: bool) -> int:
    """Session 0 controller; logs are streamed while hook runs in session 1."""
    current = process_session_id(os.getpid())
    game_session = process_session_id(pid)
    active = active_console_session_id()
    if game_session != active:
        raise RuntimeError(
            f"game session={game_session} is not active console={active}; "
            "refusing to start hook on an inactive desktop"
        )

    request_id = uuid.uuid4().hex[:16]
    task_name = f"D4Planner-F11-Diagnostic-{request_id}"
    output = remote_log_path(request_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    script_path = str(Path(__file__).resolve())
    print(
        f"RELAY: control_session={current} game_session={game_session} "
        f"active_console={active}; task={task_name}", flush=True
    )
    print(f"LOG_PATH: {output}", flush=True)
    # Run the standalone Python script by absolute path; it needs no PYTHONPATH
    # in the interactive Scheduled Task, unlike the SSH shell.
    ps = scheduled_task_script(
        task_name=task_name, python_exe=sys.executable,
        script_path=script_path, game_pid=pid, seconds=seconds,
        block=block, jsonl=jsonl, diagnose=diagnose, log_path=output,
    )
    try:
        _run_powershell(ps)
        start = time.monotonic()
        deadline = start + seconds + 25.0
        printed = 0
        while time.monotonic() < deadline:
            # Small diagnostic evidence file, read as UTF-8 every 200 ms to avoid
            # losing partial multibyte characters at the tail boundary.
            if output.exists():
                content = output.read_text(encoding="utf-8", errors="replace")
                if len(content) > printed:
                    print(content[printed:], end="", flush=True)
                    printed = len(content)
                match = re.search(
                    rf"(?m)^{re.escape(REMOTE_FINISHED)} status=(\d+)\s*$", content
                )
                if match:
                    return int(match.group(1))
            if time.monotonic() - start > 15.0 and not output.exists():
                raise RuntimeError(
                    "task did not create a worker log within 15s; "
                    "check logged-in user and Task Scheduler permissions"
                )
            time.sleep(0.2)
        raise RuntimeError(
            f"interactive worker timed out; partial log preserved at {output}"
        )
    except KeyboardInterrupt:
        print("SSH controller interrupted; stopping scheduled diagnostic", flush=True)
        return 130
    finally:
        # A closed SSH connection cannot guarantee cleanup after a hard kill;
        # workers also enforce a max 300-second duration and unhook on exit.
        try:
            _remove_task(task_name)
        except Exception as exc:
            print(f"WARNING: could not remove scheduled task: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", required=True, type=int, help="Diablo IV.exe process ID")
    parser.add_argument("--seconds", type=float, default=30.0)
    parser.add_argument("--block", action="store_true",
                        help="Opt-in: swallow F11 ONLY when Diablo IV is foreground")
    parser.add_argument("--jsonl", action="store_true", help="Print newline JSON events")
    parser.add_argument("--diagnose", action="store_true",
                        help="Also log F11 outside game foreground and count all keyboard events")
    parser.add_argument("--interactive-worker", action="store_true",
                        help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if not 0 < args.seconds <= 300:
            raise ValueError("--seconds must be > 0 and <= 300")
        if args.pid <= 0:
            raise ValueError("--pid must be positive")
        require_game_pid(args.pid)
        if args.interactive_worker:
            if args.output is None:
                raise ValueError("internal worker requires --output")
            return _run_interactive_worker(
                pid=args.pid, seconds=args.seconds, block=args.block,
                jsonl=args.jsonl, diagnose=args.diagnose, output=args.output,
            )
        if args.output is not None:
            raise ValueError("--output is reserved for the interactive worker")
        current_session = process_session_id(os.getpid())
        game_session = process_session_id(args.pid)
        if current_session != game_session:
            return _relay_ssh_to_interactive(
                pid=args.pid, seconds=args.seconds, block=args.block,
                jsonl=args.jsonl, diagnose=args.diagnose,
            )
        if game_session != active_console_session_id():
            raise RuntimeError("game is not in the active console session")
        return run_diagnostic(pid=args.pid, seconds=args.seconds, block=args.block,
                       jsonl=args.jsonl, diagnose=args.diagnose)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"DIAGNOSTIC ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
