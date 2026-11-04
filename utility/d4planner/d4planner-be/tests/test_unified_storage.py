"""UDR fixtures are isolated; they do not establish live-game acceptance."""
import json
from pathlib import Path
import sqlite3
from contextlib import closing

import pytest

from d4planner.runtime.storage import StorageError, resolve_root, child_environment
from d4planner.runtime import migration


def test_default_and_legacy_guard(tmp_path):
    env = {"LOCALAPPDATA": str(tmp_path)}
    root = tmp_path / "StreamOps/D4Planner"
    assert resolve_root(environment=env) == root
    assert not root.exists()
    legacy = tmp_path / "d4planner"  # LEGACY migration fixture
    legacy.mkdir(); (legacy / "data").write_text("preserve")
    with pytest.raises(StorageError, match="MIGRATION_REQUIRED"):
        resolve_root(environment=env)
    assert resolve_root(tmp_path / "isolated", environment=env) == tmp_path / "isolated"


@pytest.mark.parametrize("key,tail", [("D4PLANNER_HOME", "other"), ("D4PLANNER_DATA_DIR", "other/state"),
                                    ("D4_RULEKIT_DATA_ROOT", "other/rulekit"), ("D4_LOG_DIR", "other/logs/run")])
def test_conflicting_consumers(tmp_path, key, tail):
    env = {"D4PLANNER_DATA_ROOT": str(tmp_path / "root"), key: str(tmp_path / tail)}
    with pytest.raises(StorageError, match="PATH_CONFLICT"):
        resolve_root(environment=env)


def test_registered_and_child_environment(tmp_path):
    root = tmp_path / "root"
    env = child_environment(root)
    assert resolve_root(registered=root, environment=env) == root
    with pytest.raises(StorageError, match="PATH_CONFLICT"):
        resolve_root(registered=tmp_path / "other", environment=env)


def test_reject_relative_traversal_and_symlink(tmp_path):
    with pytest.raises(StorageError):
        resolve_root("relative", environment={})
    with pytest.raises(StorageError):
        resolve_root(tmp_path / "a/../b", environment={})
    try:
        (tmp_path / "alias").symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("symlink privilege unavailable")
    with pytest.raises(StorageError):
        resolve_root(tmp_path / "alias/data", environment={})


@pytest.fixture
def roots(tmp_path):
    source, target = tmp_path / "legacy", tmp_path / "new"
    (source / "state").mkdir(parents=True)
    with closing(sqlite3.connect(source / "state/character.db")) as db, db:
        db.execute("CREATE TABLE equipment(revision INTEGER)")
        db.execute("INSERT INTO equipment VALUES(17)")
    (source / "state/capture.json").write_text('{"enabled":false}')
    (source / "sessions/recorded").mkdir(parents=True)
    (source / "sessions/recorded/raw-speech.jsonl").write_text('{"speech":"fixture"}\n')
    return source, target


def test_dry_run_apply_idempotent_and_rollback(roots):
    source, target = roots
    before = {str(p.relative_to(source)): migration.sha(p) for p in source.rglob("*") if p.is_file()}
    report = migration.plan(source, target, _probe=lambda: None)
    assert not target.exists()
    migration.apply(report, _probe=lambda: None)
    migration.verify(report)
    assert report["status"] == "VERIFIED"
    assert migration.database_check(target / "state/character.db")["rowCounts"] == {"equipment": 1}
    repeat = migration.plan(source, target, _probe=lambda: None)
    assert all(f["action"] == "SKIP_IDENTICAL" for f in repeat["files"])
    assert before == {str(p.relative_to(source)): migration.sha(p) for p in source.rglob("*") if p.is_file() and p.name != ".storage-migrated.json"}
    migration.rollback(report, _probe=lambda: None)
    assert not (target / "state/character.db").exists()
    assert (source / "state/character.db").exists()


def test_conflict_and_changed_plan(roots):
    source, target = roots
    report = migration.plan(source, target, _probe=lambda: None)
    (source / "state/capture.json").write_text('{"enabled":false,"changed":true}')
    with pytest.raises(StorageError, match="inventory changed"):
        migration.apply(report, _probe=lambda: None)
    assert not target.exists()
    (target / "state").mkdir(parents=True)
    (target / "state/capture.json").write_text("foreign")
    with pytest.raises(StorageError, match="CONFLICT"):
        migration.plan(source, target, _probe=lambda: None)


