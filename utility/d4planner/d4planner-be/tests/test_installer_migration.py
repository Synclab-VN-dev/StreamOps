"""Setup orchestration uses the real storage engine; process probe is isolated."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import windows_install as engine
from d4planner.runtime import migration


@pytest.fixture
def legacy(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    for key in ('D4PLANNER_DATA_ROOT', 'D4PLANNER_HOME', 'D4PLANNER_STORAGE_ISOLATED',
                'D4PLANNER_DATA_DIR', 'D4_RULEKIT_DATA_ROOT'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(migration, 'quiescence', lambda: None)
    source = tmp_path / 'd4planner'
    target = tmp_path / 'StreamOps/D4Planner'
    (source / 'state').mkdir(parents=True)
    with closing(sqlite3.connect(source / 'state/hud.sqlite3')) as db, db:
        db.execute('CREATE TABLE equipment(revision INTEGER)')
        db.execute('INSERT INTO equipment VALUES(42)')
    for name in ('targets', 'rulekit'):
        (source / name).mkdir()
        (source / name / 'preserve.bin').write_bytes(b'preserve')
    return source, target


def test_setup_requires_explicit_confirmation_before_migration(legacy):
    source, target = legacy
    before = migration.sha(source / 'state/hud.sqlite3')
    with pytest.raises(engine.InstallError, match='MIGRATION_CONFIRMATION_REQUIRED'):
        engine.setup_storage(target)
    assert not target.exists()
    with pytest.raises(engine.InstallError, match='MIGRATION_CANCELLED'):
        engine.setup_storage(target, confirm=lambda plan: False)
    assert not target.exists()
    assert migration.sha(source / 'state/hud.sqlite3') == before


def test_setup_migrates_and_reinstall_preserves_new_data_without_prompt(legacy):
    source, target = legacy
    calls = []
    result = engine.setup_storage(target, confirm=lambda plan: calls.append(plan) or True)
    assert result['status'] == 'VERIFIED'
    assert len(calls) == 1
    for relative in ('state/hud.sqlite3', 'targets/preserve.bin', 'rulekit/preserve.bin'):
        assert migration.sha(source / relative) == migration.sha(target / relative)
    with closing(sqlite3.connect(target / 'state/hud.sqlite3')) as db, db:
        db.execute('UPDATE equipment SET revision=43')
    assert engine.setup_storage(target, confirm=lambda plan: pytest.fail('reinstall prompted'))['status'] == 'NOT_NEEDED'
    assert migration.database_check(target / 'state/hud.sqlite3')['integrity'] == 'ok'
    with closing(sqlite3.connect(target / 'state/hud.sqlite3')) as db, db:
        assert db.execute('SELECT revision FROM equipment').fetchone() == (43,)


def test_fresh_install_never_prompts(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    target = tmp_path / 'StreamOps/D4Planner'
    assert engine.setup_storage(target, confirm=lambda plan: pytest.fail('fresh install prompted'))['status'] == 'NOT_NEEDED'
    assert not target.exists()


def test_conflict_or_busy_fails_before_confirmation(legacy, monkeypatch):
    source, target = legacy
    def busy():
        raise migration.StorageError('BUSY: writer remains')
    monkeypatch.setattr(migration, 'quiescence', busy)
    with pytest.raises(migration.StorageError, match='BUSY'):
        engine.setup_storage(target, confirm=lambda plan: pytest.fail('busy prompted'))
    assert not target.exists()
    monkeypatch.setattr(migration, 'quiescence', lambda: None)
    (target / 'targets').mkdir(parents=True)
    (target / 'targets/preserve.bin').write_bytes(b'newer')
    with pytest.raises(migration.StorageError, match='CONFLICT'):
        engine.setup_storage(target, confirm=lambda plan: pytest.fail('conflict prompted'))
    assert (target / 'targets/preserve.bin').read_bytes() == b'newer'


def test_unfinished_migration_remains_blocked_without_confirmation(legacy):
    source, target = legacy
    (target / 'private').mkdir(parents=True)
    journal = target / 'private/storage-migration.json'
    journal.write_text(json.dumps({'status': 'RECOVERY_REQUIRED'}))
    with pytest.raises(engine.InstallError, match='MIGRATION_RECOVERY_REQUIRED'):
        engine.setup_storage(target)
    assert journal.exists()


def test_setup_recovers_failed_migration_only_after_confirmation(legacy, monkeypatch):
    source, target = legacy
    original = migration.os.link
    count = 0
    def interrupt(a, b):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError('interrupted publication')
        return original(a, b)
    monkeypatch.setattr(migration.os, 'link', interrupt)
    with pytest.raises(OSError, match='interrupted publication'):
        engine.setup_storage(target, confirm=lambda plan: True)
    journal = target / 'private/storage-migration.json'
    before = journal.read_bytes()
    with pytest.raises(engine.InstallError, match='MIGRATION_CANCELLED'):
        engine.setup_storage(target, confirm=lambda plan: False)
    assert journal.read_bytes() == before
    monkeypatch.setattr(migration.os, 'link', original)
    decisions = []
    result = engine.setup_storage(target, confirm=lambda plan: decisions.append(plan.get('operation', 'MIGRATE')) or True)
    assert decisions == ['RECOVER', 'MIGRATE']
    assert result['status'] == 'VERIFIED'
    assert not journal.exists()
    assert migration.sha(source / 'state/hud.sqlite3') == migration.sha(target / 'state/hud.sqlite3')


def test_missing_legacy_source_cannot_bypass_pending_recovery(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    target = tmp_path / 'StreamOps/D4Planner'
    (target / 'private').mkdir(parents=True)
    journal = target / 'private/storage-migration.json'
    journal.write_text('{}')
    with pytest.raises(engine.InstallError, match='MIGRATION_RECOVERY_REQUIRED'):
        engine.setup_storage(target, confirm=lambda plan: pytest.fail('missing source prompted'))
    assert journal.read_text() == '{}'


def test_incompatible_legacy_schema_is_rejected_before_copy(legacy, tmp_path):
    source, target = legacy
    with closing(sqlite3.connect(source / 'state/hud.sqlite3')) as db, db:
        db.execute('CREATE TABLE schema_meta(component TEXT, version INTEGER)')
        db.execute("INSERT INTO schema_meta VALUES('release1-hud',999)")
    payload = tmp_path / 'candidate'; payload.mkdir()
    (payload / 'release-manifest.json').write_text(json.dumps({'hudSchemaCompatibility': {'minimum': 2, 'maximum': 2}}))
    with pytest.raises(engine.InstallError, match='DB_SCHEMA_INCOMPATIBLE'):
        engine.setup_storage(target, payload=payload, confirm=lambda plan: pytest.fail('incompatible schema prompted'))
    assert not target.exists()
