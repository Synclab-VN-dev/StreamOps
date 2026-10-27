"""Engine tests; Windows acceptance separately uses the actual production Setup."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import zipfile

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import windows_install as engine


def package(tmp_path, version="1.0.0"):
    executable = b"unit-test-payload-not-native-acceptance"
    path = tmp_path / f"package-{version}.zip"
    manifest = {
        "schemaVersion":engine.delivery.MANIFEST_VERSION, "applicationId":engine.APP_ID,
        "version":version, "hudSchemaCompatibility":{"minimum":2,"maximum":2},
        "files":[{"path":"D4Planner.exe", "bytes":len(executable),
                  "sha256":engine.delivery.hashlib.sha256(executable).hexdigest()}],
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("release-manifest.json", json.dumps(manifest))
        archive.writestr("D4Planner.exe", executable)
    return path, engine.delivery.sha256_file(path)


def prepare(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "stop_owned", lambda root: None)
    root = tmp_path / "Cài đặt có khoảng trắng"
    data = tmp_path / "Dữ liệu riêng"; (data / "targets").mkdir(parents=True)
    (data / "targets/user.json").write_text("user target")
    (data / "settings.json").write_text('{"user":true}')
    (data / "state").mkdir()
    with sqlite3.connect(data / "state/hud.sqlite3") as db:
        db.execute("create table schema_meta(component text,version integer)")
        db.execute("insert into schema_meta values('release1-hud',2)")
    return root, data


def test_install_upgrade_reinstall_downgrade_and_uninstall_preserve_user_data(tmp_path, monkeypatch):
    root, data = prepare(tmp_path, monkeypatch)
    first, sha = package(tmp_path)
    engine.install(first, root, data, sha, health_check=lambda root: None)
    before_db = (data / "state/hud.sqlite3").read_bytes()
    second, sha = package(tmp_path, "1.0.1")
    engine.install(second, root, data, sha, health_check=lambda root: None)
    engine.install(second, root, data, sha, health_check=lambda root: None)
    assert engine.read_state(root)["version"] == "1.0.1"
    with pytest.raises(engine.InstallError, match="DOWNGRADE_REJECTED"):
        engine.install(first, root, data, engine.delivery.sha256_file(first), health_check=lambda root: None)
    user = engine.owned_payload(root, engine.read_state(root)) / "user-owned.txt"
    user.write_text("keep")
    engine.uninstall(root)
    assert user.read_text() == "keep"
    assert (data / "state/hud.sqlite3").read_bytes() == before_db
    assert (data / "targets/user.json").read_text() == "user target"
    assert (data / "settings.json").read_text() == '{"user":true}'


@pytest.mark.parametrize("failure", ["JOURNALED", "ACTIVATED"])
def test_upgrade_failure_restores_previous_without_restoring_database(tmp_path, monkeypatch, failure):
    root, data = prepare(tmp_path, monkeypatch)
    first, sha = package(tmp_path)
    engine.install(first, root, data, sha, health_check=lambda root: None)
    old = engine.read_state(root)
    second, sha = package(tmp_path, "1.0.1")
    def fail(phase):
        if phase == failure: raise OSError("test interruption")
    with pytest.raises(OSError):
        engine.install(second, root, data, sha, health_check=lambda root: None, checkpoint=fail)
    assert engine.read_state(root) == old
    assert not (root / "upgrade-journal.json").exists()


def test_process_termination_journal_recovers_on_next_run(tmp_path, monkeypatch):
    root, data = prepare(tmp_path, monkeypatch)
    first, sha = package(tmp_path)
    engine.install(first, root, data, sha, health_check=lambda root: None)
    second, sha = package(tmp_path, "1.0.1")
    def terminate(phase):
        if phase == "ACTIVATED": raise SystemExit(137)
    with pytest.raises(SystemExit):
        engine.install(second, root, data, sha, health_check=lambda root: None, checkpoint=terminate)
    assert (root / "upgrade-journal.json").exists()
    assert engine.recover(root)["recovery"] == "RESTORED_PREVIOUS"
    assert engine.read_state(root)["version"] == "1.0.0"


def test_tampered_package_and_incompatible_db_fail_closed(tmp_path, monkeypatch):
    root, data = prepare(tmp_path, monkeypatch)
    first, sha = package(tmp_path)
    with pytest.raises(engine.InstallError, match="PACKAGE_SHA256_MISMATCH"):
        engine.install(first, root, data, "0" * 64)
    with sqlite3.connect(data / "state/hud.sqlite3") as db:
        db.execute("update schema_meta set version=999")
    with pytest.raises(engine.InstallError, match="DB_SCHEMA_INCOMPATIBLE"):
        engine.install(first, root, data, sha)
    assert not root.exists()


def test_rollback_refuses_new_database_schema(tmp_path, monkeypatch):
    root, data = prepare(tmp_path, monkeypatch)
    for version in ("1.0.0", "1.0.1"):
        artifact, sha = package(tmp_path, version)
        engine.install(artifact, root, data, sha, health_check=lambda root: None)
    with sqlite3.connect(data / "state/hud.sqlite3") as db:
        db.execute("update schema_meta set version=3")
    with pytest.raises(engine.InstallError, match="DB_SCHEMA_INCOMPATIBLE"):
        engine.rollback(root)
    assert engine.read_state(root)["version"] == "1.0.1"


def test_install_refuses_redirected_application_subtree(tmp_path, monkeypatch):
    root,data = prepare(tmp_path,monkeypatch)
    root.mkdir()
    outside = tmp_path / "user-owned"; outside.mkdir()
    (outside / "preserve.txt").write_text("preserve")
    (root / "versions").symlink_to(outside,target_is_directory=True)
    artifact,digest = package(tmp_path)
    with pytest.raises(engine.InstallError,match="REPARSE_POINT"):
        engine.install(artifact,root,data,digest,health_check=lambda root: None)
    assert (outside / "preserve.txt").read_text() == "preserve"


def test_default_install_runs_runtime_health_before_commit(tmp_path, monkeypatch):
    root, data = prepare(tmp_path, monkeypatch)
    artifact, digest = package(tmp_path)
    calls = []
    def probe(command, **kwargs):
        calls.append(command)
        if '--runtime-health' in command:
            report = Path(command[command.index('--health-report') + 1])
            report.write_text(json.dumps({'ok': True, 'runtimeReady': True, 'ownedCleanup': True}))
        return type('Completed', (), {'returncode': 0})()
    monkeypatch.setattr(engine.subprocess, 'run', probe)
    engine.install(artifact, root, data, digest)
    assert any('--runtime-health' in command for command in calls)


def test_runtime_startup_failure_restores_previous_pointer_and_db(tmp_path, monkeypatch):
    root, data = prepare(tmp_path, monkeypatch)
    artifact, digest = package(tmp_path)
    engine.install(artifact, root, data, digest, health_check=lambda path: None)
    previous = engine.read_state(root)
    db_before = (data / 'state/hud.sqlite3').read_bytes()
    artifact, digest = package(tmp_path, '1.0.2')
    def probe(command, **kwargs):
        if '--runtime-health' in command:
            raise engine.subprocess.CalledProcessError(1, command)
        return type('Completed', (), {'returncode': 0})()
    monkeypatch.setattr(engine.subprocess, 'run', probe)
    with pytest.raises(engine.subprocess.CalledProcessError):
        engine.install(artifact, root, data, digest)
    assert engine.read_state(root) == previous
    assert not (root / 'upgrade-journal.json').exists()
    assert (data / 'state/hud.sqlite3').read_bytes() == db_before


def test_exit_zero_without_runtime_readiness_evidence_is_not_health(tmp_path, monkeypatch):
    def probe(command, **kwargs):
        Path(command[command.index('--health-report') + 1]).write_text(json.dumps({'ok':True}))
        return type('Completed', (), {'returncode':0})()
    monkeypatch.setattr(engine.subprocess, 'run', probe)
    with pytest.raises(engine.InstallError, match='RUNTIME_HEALTH_EVIDENCE_INVALID'):
        engine.runtime_health(tmp_path)


def test_rulekit_preflight_rejection_preserves_old_application_and_user_snapshot_store(tmp_path, monkeypatch):
    root, data = prepare(tmp_path, monkeypatch)
    old_package, old_sha = package(tmp_path)
    engine.install(old_package, root, data, old_sha, health_check=lambda path: None)
    previous = engine.read_state(root)
    sentinel = data / 'rulekit/store/synthetic-unactivated/preserve.bin'
    sentinel.parent.mkdir(parents=True)
    sentinel.write_bytes(b'isolated-user-snapshot-store')
    before_db = (data / 'state/hud.sqlite3').read_bytes()
    candidate, _ = package(tmp_path, '1.1.0')
    with zipfile.ZipFile(candidate) as archive:
        manifest = json.loads(archive.read('release-manifest.json'))
        executable = archive.read('D4Planner.exe')
    manifest['ruleKit'] = {'snapshotManagementContract':'d4-rulekit-snapshots/v1'}
    with zipfile.ZipFile(candidate, 'w') as archive:
        archive.writestr('release-manifest.json', json.dumps(manifest))
        archive.writestr('D4Planner.exe', executable)
    calls = []
    def probe(command, **kwargs):
        calls.append(command)
        if '--operation' in command:
            assert command[command.index('--operation') + 1] == 'upgradePreflight'
            Path(command[command.index('--report') + 1]).write_text(json.dumps({
                'ok':False, 'error':{'code':'TRUST_POLICY_NOT_CONFIGURED'},
            }))
            return type('Completed', (), {'returncode':1})()
        return type('Completed', (), {'returncode':0})()
    monkeypatch.setattr(engine.subprocess, 'run', probe)
    with pytest.raises(engine.InstallError, match='RULEKIT_UPGRADE_PREFLIGHT_REJECTED:TRUST_POLICY_NOT_CONFIGURED'):
        engine.install(candidate, root, data, engine.delivery.sha256_file(candidate))
    assert engine.read_state(root) == previous
    assert sentinel.read_bytes() == b'isolated-user-snapshot-store'
    assert (data / 'state/hud.sqlite3').read_bytes() == before_db
    assert not any('--runtime-health' in command for command in calls)
