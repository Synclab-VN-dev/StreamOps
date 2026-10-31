from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[4]
TOOL = ROOT / "utility/d4planner/d4planner-be/tools/release1_delivery.py"
PLAN = ROOT / "utility/d4planner/d4planner-be/release1/package-plan.json"
ACCEPTANCE = ROOT / "utility/d4planner/d4planner-be/release1/acceptance-plan.json"
LAUNCHER = ROOT / "utility/d4planner/d4planner-be/release1/start-d4planner.ps1"
STOPPER = ROOT / "utility/d4planner/d4planner-be/release1/stop-d4planner.ps1"
spec = importlib.util.spec_from_file_location("release1_delivery", TOOL)
delivery = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(delivery)


def stage(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    for index, artifact in enumerate(plan["artifacts"]):
        path = root / artifact["path"]
        if artifact.get("kind") == "tree":
            path.mkdir(parents=True, exist_ok=True)
            (path / "synthetic.txt").write_bytes(f"synthetic-test-artifact-{index}".encode())
        else:
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


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell unavailable")
def test_production_launcher_validates_no_data_and_port_modes_without_starting(tmp_path):
    install = tmp_path / "install"; data = tmp_path / "data"
    (install / "app").mkdir(parents=True); (install / "runtime/python").mkdir(parents=True)
    (install / "app/d4planner-fe.exe").write_bytes(b"test-only")
    (install / "runtime/python/python.exe").write_bytes(b"test-only")
    base = [
        shutil.which("pwsh"), "-NoProfile", "-File", str(LAUNCHER),
        "-InstallRoot", str(install), "-DataRoot", str(data), "-ValidateOnly",
    ]
    dynamic = subprocess.run(base, capture_output=True, text=True, check=False)
    assert dynamic.returncode == 0, dynamic.stderr
    configuration = json.loads(dynamic.stdout)
    assert configuration["wsPortMode"] == "Dynamic"
    assert configuration["approvedPort"] == 0
    assert configuration["equipmentRepository"] is None

    missing_approval = subprocess.run(
        base + ["-WsPortMode", "FixedApprovedUat"], capture_output=True, text=True, check=False,
    )
    assert missing_approval.returncode != 0
    assert "Owner-approved" in (missing_approval.stderr + missing_approval.stdout)
    fixed = subprocess.run(
        base + ["-WsPortMode", "FixedApprovedUat", "-ApprovedPort", "38150"],
        capture_output=True, text=True, check=False,
    )
    assert fixed.returncode == 0, fixed.stderr
    assert json.loads(fixed.stdout)["approvedPort"] == 38150

    # The production launcher cannot silently attach to any real capture DB.
    db = tmp_path / "equipment.sqlite"
    with sqlite3.connect(db) as connection:
        connection.execute("create table isolated_fixture(value integer)")
    explicit = subprocess.run(
        base + ["-EquipmentRepositoryDb", str(db)], capture_output=True, text=True, check=False,
    )
    assert explicit.returncode != 0
    opted_in = subprocess.run(
        base + ["-EquipmentRepositoryDb", str(db), "-EnableReadOnlyEquipmentRepository"],
        capture_output=True, text=True, check=False,
    )
    assert opted_in.returncode != 0
    assert "CharacterId" in (opted_in.stdout + opted_in.stderr)
    configured = subprocess.run(
        base + ["-EquipmentRepositoryDb", str(db), "-EnableReadOnlyEquipmentRepository",
                "-CharacterId", "character-isolated", "-CharacterDisplayName", "Isolated Character"],
        capture_output=True, text=True, check=False,
    )
    assert configured.returncode == 0, configured.stderr
    configured_value = json.loads(configured.stdout)
    assert configured_value["equipmentRepository"] == str(db.resolve())
    assert configured_value["characterId"] == "character-isolated"
    assert "Stop-Process -Name" not in STOPPER.read_text(encoding="utf-8")


def test_package_is_deterministic_pinned_and_verifiable(tmp_path):
    source = stage(tmp_path)
    first = tmp_path / "first.zip"; second = tmp_path / "second.zip"
    result = delivery.build_package(PLAN, source, first)
    delivery.build_package(PLAN, source, second)
    assert first.read_bytes() == second.read_bytes()
    assert result["artifactSha256"] == delivery.sha256_file(first)
    manifest = delivery.verify_package(first)
    assert manifest["contractRevision"] == "d4planner-r1-contract/1.0.0-candidate.6"
    assert manifest["magicPathRevision"] == "464988421014827008"
    assert manifest["ruleKit"]["playwrightCore"] == "1.64.1"
    assert len(manifest["files"]) == len(json.loads(PLAN.read_text())["artifacts"]) + len(json.loads(PLAN.read_text())["resources"])


def test_package_plan_pins_match_repository_sources():
    plan = json.loads(PLAN.read_text())
    maxroll_package = json.loads((ROOT / "utility/d4planner/d4planner-rulekit/providers/maxroll/package.json").read_text())
    coverage = json.loads((ROOT / "utility/d4planner/d4planner-rulekit/providers/maxroll/UNIVERSAL-IMPORT-COVERAGE.json").read_text())
    assert maxroll_package["dependencies"]["playwright-core"] == plan["ruleKit"]["playwrightCore"]
    assert plan["ruleKit"]["snapshotIncluded"] is False
    assert plan["ruleKit"]["snapshotManagementContract"] == "d4-rulekit-snapshots/v1"
    # The compatibility framework moved version-specific pins out of shared
    # codec source. Verify the actual legacy export, not its textual location.
    result = subprocess.run(
        ["node", "-e", "process.stdout.write(JSON.stringify(require('./utility/d4planner/d4planner-rulekit/providers/maxroll/src/canonical-codec').D12_COMPATIBILITY))"],
        cwd=ROOT, capture_output=True, text=True, timeout=15, check=True,
    )
    binding = json.loads(result.stdout)
    assert binding["snapshotId"] == coverage["snapshotId"]
    assert binding["snapshotManifestSha256"] == coverage["snapshotManifestSha256"]



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
    assert (app / "release-manifest.json").is_file()
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
    assert by_id["E2E-01"]["status"] == "BLOCKED"
    assert by_id["E2E-01"]["classification"] == "PENDING_DEPENDENCY"
    assert by_id["E2E-01"]["exitCode"] == 3
    assert by_id["E2E-01"]["expected"]
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


def test_reviewed_executor_runs_selected_case_and_records_failure_evidence(tmp_path):
    package = tmp_path / "package.zip"
    delivery.build_package(PLAN, stage(tmp_path), package)
    staging = tmp_path / "staging"; staging.mkdir()
    evidence = tmp_path / "evidence"; evidence.mkdir()
    passing = staging / "pass.py"; passing.write_text(
        "import json, pathlib\n"
        f"pathlib.Path({str(evidence / 'E2E-01.json')!r}).write_text(json.dumps({{'ok': True, 'scenario': 'owner'}}))\n"
        "print('real executor reached')\n"
    )
    failing = staging / "fail.py"; failing.write_text("raise SystemExit(7)\n")
    executors = tmp_path / "executors.json"
    executors.write_text(json.dumps({
        "schemaVersion": delivery.EXECUTOR_MANIFEST_VERSION,
        "cases": {
            "E2E-01": {"command": [sys.executable, "{STAGING_ROOT}/pass.py"], "workingDirectory": ".", "timeoutSeconds": 10, "requiredEvidence": {"scenario": "owner"}},
            "E2E-02": {"command": [sys.executable, "fail.py"], "workingDirectory": ".", "timeoutSeconds": 10},
        },
    }))
    report = delivery.run_acceptance(
        ACCEPTANCE, package, {"E2E-01", "E2E-02"}, None,
        staging_root=staging.resolve(), evidence_dir=evidence.resolve(),
        expected_package_sha256=delivery.sha256_file(package), platform="win32",
        component_manifest=component_manifest(tmp_path), executor_manifest=executors,
    )
    by_id = {case["id"]: case for case in report["cases"]}
    assert by_id["E2E-01"]["status"] == "PASS"
    assert by_id["E2E-01"]["processExitCode"] == 0
    assert Path(by_id["E2E-01"]["evidence"]).read_text() == "real executor reached\n"
    assert by_id["E2E-02"]["status"] == "FAIL"
    assert by_id["E2E-02"]["classification"] == "PRODUCT_FAILURE"
    assert by_id["E2E-02"]["processExitCode"] == 7
    assert delivery.acceptance_exit_code(report) == 1


def test_runner_rejects_unknown_case_and_distinguishes_subset_pass(tmp_path):
    package = tmp_path / "package.zip"
    delivery.build_package(PLAN, stage(tmp_path), package)
    components = component_manifest(tmp_path)
    with pytest.raises(delivery.DeliveryError, match="UNKNOWN_ACCEPTANCE_CASE:NOPE"):
        delivery.run_acceptance(ACCEPTANCE, package, {"NOPE"}, None, component_manifest=components)
    report = delivery.run_acceptance(
        ACCEPTANCE, package, {"S7-PKG-01"}, None, component_manifest=components,
    )
    assert report["outcome"] == "SUBSET_PASS"
    assert report["scope"] == "SUBSET"


def test_executor_exit_zero_without_valid_evidence_is_harness_failure(tmp_path):
    staging = tmp_path / "staging"; staging.mkdir()
    evidence = tmp_path / "evidence"; evidence.mkdir()
    script = staging / "empty.py"; script.write_text("print('no evidence')\n")
    result = delivery._run_executor(
        "E2E-01",
        {"command": [sys.executable, str(script)], "workingDirectory": ".", "timeoutSeconds": 10, "evidenceFile": "E2E-01.json"},
        staging, evidence, None,
    )
    assert result["status"] == "FAIL"
    assert result["classification"] == "HARNESS_FAILURE"
    assert result["actual"] == "EXECUTOR_EVIDENCE_MISSING"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process-group assertion")
def test_executor_timeout_reaps_owned_descendant_tree(tmp_path):
    staging = tmp_path / "staging"; staging.mkdir()
    evidence = tmp_path / "evidence"; evidence.mkdir()
    child_pid = tmp_path / "child.pid"
    script = staging / "hang.py"
    script.write_text(
        "import pathlib, subprocess, sys, time\n"
        "child=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"pathlib.Path({str(child_pid)!r}).write_text(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    result = delivery._run_executor(
        "E2E-09",
        {"command": [sys.executable, str(script)], "workingDirectory": ".", "timeoutSeconds": 0.3, "evidenceFile": "E2E-09.json"},
        staging, evidence, None,
    )
    assert result["actual"] == "EXECUTOR_TIMEOUT"
    pid = int(child_pid.read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.02)
    else:
        pytest.fail(f"owned descendant {pid} survived executor timeout")


@pytest.mark.parametrize('allowed,status', [(True,'BLOCKED'), (False,'FAIL')])
def test_nonzero_external_blocker_requires_explicit_reviewed_classification(tmp_path, allowed, status):
    staging = tmp_path / 'staging'; staging.mkdir()
    evidence = tmp_path / 'evidence'; evidence.mkdir()
    output = evidence / 'E2E-02.json'
    script = staging / 'blocked.py'
    script.write_text("import json,pathlib,sys\n" +
        f"pathlib.Path({str(output)!r}).write_text(json.dumps(" +
        "{'ok':False,'status':'BLOCKED','classification':'OWNER_APPROVAL_REQUIRED','reason':'TRUST_POLICY_NOT_CONFIGURED'}))\n" +
        "sys.exit(2)\n")
    spec = {'command':[sys.executable,str(script)],'workingDirectory':'.',
            'timeoutSeconds':10,'evidenceFile':'E2E-02.json',
            'allowedBlockers':['OWNER_APPROVAL_REQUIRED'] if allowed else []}
    result = delivery._run_executor('E2E-02', spec, staging, evidence, None)
    assert result['status'] == status
    assert result['processExitCode'] == 2
    assert result['status'] != 'PASS'


@pytest.mark.parametrize('change', ['manifest', 'script', 'evidence', 'input', 'unrelated', 'no-output', 'unchanged'])
def test_resume_binds_case_executor_and_evidence(tmp_path, change):
    artifact = tmp_path / 'package.zip'
    delivery.build_package(PLAN, stage(tmp_path), artifact)
    staging = tmp_path / 'staging'; staging.mkdir()
    evidence = tmp_path / 'evidence'; evidence.mkdir()
    script = staging / 'case.py'
    script.write_text("import pathlib,json\n" + f"pathlib.Path({str(evidence / 'E2E-01.json')!r}).write_text(json.dumps({{'ok':True,'proof':'v1'}}))\n")
    manifest = tmp_path / 'executors.json'
    spec = {'schemaVersion':delivery.EXECUTOR_MANIFEST_VERSION,'cases':{'E2E-01':{
        'command':[sys.executable,'case.py'],'timeoutSeconds':10,'requiredEvidence':{'proof':'v1'}}}}
    helper=staging/'assertion-data.json';helper.write_text('{"expected":1}')
    spec['cases']['E2E-01']['inputFiles']=['assertion-data.json']
    manifest.write_text(json.dumps(spec))
    inputs = dict(platform='win32',staging_root=staging,evidence_dir=evidence,
                  expected_package_sha256=delivery.sha256_file(artifact),
                  component_manifest=component_manifest(tmp_path),executor_manifest=manifest)
    old = delivery.run_acceptance(ACCEPTANCE,artifact,{'E2E-01','S7-PKG-01'},None,**inputs)
    assert next(c for c in old['cases'] if c['id']=='E2E-01')['status']=='PASS'
    prior = tmp_path/'prior.json'; prior.write_text(json.dumps(old))
    if change=='manifest':
        spec['cases']['E2E-01']['requiredEvidence']['proof']='v2'
        manifest.write_text(json.dumps(spec))
    elif change=='script': script.write_text('raise SystemExit(7)\n')
    elif change=='no-output': script.write_text('print("no new evidence")\n')
    elif change=='input': helper.write_text('{"expected":2}')
    elif change=='unrelated':
        spec['cases']['E2E-02']={'command':[sys.executable,'unrelated.py'],'timeoutSeconds':5}
        manifest.write_text(json.dumps(spec))
    elif change=='evidence': (evidence/'E2E-01.json').write_text('{"ok":true,"proof":"tampered"}')
    report=delivery.run_acceptance(ACCEPTANCE,artifact,{'E2E-01','S7-PKG-01'},prior,**inputs)
    by_id={c['id']:c for c in report['cases']}
    assert by_id['S7-PKG-01']['resumed'] is True
    if change in ('unchanged','unrelated'): assert by_id['E2E-01']['resumed'] is True
    else:
        assert not by_id['E2E-01'].get('resumed',False)
        assert by_id['E2E-01']['status']==('PASS' if change in ('evidence','input') else 'FAIL')


def test_manual_only_is_not_a_successful_acceptance_run(tmp_path):
    components=component_manifest(tmp_path)
    report=delivery.run_acceptance(ACCEPTANCE,None,{'MAN-01'},None,component_manifest=components)
    assert report['outcome']=='NOT_RUN'
    assert delivery.acceptance_exit_code(report)!=0


def test_mixed_manual_and_pass_preserves_pending_manual(tmp_path):
    artifact=tmp_path/'package.zip'; delivery.build_package(PLAN,stage(tmp_path),artifact)
    report=delivery.run_acceptance(ACCEPTANCE,artifact,{'S7-PKG-01','MAN-01'},None,component_manifest=component_manifest(tmp_path))
    assert report['outcome']=='SUBSET_PASS_MAN_PENDING'
    assert next(c for c in report['cases'] if c['id']=='MAN-01')['status']=='NOT_RUN'
    assert delivery.acceptance_exit_code(report)==0 # genuine automated subset PASS, MAN still explicit


def test_resume_changed_components_fail_closed_and_old_provenance_is_not_reused(tmp_path):
    artifact=tmp_path/'package.zip'; delivery.build_package(PLAN,stage(tmp_path),artifact)
    components=component_manifest(tmp_path)
    old=delivery.run_acceptance(ACCEPTANCE,artifact,{'S7-PKG-01'},None,component_manifest=components)
    for case in old['cases']: case.pop('provenanceSha256',None)
    prior=tmp_path/'prior.json';prior.write_text(json.dumps(old))
    result=delivery.run_acceptance(ACCEPTANCE,artifact,{'S7-PKG-01'},prior,component_manifest=components)
    assert not result['cases'][0].get('resumed',False)
    value=json.loads(components.read_text());value['components']['S7']='f'*40;components.write_text(json.dumps(value))
    with pytest.raises(delivery.DeliveryError,match='RESUME_CONTEXT_MISMATCH'):
        delivery.run_acceptance(ACCEPTANCE,artifact,{'S7-PKG-01'},prior,component_manifest=components)


def test_r1_visual_owner_waiver_is_explicit_not_a_pass_and_not_transferable(tmp_path):
    manifest = component_manifest(tmp_path)
    plan = json.loads(ACCEPTANCE.read_text())
    report = delivery.run_acceptance(ACCEPTANCE, None, ['S7-VIS-01'], None,
                                    component_manifest=manifest)
    visual = next(case for case in report['cases'] if case['id'] == 'S7-VIS-01')
    assert visual['status'] == 'OWNER_WAIVED'
    assert report['outcome'] == 'NOT_RUN'  # no automated PASS claimed
    assert delivery.acceptance_exit_code(report) == 3
    plan['releaseId'] = 'R2'
    other = tmp_path / 'other-plan.json'; other.write_text(json.dumps(plan))
    result = delivery.run_acceptance(other, None, ['S7-VIS-01'], None,
                                    component_manifest=manifest)
    assert next(case for case in result['cases'] if case['id'] == 'S7-VIS-01')['status'] == 'FAIL'


def test_package_deflates_every_entry_and_preserves_extracted_bytes(tmp_path):
    source = stage(tmp_path)
    large = source / 'app/d4planner-fe.exe'
    data = b'packager compression regression\n' * 40000
    large.write_bytes(data)
    package = tmp_path / 'compressed.zip'
    delivery.build_package(PLAN, source, package)
    with zipfile.ZipFile(package) as archive:
        assert all(i.compress_type == zipfile.ZIP_DEFLATED for i in archive.infolist())
        assert archive.read('app/d4planner-fe.exe') == data
        assert archive.getinfo('app/d4planner-fe.exe').compress_size < len(data) // 10
    delivery.verify_package(package)
    delivery.install_package(package, tmp_path/'app', tmp_path/'data')
    assert (tmp_path/'app/app/d4planner-fe.exe').read_bytes() == data


def test_corrupt_deflate_stream_is_typed_package_error(tmp_path):
    import struct
    package = tmp_path/'corrupt.zip'
    delivery.build_package(PLAN, stage(tmp_path), package)
    with zipfile.ZipFile(package) as archive:
        info = archive.getinfo('release-manifest.json')
    payload = bytearray(package.read_bytes())
    name_length, extra_length = struct.unpack_from('<HH', payload, info.header_offset + 26)
    start = info.header_offset + 30 + name_length + extra_length
    payload[start] = 0xff  # DEFLATE reserved block type; not a hash-fixture rewrite.
    package.write_bytes(payload)
    with pytest.raises(delivery.DeliveryError, match='INVALID_PACKAGE'):
        delivery.verify_package(package)


@pytest.mark.parametrize('mutation', ['duplicate', 'missing'])
def test_compressed_package_inventory_rejects_duplicate_or_missing(tmp_path, mutation):
    original=tmp_path/'good.zip';bad=tmp_path/'bad.zip'
    delivery.build_package(PLAN,stage(tmp_path),original)
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(bad,'w',zipfile.ZIP_DEFLATED) as target:
        victim=next(n for n in source.namelist() if n!='release-manifest.json')
        for name in source.namelist():
            if mutation=='missing' and name==victim:continue
            target.writestr(name,source.read(name))
        if mutation=='duplicate':
            with pytest.warns(UserWarning,match='Duplicate name'):
                target.writestr(victim,source.read(victim))
    with pytest.raises(delivery.DeliveryError):delivery.verify_package(bad)
