"""Background D4Planner supervisor entry point."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from pathlib import Path

from .runtime.pathing import UserPathManager, WindowsRegistryPathBackend
from .runtime.store import RuntimePaths, atomic_write_json, iso_now
from .runtime.supervisor import Supervisor
from .controller import load_profile, ProfileValidationError
from .runtime.windows import WindowsRuntime
from .runtime.equipment_layout_channel import LayoutInbox


def _watch_owner(stop_event: threading.Event, finished: threading.Event, fd: int, on_data=None) -> None:
    """Observe lifetime-pipe EOF without holding Python's buffered-stdin lock.

    Poll so a normal/failed startup can join this thread while the owner still
    holds its pipe open. Only this thread reads the raw descriptor.
    """
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            import msvcrt

            peek = ctypes.WinDLL("kernel32", use_last_error=True).PeekNamedPipe
            peek.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                             ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
            peek.restype = wintypes.BOOL
            handle = msvcrt.get_osfhandle(fd)
            while not finished.is_set():
                available = wintypes.DWORD()
                if not peek(handle, None, 0, None, ctypes.byref(available), None):
                    # Broken pipe or an unqueryable owner: fail closed.
                    stop_event.set()
                    return
                if available.value:
                    chunk = os.read(fd, min(available.value, 4096))
                    if not chunk:
                        stop_event.set()
                        return
                    if on_data is not None:
                        on_data(chunk)
                finished.wait(.05)
        else:
            import select
            while not finished.is_set():
                readable, _, _ = select.select([fd], [], [], .05)
                if readable:
                    chunk = os.read(fd, 4096)
                    if not chunk:
                        stop_event.set()
                        return
                    if on_data is not None:
                        on_data(chunk)
    except (OSError, ValueError):
        stop_event.set()


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


def _acquire_singleton(paths: RuntimePaths) -> Path | None:
    paths.ensure()
    lock = paths.state / "supervisor.lock"
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                old_pid = int(lock.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                old_pid = 0
            if old_pid and _pid_alive(old_pid):
                return None
            try:
                lock.unlink()
            except FileNotFoundError:
                pass
            continue
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(str(os.getpid()))
                handle.write("\n")
            return lock
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="d4planner-daemon")
    parser.add_argument("--owner-token", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--managed-by-hud", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--speech", action="store_true", help="Pass D4 speech through NVDA")
    parser.add_argument("--isolated", action="store_true", help="Use process-scoped controller discovery")
    parser.add_argument("--block", action="store_true", help="Use keyboard hook capture and suppression")
    parser.add_argument("--controller-profile", default=None)
    # Explicit run-scoped home for Task Scheduler: it does not inherit the SSH
    # caller's D4PLANNER_HOME. Required for PR95 isolated Real-A acceptance.
    parser.add_argument("--home", type=Path, default=None)
    parser.add_argument("--uat-attach-only", action="store_true",
                        help="Attach to already-running Steam/NVDA/D4 without process restart")
    parser.add_argument("--game-start-timeout", type=float, default=90.0)
    args = parser.parse_args(argv)
    if args.uat_attach_only and (not args.isolated or args.home is None):
        parser.error("--uat-attach-only requires --home and --isolated")
    try:
        profile = load_profile(args.controller_profile) if args.controller_profile else None
    except ProfileValidationError as exc:
        parser.error(str(exc))

    from .runtime.storage import resolve_root
    environment = None
    if args.home is not None and args.isolated:
        # --home plus --isolated is an explicit authorized isolated lifecycle.
        environment = {key: value for key, value in os.environ.items() if key not in {
            "D4PLANNER_HOME", "D4PLANNER_DATA_ROOT", "D4PLANNER_DATA_DIR",
            "D4_RULEKIT_DATA_ROOT", "D4_LOG_DIR", "D4_LOG_RUN_ID"}}
    paths = RuntimePaths(resolve_root(args.home, environment=environment))
    lock = _acquire_singleton(paths)
    if lock is None:
        return 5

    watcher = None
    finished = threading.Event()
    try:
        stop_event = threading.Event()
        layout_inbox = LayoutInbox(args.owner_token) if args.managed_by_hud else None
        if args.managed_by_hud:
            # EOF is owner death. Never use a shared stop file to stop another owner.
            watcher = threading.Thread(target=_watch_owner,
                args=(stop_event, finished, sys.stdin.fileno(), layout_inbox.feed), name="capture-owner")
            watcher.start()
        runtime = WindowsRuntime(paths)
        runtime.managed_by_hud = args.managed_by_hud
        path_manager = UserPathManager(paths, WindowsRegistryPathBackend())
        supervisor = Supervisor(
            equipment_layout_inbox=layout_inbox,
            managed_by_hud=args.managed_by_hud,
            stop_event=stop_event,
            paths=paths,
            runtime=runtime,
            path_manager=path_manager,
            silent=not args.speech,
            isolated=args.isolated,
            block_marker=args.block,
            controller_profile=profile,
            uat_attach_only=args.uat_attach_only,
            game_start_timeout=args.game_start_timeout,
        )
        if args.managed_by_hud:
            supervisor.status.extras["runtime"]["ownerToken"] = args.owner_token
        return supervisor.run()
    except Exception as error:
        if not args.managed_by_hud:
            raise
        # Constructor failures happen before Supervisor can persist a status.
        # Record a terminal reason bound to this owner; never claim readiness.
        atomic_write_json(paths.runtime_state, {
            "state": "BLOCKED", "updatedAt": iso_now(),
            "detail": "Capture runtime failed", "lastError": f"{type(error).__name__}: {error}",
            "supervisorPid": os.getpid(), "captureActive": False,
            "extras": {"runtime": {"ownerToken": args.owner_token}},
        })
        return 2
    finally:
        finished.set()
        if watcher is not None:
            watcher.join()
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
