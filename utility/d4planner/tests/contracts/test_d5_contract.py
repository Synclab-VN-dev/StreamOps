"""D5 contract evidence; synthetic, not native runtime acceptance."""
import copy
import json
from pathlib import Path
import sqlite3

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2] / 'contracts/release1/v1'

def load(name):
    return json.loads((ROOT / name).read_text())

def validator(name):
    hud = load('schemas/hud.schema.json')
    registry = Registry().with_resource(hud['$id'], Resource.from_contents(hud))
    return Draft202012Validator(load('schemas/' + name), registry=registry)

def test_db_projection_and_closed_envelope():
    sample = load('fixtures/hud-db.synthetic.json')
    validator('hud-db.schema.json').validate(sample)
    assert sample['hudRevision'] == sample['hud']['hudRevision']
    for field in ('dbId', 'epoch', 'schemaVersion', 'hudRevision', 'hud'):
        invalid = copy.deepcopy(sample)
        del invalid[field]
        assert not validator('hud-db.schema.json').is_valid(invalid)

def test_notification_only_rejects_payload_and_commands():
    check = validator('ws.schema.json')
    messages = load('fixtures/ws-messages.synthetic.json')['messages']
    for message in messages:
        check.validate(message)
    for key in ('hud', 'equipment', 'score', 'targets', 'command'):
        assert not check.is_valid(dict(messages[-1], **{key: {}}))
    for kind in ('target.list.request', 'target.select.request', 'hud.snapshot', 'hud.update'):
        assert not check.is_valid(dict(messages[-1], type=kind))

def test_commands_require_owner_and_exact_parameters():
    check = validator('command.schema.json')
    command = load('fixtures/command.synthetic.json')
    check.validate(command)
    for field in ('requestId', 'ownerInstanceId', 'childInstanceId', 'generation'):
        bad = copy.deepcopy(command)
        del bad[field]
        assert not check.is_valid(bad)
    assert not check.is_valid(dict(command, method='evaluate'))
    assert not check.is_valid(dict(command, params={'path': 'arbitrary.json'}))
    check.validate(dict(command, method='target.list', params={}))

def test_public_sql_wal_snapshot_is_atomic_and_query_only(tmp_path):
    path = tmp_path / 'hud.sqlite3'
    writer = sqlite3.connect(path)
    writer.executescript((ROOT / 'hud-db.sql').read_text())
    writer.execute('PRAGMA journal_mode=WAL')
    writer.execute("INSERT INTO hud_public_meta VALUES(1,'d4planner-hud-db/v1','db','epoch')")
    writer.execute("INSERT INTO hud_current VALUES(1,7,'{}')")
    writer.commit()
    reader = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    reader.execute('PRAGMA query_only=ON')
    reader.execute('BEGIN')
    assert reader.execute('SELECT hud_revision FROM hud_current').fetchone()[0] == 7
    writer.execute("UPDATE hud_current SET hud_revision=8,payload_json='{}'")
    writer.commit()
    assert reader.execute('SELECT hud_revision FROM hud_current').fetchone()[0] == 7
    reader.commit()
    assert reader.execute('SELECT hud_revision FROM hud_current').fetchone()[0] == 8
    with pytest.raises(sqlite3.OperationalError):
        reader.execute('DELETE FROM hud_current')
    reader.close()
    writer.close()
