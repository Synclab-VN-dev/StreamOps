"""Windows runtime adapter for real NVDA / Steam / Diablo IV lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from typing import Any

from .model import ProcessInfo, TolkHealth
from .store import RuntimePaths, atomic_write_json, read_json


class RuntimeBlocked(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DoctorReport:
    checks: dict[str, dict[str, Any]]

    @property
    def ok(self) -> bool:
        return all(item.get("status") != "FAIL" for item in self.checks.values())


class WindowsRuntime:
    NVDA_PROCESS_NAMES = ("nvda_noUIAccess", "nvda")
    GAME_PROCESS_NAMES = ("Diablo IV",)
    STEAM_PROCESS_NAMES = ("steam",)
    STEAM_APP_ID = "2344520"
    EXPECTED_ADDON_VERSION = "0.2.0"
    EXPECTED_NVDA_MAJOR_MINOR = (2026, 2)
    # Official NVDA 2026.2 x64 controller client verified during Real-A #41.
    EXPECTED_CONTROLLER_SHA256 = "598B7EC3DC469814F571275929F676CE73834C469FBDB359A06FD4DB4E0FC866"
    CONTROLLER_ARCHIVE_URL = (
        "https://download.nvaccess.org/releases/2026.2/"
        "nvda_2026.2_controllerClient.zip"
    )

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

    def current_process_session_id(self) -> int | None:
        self.require_windows()
        value = ctypes.c_ulong()
        if not ctypes.windll.kernel32.ProcessIdToSessionId(
            os.getpid(), ctypes.byref(value)
        ):
            return None
        return int(value.value)

    def _process(self, names: tuple[str, ...]) -> ProcessInfo | None:
        quoted = ",".join("'" + n.replace("'", "''") + "'" for n in names)
        script = (
            f"$names=@({quoted});"
            "$p=Get-Process -ErrorAction SilentlyContinue | "
            "Where-Object { $names -contains $_.ProcessName } | "
            "Sort-Object StartTime | Select-Object -Last 1;"
            "if($p){"
            "$started=$null;$path=$null;"
            "try{$started=$p.StartTime.ToString('o')}catch{};"
            "try{$path=$p.Path}catch{};"
            "[ordered]@{name=$p.ProcessName;pid=$p.Id;sessionId=$p.SessionId;"
            "startedAt=$started;path=$path}|ConvertTo-Json -Compress"
            "}"
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

    @staticmethod
    def _same_file(left: Path, right: Path) -> bool:
        try:
            return left.read_bytes() == right.read_bytes()
        except OSError:
            return False

    @classmethod
    def _sync_tree(cls, source: Path, destination: Path) -> bool:
        changed = False
        for item in source.rglob("*"):
            relative = item.relative_to(source)
            target = destination / relative
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if not cls._same_file(item, target):
                shutil.copy2(item, target)
                changed = True
        return changed

    def ensure_addon_runtime(self) -> bool:
        """Install/update the development add-on without touching the game directory.

        In packaged deployments the add-on may already be provisioned by the installer.
        In an editable StreamOps checkout we can safely sync the versioned source into
        NVDA's per-user add-ons directory, making `d4planner start` self-contained.
        """
        try:
            project_root = Path(__file__).resolve().parents[3]
        except IndexError:
            project_root = Path()
        source_root = project_root / "nvda-addon"
        source_addon = source_root / "addon"
        source_manifest = source_root / "manifest.ini"

        if not source_addon.is_dir() or not source_manifest.is_file():
            if self.addon_installed():
                return False
            raise RuntimeBlocked(
                "D4Planner NVDA add-on 0.2.0 is missing and no bundled/editable source is available"
            )

        destination = self.addon_path()
        destination.mkdir(parents=True, exist_ok=True)
        changed = self._sync_tree(source_addon, destination)

        manifest_target = destination / "manifest.ini"
        if not self._same_file(source_manifest, manifest_target):
            shutil.copy2(source_manifest, manifest_target)
            changed = True

        core_source = project_root / "src" / "d4planner" / "capture" / "core.py"
        core_target = destination / "globalPlugins" / "d4plannerCapture" / "core.py"
        if core_source.is_file() and not self._same_file(core_source, core_target):
            core_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(core_source, core_target)
            changed = True

        if self.addon_version() != self.EXPECTED_ADDON_VERSION:
            raise RuntimeBlocked(
                f"D4Planner add-on version mismatch after sync: {self.addon_version()!r}"
            )
        return changed

    def addon_version(self) -> str | None:
        manifest = self.addon_path() / "manifest.ini"
        try:
            for line in manifest.read_text(encoding="utf-8", errors="replace").splitlines():
                stripped = line.strip()
                if not stripped.startswith("version") or "=" not in stripped:
                    continue
                return stripped.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            return None
        return None

    def addon_installed(self) -> bool:
        plugin = self.addon_path() / "globalPlugins" / "d4plannerCapture"
        return plugin.is_dir() and self.addon_version() == self.EXPECTED_ADDON_VERSION

    def controller_dll(self) -> Path:
        return self.paths.controller / "nvdaControllerClient64.dll"

    def controller_machine(self, path: Path | None = None) -> int | None:
        """Return PE COFF machine type; AMD64 is 0x8664."""
        candidate = path or self.controller_dll()
        try:
            with candidate.open("rb") as handle:
                if handle.read(2) != b"MZ":
                    return None
                handle.seek(0x3C)
                offset_raw = handle.read(4)
                if len(offset_raw) != 4:
                    return None
                pe_offset = int.from_bytes(offset_raw, "little")
                handle.seek(pe_offset)
                if handle.read(4) != b"PE\x00\x00":
                    return None
                machine_raw = handle.read(2)
                if len(machine_raw) != 2:
                    return None
                return int.from_bytes(machine_raw, "little")
        except OSError:
            return None

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
        # Intentionally not environment-overridable: a user/process environment
        # must not be able to weaken the verified binary trust boundary.
        return self.EXPECTED_CONTROLLER_SHA256.strip().upper()

    def controller_ready(self) -> bool:
        path = self.controller_dll()
        if not path.is_file() or path.stat().st_size <= 0:
            return False
        return (
            self.controller_machine(path) == 0x8664
            and self.controller_sha256(path) == self.expected_controller_sha256()
        )

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
        # Development/Real-A migration path from the #41 diagnostic runtime.
        try:
            project_root = Path(__file__).resolve().parents[3]
            candidates.append(
                project_root / "runtime" / "nvda-controller" / "nvdaControllerClient64.dll"
            )
        except IndexError:
            pass
        try:
            candidates.extend(self.paths.root.rglob("nvdaControllerClient64.dll"))
        except OSError:
            pass

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
                    and self.controller_machine(candidate) == 0x8664
                    and self.controller_sha256(candidate) == self.expected_controller_sha256()
                ):
                    return candidate
            except OSError:
                continue
        return None

    def _extract_controller_archive(self, archive: Path) -> Path:
        cache = self.paths.root / "cache"
        cache.mkdir(parents=True, exist_ok=True)
        extracted = cache / "nvdaControllerClient64.dll"
        temp = cache / ".nvdaControllerClient64.dll.tmp"
        try:
            with zipfile.ZipFile(archive) as package:
                member = next(
                    (
                        name
                        for name in package.namelist()
                        if name.replace("\\", "/").casefold()
                        == "x64/nvdacontrollerclient.dll"
                    ),
                    None,
                )
                if not member:
                    raise RuntimeBlocked(
                        "official NVDA controller archive does not contain x64/nvdaControllerClient.dll"
                    )
                with package.open(member) as source, temp.open("wb") as target:
                    shutil.copyfileobj(source, target)
            os.replace(temp, extracted)
        except (OSError, zipfile.BadZipFile) as exc:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
            raise RuntimeBlocked(f"failed to extract NVDA controller archive: {exc}") from exc

        machine = self.controller_machine(extracted)
        digest = self.controller_sha256(extracted)
        if machine != 0x8664 or digest != self.expected_controller_sha256():
            try:
                extracted.unlink()
            except FileNotFoundError:
                pass
            raise RuntimeBlocked(
                "downloaded NVDA controller client validation failed: "
                f"machine={machine!r} sha256={digest or 'unreadable'}"
            )
        return extracted

    def _download_official_controller(self) -> Path:
        cache = self.paths.root / "cache"
        cache.mkdir(parents=True, exist_ok=True)
        archive = cache / "nvda_2026.2_controllerClient.zip"

        if archive.is_file():
            try:
                return self._extract_controller_archive(archive)
            except RuntimeBlocked:
                # A stale/corrupt cache is not authoritative. Redownload once.
                try:
                    archive.unlink()
                except OSError:
                    pass

        url = os.environ.get("D4PLANNER_CONTROLLER_URL", self.CONTROLLER_ARCHIVE_URL)
        temp = archive.with_suffix(archive.suffix + ".tmp")
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "D4Planner/0.2"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response, temp.open("wb") as handle:
                shutil.copyfileobj(response, handle)
            os.replace(temp, archive)
        except Exception as exc:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
            raise RuntimeBlocked(
                f"unable to obtain official NVDA 2026.2 controller client from {url}: {exc}"
            ) from exc
        return self._extract_controller_archive(archive)

    def ensure_controller_runtime(self) -> Path:
        self.paths.controller.mkdir(parents=True, exist_ok=True)
        target = self.controller_dll()
        if self.controller_ready():
            return target
        if target.exists():
            # The runtime directory is D4Planner-owned. Quarantine a corrupt or
            # wrong-architecture copy and self-heal from a verified source.
            actual = self.controller_sha256(target)
            cache = self.paths.root / "cache"
            cache.mkdir(parents=True, exist_ok=True)
            suffix = (actual or "unreadable")[:12]
            quarantine = cache / f"invalid-nvdaControllerClient64-{suffix}.dll"
            try:
                os.replace(target, quarantine)
            except OSError as exc:
                raise RuntimeBlocked(
                    "existing nvdaControllerClient64.dll is invalid and could not be quarantined: "
                    f"{exc}"
                ) from exc
        source = self.locate_controller_source()
        if not source:
            source = self._download_official_controller()
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        if not self.controller_ready():
            raise RuntimeBlocked("NVDA controller client failed validation after runtime install")
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

    def nvda_version_compatible(self, version: str | None = None) -> bool:
        value = version if version is not None else self.nvda_version()
        if not value:
            return False
        numeric = value.strip().split()[0].split(".")
        if len(numeric) < 2:
            return False
        try:
            major_minor = (int(numeric[0]), int(numeric[1]))
        except ValueError:
            return False
        return major_minor == self.EXPECTED_NVDA_MAJOR_MINOR

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

    def _probe_tolk_local(self) -> TolkHealth:
        self.require_windows()
        tolk = self.locate_tolk_dll()
        if not tolk:
            return TolkHealth(None, False, False, "Diablo IV Tolk.dll not found")
        if not self.controller_ready():
            return TolkHealth(None, False, False, "NVDA controller client missing")

        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(self.paths.controller) + os.pathsep + old_path
        dll_dirs = []
        try:
            if hasattr(os, "add_dll_directory"):
                # Keep both the controller client and the game's Tolk dependency
                # directory visible to the isolated probe process.
                dll_dirs.append(os.add_dll_directory(str(self.paths.controller)))
                dll_dirs.append(os.add_dll_directory(str(tolk.parent)))
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
            for dll_dir in reversed(dll_dirs):
                try:
                    dll_dir.close()
                except Exception:
                    pass
            os.environ["PATH"] = old_path

    def probe_tolk(self, *, timeout: float = 15.0) -> TolkHealth:
        """Probe Tolk in the active console session where NVDA owns its RPC endpoint."""
        self.require_windows()
        console_session = self.active_console_session_id()
        process_session = self.current_process_session_id()
        if console_session is None:
            return TolkHealth(None, False, False, "no active console session")
        if process_session == console_session:
            return self._probe_tolk_local()

        request_path = self.paths.state / "tolk-probe-request.json"
        result_path = self.paths.state / "tolk-probe-result.json"
        request_id = f"{os.getpid()}-{time.time_ns()}"
        atomic_write_json(
            request_path,
            {
                "requestId": request_id,
                "consoleSessionId": console_session,
            },
        )
        try:
            result_path.unlink()
        except FileNotFoundError:
            pass

        try:
            self.ensure_interactive_tasks()
            self.run_task("D4Planner-Tolk-Probe")
        except RuntimeBlocked as exc:
            return TolkHealth(None, False, False, str(exc))

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = read_json(result_path)
            if result and result.get("requestId") == request_id:
                actual_session = result.get("sessionId")
                if actual_session != console_session:
                    return TolkHealth(
                        None,
                        False,
                        False,
                        "Tolk probe ran outside active console session: "
                        f"actual={actual_session!r} expected={console_session}",
                    )
                return TolkHealth(
                    str(result["reader"]) if result.get("reader") else None,
                    bool(result.get("speech")),
                    bool(result.get("braille")),
                    str(result["error"]) if result.get("error") else None,
                )
            time.sleep(0.1)
        return TolkHealth(
            None,
            False,
            False,
            f"interactive Tolk probe timed out after {timeout:g}s",
        )

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
        nvda_restart_script = bin_dir / "restart-nvda.ps1"
        d4_script = bin_dir / "start-d4.ps1"
        tolk_probe_script = bin_dir / "probe-tolk.ps1"
        runtime = str(self.paths.controller).replace("'", "''")
        nvda_q = str(nvda).replace("'", "''")
        steam_q = str(steam).replace("'", "''")
        python_q = str(Path(sys.executable)).replace("'", "''")
        root_q = str(self.paths.root).replace("'", "''")
        nvda_script.write_text(
            "$ErrorActionPreference='Stop'\n"
            f"$runtime='{runtime}'\n"
            "$env:PATH=$runtime+';'+[Environment]::GetEnvironmentVariable('Path','User')+';'+"
            "[Environment]::GetEnvironmentVariable('Path','Machine')\n"
            "if(-not (Get-Process nvda_noUIAccess,nvda -ErrorAction SilentlyContinue)){"
            f"Start-Process -FilePath '{nvda_q}'}}\n",
            encoding="utf-8",
        )
        nvda_restart_script.write_text(
            "$ErrorActionPreference='Stop'\n"
            f"$nvda='{nvda_q}'\n"
            "& $nvda -q\n"
            "Start-Sleep -Milliseconds 800\n"
            "Start-Process -FilePath $nvda\n",
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
        tolk_probe_script.write_text(
            "$ErrorActionPreference='Stop'\n"
            f"& '{python_q}' -m d4planner.runtime.tolk_probe --root '{root_q}'\n"
            "if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}\n",
            encoding="utf-8",
        )
        return {
            "nvda": nvda_script,
            "nvda-restart": nvda_restart_script,
            "d4": d4_script,
            "tolk-probe": tolk_probe_script,
        }

    def ensure_interactive_tasks(self) -> None:
        self.require_windows()
        scripts = self.ensure_helper_scripts()
        for name, script_path in (
            ("D4Planner-NVDA", scripts["nvda"]),
            ("D4Planner-NVDA-Restart", scripts["nvda-restart"]),
            ("D4Planner-D4", scripts["d4"]),
            ("D4Planner-Tolk-Probe", scripts["tolk-probe"]),
        ):
            escaped = str(script_path).replace("'", "''")
            task_name = name.replace("'", "''")
            ps = (
                f"$existing=Get-ScheduledTask -TaskName '{task_name}' "
                "-ErrorAction SilentlyContinue;"
                "if(-not $existing){"
                f"$a=New-ScheduledTaskAction -Execute 'powershell.exe' "
                f"-Argument '-NoProfile -ExecutionPolicy Bypass -File \"{escaped}\"';"
                "$u=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name;"
                "$p=New-ScheduledTaskPrincipal -UserId $u -LogonType Interactive -RunLevel Limited;"
                f"Register-ScheduledTask -TaskName '{task_name}' -Action $a -Principal $p | Out-Null"
                "}"
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

    def launch_supervisor_task(self, *, speech: bool, isolated: bool) -> None:
        """Launch the long-lived supervisor outside the caller's SSH job."""
        self.require_windows()
        executable = str(Path(sys.executable)).replace("'", "''")
        arguments = ["-m", "d4planner.daemon"]
        if speech:
            arguments.append("--speech")
        if isolated:
            arguments.append("--isolated")
        argument_text = " ".join(arguments).replace("'", "''")
        ps = (
            f"$a=New-ScheduledTaskAction -Execute '{executable}' "
            f"-Argument '{argument_text}';"
            "$u=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name;"
            "$p=New-ScheduledTaskPrincipal -UserId $u -LogonType Interactive -RunLevel Limited;"
            "Register-ScheduledTask -TaskName 'D4Planner-Supervisor' "
            "-Action $a -Principal $p -Force | Out-Null;"
            "Start-ScheduledTask -TaskName 'D4Planner-Supervisor'"
        )
        result = self._powershell(ps)
        if result.returncode != 0:
            raise RuntimeBlocked(
                "failed to launch interactive supervisor task: "
                f"{result.stderr.strip()[:300]}"
            )

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

    def restart_nvda(self, *, timeout: float = 15.0) -> ProcessInfo:
        previous = self.nvda_process()
        previous_pid = previous.pid if previous else None
        self.ensure_interactive_tasks()
        self.run_task("D4Planner-NVDA-Restart")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            current = self.nvda_process()
            if current and (previous_pid is None or current.pid != previous_pid):
                return current
            time.sleep(0.5)
        raise RuntimeBlocked("NVDA did not restart in time after add-on update")

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
        version = self.nvda_version()
        checks["nvda_version"] = {
            "status": "PASS" if self.nvda_version_compatible(version) else "FAIL",
            "detail": {
                "version": version,
                "expectedMajorMinor": list(self.EXPECTED_NVDA_MAJOR_MINOR),
            },
        }
        checks["nvda_session"] = {
            "status": "PASS" if nvda and nvda.session_id == console else "FAIL",
            "detail": {"nvda": nvda.session_id if nvda else None, "console": console},
        }
        checks["addon"] = {
            "status": "PASS" if self.addon_installed() else "FAIL",
            "detail": {
                "path": str(self.addon_path()),
                "version": self.addon_version(),
                "expectedVersion": self.EXPECTED_ADDON_VERSION,
            },
        }
        checks["controller"] = {
            "status": "PASS" if self.controller_ready() else "FAIL",
            "detail": {
                "path": str(self.controller_dll()),
                "sha256": self.controller_sha256(),
                "expectedSha256": self.expected_controller_sha256(),
                "peMachine": self.controller_machine(),
                "expectedPeMachine": 0x8664,
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