def test_busy_corrupt_wal_metadata(roots):
    source, target = roots
    def busy():
        raise StorageError("BUSY")
    with pytest.raises(StorageError, match="BUSY"):
        migration.plan(source, target, _probe=busy)
    wal = source / "state/character.db-wal"; wal.write_bytes(b"committed frames")
    with pytest.raises(StorageError, match="checkpoint"):
        migration.plan(source, target, _probe=lambda: None)
    wal.unlink()
    (source / "state/character.db").write_bytes(b"corrupt")
    with pytest.raises(sqlite3.DatabaseError):
        migration.plan(source, target, _probe=lambda: None)
    assert not target.exists()


def test_rollback_never_overwrites_new_write(roots):
    source, target = roots
    report = migration.plan(source, target, _probe=lambda: None)
    migration.apply(report, _probe=lambda: None)
    with closing(sqlite3.connect(target / "state/character.db")) as db, db:
        db.execute("INSERT INTO equipment VALUES(18)")
    with pytest.raises(StorageError, match="post-switch"):
        migration.rollback(report, _probe=lambda: None)
    assert migration.database_check(target / "state/character.db")["rowCounts"] == {"equipment": 2}


def test_publish_failure_is_recoverable(roots, monkeypatch):
    source, target = roots
    report = migration.plan(source, target, _probe=lambda: None)
    original = migration.os.link
    count = 0
    def fail_second(a, b):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("injected failure")
        return original(a, b)
    monkeypatch.setattr(migration.os, "link", fail_second)
    with pytest.raises(OSError, match="injected"):
        migration.apply(report, _probe=lambda: None)
    journal = json.loads((target / "private/storage-migration.json").read_text())
    assert journal["status"] == "RECOVERY_REQUIRED"
    with pytest.raises(StorageError, match="MIGRATION_REQUIRED"):
        resolve_root(target, environment={})
    migration.rollback(journal, _probe=lambda: None)
    assert not (target / "private/storage-migration.json").exists()


def test_known_metadata_rebase_preserves_original_and_unknown_blocks(roots):
    source, target = roots
    session = source / 'sessions/recorded'
    metadata = source / 'state/runtime.json'
    metadata.write_text(json.dumps({'state': 'STOPPED', 'sessionDir': str(session), 'supervisorPid': 999999}))
    original = metadata.read_bytes()
    report = migration.plan(source, target, _probe=lambda: None)
    migration.apply(report, _probe=lambda: None)
    assert metadata.read_bytes() == original
    assert json.loads((target/'state/runtime.json').read_text())['sessionDir'] == str(target/'sessions/recorded')
    migration.verify(report)
    migration.rollback(report, _probe=lambda: None)
    metadata.write_text(json.dumps({'state':'STOPPED','unknownPath':str(session)}))
    with pytest.raises(StorageError, match='unknown legacy field'):
        migration.plan(source, target, _probe=lambda: None)


def test_registered_default_still_detects_legacy(tmp_path):
    root = tmp_path / 'StreamOps/D4Planner'
    source = tmp_path / 'd4planner'  # LEGACY
    (source / 'state').mkdir(parents=True)
    (source / 'state/capture.json').write_text('{"enabled":false}')
    env = {'LOCALAPPDATA':str(tmp_path)}
    with pytest.raises(StorageError, match='MIGRATION_REQUIRED'):
        resolve_root(registered=root, environment=env)
    report = migration.plan(source, root, _probe=lambda: None)
    migration.apply(report, _probe=lambda: None)
    assert resolve_root(registered=root, environment=env) == root


def test_json_manifest_roundtrip(roots):
    source, target = roots
    report = json.loads(json.dumps(migration.plan(source, target, _probe=lambda: None)))
    migration.apply(report, _probe=lambda: None)
    migration.verify(json.loads(json.dumps(report)))


def test_authorized_isolation_is_explicit_and_disjoint(tmp_path):
    registered = tmp_path / 'installed-data'
    isolated = tmp_path / 'isolated'
    env = {'D4PLANNER_STORAGE_ISOLATED':'1','D4PLANNER_DATA_ROOT':str(isolated)}
    assert resolve_root(registered=registered, environment=env) == isolated
    env['D4PLANNER_DATA_ROOT'] = str(registered/'inside')
    with pytest.raises(StorageError, match='disjoint'):
        resolve_root(registered=registered, environment=env)


def test_managed_root_never_discovers_home(tmp_path, monkeypatch):
    def unavailable_home(*args):
        raise RuntimeError('managed environment has no home')
    monkeypatch.setattr(Path, 'home', unavailable_home)
    root = tmp_path / 'managed'
    assert resolve_root(root, environment=child_environment(root)) == root


