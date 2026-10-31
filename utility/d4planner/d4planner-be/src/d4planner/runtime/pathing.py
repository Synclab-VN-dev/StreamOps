"""User PATH management for NVDA controller discovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Protocol

from .store import RuntimePaths, atomic_write_json, read_json


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def _parts(value: str) -> list[str]:
    return [part.strip() for part in value.split(os.pathsep) if part.strip()]


def _norm(value: str) -> str:
    return os.path.normcase(os.path.normpath(value.strip().strip('"')))


class PathBackend(Protocol):
    def get_user_path(self) -> str: ...
    def set_user_path(self, value: str) -> None: ...
    def get_machine_path(self) -> str: ...


@dataclass(slots=True)
class MemoryPathBackend:
    user_path: str = ""
    machine_path: str = ""

    def get_user_path(self) -> str:
        return self.user_path

    def set_user_path(self, value: str) -> None:
        self.user_path = value

    def get_machine_path(self) -> str:
        return self.machine_path


class WindowsRegistryPathBackend:
    """HKCU PATH backend. Machine PATH is read-only by design."""

    _USER_KEY = r"Environment"
    _MACHINE_KEY = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"

    def _winreg(self):
        if os.name != "nt":
            raise RuntimeError("Windows registry PATH backend requires Windows")
        import winreg

        return winreg

    def get_user_path(self) -> str:
        winreg = self._winreg()
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._USER_KEY) as key:
                value, _ = winreg.QueryValueEx(key, "Path")
                return str(value or "")
        except FileNotFoundError:
            return ""

    def set_user_path(self, value: str) -> None:
        winreg = self._winreg()
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self._USER_KEY) as key:
            winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, value)
        self._broadcast_environment_change()

    def get_machine_path(self) -> str:
        winreg = self._winreg()
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self._MACHINE_KEY) as key:
                value, _ = winreg.QueryValueEx(key, "Path")
                return str(value or "")
        except FileNotFoundError:
            return ""

    @staticmethod
    def _broadcast_environment_change() -> None:
        try:
            import ctypes

            HWND_BROADCAST = 0xFFFF
            WM_SETTINGCHANGE = 0x001A
            SMTO_ABORTIFHUNG = 0x0002
            result = ctypes.c_ulong()
            ctypes.windll.user32.SendMessageTimeoutW(
                HWND_BROADCAST,
                WM_SETTINGCHANGE,
                0,
                "Environment",
                SMTO_ABORTIFHUNG,
                2000,
                ctypes.byref(result),
            )
        except Exception:
            # Registry write is authoritative. Broadcast is best effort only.
            pass


@dataclass(frozen=True, slots=True)
class PathChange:
    changed: bool
    managed_path: str
    before: str
    after: str
    updated_at: str | None


class UserPathManager:
    def __init__(self, paths: RuntimePaths, backend: PathBackend):
        self.paths = paths
        self.backend = backend

    def ensure(self, managed_dir: Path) -> PathChange:
        managed = str(managed_dir.resolve())
        before = self.backend.get_user_path()
        parts = _parts(before)
        if any(_norm(part) == _norm(managed) for part in parts):
            state = read_json(self.paths.path_managed) or {}
            updated = state.get("updatedAt")
            if not updated:
                # The path pre-existed D4Planner management. Track it conservatively
                # for stale-Steam detection, but never claim ownership for restore.
                updated = _now()
                atomic_write_json(
                    self.paths.path_managed,
                    {
                        "managedPath": managed,
                        "updatedAt": updated,
                        "owned": False,
                        "preExisting": True,
                    },
                )
            return PathChange(False, managed, before, before, str(updated))

        if not self.paths.path_backup.exists():
            atomic_write_json(
                self.paths.path_backup,
                {
                    "originalUserPath": before,
                    "machinePathSha256": hashlib.sha256(
                        self.backend.get_machine_path().encode("utf-8", errors="replace")
                    ).hexdigest(),
                    "createdAt": _now(),
                },
            )

        # Prepend to mirror the proven #41 process-scoped discovery flow and
        # ensure this exact controller client wins over later User PATH entries.
        after = os.pathsep.join([managed, *parts]) if parts else managed
        self.backend.set_user_path(after)
        updated = _now()
        atomic_write_json(
            self.paths.path_managed,
            {
                "managedPath": managed,
                "updatedAt": updated,
                "beforeSha256": hashlib.sha256(before.encode()).hexdigest(),
                "afterSha256": hashlib.sha256(after.encode()).hexdigest(),
                "owned": True,
                "preExisting": False,
            },
        )
        return PathChange(True, managed, before, after, updated)

    def restore(self) -> PathChange:
        backup = read_json(self.paths.path_backup)
        managed_state = read_json(self.paths.path_managed) or {}
        managed = str(managed_state.get("managedPath") or self.paths.controller)
        before = self.backend.get_user_path()
        if managed_state and managed_state.get("owned") is False:
            try:
                self.paths.path_managed.unlink()
            except FileNotFoundError:
                pass
            return PathChange(False, managed, before, before, None)
        if not backup:
            cleaned = os.pathsep.join(
                part for part in _parts(before) if _norm(part) != _norm(managed)
            )
            if cleaned != before:
                self.backend.set_user_path(cleaned)
            return PathChange(cleaned != before, managed, before, cleaned, None)

        original = str(backup.get("originalUserPath") or "")
        expected_after_parts = [managed, *_parts(original)]
        expected_after = os.pathsep.join(expected_after_parts) if expected_after_parts else managed

        # Exact restore when nobody changed PATH after D4Planner managed it.
        if [_norm(x) for x in _parts(before)] == [_norm(x) for x in _parts(expected_after)]:
            after = original
        else:
            # Preserve unrelated user edits while removing only our managed segment.
            after = os.pathsep.join(
                part for part in _parts(before) if _norm(part) != _norm(managed)
            )

        changed = after != before
        if changed:
            self.backend.set_user_path(after)
        for state_file in (self.paths.path_managed, self.paths.path_backup):
            try:
                state_file.unlink()
            except FileNotFoundError:
                pass
        return PathChange(changed, managed, before, after, None)

    def managed_updated_at(self) -> str | None:
        state = read_json(self.paths.path_managed) or {}
        value = state.get("updatedAt")
        return str(value) if value else None

    def is_present(self, managed_dir: Path) -> bool:
        target = _norm(str(managed_dir.resolve()))
        return any(_norm(part) == target for part in _parts(self.backend.get_user_path()))
