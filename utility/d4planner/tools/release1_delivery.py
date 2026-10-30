"""Fail-closed Release 1 package and acceptance utility for S7.

It never starts the game, OBS, Steam, NVDA, or GitHub Actions. Runtime cases need
explicit evidence produced by the integrated Windows package; absence is BLOCKED.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import signal
import socket
import subprocess
import sys
import time
import zipfile
import zlib
sys.path.insert(0, str(Path(__file__).resolve().parent))
import public_package as public

PLAN_VERSION = "d4planner-package-plan/v1"
MANIFEST_VERSION = "d4planner-release-manifest/v1"
REPORT_VERSION = "d4planner-acceptance-report/v1"
COMPONENT_MANIFEST_VERSION = "d4planner-component-shas/v1"
EXECUTOR_MANIFEST_VERSION = "d4planner-e2e-executors/v1"
EXECUTOR_EVIDENCE_VERSION = "d4planner-executor-evidence/v1"
FORBIDDEN_NAMES = {".env", "id_rsa", "id_ed25519", "credentials.json", "secrets.json"}


class DeliveryError(RuntimeError):
    pass


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeliveryError(f"INVALID_JSON:{path.name}:{type(exc).__name__}") from exc
    if not isinstance(value, dict):
        raise DeliveryError(f"INVALID_OBJECT:{path.name}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_relative(value: str) -> Path:
    if not value or "\x00" in value or "\\" in value or ":" in value:
        raise DeliveryError(f"UNSAFE_PATH:{value}")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or ".." in posix.parts
        or not posix.parts
        or any(part in {"", "."} for part in value.split("/"))
        or posix.as_posix() != value
    ):
        raise DeliveryError(f"UNSAFE_PATH:{value}")
    return Path(*posix.parts)


def _contained_destination(root: Path, relative: str) -> Path:
    resolved_root = root.resolve()
    destination = (resolved_root / safe_relative(relative)).resolve()
    if destination == resolved_root or resolved_root not in destination.parents:
        raise DeliveryError(f"UNSAFE_PATH:{relative}")
    return destination


def validate_plan(plan: dict) -> None:
    if plan.get("schemaVersion") != PLAN_VERSION:
        raise DeliveryError("PLAN_VERSION_MISMATCH")
    paths: set[str] = set()
    ids: set[str] = set()
    for artifact in plan.get("artifacts", []):
        artifact_id = str(artifact.get("id", ""))
        path = str(artifact.get("path", ""))
        safe_relative(path)
        if not artifact_id or artifact_id in ids or path in paths:
            raise DeliveryError("DUPLICATE_OR_EMPTY_ARTIFACT")
        ids.add(artifact_id); paths.add(path)
        if artifact.get("kind", "file") not in {"file", "tree"}:
            raise DeliveryError("INVALID_ARTIFACT_KIND")
    for resource in plan.get("resources", []):
        resource_id = str(resource.get("id", "")); path = str(resource.get("path", ""))
        safe_relative(path); safe_relative(str(resource.get("source", "")))
        if not resource_id or resource_id in ids or path in paths:
            raise DeliveryError("DUPLICATE_OR_EMPTY_ARTIFACT")
        ids.add(resource_id); paths.add(path)
    if not ids:
        raise DeliveryError("NO_ARTIFACTS")
    rulekit = plan.get("ruleKit") or {}
    if rulekit.get("snapshotIncluded") is not False or rulekit.get("snapshotManagementContract") != "d4-rulekit-snapshots/v1":
        raise DeliveryError("PUBLIC_SNAPSHOT_SEPARATION_REQUIRED")


def _check_source(path: Path, relative: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise DeliveryError(f"MISSING_OR_UNSAFE_ARTIFACT:{relative}")
    if path.name.lower() in FORBIDDEN_NAMES or path.suffix.lower() in {".pem", ".key", ".pfx"}:
        raise DeliveryError(f"FORBIDDEN_SECRET_FILE:{relative}")


def build_package(plan_path: Path, source: Path, output: Path, *, release_version: str | None = None) -> dict:
    plan = load_json(plan_path); validate_plan(plan)
    if release_version is not None:
        import re
        if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", release_version):
            raise DeliveryError("INVALID_RELEASE_VERSION")
        plan["version"] = release_version
    files = []
    for artifact in plan["artifacts"]:
        relative = str(artifact["path"]); path = source / safe_relative(relative)
        if artifact.get("kind", "file") == "tree":
            if path.is_symlink() or not path.is_dir():
                raise DeliveryError(f"MISSING_OR_UNSAFE_ARTIFACT:{relative}")
            members = sorted(member for member in path.rglob("*") if member.is_file())
            if not members:
                raise DeliveryError(f"EMPTY_ARTIFACT_TREE:{relative}")
            for member in members:
                if member.is_symlink():
                    raise DeliveryError(f"MISSING_OR_UNSAFE_ARTIFACT:{relative}")
                member_relative = member.relative_to(source).as_posix()
                _check_source(member, member_relative)
                files.append({
                    "id": artifact["id"], "path": member_relative,
                    "owner": artifact["owner"], "sha256": sha256_file(member),
                    "bytes": member.stat().st_size,
                })
        else:
            _check_source(path, relative)
            files.append({
                "id": artifact["id"], "path": relative, "owner": artifact["owner"],
                "sha256": sha256_file(path), "bytes": path.stat().st_size,
            })
    repository_root = plan_path.resolve().parents[3]
    for resource in plan.get("resources", []):
        relative = str(resource["path"])
        path = repository_root / safe_relative(str(resource["source"]))
        _check_source(path, relative)
        files.append({
            "id": resource["id"], "path": relative, "owner": "S7",
            "sha256": sha256_file(path), "bytes": path.stat().st_size,
            "source": str(resource["source"]),
        })
    manifest = {
        "schemaVersion": MANIFEST_VERSION, "release": plan["release"],
        "contractRevision": plan["contractRevision"],
        "magicPathRevision": plan["magicPathRevision"], "ruleKit": plan["ruleKit"],
        "persistentPaths": plan["persistentPaths"], "files": files,
    }
    for key in ("applicationId", "version", "hudSchemaCompatibility"):
        if key in plan:
            manifest[key] = plan[key]
    stage_report = source / "build-stage.json"
    if stage_report.is_file():
        source_head = json.loads(stage_report.read_text(encoding="utf-8")).get("sourceHead")
        if isinstance(source_head, str) and len(source_head) == 40 and all(c in "0123456789abcdef" for c in source_head):
            manifest["sourceHead"] = source_head
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as package:
        info = zipfile.ZipInfo("release-manifest.json", (1980, 1, 1, 0, 0, 0)); info.external_attr = 0o644 << 16
        package.writestr(info, encoded, compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
        for entry in sorted(files, key=lambda item: item["path"]):
            info = zipfile.ZipInfo(entry["path"], (1980, 1, 1, 0, 0, 0)); info.external_attr = 0o644 << 16
            source_path = (
                repository_root / safe_relative(entry["source"])
                if "source" in entry else source / safe_relative(entry["path"])
            )
            data = source_path.read_bytes()
            public.inspect_bytes(entry["path"], data)
            package.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
    verify_package(output)
    return {"manifest": manifest, "artifactSha256": sha256_file(output)}


def verify_package(package_path: Path, *, public_only: bool = False) -> dict:
    try:
        with zipfile.ZipFile(package_path) as package:
            names = package.namelist()
            for name in names:
                safe_relative(name)
            if len(names) != len(set(names)) or "release-manifest.json" not in names:
                raise DeliveryError("INVALID_ARCHIVE_INDEX")
            manifest = json.loads(package.read("release-manifest.json"))
            if manifest.get("schemaVersion") != MANIFEST_VERSION:
                raise DeliveryError("MANIFEST_VERSION_MISMATCH")
            snapshot_free = (manifest.get("ruleKit") or {}).get("snapshotIncluded") is False
            if public_only and not snapshot_free:
                raise DeliveryError("PUBLIC_SNAPSHOT_SEPARATION_REQUIRED")
            declared = {entry["path"]: entry for entry in manifest.get("files", [])}
            if set(names) != {"release-manifest.json", *declared}:
                raise DeliveryError("UNDECLARED_OR_MISSING_FILE")
            for relative, entry in declared.items():
                safe_relative(relative)
                data = package.read(relative)
                if snapshot_free:
                    public.inspect_bytes(relative, data)
                if hashlib.sha256(data).hexdigest() != entry.get("sha256") or len(data) != entry.get("bytes"):
                    raise DeliveryError(f"ARTIFACT_HASH_MISMATCH:{relative}")
            return manifest
    except (OSError, zipfile.BadZipFile, zlib.error, KeyError, json.JSONDecodeError) as exc:
        raise DeliveryError(f"INVALID_PACKAGE:{type(exc).__name__}") from exc


def install_package(package_path: Path, app_dir: Path, data_dir: Path) -> dict:
    """Install app files atomically enough for review; never alter persistent data."""
    manifest = verify_package(package_path)
    app_resolved = app_dir.resolve(); data_resolved = data_dir.resolve()
    if (
        app_resolved == data_resolved
        or app_resolved in data_resolved.parents
        or data_resolved in app_resolved.parents
    ):
        raise DeliveryError("APP_DATA_DIR_OVERLAP")
    data_dir.mkdir(parents=True, exist_ok=True)
    targets = data_dir / "targets"; state = data_dir / "state"
    targets.mkdir(exist_ok=True); state.mkdir(exist_ok=True)
    staging = app_dir.with_name(app_dir.name + ".staging")
    if staging.exists(): shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        with zipfile.ZipFile(package_path) as package:
            (staging / "release-manifest.json").write_bytes(package.read("release-manifest.json"))
            for entry in manifest["files"]:
                destination = _contained_destination(staging, entry["path"])
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(package.read(entry["path"]))
        if app_dir.exists():
            backup = app_dir.with_name(app_dir.name + ".previous")
            if backup.exists(): shutil.rmtree(backup)
            os.replace(app_dir, backup)
        os.replace(staging, app_dir)
    finally:
        if staging.exists(): shutil.rmtree(staging)
    return {"appDir": str(app_dir), "dataDir": str(data_dir), "preserved": [str(targets), str(state)]}


def rollback_install(app_dir: Path, data_dir: Path) -> dict:
    app_resolved = app_dir.resolve(); data_resolved = data_dir.resolve()
    if app_resolved == data_resolved or app_resolved in data_resolved.parents or data_resolved in app_resolved.parents:
        raise DeliveryError("APP_DATA_DIR_OVERLAP")
    previous = app_dir.with_name(app_dir.name + ".previous")
    if previous.is_symlink() or not previous.is_dir():
        raise DeliveryError("ROLLBACK_NOT_AVAILABLE")
    failed = app_dir.with_name(app_dir.name + ".failed")
    if failed.exists(): shutil.rmtree(failed)
    if app_dir.exists(): os.replace(app_dir, failed)
    os.replace(previous, app_dir)
    return {"appDir": str(app_dir), "dataDir": str(data_dir), "rollback": "APPLIED"}


def _windows_preflight(
    package: Path | None,
    expected_package_sha256: str | None,
    staging_root: Path | None,
    evidence_dir: Path | None,
    runtime_platform: str,
    approved_port: int | None = None,
) -> dict:
    failures: list[str] = []
    if runtime_platform != "win32":
        failures.append("WINDOWS_REQUIRED")
    if package is None or not package.is_file():
        failures.append("PACKAGE_REQUIRED")
    elif not expected_package_sha256:
        failures.append("EXPECTED_PACKAGE_SHA256_REQUIRED")
    elif sha256_file(package) != expected_package_sha256.lower():
        failures.append("PACKAGE_SHA256_MISMATCH")
    if staging_root is None or not staging_root.is_absolute() or not staging_root.is_dir():
        failures.append("ISOLATED_STAGING_ROOT_REQUIRED")
    if evidence_dir is None or not evidence_dir.is_absolute() or not evidence_dir.is_dir():
        failures.append("EVIDENCE_DIRECTORY_REQUIRED")
    if sys.version_info < (3, 11):
        failures.append("PYTHON_3_11_REQUIRED")
    if approved_port is not None:
        if isinstance(approved_port, bool) or not 1 <= approved_port <= 65535:
            failures.append("INVALID_APPROVED_PORT")
        else:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                probe.bind(("127.0.0.1", approved_port))
            except OSError:
                failures.append("APPROVED_PORT_NOT_AVAILABLE")
            finally:
                probe.close()
    if failures:
        return {
            "id": "S7-PRE-01", "status": "BLOCKED",
            "classification": "ENVIRONMENT_FAILURE", "actual": failures,
        }
    return {
        "id": "S7-PRE-01", "status": "PASS", "classification": "AUTOMATED",
        "actual": {
            "platform": runtime_platform,
            "python": ".".join(map(str, sys.version_info[:3])),
            "packageSha256": expected_package_sha256.lower(),
            "stagingRoot": str(staging_root), "evidenceDir": str(evidence_dir),
            "approvedPort": approved_port,
        },
    }


def acceptance_exit_code(report: dict) -> int:
    statuses = {case.get("status") for case in report.get("cases", [])}
    if "FAIL" in statuses:
        return 1
    if "BLOCKED" in statuses:
        return 3
    return 0 if "PASS" in statuses else 3


def load_component_shas(path: Path | None) -> dict[str, str]:
    if path is None:
        raise DeliveryError("COMPONENT_MANIFEST_REQUIRED")
    value = load_json(path)
    components = value.get("components")
    if value.get("schemaVersion") != COMPONENT_MANIFEST_VERSION or not isinstance(components, dict):
        raise DeliveryError("INVALID_COMPONENT_MANIFEST")
    expected = {f"S{number}" for number in range(2, 8)}
    if set(components) != expected:
        raise DeliveryError("COMPONENT_MANIFEST_SCOPE_MISMATCH")
    for name, sha in components.items():
        if not isinstance(sha, str) or len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
            raise DeliveryError(f"INVALID_COMPONENT_SHA:{name}")
    return dict(components)


def load_executors(path: Path | None) -> dict[str, dict]:
    if path is None:
        return {}
    value = load_json(path)
    cases = value.get("cases")
    if value.get("schemaVersion") != EXECUTOR_MANIFEST_VERSION or not isinstance(cases, dict):
        raise DeliveryError("INVALID_EXECUTOR_MANIFEST")
    result: dict[str, dict] = {}
    for case_id, spec in cases.items():
        if not isinstance(case_id, str) or not isinstance(spec, dict):
            raise DeliveryError("INVALID_EXECUTOR_CASE")
        command = spec.get("command")
        timeout = spec.get("timeoutSeconds")
        cwd = spec.get("workingDirectory", ".")
        evidence_file = spec.get("evidenceFile", f"{case_id}.json")
        if (
            not isinstance(command, list) or not command
            or any(not isinstance(token, str) or not token or "\x00" in token for token in command)
            or not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 1800
            or not isinstance(cwd, str)
            or not isinstance(evidence_file, str) or not evidence_file
        ):
            raise DeliveryError(f"INVALID_EXECUTOR_CASE:{case_id}")
        blockers = spec.get("allowedBlockers", [])
        if (not isinstance(blockers, list) or any(item not in {
                "OWNER_APPROVAL_REQUIRED", "PENDING_DEPENDENCY", "ENVIRONMENT_FAILURE"
        } for item in blockers)):
            raise DeliveryError(f"INVALID_EXECUTOR_BLOCKERS:{case_id}")
        if cwd != ".":
            safe_relative(cwd)
        safe_relative(evidence_file.replace("{CASE_ID}", case_id))
        if not isinstance(spec.get("requiredEvidence", {}), dict):
            raise DeliveryError(f"INVALID_EXECUTOR_CASE:{case_id}")
        result[case_id] = {**spec, "evidenceFile": evidence_file}
    return result


def _owned_process_tree(root_pid: int) -> list[int]:
    """Read the descendant PID tree without using process-name matching."""
    if sys.platform == "win32":
        script = (
            "$p=Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId;"
            f"$todo=@({root_pid});$seen=@();while($todo.Count){{$n=$todo[0];"
            "$todo=@($todo|Select-Object -Skip 1);$seen+=$n;"
            "$todo+=@($p|Where-Object ParentProcessId -eq $n|ForEach-Object ProcessId)}};"
            "$seen|ConvertTo-Json -Compress"
        )
        try:
            value = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, timeout=10, check=False,
            )
            parsed = json.loads(value.stdout or "[]")
            return sorted({int(item) for item in (parsed if isinstance(parsed, list) else [parsed])})
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, json.JSONDecodeError):
            return [root_pid]
    parents: dict[int, int] = {}
    proc = Path("/proc")
    if proc.is_dir():
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                fields = (entry / "stat").read_text().split()
                parents[int(entry.name)] = int(fields[3])
            except (OSError, ValueError, IndexError):
                continue
    found = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, parent in parents.items():
            if parent in found and pid not in found:
                found.add(pid); changed = True
    return sorted(found)


class _OwnedProcess:
    """One executor and its descendants, killed as an ownership unit."""
    def __init__(self, command: list[str], cwd: Path):
        flags = 0
        kwargs: dict = {}
        self.job = None
        if sys.platform == "win32":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        self.process = subprocess.Popen(
            command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, shell=False, creationflags=flags, **kwargs,
        )
        if sys.platform == "win32":
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateJobObjectW.restype = ctypes.c_void_p
            kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
            kernel32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
            kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            job = kernel32.CreateJobObjectW(None, None)
            if not job:
                self.process.kill()
                raise OSError(ctypes.get_last_error(), "CreateJobObjectW")
            # JOBOBJECT_EXTENDED_LIMIT_INFORMATION is 144 bytes on 64-bit and
            # 112 bytes on 32-bit. LimitFlags is the first DWORD after two
            # LARGE_INTEGER values (offset 16); zero-filled remainder is valid.
            size = 144 if ctypes.sizeof(ctypes.c_void_p) == 8 else 112
            info = ctypes.create_string_buffer(size)
            ctypes.c_uint32.from_buffer(info, 16).value = 0x00002000  # KILL_ON_JOB_CLOSE
            if not kernel32.SetInformationJobObject(job, 9, info, size):
                kernel32.CloseHandle(job); self.process.kill()
                raise OSError(ctypes.get_last_error(), "SetInformationJobObject")
            if not kernel32.AssignProcessToJobObject(job, ctypes.c_void_p(int(self.process._handle))):
                kernel32.CloseHandle(job); self.process.kill()
                raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject")
            self.job = job

    def terminate_tree(self) -> None:
        if self.job is not None:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            kernel32.TerminateJobObject(self.job, 124)
        elif self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGKILL)

    def close(self) -> None:
        if self.job is not None:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle(self.job)
            self.job = None


def _validate_executor_evidence(case_id: str, spec: dict, evidence_root: Path) -> tuple[bool, str, Path]:
    relative = str(spec["evidenceFile"]).replace("{CASE_ID}", case_id)
    path = _contained_destination(evidence_root, relative)
    if not path.is_file():
        return False, "EXECUTOR_EVIDENCE_MISSING", path
    try:
        value = load_json(path)
    except DeliveryError:
        return False, "EXECUTOR_EVIDENCE_INVALID_JSON", path
    if value.get("ok") is not True:
        return False, "EXECUTOR_EVIDENCE_NOT_OK", path
    for key, expected in spec.get("requiredEvidence", {}).items():
        actual = value
        for part in key.split("."):
            if not isinstance(actual, dict) or part not in actual:
                return False, f"EXECUTOR_EVIDENCE_MISSING_FIELD:{key}", path
            actual = actual[part]
        if actual != expected:
            return False, f"EXECUTOR_EVIDENCE_MISMATCH:{key}", path
    return True, "EXECUTOR_EVIDENCE_VERIFIED", path


def _executor_command(spec: dict, root: Path, evidence_root: Path, package: Path | None,
                      approved_port: int | None, component_shas: dict | None) -> list[str]:
    replacements = {
        "{STAGING_ROOT}": str(root), "{INSTALL_ROOT}": str(root / "app"),
        "{DATA_ROOT}": str(root / "data"), "{EVIDENCE_DIR}": str(evidence_root),
        "{PACKAGE}": str(package.resolve()) if package else "",
        "{PYTHON}": str(root / "app/runtime/python/python.exe"),
        "{APPROVED_PORT}": str(approved_port) if approved_port is not None else "",
        **{f"{{{name}_SHA}}": sha for name, sha in (component_shas or {}).items()},
    }
    command = []
    for token in spec["command"]:
        expanded = token
        for placeholder, value in replacements.items():
            expanded = expanded.replace(placeholder, value)
        command.append(expanded)
    return command


def _run_executor(
    case_id: str,
    spec: dict,
    staging_root: Path | None,
    evidence_dir: Path | None,
    package: Path | None,
    approved_port: int | None = None,
    component_shas: dict[str, str] | None = None,
) -> dict:
    if staging_root is None or evidence_dir is None:
        return {
            "id": case_id, "status": "BLOCKED", "classification": "ENVIRONMENT_FAILURE",
            "actual": "ISOLATED_STAGING_AND_EVIDENCE_REQUIRED",
        }
    root = staging_root.resolve()
    relative_cwd = str(spec.get("workingDirectory", "."))
    cwd = root if relative_cwd == "." else _contained_destination(root, relative_cwd)
    if not cwd.is_dir():
        return {
            "id": case_id, "status": "BLOCKED", "classification": "ENVIRONMENT_FAILURE",
            "actual": "EXECUTOR_WORKING_DIRECTORY_MISSING",
        }
    evidence_root = evidence_dir.resolve()
    evidence_root.mkdir(parents=True, exist_ok=True)
    log_path = _contained_destination(evidence_root, f"{case_id}.log")
    started = time.perf_counter()
    command = _executor_command(spec, root, evidence_root, package, approved_port, component_shas)
    if spec.get("requiresApprovedPort") is True and approved_port is None:
        return {"id": case_id, "status": "BLOCKED", "classification": "OWNER_APPROVAL_REQUIRED", "actual": "APPROVED_PORT_REQUIRED"}
    scenario_path = _contained_destination(evidence_root, str(spec.get("evidenceFile", f"{case_id}.json")).replace("{CASE_ID}", case_id))
    if scenario_path.is_file():
        archive = evidence_root / ".previous-evidence"
        archive.mkdir(exist_ok=True)
        saved = archive / f"{case_id}-{sha256_file(scenario_path)}.json"
        shutil.copyfile(scenario_path, saved)
        scenario_path.unlink()
    owned = None
    before: list[int] = []
    try:
        owned = _OwnedProcess(command, cwd)
        before = _owned_process_tree(owned.process.pid)
        stdout, stderr = owned.process.communicate(timeout=float(spec["timeoutSeconds"]))
        output = (stdout or "") + (stderr or "")
        log_path.write_text(output, encoding="utf-8", errors="replace")
        owned.close()
        after = _owned_process_tree(owned.process.pid)
        evidence_ok, evidence_actual, evidence_path = _validate_executor_evidence(case_id, spec, evidence_root)
        status = "PASS" if owned.process.returncode == 0 and evidence_ok else "FAIL"
        classification = "AUTOMATED" if status == "PASS" else ("PRODUCT_FAILURE" if owned.process.returncode else "HARNESS_FAILURE")
        blocker = None
        if owned.process.returncode == 2 and evidence_path.is_file():
            candidate = load_json(evidence_path)
            if (candidate.get("ok") is False and candidate.get("status") == "BLOCKED"
                    and candidate.get("classification") in spec.get("allowedBlockers", [])):
                blocker = candidate
                status = "BLOCKED"
                classification = candidate["classification"]
        return {
            "id": case_id,
            "status": status,
            "classification": classification,
            "actual": (blocker.get("reason") or blocker.get("required") or "EXTERNAL_PREREQUISITE_REQUIRED") if blocker else (evidence_actual if owned.process.returncode == 0 else f"UNEXPECTED_EXIT_{owned.process.returncode}"),
            "processExitCode": owned.process.returncode,
            "evidence": str(log_path),
            "scenarioEvidence": str(evidence_path),
            "ownedProcessTreeBefore": before, "ownedProcessTreeAfter": after,
            "executorDurationSeconds": round(time.perf_counter() - started, 6),
        }
    except FileNotFoundError as exc:
        log_path.write_text(f"{type(exc).__name__}: executable unavailable\n", encoding="utf-8")
        return {
            "id": case_id, "status": "BLOCKED", "classification": "ENVIRONMENT_FAILURE",
            "actual": "EXECUTOR_NOT_AVAILABLE", "evidence": str(log_path),
        }
    except subprocess.TimeoutExpired as exc:
        if owned is not None:
            owned.terminate_tree()
            stdout, stderr = owned.process.communicate(timeout=10)
        else:
            stdout, stderr = exc.stdout, exc.stderr
        output = (stdout or "") + (stderr or "")
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        log_path.write_text(str(output), encoding="utf-8", errors="replace")
        return {
            "id": case_id, "status": "FAIL", "classification": "HARNESS_FAILURE",
            "actual": "EXECUTOR_TIMEOUT", "evidence": str(log_path),
            "ownedProcessTreeBefore": before,
            "ownedProcessTreeAfter": _owned_process_tree(owned.process.pid) if owned else [],
        }
    finally:
        if owned is not None:
            owned.close()


def _case_provenance(case: dict, executor: dict | None, staging_root: Path | None,
                     evidence_dir: Path | None, package: Path | None, approved_port: int | None,
                     component_shas: dict, platform: str) -> str:
    """Per-case inputs, not the entire executor manifest or machine environment.

    Direct executable/script arguments are hashed; separately imported external
    assertion/config files must be declared in inputFiles. Packaged dependencies
    are additionally bound by packageSha256 and componentShas in the report.
    """
    value = {"runnerSha256": sha256_file(Path(__file__)), "case": case, "executor": executor}
    if executor is not None:
        root = staging_root.resolve() if staging_root else Path.cwd()
        evidence = evidence_dir.resolve() if evidence_dir else root / "evidence"
        cwd = root / executor.get("workingDirectory", ".")
        command = _executor_command(executor, root, evidence, package, approved_port, component_shas)
        files = {}
        for index, token in enumerate(command):
            candidate = Path(token)
            if index == 0 and not candidate.is_absolute():
                candidate = Path(shutil.which(token) or cwd / token)
            elif not candidate.is_absolute():
                candidate = cwd / candidate
            # Output/state files are not executable inputs.
            candidate = candidate.resolve()
            executable_input = index == 0 or candidate.suffix.lower() in {".py", ".js", ".mjs", ".ps1", ".exe", ".cmd", ".bat"}
            if not executable_input and (evidence == candidate or evidence in candidate.parents):
                continue
            try:
                if candidate.is_file(): files[str(candidate)] = sha256_file(candidate)
            except OSError:
                # Inline interpreter arguments may not be legal filenames;
                # their literal bytes are already included in the executor spec.
                continue
        inputs = executor.get("inputFiles", [])
        if not isinstance(inputs, list) or any(not isinstance(item, str) or not item for item in inputs):
            raise DeliveryError("INVALID_EXECUTOR_INPUT_FILES")
        for item in inputs:
            candidate = _contained_destination(root, item)
            files[str(candidate)] = sha256_file(candidate) if candidate.is_file() else None
        value.update({"files": files, "platform": platform, "staging": str(root),
                      "evidence": str(evidence), "approvedPort": approved_port})
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _reusable_case(previous: dict, provenance: str, case: dict, executor: dict | None,
                   evidence_dir: Path | None) -> bool:
    if previous.get("status") != "PASS" or previous.get("provenanceSha256") != provenance:
        return False
    if case["kind"] == "PACKAGE_INTEGRITY": return True
    # Environment checks and MAN are never historical execution evidence.
    if executor is None or evidence_dir is None or case["kind"] not in {"RUNTIME_E2E", "VISUAL_GOLDEN", "PERFORMANCE"}:
        return False
    ok, _, path = _validate_executor_evidence(case["id"], executor, evidence_dir.resolve())
    return ok and previous.get("scenarioEvidenceSha256") == sha256_file(path)


def run_acceptance(
    plan_path: Path,
    package: Path | None,
    selected: set[str],
    prior: Path | None,
    *,
    platform: str | None = None,
    staging_root: Path | None = None,
    evidence_dir: Path | None = None,
    expected_package_sha256: str | None = None,
    component_manifest: Path | None = None,
    executor_manifest: Path | None = None,
    approved_port: int | None = None,
) -> dict:
    plan = load_json(plan_path)
    if plan.get("schemaVersion") != "d4planner-acceptance-plan/v1":
        raise DeliveryError("ACCEPTANCE_PLAN_VERSION_MISMATCH")
    plan_sha256 = sha256_file(plan_path)
    package_sha256 = sha256_file(package) if package and package.is_file() else None
    component_shas = load_component_shas(component_manifest)
    executors = load_executors(executor_manifest)
    known_ids = {str(case.get("id", "")) for case in plan.get("cases", [])}
    invalid_selected = sorted(case_id for case_id in selected if not case_id or case_id not in known_ids)
    if invalid_selected:
        raise DeliveryError(f"UNKNOWN_ACCEPTANCE_CASE:{','.join(invalid_selected)}")
    runtime_selected = any(
        (not selected or case["id"] in selected)
        and case["kind"] in {"RUNTIME_E2E", "VISUAL_GOLDEN", "PERFORMANCE"}
        and case["id"] in executors
        for case in plan["cases"]
    )
    if evidence_dir is not None:
        evidence_dir.resolve().mkdir(parents=True, exist_ok=True)
    runtime_platform = sys.platform if platform is None else platform
    if runtime_selected:
        preflight = _windows_preflight(package, expected_package_sha256, staging_root, evidence_dir, runtime_platform, approved_port)
        if preflight["status"] == "PASS" and package and staging_root:
            app_dir = staging_root.resolve() / "app"
            installed_manifest = app_dir / "release-manifest.json"
            expected_manifest = verify_package(package)
            installed = load_json(installed_manifest) if installed_manifest.is_file() else None
            if installed != expected_manifest:
                install_package(package, app_dir, staging_root.resolve() / "data")
    previous = load_json(prior) if prior else {}
    if prior and (
        previous.get("planSha256") != plan_sha256
        or previous.get("packageSha256") != package_sha256
        or previous.get("componentShas") != component_shas
    ):
        raise DeliveryError("RESUME_CONTEXT_MISMATCH")
    previous_cases = {case["id"]: case for case in previous.get("cases", []) if case.get("status") == "PASS"}
    results = []
    for case in plan["cases"]:
        case_started = time.perf_counter()
        case_id = case["id"]
        if selected and case_id not in selected:
            result = {
                "id": case_id, "status": "NOT_RUN", "classification": "NOT_SELECTED",
                "expected": case.get("expected", "Acceptance condition in plan"),
                "actual": "NOT_SELECTED", "exitCode": None,
                "durationSeconds": round(time.perf_counter() - case_started, 6),
            }
            results.append(result)
            continue
        executor = executors.get(case_id)
        provenance = _case_provenance(case, executor, staging_root, evidence_dir, package,
                                      approved_port, component_shas, runtime_platform)
        if case_id in previous_cases and _reusable_case(previous_cases[case_id], provenance, case, executor, evidence_dir):
            result = {**previous_cases[case_id], "resumed": True}
            results.append(result)
            continue
        kind = case["kind"]
        if kind == "PACKAGE_INTEGRITY":
            if package is None:
                result = {"id": case_id, "status": "BLOCKED", "classification": "MISSING_PACKAGE"}
            else:
                try:
                    verify_package(package)
                    result = {"id": case_id, "status": "PASS", "classification": "AUTOMATED"}
                except DeliveryError as exc:
                    result = {"id": case_id, "status": "FAIL", "classification": "PRODUCT_FAILURE", "error": str(exc)}
        elif kind == "WINDOWS_PREFLIGHT":
            result = _windows_preflight(
                package, expected_package_sha256, staging_root, evidence_dir, runtime_platform, approved_port
            )
        elif kind == "OWNER_WAIVER":
            waiver = case.get("waiver", {})
            if (case_id == "S7-VIS-01" and plan.get("releaseId") == "R1-EQUIPMENT-20261025"
                    and waiver == {"decision":"ISSUE158_R1_VISUAL_WAIVER_20261030", "approvedBy":"TrdHuy", "scope":"R1-EQUIPMENT-20261025"}):
                result = {"id":case_id, "status":"OWNER_WAIVED", "classification":"OWNER_WAIVED", "actual":waiver["decision"]}
            else:
                result = {"id":case_id, "status":"FAIL", "classification":"HARNESS_FAILURE", "actual":"INVALID_RELEASE_WAIVER"}
        elif kind == "OWNER_MANUAL":
            result = {"id": case_id, "status": "NOT_RUN", "classification": "OWNER_MANUAL"}
        elif kind in {"RUNTIME_E2E", "VISUAL_GOLDEN", "PERFORMANCE"}:
            executor = executors.get(case_id)
            if executor is None:
                result = {
                    "id": case_id, "status": "BLOCKED", "classification": "PENDING_DEPENDENCY",
                    "actual": "NO_REVIEWED_EXECUTOR_FOR_CASE",
                }
            else:
                preflight = _windows_preflight(package, expected_package_sha256, staging_root, evidence_dir, runtime_platform, approved_port)
                result = preflight if preflight["status"] != "PASS" else _run_executor(
                    case_id, executor, staging_root, evidence_dir, package,
                    approved_port, component_shas,
                )
        else:
            result = {"id": case_id, "status": "FAIL", "classification": "HARNESS_FAILURE", "actual": "UNKNOWN_CASE_KIND"}
        result["provenanceSha256"] = provenance
        if result["status"] == "PASS" and result.get("scenarioEvidence"):
            result["scenarioEvidenceSha256"] = sha256_file(Path(result["scenarioEvidence"]))
        result.setdefault("expected", case.get("expected", "Acceptance condition in plan"))
        result.setdefault("actual", result.get("error", result["classification"]))
        result["exitCode"] = 0 if result["status"] == "PASS" else (1 if result["status"] == "FAIL" else (3 if result["status"] == "BLOCKED" else None))
        result["durationSeconds"] = round(time.perf_counter() - case_started, 6)
        results.append(result)
    report = {
        "schemaVersion": REPORT_VERSION,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "planSha256": plan_sha256,
        "packageSha256": package_sha256,
        "componentShas": component_shas,
        "scope": "FULL" if not selected else "SUBSET",
        "cases": results,
    }
    report["outcome"] = "FAIL" if any(case["status"] == "FAIL" for case in results) else (
        "BLOCKED" if any(case["status"] == "BLOCKED" for case in results) else (
            "NOT_RUN" if not any(case["status"] == "PASS" for case in results) else (
                ("SUBSET_PASS_MAN_PENDING" if any(case["classification"] == "OWNER_MANUAL" for case in results) else "SUBSET_PASS")
                if selected else "FULL_AUTOMATED_PASS_MAN_PENDING"
            )
        )
    )
    if any(case["status"] == "OWNER_WAIVED" for case in results):
        report["ownerWaivers"] = [case["id"] for case in results if case["status"] == "OWNER_WAIVED"]
        if "PASS" in report["outcome"]:
            report["outcome"] += "_WITH_OWNER_WAIVER"
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build"); build.add_argument("--plan", type=Path, required=True); build.add_argument("--source", type=Path, required=True); build.add_argument("--output", type=Path, required=True)
    build.add_argument("--version")
    verify = sub.add_parser("verify"); verify.add_argument("--package", type=Path, required=True)
    install = sub.add_parser("install"); install.add_argument("--package", type=Path, required=True); install.add_argument("--app-dir", type=Path, required=True); install.add_argument("--data-dir", type=Path, required=True)
    rollback = sub.add_parser("rollback"); rollback.add_argument("--app-dir", type=Path, required=True); rollback.add_argument("--data-dir", type=Path, required=True)
    run = sub.add_parser("run"); run.add_argument("--plan", type=Path, required=True); run.add_argument("--package", type=Path); run.add_argument("--case", action="append", default=[]); run.add_argument("--resume", type=Path); run.add_argument("--output", type=Path, required=True)
    run.add_argument("--mode", choices=("Preflight", "Automated", "Resume"), default="Automated")
    run.add_argument("--staging-root", type=Path); run.add_argument("--evidence-dir", type=Path)
    run.add_argument("--expected-package-sha256"); run.add_argument("--approved-port", type=int)
    run.add_argument("--component-manifest", type=Path)
    run.add_argument("--executor-manifest", type=Path)
    report = sub.add_parser("report"); report.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build": result = build_package(args.plan, args.source, args.output, release_version=args.version)
        elif args.command == "verify": result = verify_package(args.package)
        elif args.command == "install": result = install_package(args.package, args.app_dir, args.data_dir)
        elif args.command == "rollback": result = rollback_install(args.app_dir, args.data_dir)
        elif args.command == "report":
            result = load_json(args.input)
            print(json.dumps(result, sort_keys=True))
            return acceptance_exit_code(result)
        else:
            if args.mode == "Resume" and args.resume is None:
                raise DeliveryError("RESUME_REPORT_REQUIRED")
            selected = set(args.case)
            if args.mode == "Preflight":
                selected = {"S7-PRE-01"}
            result = run_acceptance(
                args.plan, args.package, selected, args.resume,
                staging_root=args.staging_root, evidence_dir=args.evidence_dir,
                expected_package_sha256=args.expected_package_sha256,
                component_manifest=args.component_manifest,
                executor_manifest=args.executor_manifest,
                approved_port=args.approved_port,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, sort_keys=True))
        return acceptance_exit_code(result) if args.command == "run" else 0
    except DeliveryError as exc:
        print(str(exc), file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