def test_external_equipment_repository_remains_external(roots):
    source, target = roots
    external = source.parent/'external.db'
    with closing(sqlite3.connect(external)) as db, db:
        db.execute('CREATE TABLE user_data(value TEXT)')
    (source/'launcher.json').write_text(json.dumps({'schemaVersion':'d4planner-launcher/v1',
        'equipmentRepository':{'enabled':True,'path':str(external),'characterId':'real','characterDisplayName':'Player'}}))
    before = migration.sha(external)
    report = migration.plan(source, target, _probe=lambda: None)
    assert report['externalReferences'][0]['ownership'] == 'EXTERNAL_READ_ONLY_PRESERVED'
    migration.apply(report, _probe=lambda: None)
    assert json.loads((target/'launcher.json').read_text())['equipmentRepository']['path'] == str(external)
    assert migration.sha(external) == before


@pytest.mark.parametrize('case', json.loads((Path(__file__).parent/'fixtures/unified-storage-cases.json').read_text()), ids=lambda case: case['name'])
def test_shared_native_python_path_contract(tmp_path, case):
    expand = lambda value: value.replace('@root', str(tmp_path))
    env = {key:expand(value) for key,value in case['env'].items()}
    registered = expand(case['registered']) if case.get('registered') else None
    if 'error' in case:
        with pytest.raises(StorageError, match=case['error']):
            resolve_root(registered=registered, environment=env)
    else:
        assert resolve_root(registered=registered, environment=env) == Path(expand(case['expected']))


def test_legacy_cache_and_migration_log_mapping(roots):
    source, target = roots
    (source/'cache').mkdir(); (source/'cache/controller.zip').write_bytes(b'original asset')
    (source/'logs').mkdir(); (source/'logs/event-migration.jsonl').write_text('{"historical":true}\n')
    report = migration.plan(source, target, _probe=lambda: None)
    migration.apply(report, _probe=lambda: None)
    assert (target/'runtime/nvda-controller/cache/controller.zip').read_bytes() == b'original asset'
    assert (target/'state/event-migration.jsonl').read_bytes() == (source/'logs/event-migration.jsonl').read_bytes()
    assert not (target/'logs/event-migration.jsonl').exists()
    migration.verify(report)


@pytest.mark.skipif(__import__('sys').platform != 'win32', reason='native Windows sharing gate')
def test_open_sqlite_writer_blocks_before_destination_mutation(roots):
    source, target = roots
    report = migration.plan(source, target, _probe=lambda: None)
    with closing(sqlite3.connect(source/'state/character.db')) as db:
        db.execute('SELECT * FROM equipment').fetchall()
        with pytest.raises(StorageError, match='BUSY'):
            migration.apply(report, _probe=lambda: None)
    assert not target.exists()


@pytest.mark.skipif(__import__('sys').platform != 'win32', reason='native Windows ACL gate')
def test_foreign_write_acl_is_not_accepted(tmp_path):
    import subprocess
    root = tmp_path/'foreign-writer'; root.mkdir()
    try:
        subprocess.run(['icacls.exe', str(root), '/grant', '*S-1-1-0:(W)'], check=True, capture_output=True)
        with pytest.raises(StorageError, match='owner/ACL'):
            migration.check_owner(root)
    finally:
        subprocess.run(['icacls.exe', str(root), '/remove:g', '*S-1-1-0'], check=True, capture_output=True)


def test_repeat_apply_does_not_create_new_files_or_replace_receipt(roots):
    source, target = roots
    first = migration.apply(migration.plan(source, target, _probe=lambda: None), _probe=lambda: None)
    before = {p.relative_to(target).as_posix():migration.sha(p) for p in target.rglob('*') if p.is_file()}
    again = migration.apply(migration.plan(source, target, _probe=lambda: None), _probe=lambda: None)
    assert again['noOp'] and again['receiptId'] == first['id']
    assert before == {p.relative_to(target).as_posix():migration.sha(p) for p in target.rglob('*') if p.is_file()}
    migration.rollback(again, _probe=lambda: None)
    assert (target/'state/character.db').exists()


def test_legacy_consumers_block_and_generated_helpers_are_not_rewritten(roots):
    source, target = roots
    scripts = source/'runtime/bin'; scripts.mkdir(parents=True)
    original = f"$root='{source}'\n"
    (scripts/'start-nvda.ps1').write_text(original)
    report = migration.apply(migration.plan(source, target, _probe=lambda: None), _probe=lambda: None)
    assert (scripts/'start-nvda.ps1').read_text() == original
    assert not (target/'runtime/bin/start-nvda.ps1').exists()
    migration.verify(report)
    with pytest.raises(StorageError, match='MIGRATION_REQUIRED'):
        resolve_root(source, environment={})
    assert resolve_root(target, environment={}) == target
    migration.rollback(report, _probe=lambda: None)
    assert resolve_root(source, environment={}) == source
