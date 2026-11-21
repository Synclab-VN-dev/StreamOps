import json
import sqlite3
import pytest
from d4planner.character.export import export_character
from d4planner.character.talisman_store import TalismanProjection
from test_observed_equipment_layout import setup, feed, header, tooltip


def test_export_full_item_scope_and_no_display_loss(tmp_path):
    repo,p=setup(tmp_path)
    feed(p,header('First')+tooltip('Ranged','Example Bow','Legendary Bow')+tooltip('Main Hand','Dagger','Rare Dagger'))
    with sqlite3.connect(repo.path) as db:
        raw=json.loads(db.execute("select item_json from equipment_current where slot_family='ranged'").fetchone()[0])
        raw['native_extension']={'emptySockets':[None,None],'unicode':'Tiếng Việt'}
        db.execute("update equipment_current set item_json=? where slot_family='ranged'",(json.dumps(raw),))
    before=repo.path.read_bytes()
    result=export_character(repo.path,'s')
    assert result['capture']['freshness']=='ACTIVE_SESSION'
    assert next(i['item'] for i in result['equipment'] if i['slot']=='ranged')==raw
    assert result['character']['identity']=='UNVERIFIED' and result['character']['name'] is None
    assert 'ranged' in result['layout']['slots']
    assert repo.path.read_bytes()==before
    feed(p,header('Second')+tooltip('Two-Handed','Staff','Rare Staff'))
    changed=export_character(repo.path,'other')
    assert [i['item']['name'] for i in changed['equipment']]==['Staff']
    assert 'ranged' not in changed['layout']['slots']
    assert changed['capture']['freshness']=='LAST_KNOWN'


def test_empty_is_explicit_and_cleared_by_equip_or_new_scope(tmp_path):
    repo,p=setup(tmp_path);feed(p,header('First')+tooltip('Ranged','Bow','Rare Bow'))
    scope=repo.scope()
    repo.commit_event(session_id='s',event_seq=50,updated_at='now',observation=None,empty_slot_family='ranged',scope=scope)
    result=export_character(repo.path)
    assert result['equipment']==[] and result['confirmedEmptySlots'][0]['slot']=='ranged'
    feed(p,tooltip('Ranged','Replacement','Rare Bow'))
    assert export_character(repo.path)['confirmedEmptySlots']==[]
    feed(p,header('Second'))
    with pytest.raises(ValueError,match='CHARACTER_NO_DATA'):export_character(repo.path)


def test_talisman_same_scope_only_preserves_attributes_and_latest_seal(tmp_path):
    repo,p=setup(tmp_path);feed(p,header('First')+tooltip('Ranged','Bow','Rare Bow'))
    TalismanProjection(repo.path)
    with sqlite3.connect(repo.path) as db:
        for session,seq,role,name in [('s',20,'equipped','Current'),('s',21,'equipped','Latest'),('other',22,'equipped','Foreign'),('s',23,'bag','Bag')]:
            db.execute("INSERT INTO talisman_observation(session_id,start_seq,end_seq,observed_at,role,kind,name,item_type,item_power,attributes_json,set_bonuses_json) VALUES(?,?,?,'now',?,'seal',?,'Seal',900,?,?)",(session,seq,seq,role,name,json.dumps(['+1 Example','Unparsed effect']),json.dumps(['(2) Set: example'])))
    # Other projections may be ahead: do not attach rows beyond equipment's checkpoint.
    assert export_character(repo.path)['talisman']['observations']==[]
    feed(p,['blank']*30)
    result=export_character(repo.path)
    assert [i['name'] for i in result['talisman']['observations']]==['Latest']
    assert result['talisman']['observations'][0]['attributes']==['+1 Example','Unparsed effect']
    feed(p,header('Second')+tooltip('Main Hand','Wand','Rare Wand'))
    # Our fixture header event sequence may precede the synthetic Talisman rows;
    # explicitly advance past them before switching context.
    feed(p,['blank']*30+header('Third')+tooltip('Main Hand','New Wand','Rare Wand'))
    assert export_character(repo.path)['talisman']['observations']==[]


def test_missing_corrupt_oversize_fail_closed(tmp_path):
    with pytest.raises(ValueError,match='CHARACTER_NO_DATA'):export_character(tmp_path/'missing.db')
    repo,p=setup(tmp_path);feed(p,tooltip('Ranged','Bow','Rare Bow'))
    with sqlite3.connect(repo.path) as db:db.execute('UPDATE equipment_current SET item_json=?',(json.dumps({'large':'x'*512000}),))
    with pytest.raises(ValueError,match='CHARACTER_EXPORT_TOO_LARGE'):export_character(repo.path)
    with sqlite3.connect(repo.path) as db:db.execute("UPDATE equipment_current SET item_json='invalid'")
    with pytest.raises(ValueError,match='CHARACTER_SOURCE_INVALID'):export_character(repo.path)


def test_control_export_contract():
    from d4planner.control import validate_request
    value=dict(protocolVersion='d4planner-control/v1',type='request',requestId='r',ownerInstanceId='o',childInstanceId='c',generation=1,method='character.export',params={})
    validate_request(value)
    value['params']={'path':'foreign.db'}
    with pytest.raises(ValueError):validate_request(value)


def test_real_production_control_export_independent_of_calculation(tmp_path,monkeypatch):
    import asyncio
    from d4planner.control import dispatch
    from test_current_equipment_hud import runtime
    monkeypatch.setenv('D4PLANNER_CAPTURE_PROBE_ONLY','1')
    (tmp_path/'state').mkdir()
    repo,p=setup(tmp_path/'state');feed(p,tooltip('Ranged','Bow','Rare Bow'))
    async def run():
        be=runtime(tmp_path);await be.start()
        command=dict(protocolVersion='d4planner-control/v1',type='request',requestId='export',ownerInstanceId='owner',childInstanceId='test-current',generation=1,method='character.export',params={})
        try:
            result=await dispatch(be,command,command)
            assert result['error'] is None and result['requestId']=='export'
            assert result['result']['equipment'][0]['item']['name']=='Bow'
            assert result['result']['capture']['freshness']=='LAST_KNOWN'
            assert be.store.latest_authoritative()['score']['status']=='NO_DATA'
        finally:await be.stop()
    asyncio.run(run())
