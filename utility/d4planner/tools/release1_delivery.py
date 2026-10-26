"""Fail-closed Release 1 package and acceptance utility for S7.

It never starts the game, OBS, Steam, NVDA, or GitHub Actions. Runtime cases need
explicit evidence produced by the integrated Windows package; absence is BLOCKED.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import subprocess
import sys
import time
import zipfile

PLAN_VERSION = "d4planner-package-plan/v1"
MANIFEST_VERSION = "d4planner-release-manifest/v1"
REPORT_VERSION = "d4planner-acceptance-report/v1"
COMPONENT_MANIFEST_VERSION = "d4planner-component-shas/v1"
EXECUTOR_MANIFEST_VERSION = "d4planner-e2e-executors/v1"
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
    for resource in plan.get("resources", []):
        resource_id = str(resource.get("id", "")); path = str(resource.get("path", ""))
        safe_relative(path); safe_relative(str(resource.get("source", "")))
        if not resource_id or resource_id in ids or path in paths:
            raise DeliveryError("DUPLICATE_OR_EMPTY_ARTIFACT")
        ids.add(resource_id); paths.add(path)
    if not ids:
        raise DeliveryError("NO_ARTIFACTS")
    digest = str((plan.get("ruleKit") or {}).get("snapshotManifestSha256", ""))
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise DeliveryError("INVALID_SNAPSHOT_PIN")


def _check_source(path: Path, relative: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise DeliveryError(f"MISSING_OR_UNSAFE_ARTIFACT:{relative}")
    if path.name.lower() in FORBIDDEN_NAMES or path.suffix.lower() in {".pem", ".key", ".pfx"}:
        raise DeliveryError(f"FORBIDDEN_SECRET_FILE:{relative}")


def build_package(plan_path: Path, source: Path, output: Path) -> dict:
    plan = load_json(plan_path); validate_plan(plan)
    files = []
    for artifact in plan["artifacts"]:
        relative = str(artifact["path"]); path = source / safe_relative(relative)
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
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as package:
        info = zipfile.ZipInfo("release-manifest.json", (1980, 1, 1, 0, 0, 0)); info.external_attr = 0o644 << 16
        package.writestr(info, encoded)
        for entry in sorted(files, key=lambda item: item["path"]):
            info = zipfile.ZipInfo(entry["path"], (1980, 1, 1, 0, 0, 0)); info.external_attr = 0o644 << 16
            source_path = (
                repository_root / safe_relative(entry["source"])
                if "source" in entry else source / safe_relative(entry["path"])
            )
            package.writestr(info, source_path.read_bytes())
    verify_package(output)
    return {"manifest": manifest, "artifactSha256": sha256_file(output)}


def verify_package(package_path: Path) -> dict:
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
            declared = {entry["path"]: entry for entry in manifest.get("files", [])}
            if set(names) != {"release-manifest.json", *declared}:
                raise DeliveryError("UNDECLARED_OR_MISSING_FILE")
            for relative, entry in declared.items():
                safe_relative(relative)
                data = package.read(relative)
                if hashlib.sha256(data).hexdigest() != entry.get("sha256") or len(data) != entry.get("bytes"):
                    raise DeliveryError(f"ARTIFACT_HASH_MISMATCH:{relative}")
            return manifest
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
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
        },
    }


def acceptance_exit_code(report: dict) -> int:
    statuses = {case.get("status") for case in report.get("cases", [])}
    if "FAIL" in statuses:
        return 1
    if "BLOCKED" in statuses:
        return 3
    return 0


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
        if (
            not isinstance(command, list) or not command
            or any(not isinstance(token, str) or not token or "\x00" in token for token in command)
            or not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 1800
            or not isinstance(cwd, str)
        ):
            raise DeliveryError(f"INVALID_EXECUTOR_CASE:{case_id}")
        if cwd != ".":
            safe_relative(cwd)
        result[case_id] = dict(spec)
    return result


def _run_executor(
    case_id: str,
    spec: dict,
    staging_root: Path | None,
    evidence_dir: Path | None,
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
    try:
        completed = subprocess.run(
            spec["command"], cwd=cwd, check=False, capture_output=True, text=True,
            timeout=float(spec["timeoutSeconds"]), shell=False,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        log_path.write_text(output, encoding="utf-8", errors="replace")
        status = "PASS" if completed.returncode == 0 else "FAIL"
        return {
            "id": case_id,
            "status": status,
            "classification": "AUTOMATED" if status == "PASS" else "PRODUCT_FAILURE",
            "actual": "EXPECTED_EXIT_0" if status == "PASS" else f"UNEXPECTED_EXIT_{completed.returncode}",
            "processExitCode": completed.returncode,
            "evidence": str(log_path),
            "executorDurationSeconds": round(time.perf_counter() - started, 6),
        }
    except FileNotFoundError as exc:
        log_path.write_text(f"{type(exc).__name__}: executable unavailable\n", encoding="utf-8")
        return {
            "id": case_id, "status": "BLOCKED", "classification": "ENVIRONMENT_FAILURE",
            "actual": "EXECUTOR_NOT_AVAILABLE", "evidence": str(log_path),
        }
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + (exc.stderr or "")
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        log_path.write_text(str(output), encoding="utf-8", errors="replace")
        return {
            "id": case_id, "status": "FAIL", "classification": "HARNESS_FAILURE",
            "actual": "EXECUTOR_TIMEOUT", "evidence": str(log_path),
        }


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
) -> dict:
    plan = load_json(plan_path)
    if plan.get("schemaVersion") != "d4planner-acceptance-plan/v1":
        raise DeliveryError("ACCEPTANCE_PLAN_VERSION_MISMATCH")
    plan_sha256 = sha256_file(plan_path)
    package_sha256 = sha256_file(package) if package and package.is_file() else None
    component_shas = load_component_shas(component_manifest)
    executors = load_executors(executor_manifest)
    previous = load_json(prior) if prior else {}
    if prior and (
        previous.get("planSha256") != plan_sha256
        or previous.get("packageSha256") != package_sha256
        or previous.get("componentShas") != component_shas
    ):
        raise DeliveryError("RESUME_CONTEXT_MISMATCH")
    previous_cases = {case["id"]: case for case in previous.get("cases", []) if case.get("status") == "PASS"}
    runtime_platform = sys.platform if platform is None else platform
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
        if case_id in previous_cases:
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
                package, expected_package_sha256, staging_root, evidence_dir, runtime_platform
            )
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
                result = _run_executor(case_id, executor, staging_root, evidence_dir)
        else:
            result = {"id": case_id, "status": "FAIL", "classification": "HARNESS_FAILURE", "actual": "UNKNOWN_CASE_KIND"}
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
        "BLOCKED" if any(case["status"] == "BLOCKED" for case in results) else "PASS"
    )
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build"); build.add_argument("--plan", type=Path, required=True); build.add_argument("--source", type=Path, required=True); build.add_argument("--output", type=Path, required=True)
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
        if args.command == "build": result = build_package(args.plan, args.source, args.output)
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
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, sort_keys=True))
        return acceptance_exit_code(result) if args.command == "run" else 0
    except DeliveryError as exc:
        print(str(exc), file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
