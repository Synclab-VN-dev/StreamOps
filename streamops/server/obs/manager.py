"""OBS process lifecycle and WebSocket readiness management for streamops-node."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any, Callable, Literal

from ..errors import (
    ObsExecutableNotAllowedError,
    ObsOperationInProgressError,
    ObsReadinessTimeoutError,
    ObsShutdownError,
    ObsShutdownTimeoutError,
    ObsStartError,
    ObsStartTimeoutError,
    ObsStatusError,
    ObsUnsafeOperationError,
    ObsWebSocketConnectionError,
    ObsWebSocketRequestError,
    WrongDesktopSessionError,
)
from ..platform.windows.session import (
    NO_ACTIVE_CONSOLE_SESSION,
    DesktopSessionInfo,
    desktop_session_info,
)
from .client import ObsClient


TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
WINDOWS_TO_UNIX_EPOCH_100NS = 116_444_736_000_000_000
WM_CLOSE = 0x0010
GW_OWNER = 4
SMTO_ABORTIFHUNG = 0x0002
DEFAULT_OBS_EXECUTABLE = Path(r"C:\Program Files\obs-studio\bin\64bit\obs64.exe")


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


@dataclass(frozen=True)
class ObsProcess:
    pid: int
    path: Path | None
    started_at_timestamp: float | None
    session_id: int | None


@dataclass(frozen=True)
class LastOperation:
    action: Literal["start", "stop", "restart"]
    result: Literal["success", "failed"]
    timestamp: str
    error: str | None = None


@dataclass(frozen=True)
class ObsRuntimeStatus:
    state: Literal["READY", "STARTING", "RUNNING_NO_WEBSOCKET", "STOPPED", "ERROR"]
    process: dict[str, Any]
    websocket: dict[str, Any]
    output: dict[str, Any]
    last_operation: dict[str, Any] | None
    error: str | None = None

    def api_payload(self) -> dict[str, Any]:
        return asdict(self)


class ObsManager:
    """Own OBS process lifecycle and derive readiness from process + WebSocket state."""

    def __init__(
        self,
        *,
        client_factory: Callable[[], ObsClient] = ObsClient.from_env,
        start_timeout: float = 30.0,
        shutdown_timeout: float = 15.0,
        readiness_timeout: float = 30.0,
        poll_interval: float = 0.5,
        executable: Path | None = None,
    ) -> None:
        configured = executable or Path(
            os.environ.get("STREAMOPS_OBS_EXECUTABLE", str(DEFAULT_OBS_EXECUTABLE))
        )
        self.expected_executable = configured.expanduser().resolve(strict=False)
        self.client_factory = client_factory
        self.start_timeout = start_timeout
        self.shutdown_timeout = shutdown_timeout
        self.readiness_timeout = readiness_timeout
        self.poll_interval = poll_interval
        self._operation_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._active_operation: str | None = None
        self._last_operation: LastOperation | None = None

    def status(self) -> ObsRuntimeStatus:
        return self._status_impl(include_operation=True)

    def start(self) -> ObsRuntimeStatus:
        return self._run_operation("start", self._start_locked)

    def stop(self) -> ObsRuntimeStatus:
        return self._run_operation("stop", self._stop_locked)

    def restart(self) -> ObsRuntimeStatus:
        def restart_locked() -> ObsRuntimeStatus:
            self._stop_locked()
            return self._start_locked()

        return self._run_operation("restart", restart_locked)

    def _run_operation(
        self,
        action: Literal["start", "stop", "restart"],
        operation: Callable[[], ObsRuntimeStatus],
    ) -> ObsRuntimeStatus:
        if not self._operation_lock.acquire(blocking=False):
            raise ObsOperationInProgressError("Another OBS lifecycle operation is already in progress.")
        with self._state_lock:
            self._active_operation = action
        try:
            operation()
        except Exception as exc:
            self._remember_operation(action, "failed", str(exc))
            raise
        else:
            self._remember_operation(action, "success", None)
            return self._status_impl(include_operation=False)
        finally:
            with self._state_lock:
                self._active_operation = None
            self._operation_lock.release()

    def _start_locked(self) -> ObsRuntimeStatus:
        status = self._status_impl(include_operation=False)
        if status.state == "READY":
            return status

        if status.process["running"]:
            if status.state == "ERROR":
                raise ObsStartError(status.error or "OBS process is not safe to manage.")
            return self._wait_for_ready()

        session = self._session_info()
        if not session.is_interactive:
            raise WrongDesktopSessionError(
                session.current_session_id,
                session.active_console_session_id,
                operation="OBS start",
            )

        executable = self._resolve_executable(required=True)
        assert executable is not None
        launched = self._launch(executable)
        process = self._wait_for_process(
            excluded_pids=set(),
            active_session_id=session.active_console_session_id,
            preferred_pid=launched.pid,
        )
        if process is None:
            raise ObsStartTimeoutError(
                f"OBS did not appear in active console session {session.active_console_session_id} "
                f"within {self.start_timeout:g} seconds."
            )
        return self._wait_for_ready()

    def _stop_locked(self) -> ObsRuntimeStatus:
        status = self._status_impl(include_operation=False)
        if status.state == "STOPPED":
            return status
        if status.state != "READY":
            raise ObsUnsafeOperationError(
                "OBS cannot be stopped safely unless WebSocket readiness is available."
            )
        if status.output["streaming"]:
            raise ObsUnsafeOperationError("OBS stop is blocked while streaming is active.")
        if status.output["recording"]:
            raise ObsUnsafeOperationError("OBS stop is blocked while recording is active.")

        pid = int(status.process["pid"])
        close_target = self._request_graceful_close(pid)
        if not self._wait_until_stopped({pid}):
            detail = f" Targeted {close_target}." if close_target else ""
            raise ObsShutdownTimeoutError(
                f"OBS did not exit within {self.shutdown_timeout:g} seconds; "
                f"it was not force-killed.{detail}"
            )
        return self._status_impl(include_operation=False)

    def _wait_for_ready(self) -> ObsRuntimeStatus:
        deadline = time.monotonic() + self.readiness_timeout
        last = self._status_impl(include_operation=False)
        while True:
            if last.state == "READY":
                return last
            if not last.process["running"]:
                raise ObsStartError("OBS exited before WebSocket became ready.")
            if last.state == "ERROR":
                raise ObsStartError(last.error or "OBS entered an error state while starting.")
            if time.monotonic() >= deadline:
                raise ObsReadinessTimeoutError(
                    f"OBS process is running but WebSocket did not become ready within "
                    f"{self.readiness_timeout:g} seconds."
                )
            time.sleep(self.poll_interval)
            last = self._status_impl(include_operation=False)

    def _status_impl(self, *, include_operation: bool) -> ObsRuntimeStatus:
        session = self._session_info()
        processes = self._obs_processes()
        allowed = [
            process
            for process in processes
            if process.path is not None and self._same_path(process.path, self.expected_executable)
        ]
        disallowed = [process for process in processes if process not in allowed]

        if disallowed:
            return self._build_status(
                state="ERROR",
                process=disallowed[0],
                session=session,
                websocket=self._disconnected_websocket(),
                output={"streaming": None, "recording": None},
                error=(
                    "OBS process was found outside the server-side allowed executable path "
                    f"{self.expected_executable}."
                ),
                include_operation=include_operation,
            )

        if not allowed:
            return self._build_status(
                state="STOPPED",
                process=None,
                session=session,
                websocket=self._disconnected_websocket(),
                output={"streaming": False, "recording": False},
                error=None,
                include_operation=include_operation,
            )

        if len(allowed) > 1:
            return self._build_status(
                state="ERROR",
                process=allowed[0],
                session=session,
                websocket=self._disconnected_websocket(),
                output={"streaming": None, "recording": None},
                error=f"Multiple managed OBS processes are running: {[p.pid for p in allowed]}.",
                include_operation=include_operation,
            )

        process = allowed[0]
        if process.session_id is None:
            return self._build_status(
                state="ERROR",
                process=process,
                session=session,
                websocket=self._disconnected_websocket(),
                output={"streaming": None, "recording": None},
                error=f"OBS process {process.pid} Windows session could not be read.",
                include_operation=include_operation,
            )
        if (
            session.active_console_session_id == NO_ACTIVE_CONSOLE_SESSION
            or process.session_id != session.active_console_session_id
        ):
            return self._build_status(
                state="ERROR",
                process=process,
                session=session,
                websocket=self._disconnected_websocket(),
                output={"streaming": None, "recording": None},
                error=(
                    f"OBS process session {process.session_id} does not match active console "
                    f"session {session.active_console_session_id}."
                ),
                include_operation=include_operation,
            )

        websocket, output, websocket_error = self._websocket_status()
        state: Literal["READY", "STARTING", "RUNNING_NO_WEBSOCKET", "STOPPED", "ERROR"]
        state = "READY" if websocket["connected"] else "RUNNING_NO_WEBSOCKET"
        return self._build_status(
            state=state,
            process=process,
            session=session,
            websocket=websocket,
            output=output,
            error=websocket_error,
            include_operation=include_operation,
        )

    def _build_status(
        self,
        *,
        state: Literal["READY", "STARTING", "RUNNING_NO_WEBSOCKET", "STOPPED", "ERROR"],
        process: ObsProcess | None,
        session: DesktopSessionInfo,
        websocket: dict[str, Any],
        output: dict[str, Any],
        error: str | None,
        include_operation: bool,
    ) -> ObsRuntimeStatus:
        started_at = None
        uptime = None
        if process and process.started_at_timestamp is not None:
            started_at = datetime.fromtimestamp(process.started_at_timestamp, UTC).astimezone().isoformat()
            uptime = max(0, int(time.time() - process.started_at_timestamp))

        with self._state_lock:
            last = asdict(self._last_operation) if self._last_operation else None
            active = self._active_operation

        if (
            include_operation
            and active in {"start", "restart"}
            and state in {"STOPPED", "RUNNING_NO_WEBSOCKET"}
        ):
            state = "STARTING"

        return ObsRuntimeStatus(
            state=state,
            process={
                "running": process is not None,
                "pid": process.pid if process else None,
                "started_at": started_at,
                "uptime_seconds": uptime,
                "session_id": process.session_id if process else None,
                "active_console_session_id": (
                    None
                    if session.active_console_session_id == NO_ACTIVE_CONSOLE_SESSION
                    else session.active_console_session_id
                ),
                "interactive": bool(
                    process
                    and process.session_id is not None
                    and session.active_console_session_id != NO_ACTIVE_CONSOLE_SESSION
                    and process.session_id == session.active_console_session_id
                ),
                "executable_path": str(process.path) if process and process.path else None,
                "expected_executable_path": str(self.expected_executable),
            },
            websocket=websocket,
            output=output,
            last_operation=last,
            error=error,
        )

    def _websocket_status(self) -> tuple[dict[str, Any], dict[str, Any], str | None]:
        client = self.client_factory()
        host = getattr(client, "host", "127.0.0.1")
        port = getattr(client, "port", 4455)
        try:
            client.connect()
            version = client.get_version()
            stream = client.get_stream_status()
            record = client.get_record_status()
            return (
                {
                    "connected": True,
                    "host": host,
                    "port": port,
                    "obs_version": version.get("obsVersion") or version.get("obsStudioVersion"),
                    "obs_websocket_version": version.get("obsWebSocketVersion"),
                },
                {
                    "streaming": bool(stream.get("outputActive")),
                    "recording": bool(record.get("outputActive")),
                },
                None,
            )
        except (ObsWebSocketConnectionError, ObsWebSocketRequestError) as exc:
            return (
                {
                    "connected": False,
                    "host": host,
                    "port": port,
                    "obs_version": None,
                    "obs_websocket_version": None,
                },
                {"streaming": None, "recording": None},
                str(exc),
            )
        finally:
            client.close()

    def _disconnected_websocket(self) -> dict[str, Any]:
        try:
            client = self.client_factory()
        except Exception:
            return {
                "connected": False,
                "host": "127.0.0.1",
                "port": 4455,
                "obs_version": None,
                "obs_websocket_version": None,
            }
        try:
            return {
                "connected": False,
                "host": getattr(client, "host", "127.0.0.1"),
                "port": getattr(client, "port", 4455),
                "obs_version": None,
                "obs_websocket_version": None,
            }
        finally:
            client.close()

    def _remember_operation(
        self,
        action: Literal["start", "stop", "restart"],
        result: Literal["success", "failed"],
        error: str | None,
    ) -> None:
        operation = LastOperation(
            action=action,
            result=result,
            timestamp=datetime.now(UTC).astimezone().isoformat(),
            error=error,
        )
        with self._state_lock:
            self._last_operation = operation

    def _resolve_executable(self, *, required: bool) -> Path | None:
        candidate = self.expected_executable
        if candidate.is_file() and candidate.name.casefold() == "obs64.exe":
            return candidate
        if required:
            raise ObsExecutableNotAllowedError(
                f"Allowed OBS executable was not found: {candidate}. "
                "Configure STREAMOPS_OBS_EXECUTABLE on the server if OBS is installed elsewhere."
            )
        return None

    def _session_info(self) -> DesktopSessionInfo:
        try:
            return desktop_session_info()
        except Exception as exc:
            raise ObsStatusError(f"Windows desktop session could not be inspected: {exc}") from exc

    def _launch(self, executable: Path) -> subprocess.Popen[bytes]:
        try:
            return subprocess.Popen(
                [str(executable), "--disable-updater"],
                cwd=str(executable.parent),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise ObsStartError(f"Could not launch OBS from {executable}: {exc}") from exc

    def _wait_for_process(
        self,
        *,
        excluded_pids: set[int],
        active_session_id: int,
        preferred_pid: int,
    ) -> ObsProcess | None:
        deadline = time.monotonic() + self.start_timeout
        while True:
            candidates = [
                process
                for process in self._obs_processes()
                if process.pid not in excluded_pids
                and process.session_id == active_session_id
                and process.path is not None
                and self._same_path(process.path, self.expected_executable)
            ]
            if candidates:
                preferred = next((p for p in candidates if p.pid == preferred_pid), None)
                return preferred or min(candidates, key=lambda p: p.pid)
            if time.monotonic() >= deadline:
                return None
            time.sleep(self.poll_interval)

    def _wait_until_stopped(self, pids: set[int]) -> bool:
        deadline = time.monotonic() + self.shutdown_timeout
        while True:
            running = {process.pid for process in self._obs_processes()}
            if pids.isdisjoint(running):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(self.poll_interval)

    def _request_graceful_close(self, pid: int) -> str:
        if os.name != "nt":
            raise ObsShutdownError("OBS graceful shutdown is supported only on Windows.")

        user32 = self._user32()
        windows: list[tuple[int, bool, bool, str, str]] = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @callback_type
        def callback(hwnd: int, _lparam: int) -> bool:
            process_id = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
            if int(process_id.value) != pid or not user32.IsWindow(hwnd):
                return True

            title_length = max(0, int(user32.GetWindowTextLengthW(hwnd)))
            title_buffer = ctypes.create_unicode_buffer(title_length + 1)
            user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
            class_buffer = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
            visible = bool(user32.IsWindowVisible(hwnd))
            unowned = not bool(user32.GetWindow(hwnd, GW_OWNER))
            windows.append(
                (int(hwnd), visible, unowned, title_buffer.value, class_buffer.value)
            )
            return True

        if not user32.EnumWindows(callback, 0):
            raise ObsShutdownError(f"Windows could not enumerate top-level windows for OBS PID {pid}.")
        if not windows:
            raise ObsShutdownError(
                f"OBS PID {pid} has no top-level window that can receive a graceful close request."
            )

        def score(window: tuple[int, bool, bool, str, str]) -> tuple[int, int]:
            hwnd, visible, unowned, title, class_name = window
            priority = 0
            if "obs" in title.casefold():
                priority += 8
            if visible:
                priority += 4
            if unowned:
                priority += 2
            if "qt" in class_name.casefold():
                priority += 1
            return priority, -hwnd

        target = max(windows, key=score)
        hwnd, visible, unowned, title, class_name = target
        result = ctypes.c_size_t()
        sent = user32.SendMessageTimeoutW(
            hwnd,
            WM_CLOSE,
            0,
            0,
            SMTO_ABORTIFHUNG,
            5000,
            ctypes.byref(result),
        )
        if not sent:
            raise ObsShutdownError(
                "Windows could not deliver a graceful WM_CLOSE to the selected OBS window "
                f"(PID {pid}, title={title!r}, class={class_name!r}, visible={visible}, "
                f"unowned={unowned})."
            )
        return (
            f"window title={title!r}, class={class_name!r}, "
            f"visible={visible}, unowned={unowned}"
        )

    def _obs_processes(self) -> list[ObsProcess]:
        if os.name != "nt":
            raise ObsStatusError("OBS process inspection is supported only on Windows.")
        kernel32 = self._kernel32()
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == INVALID_HANDLE_VALUE:
            raise ObsStatusError("Windows could not create a process snapshot for OBS status.")
        processes: list[ObsProcess] = []
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        try:
            has_entry = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while has_entry:
                if entry.szExeFile.casefold() == "obs64.exe":
                    processes.append(self._read_process(int(entry.th32ProcessID)))
                has_entry = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
        return processes

    def _read_process(self, pid: int) -> ObsProcess:
        kernel32 = self._kernel32()
        session_id = wintypes.DWORD()
        session = (
            int(session_id.value)
            if kernel32.ProcessIdToSessionId(pid, ctypes.byref(session_id))
            else None
        )
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ObsProcess(pid, None, None, session)
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
            return ObsProcess(pid, path, started_at, session)
        finally:
            kernel32.CloseHandle(handle)

    @staticmethod
    def _same_path(first: Path, second: Path) -> bool:
        return os.path.normcase(str(first.resolve(strict=False))) == os.path.normcase(
            str(second.resolve(strict=False))
        )

    @staticmethod
    def _user32():
        user32 = ctypes.windll.user32
        user32.EnumWindows.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetClassNameW.restype = ctypes.c_int
        user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetWindow.restype = wintypes.HWND
        user32.SendMessageTimeoutW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
            wintypes.UINT,
            wintypes.UINT,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        user32.SendMessageTimeoutW.restype = wintypes.LPARAM
        return user32

    @staticmethod
    def _kernel32():
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32FirstW.restype = wintypes.BOOL
        kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
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
        kernel32.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        kernel32.ProcessIdToSessionId.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        return kernel32
