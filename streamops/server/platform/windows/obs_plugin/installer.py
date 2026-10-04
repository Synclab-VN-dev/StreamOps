"""Pinned, transactional installer for the single supported OBS plugin."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.resources
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import tempfile
from typing import Any, BinaryIO, Callable
from urllib.request import Request, urlopen
import uuid
import zipfile



# TODO(tech-debt): Inject/reuse the OBS executable configured by ObsManager/ServerConfig
# instead of maintaining a second hard-coded default here. A custom STREAMOPS_OBS_EXECUTABLE
# can otherwise make lifecycle management and plugin verification inspect different binaries.
OBS_EXECUTABLE = Path(r"C:\Program Files\obs-studio\bin\64bit\obs64.exe")
PLUGIN_ROOT = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "obs-studio" / "plugins" / "obs-multi-rtmp"
PLUGIN_CONFIG_NAME = "obs-multi-rtmp.json"
ZIP_TO_INSTALL = {
    "obs-plugins/64bit/obs-multi-rtmp.dll": "bin/64bit/obs-multi-rtmp.dll",
    "obs-plugins/64bit/obs-multi-rtmp.pdb": "bin/64bit/obs-multi-rtmp.pdb",
}
LOCALE_PREFIX = "data/obs-plugins/obs-multi-rtmp/locale/"


class PluginInstallerFailure(RuntimeError):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


@dataclass(frozen=True)
class InstallerStatus:
    installation: str
    compatible: bool
    loaded: bool
    loaded_version: str | None = None


@dataclass(frozen=True)
class InstallerResult:
    result: str


@dataclass(frozen=True)
class ProcessEvidence:
    pid: int
    executable: Path
    started_at: datetime


def _load_manifest() -> dict[str, Any]:
    resource = importlib.resources.files(__package__).joinpath("manifest.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_records(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir():
        return []
    records = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise PluginInstallerFailure("plugin_state_conflict", "Managed plugin directory contains a link.")
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            records.append({"relative_path": relative, "length": path.stat().st_size, "sha256": _sha256_file(path)})
    return sorted(records, key=lambda item: item["relative_path"])


def _tree_digest(records: list[dict[str, Any]]) -> str:
    lines = [f"{f['relative_path']}|{f['length']}|{f['sha256']}" for f in sorted(records, key=lambda x: x["relative_path"])]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"..", ""} for part in path.parts) or "\\" in value:
        raise PluginInstallerFailure("artifact_invalid", "Pinned artifact contains an unsafe path.")
    return path


class WindowsObsMultiRtmpInstaller:
    def __init__(
        self,
        data_dir: Path,
        *,
        plugin_root: Path = PLUGIN_ROOT,
        obs_executable: Path = OBS_EXECUTABLE,
        manifest: dict[str, Any] | None = None,
        downloader: Callable[[str], BinaryIO] | None = None,
        process_probe: Callable[[], list[ProcessEvidence]] | None = None,
        version_probe: Callable[[Path], str | None] | None = None,
        appdata: Path | None = None,
    ) -> None:
        self.data_dir = Path(data_dir).resolve()
        self.plugin_root = Path(plugin_root)
        self.obs_executable = Path(obs_executable)
        self.manifest = manifest or _load_manifest()
        self.state_root = self.data_dir / "obs-plugins" / "obs-multi-rtmp"
        self.transactions_root = self.state_root / "transactions"
        self.pointer = self.state_root / "current-transaction.json"
        self.downloader = downloader or self._download
        self.process_probe = process_probe or _obs_processes
        self.version_probe = version_probe or _file_product_version
        roaming = os.environ.get("APPDATA")
        self.appdata = Path(appdata) if appdata else (Path(roaming) if roaming else None)

    @staticmethod
    def _download(url: str) -> BinaryIO:
        request = Request(url, headers={"User-Agent": "StreamOps OBS plugin installer"})
        return urlopen(request, timeout=60)

    def status(self) -> InstallerStatus:
        version = self.version_probe(self.obs_executable)
        records = _file_records(self.plugin_root)
        if not records:
            installation = "absent"
        elif self._is_exact(records):
            installation = "exact"
        else:
            installation = "conflict"
        loaded_version = None
        processes = self._matching_obs_processes()
        if len(processes) == 1:
            loaded_version, module_loaded = self._load_evidence(processes[0])
        else:
            module_loaded = False
        return InstallerStatus(
            installation=installation,
            compatible=version == self.manifest["expected_obs_version"],
            loaded=module_loaded,
            loaded_version=loaded_version,
        )

    def install(self) -> InstallerResult:
        self._assert_compatible()
        records = _file_records(self.plugin_root)
        if records and self._is_exact(records):
            return InstallerResult("already_installed")
        if records:
            raise PluginInstallerFailure("plugin_state_conflict", "Managed plugin directory has conflicting files.")
        self._assert_obs_stopped()
        staged = Path(tempfile.mkdtemp(prefix="streamops-obs-multi-rtmp-"))
        try:
            expected_records = self._stage_artifact(staged)
            self.state_root.mkdir(parents=True, exist_ok=True)
            transaction_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
            transaction_root = self.transactions_root / transaction_id
            backup_root = transaction_root / "backup" / "obs-multi-rtmp"
            transaction_root.mkdir(parents=True)
            existing_root = self.plugin_root.is_dir()
            if existing_root:
                backup_root.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(self.plugin_root, backup_root)
            baseline_configs = self._plugin_configs()
            transaction = {
                "state": "pending",
                "transaction_id": transaction_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "plugin_root_existed": existing_root,
                "backup_relative": backup_root.relative_to(transaction_root).as_posix() if existing_root else None,
                "baseline_plugin_configs": baseline_configs,
                "expected_files": expected_records,
            }
            self._write_json(transaction_root / "transaction.json", transaction)
            self._write_json(self.pointer, {"transaction_id": transaction_id})
            # TODO(tech-debt): Reconcile unfinished transactions after process crash/power loss.
            # In-process exceptions restore the backup, but a hard termination between this journal
            # write and the final installed state can leave partial files that need manual recovery.
            self.plugin_root.mkdir(parents=True, exist_ok=True)
            try:
                self._copy_contents(staged, self.plugin_root)
                installed = _file_records(self.plugin_root)
                if not self._is_exact(installed):
                    raise PluginInstallerFailure("install_failed", "Installed plugin failed exact manifest verification.")
                transaction["state"] = "installed"
                transaction["installed_at"] = datetime.now(timezone.utc).isoformat()
                self._write_json(transaction_root / "transaction.json", transaction)
            except Exception:
                self._restore_backup(transaction_root, transaction)
                raise
            return InstallerResult("installed")
        except PermissionError as exc:
            raise PluginInstallerFailure("permission_denied", "Permission denied for the managed plugin directory.") from exc
        finally:
            shutil.rmtree(staged, ignore_errors=True)

    def verify(self) -> InstallerStatus:
        self._assert_compatible()
        status = self.status()
        if status.installation != "exact":
            raise PluginInstallerFailure("manifest_mismatch", "Installed files do not match the pinned manifest.")
        processes = self._matching_obs_processes()
        if len(processes) != 1:
            raise PluginInstallerFailure("obs_not_running", "OBS is not running from the expected executable.")
        if not status.loaded or status.loaded_version != self.manifest["package_version"]:
            raise PluginInstallerFailure("module_not_loaded", "Current OBS process has no matching plugin load evidence.")
        return status

    def rollback(self) -> InstallerResult:
        self._assert_obs_stopped()
        transaction_root, transaction = self._read_current_transaction()
        current = _file_records(self.plugin_root)
        expected = transaction.get("expected_files", [])
        if self._record_map(current) != self._record_map(expected):
            raise PluginInstallerFailure("rollback_conflict", "Plugin files are missing, modified, or unmanaged.")
        baseline_paths = {item["path"] for item in transaction.get("baseline_plugin_configs", [])}
        new_empty_configs = []
        for item in self._plugin_configs():
            if item["path"] not in baseline_paths:
                if not self._is_empty_plugin_config(Path(item["path"])):
                    raise PluginInstallerFailure("config_conflict", "A new plugin configuration contains settings.")
                new_empty_configs.append(Path(item["path"]))
        self._clear_contents(self.plugin_root)
        if transaction.get("plugin_root_existed"):
            relative = _safe_relative(str(transaction.get("backup_relative") or ""))
            backup = transaction_root.joinpath(*relative.parts)
            if not backup.is_dir():
                raise PluginInstallerFailure("transaction_missing", "The plugin backup is missing.")
            self._copy_contents(backup, self.plugin_root)
        for config in new_empty_configs:
            config.unlink(missing_ok=True)
        transaction["state"] = "rolled_back"
        transaction["rolled_back_at"] = datetime.now(timezone.utc).isoformat()
        self._write_json(transaction_root / "transaction.json", transaction)
        return InstallerResult("rolled_back")

    def _stage_artifact(self, destination: Path) -> list[dict[str, Any]]:
        artifact_path = destination / str(self.manifest["artifact_name"])
        digest = hashlib.sha256()
        try:
            with self.downloader(str(self.manifest["artifact_url"])) as source, artifact_path.open("wb") as target:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    target.write(block)
                    digest.update(block)
        except PermissionError:
            raise
        except Exception as exc:
            raise PluginInstallerFailure("download_failed", "Pinned plugin artifact could not be downloaded.") from exc
        if digest.hexdigest() != self.manifest["artifact_sha256"]:
            raise PluginInstallerFailure("artifact_hash_mismatch", "Pinned plugin artifact failed SHA-256 validation.")
        allowed_zip = dict(ZIP_TO_INSTALL)
        with zipfile.ZipFile(artifact_path) as archive:
            allowed_prefixes = {
                "/".join(PurePosixPath(name).parts[:index])
                for name in (*ZIP_TO_INSTALL.keys(), LOCALE_PREFIX.rstrip("/"))
                for index in range(1, len(PurePosixPath(name).parts))
            }
            allowed_prefixes.add(LOCALE_PREFIX.rstrip("/"))
            entries = [entry for entry in archive.infolist() if not entry.is_dir()]
            mapping: dict[str, str] = {}
            for entry in archive.infolist():
                if entry.is_dir():
                    directory = entry.filename.rstrip("/")
                    _safe_relative(directory)
                    if directory not in allowed_prefixes and not directory.startswith(LOCALE_PREFIX.rstrip("/")):
                        raise PluginInstallerFailure("artifact_invalid", "Pinned artifact contains an unexpected directory.")
            for entry in entries:
                name = entry.filename
                _safe_relative(name)
                if name in allowed_zip:
                    target = allowed_zip[name]
                elif name.startswith(LOCALE_PREFIX) and re.fullmatch(r"[A-Za-z0-9-]+\.ini", name[len(LOCALE_PREFIX):]):
                    target = "data/locale/" + name[len(LOCALE_PREFIX):]
                else:
                    raise PluginInstallerFailure("artifact_invalid", "Pinned artifact contains an unexpected file.")
                if target in mapping.values() or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                    raise PluginInstallerFailure("artifact_invalid", "Pinned artifact contains duplicate or link entries.")
                mapping[name] = target
            if len(entries) != self.manifest["file_count"] or set(mapping.values()) != set(self.manifest["relative_paths"]):
                raise PluginInstallerFailure("artifact_manifest_mismatch", "Pinned archive does not match the exact path allowlist.")
            for entry in entries:
                relative = _safe_relative(mapping[entry.filename])
                output = destination.joinpath(*relative.parts)
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, output.open("xb") as target:
                    shutil.copyfileobj(source, target)
        records = _file_records(destination)
        # Exclude downloaded archive itself from the staged plugin tree.
        records = [item for item in records if item["relative_path"] != artifact_path.name]
        if len(records) != self.manifest["file_count"] or _tree_digest(records) != self.manifest["tree_sha256"]:
            raise PluginInstallerFailure("artifact_manifest_mismatch", "Extracted package failed the pinned tree digest.")
        artifact_path.unlink()
        return records

    def _is_exact(self, records: list[dict[str, Any]]) -> bool:
        expected_paths = set(self.manifest["relative_paths"])
        return (
            len(records) == self.manifest["file_count"]
            and {item["relative_path"] for item in records} == expected_paths
            and _tree_digest(records) == self.manifest["tree_sha256"]
        )

    @staticmethod
    def _record_map(records: list[dict[str, Any]]) -> dict[str, tuple[int, str]]:
        return {str(item["relative_path"]): (int(item["length"]), str(item["sha256"])) for item in records}

    def _assert_compatible(self) -> None:
        version = self.version_probe(self.obs_executable)
        if version != self.manifest["expected_obs_version"]:
            raise PluginInstallerFailure("incompatible_obs", "Pinned plugin requires OBS 32.2.1.")

    def _assert_obs_stopped(self) -> None:
        if self._matching_obs_processes():
            raise PluginInstallerFailure("obs_running", "OBS must be stopped through StreamOps before file mutation.")

    def _matching_obs_processes(self) -> list[ProcessEvidence]:
        expected = os.path.normcase(str(self.obs_executable.resolve(strict=False)))
        return [p for p in self.process_probe() if os.path.normcase(str(p.executable.resolve(strict=False))) == expected]

    def _load_evidence(self, process: ProcessEvidence) -> tuple[str | None, bool]:
        # TODO(tech-debt): Prefer direct module enumeration or a plugin/vendor health signal when
        # available. Parsing OBS logs couples verification to log format and a startup time window.
        if self.appdata is None:
            return None, False
        logs = self.appdata / "obs-studio" / "logs"
        if not logs.is_dir():
            return None, False
        candidates = [path for path in logs.glob("*.txt") if path.stat().st_mtime >= process.started_at.timestamp() - 5]
        if not candidates:
            return None, False
        latest = max(candidates, key=lambda path: path.stat().st_mtime)
        try:
            content = latest.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None, False
        versions = re.findall(r"\[obs-multi-rtmp\]\s+version:\s*([0-9.]+)", content, re.IGNORECASE)
        version = versions[-1] if versions else None
        module_loaded = re.search(r"obs-multi-rtmp\.dll\s*$", content, re.IGNORECASE | re.MULTILINE) is not None
        return version, module_loaded and version == self.manifest["package_version"]

    def _plugin_configs(self) -> list[dict[str, Any]]:
        if self.appdata is None:
            return []
        root = self.appdata / "obs-studio" / "basic" / "profiles"
        if not root.is_dir():
            return []
        results = []
        for path in sorted(root.rglob(PLUGIN_CONFIG_NAME)):
            if path.is_file():
                results.append({"path": str(path), "length": path.stat().st_size, "sha256": _sha256_file(path)})
        return results

    @staticmethod
    def _is_empty_plugin_config(path: Path) -> bool:
        try:
            # OBS writes this file with a UTF-8 BOM on Windows.
            value = json.loads(path.read_text(encoding="utf-8-sig"))
            return isinstance(value, dict) and set(value) <= {"audio_configs", "targets", "video_configs"} and all(
                isinstance(value.get(name), list) and not value[name]
                for name in ("audio_configs", "targets", "video_configs")
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return False

    def _read_current_transaction(self) -> tuple[Path, dict[str, Any]]:
        try:
            pointer = json.loads(self.pointer.read_text(encoding="utf-8"))
            transaction_id = str(pointer["transaction_id"])
            if not re.fullmatch(r"\d{8}-\d{6}-[a-f0-9]{8}", transaction_id):
                raise ValueError("bad transaction ID")
            root = self.transactions_root / transaction_id
            transaction = json.loads((root / "transaction.json").read_text(encoding="utf-8"))
            if transaction.get("transaction_id") != transaction_id:
                raise ValueError("transaction mismatch")
            return root, transaction
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PluginInstallerFailure("transaction_missing", "Managed rollback transaction is unavailable.") from exc

    def _restore_backup(self, transaction_root: Path, transaction: dict[str, Any]) -> None:
        self._clear_contents(self.plugin_root)
        if transaction.get("plugin_root_existed"):
            relative = _safe_relative(str(transaction.get("backup_relative") or ""))
            backup = transaction_root.joinpath(*relative.parts)
            if backup.is_dir():
                self._copy_contents(backup, self.plugin_root)
        transaction["state"] = "failed_restored"
        self._write_json(transaction_root / "transaction.json", transaction)

    @staticmethod
    def _clear_contents(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        for child in path.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()

    @staticmethod
    def _copy_contents(source: Path, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        for child in source.iterdir():
            target = destination / child.name
            if child.is_dir():
                shutil.copytree(child, target, dirs_exist_ok=True)
            else:
                shutil.copy2(child, target)

    @staticmethod
    def _write_json(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
        encoded = json.dumps(value, indent=2, sort_keys=True).encode("utf-8")
        with temporary.open("xb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)


def _file_product_version(path: Path) -> str | None:
    if platform.system() != "Windows" or not path.is_file():
        return None
    import ctypes
    from ctypes import wintypes

    version = ctypes.windll.version
    version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    version.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
    version.GetFileVersionInfoW.restype = wintypes.BOOL
    version.VerQueryValueW.argtypes = [wintypes.LPCVOID, wintypes.LPCWSTR, ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.UINT)]
    version.VerQueryValueW.restype = wintypes.BOOL
    size = version.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return None
    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, buffer):
        return None
    value = ctypes.c_void_p()
    length = wintypes.UINT()
    if not version.VerQueryValueW(buffer, "\\", ctypes.byref(value), ctypes.byref(length)) or not value.value:
        return None
    fixed = ctypes.cast(value, ctypes.POINTER(ctypes.c_uint32 * 13)).contents
    return _version_from_fixed_info(fixed)


def _version_from_fixed_info(fixed: Any) -> str:
    # Some OBS builds leave ProductVersion unset while publishing the same
    # semantic version in FileVersion. Prefer ProductVersion, then fall back.
    version_ms, version_ls = fixed[4], fixed[5]
    if version_ms == 0 and version_ls == 0:
        version_ms, version_ls = fixed[2], fixed[3]
    major = (version_ms >> 16) & 0xFFFF
    minor = version_ms & 0xFFFF
    patch = (version_ls >> 16) & 0xFFFF
    return f"{major}.{minor}.{patch}"


def _obs_processes() -> list[ProcessEvidence]:
    if platform.system() != "Windows":
        return []
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel = ctypes.windll.kernel32
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel.Process32FirstW.restype = wintypes.BOOL
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel.Process32NextW.restype = wintypes.BOOL
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME)]
    kernel.GetProcessTimes.restype = wintypes.BOOL
    snapshot = kernel.CreateToolhelp32Snapshot(0x00000002, 0)
    invalid = ctypes.c_void_p(-1).value
    if snapshot == invalid or snapshot == wintypes.HANDLE(invalid).value:
        return []
    results = []
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        has_entry = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while has_entry:
            if entry.szExeFile.casefold() == "obs64.exe":
                handle = kernel.OpenProcess(0x1000, False, entry.th32ProcessID)
                if handle:
                    try:
                        capacity = wintypes.DWORD(32768)
                        buffer = ctypes.create_unicode_buffer(capacity.value)
                        if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(capacity)):
                            creation, exit_time, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
                            if kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(kernel_time), ctypes.byref(user_time)):
                                ticks = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
                                seconds = ticks / 10_000_000 - 11_644_473_600
                                results.append(ProcessEvidence(entry.th32ProcessID, Path(buffer.value), datetime.fromtimestamp(seconds, timezone.utc)))
                    finally:
                        kernel.CloseHandle(handle)
            has_entry = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    return results
