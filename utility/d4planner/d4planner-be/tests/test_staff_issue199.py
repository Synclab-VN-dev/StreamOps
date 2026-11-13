"""Issue #199: replay real speech through resolution and durable storage."""
import json
from pathlib import Path

from d4planner.character.equipment.parser import is_item_anchor
from d4planner.character.equipment.projector import EquipmentProjector
from d4planner.character.repository import EquipmentRepository

FIXTURE = Path(__file__).parent / 'fixtures/equipment/staff_real_a_2026-11-11.jsonl'


def test_staff_is_a_valid_item_anchor():
    assert is_item_anchor('STAFF OF LAM ESEN', 'Unique Staff', '850 Item Power')


def test_real_staff_reaches_storage_without_overwriting_previous_slot(tmp_path):
    repo = EquipmentRepository(tmp_path / 'character.db')
    projector = EquipmentProjector(repo)
    projector.equipment_layouts = json.loads((FIXTURE.parent / "verified_equipment_layouts.json").read_text())
    # Start with the previous armor context, as when browsing equipped slots.
    for seq, text in enumerate([
        'Feet', 'EQUIPPED', 'PREVIOUS BOOTS', 'Rare Boots',
        '800 Item Power', 'Unequip', 'blank',
    ], 1):
        projector.consume({'eventSeq': seq, 'sessionId': 'issue199-real-a',
                           'type': 'speech.raw', 'timestamp': '2026-11-11T15:09:00+07:00',
                           'data': {'text': text}})
    events = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    # Check immediately at terminal Unequip, before navigating away.
    for event in events:
        projector.consume(event)
        if event['eventSeq'] == 419:
            rows = repo.list_equipment()
            staff = [row for row in rows if row['name'] == 'STAFF OF LAM ESEN']
            assert len(staff) == 1
            assert staff[0]['itemPower'] == 850
            assert staff[0]['slotFamily'] != 'boots'
            assert any(row['name'] == 'PREVIOUS BOOTS' for row in rows)
    rows = repo.list_equipment()
    assert any(row['name'] == 'STAFF OF LAM ESEN' for row in rows)
    for event in events:
        projector.consume(event)
    assert repo.list_equipment() == rows


def test_full_real_inventory_replay_preserves_armor_and_replaces_stale_weapons(tmp_path):
    repo = EquipmentRepository(tmp_path / 'character.db')
    from d4planner.character.models import EquipmentObservation, ParsedItem
    for seq, slot, kind in [(1, 'main_hand', 'Sword'), (2, 'off_hand', 'Focus')]:
        repo.commit_event(session_id='older-session', event_seq=seq, updated_at='2026-11-12',
            observation=EquipmentObservation(slot, None, ParsedItem('OLD '+kind,kind,800),
                '2026-11-12','older-session',seq,seq,'HIGH','old-'+slot))
    projector = EquipmentProjector(repo)
    projector.equipment_layouts = json.loads((FIXTURE.parent / 'verified_equipment_layouts.json').read_text())
    events = [json.loads(line) for line in (FIXTURE.parent / 'staff_full_a_2026-11-13.jsonl').read_text().splitlines()]
    for event in events:
        projector.consume(event)
        if event['eventSeq'] == 513:
            staff = [r for r in repo.list_equipment() if r['name'] == 'STAFF OF LAM ESEN']
            assert len(staff) == 1, 'Staff must be persisted at terminal Unequip'
            assert staff[0]['slotFamily'] == 'main_hand'
            assert staff[0]['itemPower'] == 850
    rows = repo.list_equipment()
    assert len(rows) == 9
    assert not any(r['name'].startswith('OLD ') for r in rows)
    assert {r['slotFamily'] for r in rows} == {'helm','chest','gloves','pants','boots','main_hand','ring','amulet'}
    assert len([r for r in rows if r['slotFamily'] == 'ring']) == 2
    assert next(r for r in rows if r['slotFamily']=='main_hand')['sourceEventSeqStart'] == 474
    for event in events:
        projector.consume(event)
    assert repo.list_equipment() == rows


