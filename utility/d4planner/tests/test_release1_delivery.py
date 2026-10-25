from __future__ import annotations

import importlib.util
import json
from pathlib import Path
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
    report = delivery.run_acceptance(ACCEPTANCE, package, set(), None, platform="linux")
    by_id = {case["id"]: case for case in report["cases"]}
    assert by_id["S7-PKG-01"]["status"] == "PASS"
    assert by_id["S7-PRE-01"]["status"] == "BLOCKED"
    assert by_id["S7-E2E-01"] == {"id": "S7-E2E-01", "status": "BLOCKED", "classification": "PENDING_DEPENDENCY"}
    assert by_id["MAN-01"]["status"] == "NOT_RUN"
    prior = tmp_path / "prior.json"; prior.write_text(json.dumps(report))
    resumed = delivery.run_acceptance(
        ACCEPTANCE, package, {"S7-PKG-01"}, prior, platform="linux"
    )
    resumed_by_id = {case["id"]: case for case in resumed["cases"]}
    assert resumed_by_id["S7-PKG-01"]["resumed"] is True
    assert resumed_by_id["S7-PRE-01"]["classification"] == "NOT_SELECTED"
    report["packageSha256"] = "0" * 64
    prior.write_text(json.dumps(report))
    with pytest.raises(delivery.DeliveryError, match="RESUME_CONTEXT_MISMATCH"):
        delivery.run_acceptance(
            ACCEPTANCE, package, {"S7-PKG-01"}, prior, platform="linux"
        )

    windows = delivery.run_acceptance(
        ACCEPTANCE, package, {"S7-PRE-01"}, None, platform="win32"
    )
    windows_by_id = {case["id"]: case for case in windows["cases"]}
    assert windows_by_id["S7-PRE-01"] == {
        "id": "S7-PRE-01", "status": "PASS", "classification": "AUTOMATED"
    }


def test_runner_invalid_package_is_product_failure_and_missing_is_blocked(tmp_path):
    invalid = tmp_path / "invalid.zip"; invalid.write_bytes(b"not zip")
    failed = delivery.run_acceptance(ACCEPTANCE, invalid, {"S7-PKG-01"}, None)
    assert failed["cases"][0]["status"] == "FAIL"
    blocked = delivery.run_acceptance(ACCEPTANCE, None, {"S7-PKG-01"}, None)
    assert blocked["cases"][0]["status"] == "BLOCKED"
