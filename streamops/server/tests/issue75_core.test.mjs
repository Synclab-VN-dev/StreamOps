import test from 'node:test';
import assert from 'node:assert/strict';
import {parseInventory, parseCatalog, summary, safeActions, typedError, runtimeFromSnapshot, stateLabel} from '../web/obs-plugins/core.mjs';
const unmanaged = {plugin_id:'obs-multi-rtmp',state:'UNMANAGED',installed:true,managed:false,adoptable:true,compatible:true};
const stopped = {state:'STOPPED',streaming:false,recording:false,websocket:false};
const ready = {state:'READY',streaming:false,recording:false,websocket:true};
const approved = {installable:true,compatibility:'compatible',available_version:'0.7.4.3'};
test('inventory validates allowlisted identities and unknown states fail closed', () => {
  const inv = parseInventory({plugins:[unmanaged,{plugin_id:'future',state:'SOMETHING_NEW'}]});
  assert.equal(inv[1].state,'UNKNOWN');
  assert.equal(inv[0].managed,false);
  assert.throws(() => parseInventory({plugins:[unmanaged,unmanaged]}), /duplicate/);
  assert.throws(() => parseInventory({plugins:null}), /Invalid/);
});
test('Adopt requires explicit legacy eligibility and stopped OBS, no auto stop', () => {
  const plugin = parseInventory({plugins:[unmanaged]}).at(0);
  assert.equal(safeActions(plugin,null,stopped,true).adopt.enabled,true);
  assert.equal(safeActions(plugin,null,ready,true).adopt.enabled,false);
  assert.equal(safeActions(plugin,null,{...stopped,recording:true},true).adopt.enabled,false);
  assert.equal(safeActions(plugin,null,{...stopped,streaming:undefined},true).adopt.enabled,false);
  assert.equal(safeActions(plugin,null,stopped,false).adopt.enabled,false);
  assert.equal(safeActions({...plugin,adoptable:false},null,stopped,true).adopt.enabled,false);
  assert.equal(safeActions({...plugin,state:'LEGACY_ADOPTED'},null,stopped,true).adopt.enabled,false);
});
test('Adopted legacy baseline is not verified; install requires approved release', () => {
  const legacy = parseInventory({plugins:[{...unmanaged,state:'LEGACY_ADOPTED',managed:true,adoptable:false}]}).at(0);
  assert.equal(legacy.installed_version,null);
  assert.equal(safeActions(legacy,null,stopped,true).install.enabled,false);
  assert.equal(safeActions(legacy,approved,stopped,true).install.enabled,true);
  assert.equal(safeActions(legacy,approved,stopped,true).verify.enabled,false);
  assert.equal(stateLabel(legacy.state),'Legacy baseline adopted');
});
test('No synthetic rollback baseline, even if installed and managed', () => {
  const plugin = parseInventory({plugins:[{...unmanaged,state:'VERIFIED',managed:true}]}).at(0);
  assert.equal(safeActions(plugin,approved,ready,true).rollback.enabled,false);
  assert.equal(safeActions({...plugin,rollback_available:true},approved,ready,true).rollback.enabled,true);
});
test('update and install remain distinct and safe', () => {
  const normal = {...unmanaged,state:'NOT_INSTALLED',installed:false};
  assert.equal(safeActions(normal,approved,stopped,true).install.enabled,true);
  assert.equal(safeActions(normal,approved,stopped,true).update.enabled,false);
  const update = {...unmanaged,state:'UPDATE_AVAILABLE'};
  assert.equal(safeActions(update,approved,ready,true).update.enabled,true);
  assert.equal(safeActions(update,approved,{...ready,streaming:true},true).update.enabled,false);
});
test('catalog errors and source state are explicit', () => {
  const catalog = parseCatalog({plugins:[],source_state:'EMPTY'});
  assert.equal(catalog.entries.size,0);
  assert.equal(catalog.sourceState,'EMPTY');
  assert.throws(() => parseCatalog({plugins:[{plugin_id:'x'},{plugin_id:'x'}]}), /duplicate/);
});
test('summary counts distinct attention, not each reason or uninstalled', () => {
  const inventory = parseInventory({plugins:[
    {...unmanaged,state:'NOT_INSTALLED',installed:false,adoptable:false},
    {...unmanaged,plugin_id:'b',state:'UPDATE_AVAILABLE',restart_required:true},
    {...unmanaged,plugin_id:'c',state:'RECOVERY_REQUIRED'}
  ]});
  assert.deepEqual(summary(inventory),{managed:3,installed:2,attention:2});
});
test('unknown output and unknown result are fail closed', () => {
  assert.equal(safeActions(unmanaged,null,{state:'STOPPED'},true).adopt.enabled,false);
  assert.equal(typedError({code:'plugin_adopt_requires_obs_stopped'}).outcomeUnknown,false);
  assert.equal(typedError({message:'socket closed'}).outcomeUnknown,true);
  assert.equal(runtimeFromSnapshot({runtime:{state:'READY',output:{streaming:false,recording:false},websocket:{connected:true}}}).websocket,true);
});
