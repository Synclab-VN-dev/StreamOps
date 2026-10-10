"""Read-only Windows game identity/installation checks and allowlisted graceful actions.

This module never terminates arbitrary PIDs, shells out to caller input, or
starts Steam/OBS implicitly. Steam launch is permitted only in the interactive
node session, from an installed manifest, through the resolved Steam binary.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import subprocess

from .session import desktop_session_info
from .steam import (
    PROCESSENTRY32W, TH32CS_SNAPPROCESS, INVALID_HANDLE_VALUE,
    WindowsSteamBackend, _kernel32,
)
from ...services.games.models import GameDefinition, GameObservation, ProcessIdentity

class GamePlatformError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)

class WindowsGameProcess:
    """The only native boundary used by GameObserver and GameLifecycle."""

    def __init__(self, steam: WindowsSteamBackend | None = None):
        self.steam = steam or WindowsSteamBackend()

    def _installed_dir(self, game: GameDefinition) -> Path | None:
        steam_exe = self.steam.resolve_installation(required=False)
        if steam_exe is None:
            return None
        # V1: primary Steam library only. Other libraries remain UNKNOWN.
        manifest = steam_exe.parent / "steamapps" / f"appmanifest_{game.providerGameId}.acf"
        if not manifest.is_file():
            return None
        try:
            content = manifest.read_text(encoding="utf-8-sig")
            match = re.search(r'"installdir"\s+"([^"]+)"', content, re.IGNORECASE)
            if not match:
                return None
            name = match.group(1)
            if name in (".", "..") or "/" in name or "\\" in name or ":" in name:
                return None
            folder = (manifest.parent / "common" / name).resolve()
            return folder if folder.is_dir() else None
        except OSError:
            return None

    def _processes(self, game: GameDefinition):
        if os.name != "nt":
            raise GamePlatformError("capability_disabled", "Windows game inspection is unavailable.")
        kernel32 = _kernel32()
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == INVALID_HANDLE_VALUE:
            raise GamePlatformError("game_status_unknown", "Windows process enumeration failed.")
        names = {name.casefold() for name in game.detection.processNames}
        matching = []
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        try:
            more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while more:
                if entry.szExeFile.casefold() in names:
                    matching.append(self.steam._read_process(int(entry.th32ProcessID)))
                more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
        return matching

    @staticmethod
    def _windows(pid: int) -> list[int]:
        user32 = ctypes.windll.user32
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        result: list[int] = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def scan(hwnd, _):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid and user32.IsWindowVisible(hwnd):
                result.append(int(hwnd))
            return True
        callback = callback_type(scan)
        if not user32.EnumWindows(callback, 0):
            raise GamePlatformError("game_status_unknown", "Window enumeration failed.")
        return result

    def inspect(self, game: GameDefinition) -> GameObservation:
        folder = self._installed_dir(game)
        processes = self._processes(game)
        if len(processes) > 1:
            raise GamePlatformError("game_identity_ambiguous", "Several candidate game processes found.")
        if not processes:
            return GameObservation(
                installed=True if folder else None,
                process=ProcessIdentity(state="STOPPED", stale=False),
                window="NOT_DETECTED",
            )
        process = processes[0]
        if not process.path or process.session_id is None or process.started_at_timestamp is None:
            raise GamePlatformError("game_status_unknown", "Process identity cannot be verified.")
        # Without a manifest-backed directory, path alone cannot be trusted.
        if folder is None or not process.path.resolve().is_relative_to(folder):
            raise GamePlatformError("game_identity_ambiguous", "Candidate process is outside the verified Steam game directory.")
        active_session = desktop_session_info().active_console_session_id
        if process.session_id != active_session:
            raise GamePlatformError("wrong_desktop_session", "Game is outside active console session.")
        windows = self._windows(process.pid)
        return GameObservation(
            installed=True,
            process=ProcessIdentity(
                state="RUNNING", pid=process.pid, session_id=process.session_id,
                executable=str(process.path),
                created_at=datetime.fromtimestamp(process.started_at_timestamp, timezone.utc).isoformat(),
                stale=False,
            ),
            window="BACKGROUND" if windows else "NOT_DETECTED",
        )

    def _require_interactive(self) -> None:
        if os.name != "nt" or not desktop_session_info().is_interactive:
            raise GamePlatformError("wrong_desktop_session", "Node must run in the active Windows desktop.")

    def start(self, game: GameDefinition) -> None:
        self._require_interactive()
        if self._installed_dir(game) is None:
            raise GamePlatformError("game_not_installed", "V1 supports installations in the primary Steam library only.")
        steam_status = self.steam.status()
        if not steam_status.running or not steam_status.interactive:
            raise GamePlatformError("capability_disabled", "Steam must already run in active desktop session.")
        steam_exe = self.steam.resolve_installation(required=True)
        assert steam_exe is not None
        subprocess.Popen([str(steam_exe), "-applaunch", game.providerGameId], cwd=steam_exe.parent,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def stop(self, game: GameDefinition, expected: ProcessIdentity) -> None:
        self._require_interactive()
        current = self.inspect(game).process
        if (current.state != "RUNNING" or current.pid != expected.pid or
                current.created_at != expected.created_at or current.session_id != expected.session_id or
                current.executable != expected.executable):
            raise GamePlatformError("game_identity_ambiguous", "Game process changed before graceful close.")
        windows = self._windows(current.pid)
        if len(windows) != 1:
            raise GamePlatformError("capability_disabled", "Exactly one verified game window is required for safe Stop.")
        WM_CLOSE = 0x0010
        if not ctypes.windll.user32.PostMessageW(windows[0], WM_CLOSE, 0, 0):
            raise GamePlatformError("capability_disabled", "Failed to request a graceful window close.")
