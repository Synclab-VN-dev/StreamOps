from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "utility/d4planner/tools/release1_delivery.py"
PLAN = ROOT / "utility/d4planner/release1/package-plan.json"
ACCEPTANCE = ROOT / "utility/d4planner/release1/acceptance-plan.json"
spec = importlib.util.spec_from_file_location("release1_delivery", TOOL)
delivery = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(delivery)


def stage(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    for index, artifact in enumerate(plan["artifacts"]):
        path = root / artifact["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"synthetic-test-artifact-{index}".encode())
    return root


def component_manifest(tmp_path: Path) -> Path:
    path = tmp_path / "component-shas.json"
    path.write_text(json.dumps({
        "schemaVersion": delivery.COMPONENT_MANIFEST_VERSION,
        "components": {f"S{number}": str(number) * 40 for number in range(2, 8)},
    }))
    return path


def test_package_is_deterministic_pinned_and_verifiable(tmp_path):
    source = stage(tmp_path)
    first = tmp_path / "first.zip"; second = tmp_path / "second.zip"
    result = delivery.build_package(PLAN, source, first)
    delivery.build_package(PLAN, source, second)
    assert first.read_bytes() == second.read_bytes()
    assert result["artifactSha256"] == delivery.sha256_file(first)
    manifest = delivery.verify_package(first)
    assert manifest["contractRevision"] == "d4planner-r1-contract/1.0.0-candidate.5"
    assert manifest["magicPathRevision"] == "464988421014827008"
    assert manifest["ruleKit"]["playwrightCore"] == "1.64.1"
    assert len(manifest["files"]) == 13


def test_package_plan_pins_match_repository_sources():
    plan = json.loads(PLAN.read_text())
    maxroll_package = json.loads((ROOT / "utility/d4-rulekit/providers/maxroll/package.json").read_text())
    coverage = json.loads((ROOT / "utility/d4-rulekit/providers/maxroll/UNIVERSAL-IMPORT-COVERAGE.json").read_text())
    assert maxroll_package["dependencies"]["playwright-core"] == plan["ruleKit"]["playwrightCore"]
    assert coverage["snapshotId"] == plan["ruleKit"]["snapshotId"]
    assert coverage["snapshotManifestSha256"] == plan["ruleKit"]["snapshotManifestSha256"]


def test_missing_symlink_secret_and_unsafe_plan_fail_closed(tmp_path):
    source = stage(tmp_path)
    missing = source / "app/d4planner-fe.exe"
    missing.unlink()
    with pytest.raises(delivery.DeliveryError, match="MISSING_OR_UNSAFE"):
        delivery.build_package(PLAN, source, tmp_path / "missing.zip")
    missing.symlink_to(source / "app/d4planner-be.exe")
    with pytest.raises(delivery.DeliveryError, match="MISSING_OR_UNSAFE"):
        delivery.build_package(PLAN, source, tmp_path / "linked.zip")
    bad = json.loads(PLAN.read_text())
    bad["artifacts"][0]["path"] = "../escape.exe"
    bad_plan = tmp_path / "bad.json"; bad_plan.write_text(json.dumps(bad))
    with pytest.raises(delivery.DeliveryError, match="UNSAFE_PATH"):
        delivery.build_package(bad_plan, source, tmp_path / "bad.zip")


def test_hash_tamper_and_undeclared_archive_member_are_rejected(tmp_path):
    package = tmp_path / "package.zip"
    delivery.build_package(PLAN, stage(tmp_path), package)
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(package) as source, zipfile.ZipFile(tampered, "w") as target:
        for name in source.namelist():
            data = b"changed" if name == "app/d4planner-fe.exe" else source.read(name)
            target.writestr(name, data)
        target.writestr("unexpected.txt", b"no")
    with pytest.raises(delivery.DeliveryError, match="UNDECLARED_OR_MISSING_FILE"):
        delivery.verify_package(tampered)


@pytest.mark.parametrize("member", [
    r"..\escape.exe",
    r"app\..\escape.exe",
    r"C:\escape.exe",
    "C:/escape.exe",
    r"\\server\share\escape.exe",
    "//server/share/escape.exe",
    "app/file.exe:stream",
    "app//file.exe",
])
def test_windows_semantic_archive_paths_fail_closed(tmp_path, member):
    package = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("release-manifest.json", json.dumps({
            "schemaVersion": delivery.MANIFEST_VERSION,
            "files": [{"path": member, "sha256": "0" * 64, "bytes": 0}],
        }))
        archive.writestr(member, b"")
    with pytest.raises(delivery.DeliveryError, match="UNSAFE_PATH"):
        delivery.verify_package(package)


@pytest.mark.parametrize("path", [r"..\escape.exe", r"C:\escape.exe", "C:/escape.exe", r"\\server\share\x"])
def test_windows_semantic_plan_paths_fail_closed(tmp_path, path):
    bad = json.loads(PLAN.read_text())
    bad["artifacts"][0]["path"] = path
    bad_plan = tmp_path / "bad.json"; bad_plan.write_text(json.dumps(bad))
    with pytest.raises(delivery.DeliveryError, match="UNSAFE_PATH"):
        delivery.build_package(bad_plan, stage(tmp_path), tmp_path / "bad.zip")


def test_upgrade_preserves_targets_and_state(tmp_path):
    package = tmp_path / "package.zip"
    delivery.build_package(PLAN, stage(tmp_path), package)
    app = tmp_path / "install/app"; data = tmp_path / "data"
    (data / "targets").mkdir(parents=True); (data / "state").mkdir()
    (data / "targets/user target.json").write_text("user-owned")
    (data / "state/database.sqlite").write_bytes(b"database")
    delivery.install_package(package, app, data)
    (app / "old.txt").write_text("old")
    delivery.install_package(package, app, data)
    assert (data / "targets/user target.json").read_text() == "user-owned"
    assert (data / "state/database.sqlite").read_bytes() == b"database"
    assert not (app / "old.txt").exists()
    assert (app.with_name("app.previous") / "old.txt").exists()
    delivery.rollback_install(app, data)
    assert (app / "old.txt").read_text() == "old"
    assert (data / "state/database.sqlite").read_bytes() == b"database"


def test_runner_distinguishes_platform_dependency_manual_subset_and_resume(tmp_path):
    package = tmp_path / "package.zip"
    delivery.build_package(PLAN, stage(tmp_path), package)
    components = component_manifest(tmp_path)
    report = delivery.run_acceptance(ACCEPTANCE, package, set(), None, platform="linux", component_manifest=components)
    by_id = {case["id"]: case for case in report["cases"]}
    assert by_id["S7-PKG-01"]["status"] == "PASS"
    assert by_id["S7-PRE-01"]["status"] == "BLOCKED"
    assert by_id["S7-E2E-01"]["status"] == "BLOCKED"
    assert by_id["S7-E2E-01"]["classification"] == "PENDING_DEPENDENCY"
    assert by_id["S7-E2E-01"]["exitCode"] == 3
    assert by_id["S7-E2E-01"]["expected"]
    assert by_id["MAN-01"]["status"] == "NOT_RUN"
    prior = tmp_path / "prior.json"; prior.write_text(json.dumps(report))
    resumed = delivery.run_acceptance(
        ACCEPTANCE, package, {"S7-PKG-01"}, prior, platform="linux", component_manifest=components
    )
    resumed_by_id = {case["id"]: case for case in resumed["cases"]}
    assert resumed_by_id["S7-PKG-01"]["resumed"] is True
    assert resumed_by_id["S7-PRE-01"]["classification"] == "NOT_SELECTED"
    report["packageSha256"] = "0" * 64
    prior.write_text(json.dumps(report))
    with pytest.raises(delivery.DeliveryError, match="RESUME_CONTEXT_MISMATCH"):
        delivery.run_acceptance(
            ACCEPTANCE, package, {"S7-PKG-01"}, prior, platform="linux", component_manifest=components
        )

    windows = delivery.run_acceptance(
        ACCEPTANCE, package, {"S7-PRE-01"}, None, platform="win32",
        staging_root=tmp_path.resolve(), evidence_dir=tmp_path.resolve(),
        expected_package_sha256=delivery.sha256_file(package),
        component_manifest=components,
    )
    windows_by_id = {case["id"]: case for case in windows["cases"]}
    assert windows_by_id["S7-PRE-01"]["status"] == "PASS"
    assert windows_by_id["S7-PRE-01"]["classification"] == "AUTOMATED"


def test_runner_invalid_package_is_product_failure_and_missing_is_blocked(tmp_path):
    invalid = tmp_path / "invalid.zip"; invalid.write_bytes(b"not zip")
    components = component_manifest(tmp_path)
    failed = delivery.run_acceptance(ACCEPTANCE, invalid, {"S7-PKG-01"}, None, component_manifest=components)
    assert failed["cases"][0]["status"] == "FAIL"
    blocked = delivery.run_acceptance(ACCEPTANCE, None, {"S7-PKG-01"}, None, component_manifest=components)
    assert blocked["cases"][0]["status"] == "BLOCKED"


def test_windows_preflight_requires_real_isolated_inputs_and_exact_package_hash(tmp_path):
    package = tmp_path / "package.zip"
    delivery.build_package(PLAN, stage(tmp_path), package)
    blocked = delivery.run_acceptance(
        ACCEPTANCE, package, {"S7-PRE-01"}, None, platform="win32",
        component_manifest=component_manifest(tmp_path),
    )
    case = {item["id"]: item for item in blocked["cases"]}["S7-PRE-01"]
    assert case["status"] == "BLOCKED"
    assert set(case["actual"]) >= {
        "EXPECTED_PACKAGE_SHA256_REQUIRED", "ISOLATED_STAGING_ROOT_REQUIRED",
        "EVIDENCE_DIRECTORY_REQUIRED",
    }
    mismatch = delivery.run_acceptance(
        ACCEPTANCE, package, {"S7-PRE-01"}, None, platform="win32",
        staging_root=tmp_path.resolve(), evidence_dir=tmp_path.resolve(),
        expected_package_sha256="0" * 64,
        component_manifest=component_manifest(tmp_path),
    )
    assert "PACKAGE_SHA256_MISMATCH" in {item["id"]: item for item in mismatch["cases"]}["S7-PRE-01"]["actual"]


def test_cli_writes_report_but_returns_nonzero_for_fail_or_blocked(tmp_path):
    package = tmp_path / "package.zip"
    delivery.build_package(PLAN, stage(tmp_path), package)
    output = tmp_path / "blocked.json"
    completed = subprocess.run([
        sys.executable, str(TOOL), "run", "--mode", "Preflight",
        "--plan", str(ACCEPTANCE), "--package", str(package), "--output", str(output),
        "--component-manifest", str(component_manifest(tmp_path)),
    ], check=False, capture_output=True, text=True)
    assert completed.returncode == 3
    assert output.is_file()
    assert json.loads(output.read_text())["outcome"] == "BLOCKED"

    failed = tmp_path / "failed.json"
    failed.write_text(json.dumps({"cases": [{"id": "x", "status": "FAIL"}]}))
    report = subprocess.run([
        sys.executable, str(TOOL), "report", "--input", str(failed),
    ], check=False, capture_output=True, text=True)
    assert report.returncode == 1


def test_runner_rejects_missing_or_unpinned_component_shas(tmp_path):
    package = tmp_path / "package.zip"
    delivery.build_package(PLAN, stage(tmp_path), package)
    with pytest.raises(delivery.DeliveryError, match="COMPONENT_MANIFEST_REQUIRED"):
        delivery.run_acceptance(ACCEPTANCE, package, set(), None)
    invalid = component_manifest(tmp_path)
    value = json.loads(invalid.read_text())
    value["components"]["S5"] = "not-a-sha"
    invalid.write_text(json.dumps(value))
    with pytest.raises(delivery.DeliveryError, match="INVALID_COMPONENT_SHA:S5"):
        delivery.run_acceptance(ACCEPTANCE, package, set(), None, component_manifest=invalid)
