"""Regression structure from A #226/#227; synthetic names/stats, no private payload."""
import json
from pathlib import Path
import pytest
from d4planner.character.equipment.projector import EquipmentProjector
from d4planner.character.repository import EquipmentRepository, ReadOnlyEquipmentRepository
from d4planner.character.current_view import current_view


def layouts():
    # Provider-mapped synthetic catalog, deliberately not a class inferred from a name.
    return {'schemaVersion':'d4planner-equipment-layout/v1', 'status':'READY', 'classes':[
        {'className':'Rogue', 'slots':[
            {'slotFamily':'ranged','itemTypes':['Bow','Crossbow']},
            {'slotFamily':'main_hand','itemTypes':['Dagger','Sword']},
            {'slotFamily':'off_hand','itemTypes':['Dagger','Sword']}]},
        {'className':'Sorcerer', 'slots':[
            {'slotFamily':'main_hand','itemTypes':['Wand','Staff','Dagger']},
            {'slotFamily':'off_hand','itemTypes':['Focus']}]},
    ]}


def feed(p, lines, session='s'):
    checkpoint = p.repository.checkpoint()
    start = checkpoint[1]+1 if checkpoint and checkpoint[0] == session else 1
    for seq,text in enumerate(lines,start):
        p.consume({'type':'speech.raw','sessionId':session,'eventSeq':seq,
                   'timestamp':f'2026-11-21T03:00:{seq%60:02d}Z','data':{'text':text}})


def tooltip(slot, name, kind, terminal='Unequip'):
    return [slot,'Slot Transmog: ON','EQUIPPED',name,kind,'900 Item Power',terminal]


def header(name):
    return ['CHARACTER','Left shoulder button','Right shoulder button',name,'No Title Selected','Weapon Damage']


def setup(tmp_path):
    repo=EquipmentRepository(tmp_path/'character.db');p=EquipmentProjector(repo);p.equipment_layouts=layouts()
    return repo,p


def view(repo):
    result=ReadOnlyEquipmentRepository(repo.path).projection_snapshot()
    return current_view(result.rows,result.revision[0],result.layout)


def test_ranged_and_two_daggers_have_independent_slots_and_stash_cannot_replace(tmp_path):
    repo,p=setup(tmp_path)
    feed(p,header('Example One')+tooltip('Feet','Example Boots','Rare Boots')+
         tooltip('Ranged','Example Bow','Ancestral Legendary Bow')+
         tooltip('Off-Hand','Example Offhand','Unique Dagger')+
         tooltip('Main Hand','Example Mainhand','Ancestral Legendary Dagger'))
    feed(p,['Stash','CHEST 5','Example Crossbow','Ancestral Rare Crossbow','900 Item Power','Take'])
    result=view(repo)
    assert {x['slotFamily']:x['name'] for x in result['items']} == {
        'boots':'Example Boots','ranged':'Example Bow','off_hand':'Example Offhand','main_hand':'Example Mainhand'}
    assert result['layout']['status']=='VERIFIED'
    assert result['layout']['slots'][5:8]==['ranged','main_hand','off_hand']
    assert result['identity']=='UNVERIFIED'
    # Same-session restart retains verified topology, no live capture required.
    restarted=EquipmentProjector(EquipmentRepository(repo.path));restarted.equipment_layouts=layouts()
    assert view(restarted.repository)==result
    feed(restarted,tooltip('Ranged','Replacement Crossbow','Ancestral Rare Crossbow'))
    assert {x['slotFamily'] for x in view(repo)['items']}=={'boots','ranged','main_hand','off_hand'}


def test_anchor_only_fix_cannot_write_bow_into_boots(tmp_path):
    repo,p=setup(tmp_path)
    feed(p,tooltip('Feet','Example Boots','Rare Boots'))
    # Missing/unsupported slot label cannot inherit a compatible equipped item.
    feed(p,['Unrecognized Slot','EQUIPPED','Example Bow','Legendary Bow','900 Item Power','Unequip'])
    assert [(x['slotFamily'],x['name']) for x in repo.list_equipment()]==[('boots','Example Boots')]