def test_missing_or_ambiguous_layout_keeps_existing_equipment(tmp_path):
    import copy
    layouts = json.loads((FIXTURE.parent / 'verified_equipment_layouts.json').read_text())
    ambiguous = copy.deepcopy(layouts)
    ambiguous['classes'].append({'className':'Other', 'slots':[
        {'slotFamily':'unsupported_weapon','itemTypes':['Staff']}]})
    for index, layout in enumerate([None, {}, {'status':'READY'}, ambiguous]):
        repo = EquipmentRepository(tmp_path / str(index) / 'character.db')
        projector = EquipmentProjector(repo)
        projector.equipment_layouts = layout
        for seq, text in enumerate(['Feet','EQUIPPED','PREVIOUS BOOTS','Rare Boots','800 Item Power','Unequip'],1):
            projector.consume({'eventSeq':seq,'sessionId':'issue199-real-a','type':'speech.raw','data':{'text':text}})
        for event in [json.loads(line) for line in FIXTURE.read_text().splitlines()]:
            if event['eventSeq'] > 419: break
            projector.consume(event)
        rows=repo.list_equipment()
        assert not any(r['itemType']=='Staff' for r in rows)
        assert any(r['name']=='PREVIOUS BOOTS' for r in rows)


def test_two_handed_occupancy_is_replaced_atomically_by_offhand_evidence(tmp_path):
    repo=EquipmentRepository(tmp_path/'character.db')
    projector=EquipmentProjector(repo)
    projector.equipment_layouts=json.loads((FIXTURE.parent/'verified_equipment_layouts.json').read_text())
    events=[json.loads(line) for line in FIXTURE.read_text().splitlines()]
    for event in events: projector.consume(event)
    assert any(r['itemType']=='Staff' for r in repo.list_equipment())
    for seq,text in enumerate(['Off-Hand','EQUIPPED','NEW FOCUS','Rare Focus','850 Item Power','Unequip'],1000):
        projector.consume({'eventSeq':seq,'sessionId':'issue199-real-a','type':'speech.raw','data':{'text':text}})
    assert [(r['slotFamily'],r['name']) for r in repo.list_equipment() if r['slotFamily'] in ('main_hand','off_hand')]==[('off_hand','NEW FOCUS')]


def test_incomplete_staff_never_replaces_existing_weapon(tmp_path):
    repo=EquipmentRepository(tmp_path/'character.db'); projector=EquipmentProjector(repo)
    projector.equipment_layouts=json.loads((FIXTURE.parent/'verified_equipment_layouts.json').read_text())
    for seq,text in enumerate(['Main Hand','EQUIPPED','OLD WAND','Rare Wand','800 Item Power','Unequip',
            'Two-Handed','EQUIPPED','STAFF OF LAM ESEN','Unique Staff','850 Item Power','Feet'],1):
        projector.consume({'eventSeq':seq,'sessionId':'test','type':'speech.raw','data':{'text':text}})
    assert [r['name'] for r in repo.list_equipment()]==['OLD WAND']


def test_repeated_tooltip_keeps_two_handed_occupancy_without_new_header(tmp_path):
    repo=EquipmentRepository(tmp_path/'character.db'); projector=EquipmentProjector(repo)
    projector.equipment_layouts=json.loads((FIXTURE.parent/'verified_equipment_layouts.json').read_text())
    texts=['Two-Handed','EQUIPPED','STAFF OF LAM ESEN','Unique Staff','850 Item Power','Unequip',
           'EQUIPPED','STAFF OF LAM ESEN','Unique Staff','850 Item Power','Unequip']
    for seq,text in enumerate(texts,1):
        projector.consume({'eventSeq':seq,'sessionId':'repeat','type':'speech.raw','data':{'text':text}})
    import sqlite3
    with sqlite3.connect(repo.path) as db:
        item=json.loads(db.execute('select item_json from equipment_current').fetchone()[0])
    assert item['occupied_slot_families']==['main_hand','off_hand']


def test_staff_without_two_handed_header_cannot_inherit_armor_context(tmp_path):
    repo=EquipmentRepository(tmp_path/'character.db'); projector=EquipmentProjector(repo)
    projector.equipment_layouts=json.loads((FIXTURE.parent/'verified_equipment_layouts.json').read_text())
    texts=['Feet','EQUIPPED','PREVIOUS BOOTS','Rare Boots','800 Item Power','Unequip',
           'EQUIPPED','STAFF OF LAM ESEN','Unique Staff','850 Item Power','Unequip']
    for seq,text in enumerate(texts,1):
        projector.consume({'eventSeq':seq,'sessionId':'missing-header','type':'speech.raw','data':{'text':text}})
    assert [r['name'] for r in repo.list_equipment()]==['PREVIOUS BOOTS']
