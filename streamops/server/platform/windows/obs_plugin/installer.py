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

from ....errors import ObsPluginError
from ....services.obs_plugin_release_source import ManagedPluginReleaseSource
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
ACTIVE_TRANSACTION_STATES = {"preparing", "backup_verified", "mutation_pending", "recovery_required"}
APPROVED_TRANSACTION_STATES = {"installed", "approved_release_installed"}


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
    installed_version: str | None = None
    available_version: str | None = None
    restart_required: bool = False


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
        release_source: ManagedPluginReleaseSource | None = None,
    ) -> None:
        self.data_dir = Path(data_dir).resolve()
        self.plugin_root = Path(plugin_root)
        self.obs_executable = Path(obs_executable)
        self.manifest = manifest if manifest is not None else _load_manifest()
        self.release_source = release_source
        self._approved_release = None
        # Explicit manifests are supported for isolated package fixture tests only.
        # Production cannot install from the bundled upstream URL.
        self._fixture_manifest = manifest is not None
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
        installed_version = None
        if self._pending_transactions():
            installation = "recovery_required"
        elif self.pointer.exists():
            try:
                _, journal = self._read_current_transaction()
            except PluginInstallerFailure:
                installation = "recovery_required"
            else:
                matches = self._record_map(records) == self._record_map(journal.get("expected_files", []))
                if not matches:
                    installation = "conflict"
                elif journal.get("state") == "legacy_adopted":
                    installation = "legacy_adopted"
                elif journal.get("state") in APPROVED_TRANSACTION_STATES:
                    installation = "exact"
                    installed_version = journal.get("installed_version")
                else:
                    installation = "conflict"
        elif not records:
            installation = "absent"
        else:
            installation = "unmanaged"
        available_version = self.manifest["package_version"] if self._fixture_manifest else None
        if self.release_source is not None:
            try:
                available_version = self.release_source.latest("obs-multi-rtmp").version
            except ObsPluginError:
                available_version = None
        loaded_version = None
        processes = self._matching_obs_processes()
        if len(processes) == 1:
            loaded_version, module_loaded = self._load_evidence(
                processes[0], installed_version
            )
        else:
            module_loaded = False
        return InstallerStatus(
            installation=installation,
            compatible=version == self.manifest["expected_obs_version"],
            loaded=module_loaded,
            loaded_version=loaded_version,
            installed_version=installed_version,
            available_version=available_version,
        )

    def adopt(self) -> InstallerResult:
        """Snapshot an existing unmanaged tree without assigning release provenance."""
        self._assert_obs_stopped()
        pending = self._pending_transactions()
        if pending:
            raise PluginInstallerFailure("recovery_required", "An unfinished plugin transaction must be recovered first.")
        records = _file_records(self.plugin_root)
        if not records:
            raise PluginInstallerFailure("plugin_state_conflict", "No existing plugin files are available to adopt.")
        current = None
        if self.pointer.exists():
            try:
                _, current = self._read_current_transaction()
            except PluginInstallerFailure as exc:
                raise PluginInstallerFailure("recovery_required", "Managed transaction pointer is invalid.") from exc
        if current is not None:
            if (current.get("state") == "legacy_adopted" and
                    self._record_map(records) == self._record_map(current.get("expected_files", []))):
                return InstallerResult("already_adopted")
            raise PluginInstallerFailure("plugin_state_conflict", "The plugin already has managed transaction state.")

        transaction_root, transaction = self._begin_transaction(
            kind="legacy_adoption", baseline_records=records, expected_files=records,
            previous_transaction_id=None, installed_version=None,
        )
        try:
            self._snapshot_and_verify(transaction_root, transaction, records)
            if self._record_map(_file_records(self.plugin_root)) != self._record_map(records):
                raise PluginInstallerFailure("plugin_state_conflict", "Plugin files changed during adoption.")
            if self._plugin_configs() != transaction["baseline_plugin_configs"]:
                raise PluginInstallerFailure("config_conflict", "Plugin configuration changed during adoption.")
            transaction["state"] = "legacy_adopted"
            transaction["adopted_at"] = datetime.now(timezone.utc).isoformat()
            # Publish the pointer while the transaction is still recoverable.
            # A crash in this window is detected as pending; recovery restores
            # the previous pointer (or removes it for the first adoption).
            self._write_json(self.pointer, {"transaction_id": transaction["transaction_id"]})
            self._write_json(transaction_root / "transaction.json", transaction)
            return InstallerResult("adopted")
        except Exception:
            if transaction.get("state") != "legacy_adopted":
                transaction["state"] = "failed_no_mutation"
                self._write_json(transaction_root / "transaction.json", transaction)
            raise

    def _require_managed_release(self) -> None:
        if self.release_source is None and not self._fixture_manifest:
            raise PluginInstallerFailure(
                "release_unavailable", "No approved managed distribution source is configured."
            )

    def _prepare_release(self) -> None:
        self._require_managed_release()
        if self.release_source is None:
            return
        try:
            release = self.release_source.latest("obs-multi-rtmp")
        except ObsPluginError as exc:
            raise PluginInstallerFailure("release_unavailable", "Approved managed release is unavailable.") from exc
        self._approved_release = release
        metadata = release.metadata
        if not (
            isinstance(metadata.get("file_count"), int)
            and isinstance(metadata.get("relative_paths"), list)
            and isinstance(metadata.get("tree_sha256"), str)
            and re.fullmatch(r"[a-fA-F0-9]{64}", metadata["tree_sha256"])
        ):
            raise PluginInstallerFailure("artifact_manifest_mismatch", "Approved release lacks an exact file manifest.")
        self.manifest = {
            "plugin_id": release.plugin_id,
            "package_version": release.version,
            "expected_obs_version": release.obs_version,
            "artifact_name": release.artifact_name,
            "artifact_sha256": release.artifact_sha256,
            "file_count": metadata["file_count"],
            "relative_paths": metadata["relative_paths"],
            "tree_sha256": metadata["tree_sha256"],
        }

    def install(self) -> InstallerResult:
        self._prepare_release()
        self._assert_compatible()
        if self._pending_transactions():
            raise PluginInstallerFailure("recovery_required", "An unfinished plugin transaction must be recovered first.")
        records = _file_records(self.plugin_root)
        previous = None
        if self.pointer.exists() and not records:
            raise PluginInstallerFailure("recovery_required", "Managed transaction state has no plugin files.")
        if records:
            if not self.pointer.exists():
                raise PluginInstallerFailure(
                    "adoption_required", "Existing plugin files must be explicitly adopted before installation."
                )
            try:
                _, previous = self._read_current_transaction()
            except PluginInstallerFailure as exc:
                raise PluginInstallerFailure("recovery_required", "Managed transaction pointer is invalid.") from exc
            if self._record_map(records) != self._record_map(previous.get("expected_files", [])):
                raise PluginInstallerFailure("plugin_state_conflict", "Current plugin differs from its managed baseline.")
            if previous.get("state") in APPROVED_TRANSACTION_STATES:
                if previous.get("installed_version") == self.manifest["package_version"] and self._is_exact(records):
                    return InstallerResult("already_installed")
                raise PluginInstallerFailure("plugin_state_conflict", "Use update for an existing approved release.")
            if previous.get("state") != "legacy_adopted":
                raise PluginInstallerFailure("plugin_state_conflict", "Existing plugin state cannot be installed safely.")
        self._assert_obs_stopped()
        staged = Path(tempfile.mkdtemp(prefix="streamops-obs-multi-rtmp-"))
        try:
            expected_records = self._stage_artifact(staged)
            transaction_root, transaction = self._begin_transaction(
                kind="approved_release_install", baseline_records=records,
                expected_files=expected_records,
                previous_transaction_id=previous.get("transaction_id") if previous else None,
                installed_version=self.manifest["package_version"],
            )
            self._add_release_identity(transaction)
            try:
                self._snapshot_and_verify(transaction_root, transaction, records)
                transaction["state"] = "mutation_pending"
                transaction["mutation_started"] = False
                self._write_json(transaction_root / "transaction.json", transaction)
                # Exact legacy bytes are promoted only after the approved artifact
                # has been downloaded and verified; no unnecessary rewrite occurs.
                if self._record_map(records) != self._record_map(expected_records):
                    transaction["mutation_started"] = True
                    self._write_json(transaction_root / "transaction.json", transaction)
                    self._clear_contents(self.plugin_root)
                    self._copy_contents(staged, self.plugin_root)
                installed = _file_records(self.plugin_root)
                if not self._is_exact(installed):
                    raise PluginInstallerFailure("install_failed", "Installed plugin failed exact manifest verification.")
                if self._plugin_configs() != transaction["baseline_plugin_configs"]:
                    raise PluginInstallerFailure("config_conflict", "Plugin configuration changed during install.")
                self._write_json(self.pointer, {"transaction_id": transaction["transaction_id"]})
                transaction["state"] = "approved_release_installed"
                transaction["installed_at"] = datetime.now(timezone.utc).isoformat()
                self._write_json(transaction_root / "transaction.json", transaction)
            except Exception:
                self._restore_or_mark_failed(transaction_root, transaction)
                raise
            return InstallerResult("installed")
        except PermissionError as exc:
            raise PluginInstallerFailure("permission_denied", "Permission denied for the managed plugin directory.") from exc
        finally:
            shutil.rmtree(staged, ignore_errors=True)

    def update(self) -> InstallerResult:
        """Replace v1 with a verified v2 package in a separate rollback journal."""
        self._prepare_release()
        self._assert_compatible()
        self._assert_obs_stopped()
        if self._pending_transactions():
            raise PluginInstallerFailure("recovery_required", "An unfinished plugin transaction must be recovered first.")
        current = _file_records(self.plugin_root)
        if not current:
            raise PluginInstallerFailure("plugin_state_conflict", "Plugin is not installed.")
        try:
            _, previous = self._read_current_transaction()
        except PluginInstallerFailure as exc:
            raise PluginInstallerFailure("transaction_missing", "Cannot update without a verified baseline.") from exc
        if (previous.get("state") not in APPROVED_TRANSACTION_STATES or
                self._record_map(current) != self._record_map(previous.get("expected_files", []))):
            raise PluginInstallerFailure("plugin_state_conflict", "Current plugin differs from verified baseline.")
        previous_version = previous.get("installed_version")
        new_version = self.manifest["package_version"]
        if previous_version is not None:
            def parts(value: str) -> tuple[int, ...]:
                return tuple(int(piece) for piece in value.split("."))
            if parts(new_version) <= parts(previous_version):
                raise PluginInstallerFailure("update_not_available", "No newer approved version exists.")
        staged = Path(tempfile.mkdtemp(prefix="streamops-obs-multi-rtmp-update-"))
        try:
            expected = self._stage_artifact(staged)
            transaction_root, transaction = self._begin_transaction(
                kind="approved_release_update", baseline_records=current,
                expected_files=expected, previous_transaction_id=previous["transaction_id"],
                installed_version=new_version,
            )
            transaction["previous_version"] = previous_version
            self._add_release_identity(transaction)
            try:
                self._snapshot_and_verify(transaction_root, transaction, current)
                transaction["state"] = "mutation_pending"
                transaction["mutation_started"] = True
                self._write_json(transaction_root / "transaction.json", transaction)
                self._clear_contents(self.plugin_root)
                self._copy_contents(staged, self.plugin_root)
                if self._record_map(_file_records(self.plugin_root)) != self._record_map(expected):
                    raise PluginInstallerFailure("update_failed", "Updated files failed verification.")
                if self._plugin_configs() != transaction["baseline_plugin_configs"]:
                    raise PluginInstallerFailure("config_conflict", "OBS config changed during update.")
                self._write_json(self.pointer, {"transaction_id": transaction["transaction_id"]})
                transaction["state"] = "approved_release_installed"
                self._write_json(transaction_root / "transaction.json", transaction)
            except Exception:
                self._restore_or_mark_failed(transaction_root, transaction)
                raise
            return InstallerResult("updated")
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
        if not status.loaded or status.loaded_version != status.installed_version:
            raise PluginInstallerFailure("module_not_loaded", "Current OBS process has no matching plugin load evidence.")
        return status

    def rollback(self) -> InstallerResult:
        self._assert_obs_stopped()
        pending = self._pending_transactions()
        if pending:
            if len(pending) != 1:
                raise PluginInstallerFailure("recovery_required", "Multiple unfinished transactions require manual review.")
            transaction_root, transaction = pending[0]
            baseline = transaction.get("baseline_files", [])
            current = _file_records(self.plugin_root)
            if transaction.get("state") in {"preparing", "backup_verified"} and not transaction.get("mutation_started"):
                if self._record_map(current) != self._record_map(baseline):
                    raise PluginInstallerFailure("recovery_required", "Plugin changed during an unfinished transaction.")
                if self._plugin_configs() != transaction.get("baseline_plugin_configs", []):
                    raise PluginInstallerFailure("recovery_required", "Configuration changed during an unfinished transaction.")
                self._restore_previous_pointer(transaction)
                transaction["state"] = "failed_no_mutation"
                transaction["recovered_at"] = datetime.now(timezone.utc).isoformat()
                self._write_json(transaction_root / "transaction.json", transaction)
                return InstallerResult("recovered_no_mutation")
            if (transaction.get("state") in {"mutation_pending", "recovery_required"} and
                    transaction.get("backup_verified") is True and transaction.get("mutation_started") is True):
                self._restore_backup_verified(transaction_root, transaction)
                self._restore_previous_pointer(transaction)
                transaction["state"] = "recovered_rolled_back"
                transaction["recovered_at"] = datetime.now(timezone.utc).isoformat()
                self._write_json(transaction_root / "transaction.json", transaction)
                return InstallerResult("recovered_rolled_back")
            raise PluginInstallerFailure("recovery_required", "The unfinished transaction has no verified recovery path.")

        transaction_root, transaction = self._read_current_transaction()
        if transaction.get("state") == "legacy_adopted":
            raise PluginInstallerFailure("plugin_state_conflict", "No approved release is available to roll back.")
        if transaction.get("state") not in APPROVED_TRANSACTION_STATES:
            raise PluginInstallerFailure("recovery_required", "Current transaction is not safely committed.")
        current = _file_records(self.plugin_root)
        expected = transaction.get("expected_files", [])
        if self._record_map(current) != self._record_map(expected):
            raise PluginInstallerFailure("rollback_conflict", "Plugin files are missing, modified, or unmanaged.")
        self._restore_backup_verified(transaction_root, transaction)
        # Switch to the already-committed previous baseline before retiring
        # this transaction. A crash leaves either a recoverable current
        # transaction or a pointer to a byte-matching committed baseline.
        self._restore_previous_pointer(transaction)
        transaction["state"] = "rolled_back"
        transaction["rolled_back_at"] = datetime.now(timezone.utc).isoformat()
        self._write_json(transaction_root / "transaction.json", transaction)
        return InstallerResult("rolled_back")

    def _stage_artifact(self, destination: Path) -> list[dict[str, Any]]:
        artifact_path = destination / str(self.manifest["artifact_name"])
        digest = hashlib.sha256()
        try:
            with (self.release_source.open_artifact(self._approved_release) if self.release_source is not None else self.downloader(str(self.manifest["artifact_url"]))) as source, artifact_path.open("wb") as target:
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

    def _load_evidence(self, process: ProcessEvidence, expected_version: str | None) -> tuple[str | None, bool]:
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
        return version, module_loaded and expected_version is not None and version == expected_version

    def _plugin_configs(self) -> list[dict[str, Any]]:
        if self.appdata is None:
            return []
        root = self.appdata / "obs-studio" / "basic" / "profiles"
        if not root.is_dir():
            return []
        results = []
        for path in sorted(root.rglob(PLUGIN_CONFIG_NAME)):
            if path.is_symlink():
                raise PluginInstallerFailure("config_conflict", "Plugin configuration contains a link.")
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
            if transaction.get("state") not in APPROVED_TRANSACTION_STATES | {"legacy_adopted"}:
                raise ValueError("transaction is not committed")
            return root, transaction
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PluginInstallerFailure("transaction_missing", "Managed rollback transaction is unavailable.") from exc

    def _pending_transactions(self) -> list[tuple[Path, dict[str, Any]]]:
        if not self.transactions_root.is_dir():
            return []
        pending = []
        for root in sorted(self.transactions_root.iterdir()):
            if not root.is_dir():
                continue
            try:
                transaction = json.loads((root / "transaction.json").read_text(encoding="utf-8"))
            except (OSError, TypeError, json.JSONDecodeError):
                pending.append((root, {"state": "recovery_required", "transaction_id": root.name}))
                continue
            if transaction.get("state") in ACTIVE_TRANSACTION_STATES:
                pending.append((root, transaction))
        return pending

    def _begin_transaction(
        self, *, kind: str, baseline_records: list[dict[str, Any]],
        expected_files: list[dict[str, Any]], previous_transaction_id: str | None,
        installed_version: str | None,
    ) -> tuple[Path, dict[str, Any]]:
        self.state_root.mkdir(parents=True, exist_ok=True)
        transaction_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
        transaction_root = self.transactions_root / transaction_id
        transaction_root.mkdir(parents=True)
        transaction = {
            "schema_version": 2,
            "kind": kind,
            "state": "preparing",
            "transaction_id": transaction_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "plugin_root_existed": self.plugin_root.is_dir(),
            "backup_relative": "backup/obs-multi-rtmp" if self.plugin_root.is_dir() else None,
            "backup_verified": False,
            "mutation_started": False,
            "baseline_files": baseline_records,
            "baseline_plugin_configs": self._plugin_configs(),
            "expected_files": expected_files,
            "installed_version": installed_version,
            "previous_transaction_id": previous_transaction_id,
        }
        self._write_json(transaction_root / "transaction.json", transaction)
        return transaction_root, transaction

    def _snapshot_and_verify(
        self, transaction_root: Path, transaction: dict[str, Any], baseline_records: list[dict[str, Any]],
    ) -> None:
        if self._record_map(_file_records(self.plugin_root)) != self._record_map(baseline_records):
            raise PluginInstallerFailure("plugin_state_conflict", "Plugin files changed before backup.")
        backup_relative = transaction.get("backup_relative")
        if backup_relative:
            relative = _safe_relative(str(backup_relative))
            backup = transaction_root.joinpath(*relative.parts)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self.plugin_root, backup)
            self._sync_tree(backup)
            if self._record_map(_file_records(backup)) != self._record_map(baseline_records):
                raise PluginInstallerFailure("backup_invalid", "Plugin backup failed byte-for-byte verification.")
        elif baseline_records:
            raise PluginInstallerFailure("backup_invalid", "Existing plugin files have no backup path.")
        if self._record_map(_file_records(self.plugin_root)) != self._record_map(baseline_records):
            raise PluginInstallerFailure("plugin_state_conflict", "Plugin files changed during backup.")
        if self._plugin_configs() != transaction["baseline_plugin_configs"]:
            raise PluginInstallerFailure("config_conflict", "Plugin configuration changed during backup.")
        config_backup_root = transaction_root / "backup" / "configs"
        for index, item in enumerate(transaction["baseline_plugin_configs"]):
            source = self._safe_config_path(str(item["path"]))
            target = config_backup_root / f"{index:04d}.bin"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            self._sync_file(target)
            if target.stat().st_size != item["length"] or _sha256_file(target) != item["sha256"]:
                raise PluginInstallerFailure("backup_invalid", "Plugin configuration backup failed verification.")
        if self._plugin_configs() != transaction["baseline_plugin_configs"]:
            raise PluginInstallerFailure("config_conflict", "Plugin configuration changed during backup.")
        transaction["backup_verified"] = True
        transaction["state"] = "backup_verified"
        self._write_json(transaction_root / "transaction.json", transaction)

    def _add_release_identity(self, transaction: dict[str, Any]) -> None:
        release = self._approved_release
        transaction["source_commit"] = getattr(release, "source_commit", None)
        transaction["release_ref"] = (
            f"obs-multi-rtmp/v{self.manifest['package_version']}" if release is not None else None
        )

    def _restore_backup_verified(
        self, transaction_root: Path, transaction: dict[str, Any], *, restore_configs: bool = True,
    ) -> None:
        if transaction.get("backup_verified") is not True:
            raise PluginInstallerFailure("backup_invalid", "Transaction backup was not verified.")
        baseline = transaction.get("baseline_files", [])
        backup = None
        if transaction.get("plugin_root_existed"):
            relative = _safe_relative(str(transaction.get("backup_relative") or ""))
            backup = transaction_root.joinpath(*relative.parts)
            if not backup.is_dir() or self._record_map(_file_records(backup)) != self._record_map(baseline):
                raise PluginInstallerFailure("backup_invalid", "Transaction backup is missing or corrupt.")
        config_backups: list[tuple[Path, Path, dict[str, Any]]] = []
        if restore_configs:
            baseline_configs = transaction.get("baseline_plugin_configs", [])
            baseline_paths = {str(item["path"]) for item in baseline_configs}
            for item in self._plugin_configs():
                if item["path"] not in baseline_paths and not self._is_empty_plugin_config(Path(item["path"])):
                    raise PluginInstallerFailure("config_conflict", "A new plugin configuration contains settings.")
            for index, item in enumerate(baseline_configs):
                destination = self._safe_config_path(str(item["path"]))
                source = transaction_root / "backup" / "configs" / f"{index:04d}.bin"
                if (not source.is_file() or source.stat().st_size != item["length"] or
                        _sha256_file(source) != item["sha256"]):
                    raise PluginInstallerFailure("backup_invalid", "Plugin configuration backup is missing or corrupt.")
                config_backups.append((source, destination, item))
        if backup is not None:
            self._clear_contents(self.plugin_root)
            self._copy_contents(backup, self.plugin_root)
        else:
            self._clear_contents(self.plugin_root)
        if self._record_map(_file_records(self.plugin_root)) != self._record_map(baseline):
            raise PluginInstallerFailure("backup_invalid", "Restored plugin differs from its baseline.")
        if restore_configs:
            baseline_paths = {str(item["path"]) for _, _, item in config_backups}
            for item in self._plugin_configs():
                if item["path"] not in baseline_paths:
                    extra = Path(item["path"])
                    if not self._is_empty_plugin_config(extra):
                        raise PluginInstallerFailure("config_conflict", "A new plugin configuration changed during recovery.")
                    extra.unlink(missing_ok=True)
            for source, destination, _ in config_backups:
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_name(destination.name + ".tmp-" + uuid.uuid4().hex)
                shutil.copy2(source, temporary)
                self._sync_file(temporary)
                os.replace(temporary, destination)
            if self._plugin_configs() != transaction.get("baseline_plugin_configs", []):
                raise PluginInstallerFailure("config_conflict", "Plugin configuration differs from the rollback baseline.")

    def _safe_config_path(self, value: str) -> Path:
        if self.appdata is None:
            raise PluginInstallerFailure("config_conflict", "Plugin configuration root is unavailable.")
        root = (self.appdata / "obs-studio" / "basic" / "profiles").resolve(strict=False)
        path = Path(value).resolve(strict=False)
        if not path.is_relative_to(root) or path.name != PLUGIN_CONFIG_NAME:
            raise PluginInstallerFailure("config_conflict", "Plugin configuration path is outside the managed profile root.")
        return path

    def _restore_or_mark_failed(self, transaction_root: Path, transaction: dict[str, Any]) -> None:
        if not transaction.get("mutation_started"):
            self._restore_previous_pointer(transaction)
            transaction["state"] = "failed_no_mutation"
            self._write_json(transaction_root / "transaction.json", transaction)
            return
        try:
            self._restore_backup_verified(transaction_root, transaction)
        except Exception:
            transaction["state"] = "recovery_required"
            self._write_json(transaction_root / "transaction.json", transaction)
            raise
        self._restore_previous_pointer(transaction)
        transaction["state"] = "failed_restored"
        transaction["restored_at"] = datetime.now(timezone.utc).isoformat()
        self._write_json(transaction_root / "transaction.json", transaction)

    def _restore_previous_pointer(self, transaction: dict[str, Any]) -> None:
        previous_id = transaction.get("previous_transaction_id")
        if previous_id:
            if not re.fullmatch(r"\d{8}-\d{6}-[a-f0-9]{8}", str(previous_id)):
                raise PluginInstallerFailure("transaction_missing", "Previous transaction identity is invalid.")
            previous_root = self.transactions_root / str(previous_id)
            try:
                previous = json.loads((previous_root / "transaction.json").read_text(encoding="utf-8"))
            except (OSError, TypeError, json.JSONDecodeError) as exc:
                raise PluginInstallerFailure("transaction_missing", "Previous transaction is unavailable.") from exc
            if (previous.get("transaction_id") != previous_id or
                    previous.get("state") not in APPROVED_TRANSACTION_STATES | {"legacy_adopted"}):
                raise PluginInstallerFailure("transaction_missing", "Previous transaction is not committed.")
            self._write_json(self.pointer, {"transaction_id": previous_id})
        else:
            self.pointer.unlink(missing_ok=True)

    @staticmethod
    def _sync_file(path: Path) -> None:
        # Windows rejects fsync on a read-only descriptor (Errno 9). Backups
        # are owned by this transaction, so open writable without changing
        # bytes before flushing them to disk.
        with path.open("r+b") as handle:
            os.fsync(handle.fileno())

    @classmethod
    def _sync_tree(cls, root: Path) -> None:
        for path in root.rglob("*"):
            if path.is_file():
                cls._sync_file(path)

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