def test_switch_character_reidentifies_layout_without_old_equipment(tmp_path):
    repo,p=setup(tmp_path)
    feed(p,header('First')+tooltip('Ranged','Bow','Rare Bow')+tooltip('Main Hand','Dagger','Rare Dagger'))
    feed(p,header('Second'))
    assert view(repo)['items']==[]
    assert view(repo)['layout']['status']=='UNKNOWN'
    feed(p,tooltip('Two-Handed','Staff','Rare Staff'))
    result=view(repo)
    assert [x['name'] for x in result['items']]==['Staff']
    assert 'ranged' not in result['layout']['slots']
    assert result['layout']['status']=='VERIFIED'
    feed(p,header('First')+tooltip('Ranged','Bow','Rare Bow'))
    assert [x['name'] for x in view(repo)['items']]==['Bow']
    assert 'ranged' in view(repo)['layout']['slots']
    # Original rows still exist, but are never displayed as the new context.
    import sqlite3
    with sqlite3.connect(repo.path) as db:
        assert db.execute('select count(*) from equipment_current').fetchone()[0]>1


def test_session_change_discards_layout_and_item_view_and_resets_pending_tooltip(tmp_path):
    repo,p=setup(tmp_path)
    feed(p,tooltip('Ranged','Bow','Rare Bow')+['Main Hand','EQUIPPED','Partial','Rare Dagger','900 Item Power'])
    feed(p,['Unequip'],session='new')
    assert view(repo)['items']==[]
    assert view(repo)['layout']['status']=='UNKNOWN'
    feed(p,tooltip('Main Hand','Wand','Rare Wand'),session='new')
    assert [x['name'] for x in view(repo)['items']]==['Wand']
    assert 'ranged' not in view(repo)['layout']['slots']


def test_ambiguous_dagger_does_not_claim_class_or_three_slot_layout(tmp_path):
    repo,p=setup(tmp_path);feed(p,tooltip('Main Hand','Dagger','Rare Dagger'))
    assert view(repo)['layout']['status']=='OBSERVED'
    assert 'ranged' not in view(repo)['layout']['slots']
    feed(p,tooltip('Off-Hand','Other Dagger','Rare Dagger'))
    assert view(repo)['layout']['status']=='VERIFIED'
    assert 'ranged' in view(repo)['layout']['slots']


def test_unavailable_catalog_is_observed_not_verified(tmp_path):
    repo,p=setup(tmp_path);p.equipment_layouts=None
    feed(p,tooltip('Ranged','Bow','Rare Bow'))
    assert view(repo)['layout']['status']=='OBSERVED'
    p.equipment_layouts=layouts();feed(p,['blank'])
    assert view(repo)['layout']['status']=='VERIFIED'
    p.equipment_layouts=None;feed(p,['blank'])
    assert view(repo)['layout']['status']=='OBSERVED'


def test_ranged_unequip_does_not_clear_melee(tmp_path):
    repo,p=setup(tmp_path)
    feed(p,tooltip('Main Hand','Dagger','Rare Dagger')+tooltip('Off-Hand','Other Dagger','Rare Dagger')+
         tooltip('Ranged','Bow','Rare Bow')+['Ranged'])
    assert {x['slotFamily'] for x in view(repo)['items']}=={'main_hand','off_hand'}


def test_hud_schema_accepts_additive_layout_and_rejects_invalid_slots(tmp_path):
    import jsonschema
    schema=json.loads((Path(__file__).parents[1]/'contracts/release1/v1/schemas/hud.schema.json').read_text())
    layout_schema=schema['properties']['currentEquipment']['properties']['layout']
    jsonschema.validate({'status':'VERIFIED','slots':['ranged','main_hand','off_hand']},layout_schema)
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate({'status':'VERIFIED','slots':['invented']},layout_schema)
