"""Windows runtime adapter for real NVDA / Steam / Diablo IV lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

from .model import ProcessInfo, TolkHealth
from .store import RuntimePaths


class RuntimeBlocked(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DoctorReport:
    checks: dict[str, dict[str, Any]]

    @property
    def ok(self) -> bool:
        return all(item.get("status") == "PASS" for item in self.checks.values())


class WindowsRuntime:
    NVDA_PROCESS_NAMES = ("nvda_noUIAccess", "nvda")
    GAME_PROCESS_NAMES = ("Diablo IV",)
    STEAM_PROCESS_NAMES = ("steam",)
    STEAM_APP_ID = "2344520"
    # Official NVDA 2026.2 x64 controller client verified during Real-A #41.
    EXPECTED_CONTROLLER_SHA256 = "598B7EC3DC469814F571275929F676CE73834C469FBDB359A06FD4DB4E0FC866"

    def __init__(self, paths: RuntimePaths):
        self.paths = paths

    def require_windows(self) -> None:
        if os.name != "nt":
            raise RuntimeBlocked("D4Planner real runtime requires Windows")

    @staticmethod
    def _powershell(script: str, *, timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def active_console_session_id(self) -> int | None:
        self.require_windows()
        value = ctypes.windll.kernel32.WTSGetActiveConsoleSessionId()
        if value == 0xFFFFFFFF:
            return None
        return int(value)

    def _process(self, names: tuple[str, ...]) -> ProcessInfo | None:
        quoted = ",".join("'" + n.replace("'", "''") + "'" for n in names)
        script = (
            f"$names=@({quoted});"
            "$p=Get-Process -ErrorAction SilentlyContinue | "
            "Where-Object { $names -contains $_.ProcessName } | "
            "Sort-Object StartTime | Select-Object -Last 1;"
            "if($p){[ordered]@{name=$p.ProcessName;pid=$p.Id;sessionId=$p.SessionId;"
            "startedAt=try{$p.StartTime.ToString('o')}catch{$null};"
            "path=try{$p.Path}catch{$null}}|ConvertTo-Json -Compress}"
        )
        result = self._powershell(script)
        if result.returncode != 0 or not result.stdout.strip():
            return None
        try:
            data = json.loads(result.stdout)
            return ProcessInfo(
                name=str(data.get("name") or names[0]),
                pid=int(data["pid"]),
                session_id=int(data["sessionId"]) if data.get("sessionId") is not None else None,
                started_at=str(data["startedAt"]) if data.get("startedAt") else None,
                path=str(data["path"]) if data.get("path") else None,
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    def nvda_process(self) -> ProcessInfo | None:
        return self._process(self.NVDA_PROCESS_NAMES)

    def steam_process(self) -> ProcessInfo | None:
        return self._process(self.STEAM_PROCESS_NAMES)

    def game_process(self) -> ProcessInfo | None:
        return self._process(self.GAME_PROCESS_NAMES)

    def addon_path(self) -> Path:
        roaming = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return roaming / "nvda" / "addons" / "d4plannerCapture"

    def addon_installed(self) -> bool:
        return (self.addon_path() / "globalPlugins" / "d4plannerCapture").is_dir() or (
            self.addon_path() / "__init__.py"
        ).exists()

    def controller_dll(self) -> Path:
        return self.paths.controller / "nvdaControllerClient64.dll"

    def controller_sha256(self, path: Path | None = None) -> str | None:
        candidate = path or self.controller_dll()
        try:
            digest = hashlib.sha256()
            with candidate.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest().upper()
        except OSError:
            return None

    def expected_controller_sha256(self) -> str:
        return os.environ.get(
            "D4PLANNER_CONTROLLER_SHA256",
            self.EXPECTED_CONTROLLER_SHA256,
        ).strip().upper()

    def controller_ready(self) -> bool:
        path = self.controller_dll()
        if not path.is_file() or path.stat().st_size <= 0:
            return False
        return self.controller_sha256(path) == self.expected_controller_sha256()

    def locate_controller_source(self) -> Path | None:
        override = os.environ.get("D4PLANNER_CONTROLLER_DLL")
        candidates: list[Path] = []
        if override:
            candidates.append(Path(override))
        candidates.extend(
            [
                self.controller_dll(),
                self.paths.root / "nvdaControllerClient64.dll",
                self.paths.root / "cache" / "nvdaControllerClient64.dll",
            ]
        )
        program_files = Path(os.environ.get("ProgramFiles") or r"C:\Program Files")
        nvda_root = program_files / "NVDA"
        if nvda_root.is_dir():
            try:
                candidates.extend(nvda_root.rglob("nvdaControllerClient64.dll"))
            except OSError:
                pass
        for candidate in candidates:
            try:
                if (
                    candidate.is_file()
                    and candidate.stat().st_size > 0
                    and self.controller_sha256(candidate) == self.expected_controller_sha256()
                ):
                    return candidate
            except OSError:
                continue
        return None

    def ensure_controller_runtime(self) -> Path:
        self.paths.controller.mkdir(parents=True, exist_ok=True)
        target = self.controller_dll()
        if self.controller_ready():
            return target
        if target.exists():
            actual = self.controller_sha256(target)
            raise RuntimeBlocked(
                "existing nvdaControllerClient64.dll checksum mismatch: "
                f"actual={actual or 'unreadable'} expected={self.expected_controller_sha256()}"
            )
        source = self.locate_controller_source()
        if not source:
            raise RuntimeBlocked(
                "nvdaControllerClient64.dll not found. Set D4PLANNER_CONTROLLER_DLL "
                "or place the official NVDA x64 controller client in the D4Planner runtime."
            )
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        return target

    def locate_nvda_executable(self) -> Path | None:
        override = os.environ.get("D4PLANNER_NVDA_EXE")
        candidates = [
            Path(override) if override else None,
            Path(os.environ.get("ProgramFiles") or r"C:\Program Files")
            / "NVDA"
            / "nvda_noUIAccess.exe",
            Path(os.environ.get("ProgramFiles") or r"C:\Program Files") / "NVDA" / "nvda.exe",
        ]
        for candidate in candidates:
            if candidate and candidate.is_file():
                return candidate
        return None

    def nvda_version(self) -> str | None:
        exe = self.locate_nvda_executable()
        if not exe:
            return None
        escaped = str(exe).replace("'", "''")
        script = (
            "$v=(Get-Item -LiteralPath '" + escaped + "').VersionInfo.FileVersion;"
            "$v"
        )
        result = self._powershell(script)
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def locate_steam_executable(self) -> Path | None:
        process = self.steam_process()
        if process and process.path:
            path = Path(process.path)
            if path.is_file():
                return path
        override = os.environ.get("D4PLANNER_STEAM_EXE")
        candidates = [
            Path(override) if override else None,
            Path(os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)") / "Steam" / "steam.exe",
            Path(os.environ.get("ProgramFiles") or r"C:\Program Files") / "Steam" / "steam.exe",
        ]
        for candidate in candidates:
            if candidate and candidate.is_file():
                return candidate
        return None

    def _steam_library_roots(self) -> list[Path]:
        roots: list[Path] = []
        steam = self.locate_steam_executable()
        if steam:
            roots.append(steam.parent)
            vdf = steam.parent / "steamapps" / "libraryfolders.vdf"
            try:
                text = vdf.read_text(encoding="utf-8", errors="replace")
                for raw in text.splitlines():
                    if '"path"' not in raw:
                        continue
                    parts = raw.split('"')
                    values = [p for p in parts if p and p not in {"path", "\t", " "} and "\\" in p]
                    if values:
                        roots.append(Path(values[-1].replace("\\\\", "\\")))
            except OSError:
                pass
        # Real-A POC location remains a useful safe candidate.
        roots.append(Path(r"D:\SteamLibrary"))
        unique: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            key = os.path.normcase(os.path.normpath(str(root)))
            if key not in seen:
                unique.append(root)
                seen.add(key)
        return unique

    def locate_tolk_dll(self) -> Path | None:
        override = os.environ.get("D4PLANNER_TOLK_DLL")
        if override and Path(override).is_file():
            return Path(override)
        for root in self._steam_library_roots():
            candidate = root / "steamapps" / "common" / "Diablo IV" / "Tolk.dll"
            if candidate.is_file():
                return candidate
        return None

    def probe_tolk(self) -> TolkHealth:
        self.require_windows()
        tolk = self.locate_tolk_dll()
        if not tolk:
            return TolkHealth(None, False, False, "Diablo IV Tolk.dll not found")
        if not self.controller_ready():
            return TolkHealth(None, False, False, "NVDA controller client missing")

        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(self.paths.controller) + os.pathsep + old_path
        dll_dir = None
        try:
            if hasattr(os, "add_dll_directory"):
                dll_dir = os.add_dll_directory(str(self.paths.controller))
            dll = ctypes.WinDLL(str(tolk))
            dll.Tolk_Load.argtypes = []
            dll.Tolk_Load.restype = None
            dll.Tolk_Unload.argtypes = []
            dll.Tolk_Unload.restype = None
            dll.Tolk_DetectScreenReader.argtypes = []
            dll.Tolk_DetectScreenReader.restype = ctypes.c_wchar_p
            dll.Tolk_HasSpeech.argtypes = []
            dll.Tolk_HasSpeech.restype = ctypes.c_bool
            try:
                dll.Tolk_HasBraille.argtypes = []
                dll.Tolk_HasBraille.restype = ctypes.c_bool
            except AttributeError:
                pass

            dll.Tolk_Load()
            try:
                reader = dll.Tolk_DetectScreenReader()
                speech = bool(dll.Tolk_HasSpeech())
                braille = bool(dll.Tolk_HasBraille()) if hasattr(dll, "Tolk_HasBraille") else False
            finally:
                dll.Tolk_Unload()
            return TolkHealth(reader, speech, braille)
        except Exception as exc:
            return TolkHealth(None, False, False, f"{type(exc).__name__}: {exc}")
        finally:
            if dll_dir:
                dll_dir.close()
            os.environ["PATH"] = old_path

    @staticmethod
    def process_started_before(process: ProcessInfo | None, timestamp: str | None) -> bool:
        if not process or not process.started_at or not timestamp:
            return False
        try:
            started = datetime.fromisoformat(process.started_at)
            changed = datetime.fromisoformat(timestamp)
            if started.tzinfo is None and changed.tzinfo is not None:
                started = started.replace(tzinfo=changed.tzinfo)
            return started < changed
        except ValueError:
            return False

    def ensure_helper_scripts(self) -> dict[str, Path]:
        self.paths.runtime.mkdir(parents=True, exist_ok=True)
        bin_dir = self.paths.runtime / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        nvda = self.locate_nvda_executable()
        steam = self.locate_steam_executable()
        if not nvda:
            raise RuntimeBlocked("NVDA executable not found")
        if not steam:
            raise RuntimeBlocked("Steam executable not found")

        nvda_script = bin_dir / "start-nvda.ps1"
        d4_script = bin_dir / "start-d4.ps1"
        runtime = str(self.paths.controller).replace("'", "''")
        nvda_q = str(nvda).replace("'", "''")
        steam_q = str(steam).replace("'", "''")
        nvda_script.write_text(
            "$ErrorActionPreference='Stop'\n"
            f"$runtime='{runtime}'\n"
            "$env:PATH=$runtime+';'+[Environment]::GetEnvironmentVariable('Path','User')+';'+"
            "[Environment]::GetEnvironmentVariable('Path','Machine')\n"
            "if(-not (Get-Process nvda_noUIAccess,nvda -ErrorAction SilentlyContinue)){"
            f"Start-Process -FilePath '{nvda_q}'}}\n",
            encoding="utf-8",
        )
        d4_script.write_text(
            "$ErrorActionPreference='Stop'\n"
            f"$runtime='{runtime}'\n"
            "$env:PATH=$runtime+';'+[Environment]::GetEnvironmentVariable('Path','User')+';'+"
            "[Environment]::GetEnvironmentVariable('Path','Machine')\n"
            f"$steam='{steam_q}'\n"
            "if(-not (Get-Process steam -ErrorAction SilentlyContinue)){"
            "Start-Process -FilePath $steam -ArgumentList '-silent'; Start-Sleep -Seconds 3}\n"
            f"Start-Process -FilePath $steam -ArgumentList '-applaunch {self.STEAM_APP_ID}'\n",
            encoding="utf-8",
        )
        return {"nvda": nvda_script, "d4": d4_script}

    def ensure_interactive_tasks(self) -> None:
        self.require_windows()
        scripts = self.ensure_helper_scripts()
        for name, script_path in (
            ("D4Planner-NVDA", scripts["nvda"]),
            ("D4Planner-D4", scripts["d4"]),
        ):
            escaped = str(script_path).replace("'", "''")
            ps = (
                f"$a=New-ScheduledTaskAction -Execute 'powershell.exe' "
                f"-Argument '-NoProfile -ExecutionPolicy Bypass -File \"{escaped}\"';"
                "$u=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name;"
                "$p=New-ScheduledTaskPrincipal -UserId $u -LogonType Interactive -RunLevel Limited;"
                f"Register-ScheduledTask -TaskName '{name}' -Action $a -Principal $p -Force | Out-Null"
            )
            result = self._powershell(ps)
            if result.returncode != 0:
                raise RuntimeBlocked(
                    f"failed to register interactive task {name}: {result.stderr.strip()[:300]}"
                )

    def run_task(self, name: str) -> None:
        result = self._powershell(f"Start-ScheduledTask -TaskName '{name}'")
        if result.returncode != 0:
            raise RuntimeBlocked(f"failed to start task {name}: {result.stderr.strip()[:300]}")

    def ensure_nvda_running(self, *, timeout: float = 15.0) -> ProcessInfo:
        existing = self.nvda_process()
        if existing:
            return existing
        self.ensure_interactive_tasks()
        self.run_task("D4Planner-NVDA")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            process = self.nvda_process()
            if process:
                return process
            time.sleep(0.5)
        raise RuntimeBlocked("NVDA did not start in time")

    def launch_game(self) -> None:
        self.ensure_interactive_tasks()
        self.run_task("D4Planner-D4")

    def wait_for_game(self, *, timeout: float = 90.0) -> ProcessInfo | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            process = self.game_process()
            if process:
                return process
            time.sleep(1.0)
        return None

    def doctor(self) -> DoctorReport:
        checks: dict[str, dict[str, Any]] = {}
        if os.name != "nt":
            return DoctorReport({"platform": {"status": "FAIL", "detail": "Windows required"}})

        console = self.active_console_session_id()
        checks["active_console"] = {
            "status": "PASS" if console is not None else "FAIL",
            "detail": console,
        }
        nvda = self.nvda_process()
        checks["nvda"] = {
            "status": "PASS" if nvda else "FAIL",
            "detail": nvda.as_dict() if nvda else "not running",
        }
        checks["nvda_session"] = {
            "status": "PASS" if nvda and nvda.session_id == console else "FAIL",
            "detail": {"nvda": nvda.session_id if nvda else None, "console": console},
        }
        checks["addon"] = {
            "status": "PASS" if self.addon_installed() else "FAIL",
            "detail": str(self.addon_path()),
        }
        checks["controller"] = {
            "status": "PASS" if self.controller_ready() else "FAIL",
            "detail": {
                "path": str(self.controller_dll()),
                "sha256": self.controller_sha256(),
                "expectedSha256": self.expected_controller_sha256(),
            },
        }
        health = self.probe_tolk()
        checks["tolk"] = {
            "status": "PASS" if health.ready else "FAIL",
            "detail": health.as_dict(),
        }
        steam = self.steam_process()
        game = self.game_process()
        checks["steam"] = {
            "status": "PASS" if steam else "WARN",
            "detail": steam.as_dict() if steam else "not running",
        }
        checks["game"] = {
            "status": "PASS" if game else "WARN",
            "detail": game.as_dict() if game else "not running",
        }
        return DoctorReport(checks)
