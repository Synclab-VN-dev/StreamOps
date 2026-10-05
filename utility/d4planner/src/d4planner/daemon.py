"""Background D4Planner supervisor entry point."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .runtime.pathing import UserPathManager, WindowsRegistryPathBackend
from .runtime.store import RuntimePaths
from .runtime.supervisor import Supervisor
from .runtime.windows import WindowsRuntime


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
    parser.add_argument("--speech", action="store_true", help="Pass D4 speech through NVDA")
    parser.add_argument("--isolated", action="store_true", help="Use process-scoped controller discovery")
    parser.add_argument("--game-start-timeout", type=float, default=90.0)
    args = parser.parse_args(argv)

    paths = RuntimePaths.default()
    lock = _acquire_singleton(paths)
    if lock is None:
        return 5

    try:
        runtime = WindowsRuntime(paths)
        path_manager = UserPathManager(paths, WindowsRegistryPathBackend())
        supervisor = Supervisor(
            paths=paths,
            runtime=runtime,
            path_manager=path_manager,
            silent=not args.speech,
            isolated=args.isolated,
            game_start_timeout=args.game_start_timeout,
        )
        return supervisor.run()
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
