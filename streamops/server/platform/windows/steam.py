"""Native Windows integration for inspecting and restarting Steam."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from datetime import UTC, datetime
import os
from pathlib import Path
import subprocess
import time
from typing import Iterator

try:
    import winreg
except ImportError:  # pragma: no cover - imported only for cross-platform test collection
    winreg = None  # type: ignore[assignment]

from ...errors import (
    SteamLaunchError,
    SteamNotFoundError,
    SteamShutdownError,
    SteamShutdownTimeoutError,
    SteamStatusError,
    WrongDesktopSessionError,
)
from ...services.steam import SteamStatus
from .session import NO_ACTIVE_CONSOLE_SESSION, desktop_session_info


TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
WINDOWS_TO_UNIX_EPOCH_100NS = 116_444_736_000_000_000


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def _kernel32():
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(PROCESSENTRY32W),
    ]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(PROCESSENTRY32W),
    ]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.ProcessIdToSessionId.argtypes = [
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.ProcessIdToSessionId.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


@dataclass(frozen=True)
class SteamProcess:
    pid: int
    path: Path | None
    started_at_timestamp: float | None
    session_id: int | None


class WindowsSteamBackend:
    def __init__(
        self,
        *,
        shutdown_timeout: float = 30.0,
        launch_timeout: float = 30.0,
        poll_interval: float = 0.5,
    ) -> None:
        self.shutdown_timeout = shutdown_timeout
        self.launch_timeout = launch_timeout
        self.poll_interval = poll_interval

    def status(self) -> SteamStatus:
        processes = self._steam_processes()
        executable = self.resolve_installation(processes=processes, required=False)
        process = self._select_process(processes, executable)
        return self._status_for_process(process, executable is not None)

    def restart(self) -> SteamStatus:
        session = desktop_session_info()
        if not session.is_interactive:
            raise WrongDesktopSessionError(
                session.current_session_id,
                session.active_console_session_id,
                operation="Steam restart",
            )

        old_processes = self._steam_processes()
        executable = self.resolve_installation(processes=old_processes, required=True)
        assert executable is not None
        old_pids = {process.pid for process in old_processes}
        excluded_pids = set(old_pids)

        if old_pids:
            shutdown_process = self._spawn(executable, "-shutdown", SteamShutdownError)
            excluded_pids.add(shutdown_process.pid)
            if not self._wait_until_stopped(old_pids):
                raise SteamShutdownTimeoutError(
                    f"Steam did not exit within {self.shutdown_timeout:g} seconds; it was not force-killed."
                )

        launch_process = self._spawn(executable, "-bigpicture", SteamLaunchError)
        process = self._wait_for_new_process(
            executable,
            excluded_pids,
            session.active_console_session_id,
            preferred_pid=launch_process.pid,
        )
        if process is None:
            raise SteamLaunchError(
                f"Steam was launched with Big Picture requested but no process appeared "
                f"in interactive session {session.active_console_session_id} within "
                f"{self.launch_timeout:g} seconds."
            )
        return self._status_for_process(process, installation_detected=True)

    def resolve_installation(
        self,
        *,
        processes: list[SteamProcess] | None = None,
        required: bool,
    ) -> Path | None:
        for candidate in self._registry_candidates():
            executable = self._validate_executable(candidate)
            if executable is not None:
                return executable

        for process in processes if processes is not None else self._steam_processes():
            executable = self._validate_executable(process.path)
            if executable is not None:
                return executable

        if required:
            raise SteamNotFoundError(
                "Steam installation was not found in the Windows registry or running process metadata."
            )
        return None

    def _status_for_process(
        self,
        process: SteamProcess | None,
        installation_detected: bool,
    ) -> SteamStatus:
        if process is None:
            return SteamStatus(
                state="stopped",
                running=False,
                pid=None,
                started_at=None,
                uptime_seconds=None,
                session_id=None,
                interactive=False,
                installation_detected=installation_detected,
            )
        if process.started_at_timestamp is None or process.session_id is None:
            raise SteamStatusError(
                f"Steam process {process.pid} was found but its start time or Windows session could not be read."
            )
        session = desktop_session_info()
        started_at = datetime.fromtimestamp(process.started_at_timestamp, UTC).astimezone()
        return SteamStatus(
            state="running",
            running=True,
            pid=process.pid,
            started_at=started_at.isoformat(),
            uptime_seconds=max(0, int(time.time() - process.started_at_timestamp)),
            session_id=process.session_id,
            interactive=(
                session.active_console_session_id != NO_ACTIVE_CONSOLE_SESSION
                and process.session_id == session.active_console_session_id
            ),
            installation_detected=installation_detected,
        )

    def _registry_candidates(self) -> Iterator[Path]:
        if winreg is None:
            return
        locations = [
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", 0),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", winreg.KEY_WOW64_32KEY),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", winreg.KEY_WOW64_64KEY),
        ]
        for hive, key_name, view in locations:
            try:
                with winreg.OpenKey(hive, key_name, 0, winreg.KEY_READ | view) as key:
                    values = {}
                    for value_name in ("SteamExe", "InstallPath", "SteamPath"):
                        try:
                            values[value_name] = winreg.QueryValueEx(key, value_name)[0]
                        except OSError:
                            pass
            except OSError:
                continue
            steam_exe = values.get("SteamExe")
            if steam_exe:
                yield Path(str(steam_exe))
            for value_name in ("InstallPath", "SteamPath"):
                install_path = values.get(value_name)
                if install_path:
                    yield Path(str(install_path)) / "steam.exe"

    def _steam_processes(self) -> list[SteamProcess]:
        if os.name != "nt":
            raise SteamStatusError("Steam process inspection is supported only on Windows.")
        kernel32 = _kernel32()
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == INVALID_HANDLE_VALUE:
            raise SteamStatusError("Windows could not create a process snapshot for Steam status.")
        processes: list[SteamProcess] = []
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        try:
            has_entry = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while has_entry:
                if entry.szExeFile.casefold() == "steam.exe":
                    processes.append(self._read_process(int(entry.th32ProcessID)))
                has_entry = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
        return processes

    def _read_process(self, pid: int) -> SteamProcess:
        kernel32 = _kernel32()
        session_id = wintypes.DWORD()
        session = (
            int(session_id.value)
            if kernel32.ProcessIdToSessionId(pid, ctypes.byref(session_id))
            else None
        )
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return SteamProcess(pid, None, None, session)
        try:
            path_buffer = ctypes.create_unicode_buffer(32768)
            path_size = wintypes.DWORD(len(path_buffer))
            path = (
                Path(path_buffer.value)
                if kernel32.QueryFullProcessImageNameW(
                    handle, 0, path_buffer, ctypes.byref(path_size)
                )
                else None
            )
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel_time = wintypes.FILETIME()
            user_time = wintypes.FILETIME()
            started_at = None
            if kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel_time),
                ctypes.byref(user_time),
            ):
                filetime = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
                started_at = (filetime - WINDOWS_TO_UNIX_EPOCH_100NS) / 10_000_000
            return SteamProcess(pid, path, started_at, session)
        finally:
            kernel32.CloseHandle(handle)

    def _select_process(
        self,
        processes: list[SteamProcess],
        executable: Path | None,
    ) -> SteamProcess | None:
        if not processes:
            return None
        if executable is not None:
            matching = [
                process
                for process in processes
                if process.path is not None and self._same_path(process.path, executable)
            ]
            if matching:
                processes = matching
        return min(
            processes,
            key=lambda process: (
                process.started_at_timestamp
                if process.started_at_timestamp is not None
                else float("inf"),
                process.pid,
            ),
        )

    def _wait_until_stopped(self, pids: set[int]) -> bool:
        deadline = time.monotonic() + self.shutdown_timeout
        while True:
            running_pids = {process.pid for process in self._steam_processes()}
            if pids.isdisjoint(running_pids):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(self.poll_interval)

    def _wait_for_new_process(
        self,
        executable: Path,
        excluded_pids: set[int],
        active_session_id: int,
        *,
        preferred_pid: int,
    ) -> SteamProcess | None:
        deadline = time.monotonic() + self.launch_timeout
        while True:
            candidates = [
                process
                for process in self._steam_processes()
                if process.pid not in excluded_pids
                and process.session_id == active_session_id
                and (process.path is None or self._same_path(process.path, executable))
            ]
            if candidates:
                preferred = next(
                    (process for process in candidates if process.pid == preferred_pid),
                    None,
                )
                return preferred or self._select_process(candidates, executable)
            if time.monotonic() >= deadline:
                return None
            time.sleep(self.poll_interval)

    def _spawn(self, executable: Path, argument: str, error_type: type[Exception]):
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "NORMAL_PRIORITY_CLASS", 0x00000020
        )
        try:
            return subprocess.Popen(
                [str(executable), argument],
                cwd=str(executable.parent),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except OSError as exc:
            action = "request graceful shutdown from" if argument == "-shutdown" else "launch"
            raise error_type(f"Could not {action} Steam: {exc}") from exc

    @staticmethod
    def _validate_executable(candidate: Path | None) -> Path | None:
        if candidate is None or candidate.name.casefold() != "steam.exe":
            return None
        try:
            return candidate.resolve(strict=True) if candidate.is_file() else None
        except OSError:
            return None

    @staticmethod
    def _same_path(first: Path, second: Path) -> bool:
        return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(second))
