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
from pathlib import Path, PurePosixPath
import shutil
import sys
import zipfile

PLAN_VERSION = "d4planner-package-plan/v1"
MANIFEST_VERSION = "d4planner-release-manifest/v1"
REPORT_VERSION = "d4planner-acceptance-report/v1"
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
    posix = PurePosixPath(value)
    if posix.is_absolute() or ".." in posix.parts or not posix.parts:
        raise DeliveryError(f"UNSAFE_PATH:{value}")
    return Path(*posix.parts)


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
                destination = staging / safe_relative(entry["path"])
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


def run_acceptance(
    plan_path: Path,
    package: Path | None,
    selected: set[str],
    prior: Path | None,
    *,
    platform: str | None = None,
) -> dict:
    plan = load_json(plan_path)
    if plan.get("schemaVersion") != "d4planner-acceptance-plan/v1":
        raise DeliveryError("ACCEPTANCE_PLAN_VERSION_MISMATCH")
    plan_sha256 = sha256_file(plan_path)
    package_sha256 = sha256_file(package) if package and package.is_file() else None
    previous = load_json(prior) if prior else {}
    if prior and (
        previous.get("planSha256") != plan_sha256
        or previous.get("packageSha256") != package_sha256
    ):
        raise DeliveryError("RESUME_CONTEXT_MISMATCH")
    previous_cases = {case["id"]: case for case in previous.get("cases", []) if case.get("status") == "PASS"}
    runtime_platform = sys.platform if platform is None else platform
    results = []
    for case in plan["cases"]:
        case_id = case["id"]
        if selected and case_id not in selected:
            results.append({"id": case_id, "status": "NOT_RUN", "classification": "NOT_SELECTED"}); continue
        if case_id in previous_cases:
            results.append({**previous_cases[case_id], "resumed": True}); continue
        kind = case["kind"]
        if kind == "PACKAGE_INTEGRITY":
            if package is None:
                results.append({"id": case_id, "status": "BLOCKED", "classification": "MISSING_PACKAGE"})
            else:
                try:
                    verify_package(package)
                    results.append({"id": case_id, "status": "PASS", "classification": "AUTOMATED"})
                except DeliveryError as exc:
                    results.append({"id": case_id, "status": "FAIL", "classification": "PRODUCT_FAILURE", "error": str(exc)})
        elif kind == "WINDOWS_PREFLIGHT":
            status = "PASS" if runtime_platform == "win32" else "BLOCKED"
            results.append({"id": case_id, "status": status, "classification": "AUTOMATED" if status == "PASS" else "ENVIRONMENT_FAILURE"})
        elif kind == "OWNER_MANUAL":
            results.append({"id": case_id, "status": "NOT_RUN", "classification": "OWNER_MANUAL"})
        else:
            results.append({"id": case_id, "status": "BLOCKED", "classification": "PENDING_DEPENDENCY"})
    return {
        "schemaVersion": REPORT_VERSION,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "planSha256": plan_sha256,
        "packageSha256": package_sha256,
        "scope": "FULL" if not selected else "SUBSET",
        "cases": results,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build"); build.add_argument("--plan", type=Path, required=True); build.add_argument("--source", type=Path, required=True); build.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify"); verify.add_argument("--package", type=Path, required=True)
    install = sub.add_parser("install"); install.add_argument("--package", type=Path, required=True); install.add_argument("--app-dir", type=Path, required=True); install.add_argument("--data-dir", type=Path, required=True)
    rollback = sub.add_parser("rollback"); rollback.add_argument("--app-dir", type=Path, required=True); rollback.add_argument("--data-dir", type=Path, required=True)
    run = sub.add_parser("run"); run.add_argument("--plan", type=Path, required=True); run.add_argument("--package", type=Path); run.add_argument("--case", action="append", default=[]); run.add_argument("--resume", type=Path); run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build": result = build_package(args.plan, args.source, args.output)
        elif args.command == "verify": result = verify_package(args.package)
        elif args.command == "install": result = install_package(args.package, args.app_dir, args.data_dir)
        elif args.command == "rollback": result = rollback_install(args.app_dir, args.data_dir)
        else:
            result = run_acceptance(args.plan, args.package, set(args.case), args.resume)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, sort_keys=True))
        return 0
    except DeliveryError as exc:
        print(str(exc), file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
