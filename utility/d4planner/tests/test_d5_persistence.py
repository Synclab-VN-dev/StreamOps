import json
import sqlite3
from pathlib import Path
import pytest
from d4planner.release1.persistence import DurableHudStore

FIXTURE = Path(__file__).parents[1] / 'contracts/release1/v1/fixtures/hud.no-data.synthetic.json'

def payload(revision):
    hud = json.loads(FIXTURE.read_text())
    hud['hudRevision'] = revision
    return hud

def test_public_identity_survives_restart_and_revision_advances(tmp_path):
    path = tmp_path / 'hud.sqlite3'
    store = DurableHudStore(path)
    store.commit_context(payload, '2026-10-31T00:00:00Z')
    first = store.public_checkpoint()
    store = DurableHudStore(path)
    assert store.public_checkpoint() == first
    store.commit_context(payload, '2026-10-31T00:00:01Z')
    assert store.public_checkpoint() == dict(first, hudRevision=first['hudRevision'] + 1)

def test_v2_migration_preserves_data_and_latest_revision(tmp_path):
    path = tmp_path / 'hud.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript('CREATE TABLE schema_meta(component TEXT PRIMARY KEY,version INTEGER); INSERT INTO schema_meta VALUES("release1-hud",2); CREATE TABLE hud_snapshot(hud_revision INTEGER PRIMARY KEY,binding_key TEXT UNIQUE,payload_json TEXT,published INTEGER,committed_at TEXT);')
        db.execute('INSERT INTO hud_snapshot VALUES(14,?,?,0,?)', ('binding', json.dumps(payload(14)), '2026-10-31T00:00:00Z'))
    store = DurableHudStore(path)
    assert store.latest_authoritative() == payload(14)
    assert store.public_checkpoint()['hudRevision'] == 14
    store.commit_context(payload, '2026-10-31T00:00:01Z')
    assert store.public_checkpoint()['hudRevision'] == 15

def test_newer_schema_rejected_without_creating_public_tables(tmp_path):
    path = tmp_path / 'hud.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript('CREATE TABLE schema_meta(component TEXT PRIMARY KEY,version INTEGER); INSERT INTO schema_meta VALUES("release1-hud",99);')
    with pytest.raises(RuntimeError, match='NEWER'):
        DurableHudStore(path)
    with sqlite3.connect(path) as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='hud_public_meta'").fetchall()

def test_factory_failure_cannot_change_committed_projection(tmp_path):
    store = DurableHudStore(tmp_path / 'hud.sqlite3')
    store.commit_context(payload, '2026-10-31T00:00:00Z')
    before = store.public_checkpoint()
    def fail(_):
        raise RuntimeError('assessment failed')
    with pytest.raises(RuntimeError):
        store.commit_context(fail, '2026-10-31T00:00:01Z')
    assert store.public_checkpoint() == before
    assert store.latest_authoritative() == payload(before['hudRevision'])
