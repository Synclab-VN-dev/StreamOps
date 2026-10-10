// #75 state-matrix regression tests. All expectations are product behaviour,
// not snapshot snapshots or acceptance shortcuts.
import test from 'node:test';
import assert from 'node:assert/strict';
import {parseInventory,parseCatalog,summary,safeActions,typedError,shouldOfferInstall,stateLabel,runtimeFromSnapshot} from '../web/obs-plugins/core.mjs';

const obs = (state='STOPPED', streaming=false, recording=false) =>
  ({state,streaming,recording,websocket:state==='READY'});
const catalog = {plugin_id:'obs-multi-rtmp',installable:true,compatibility:'compatible',available_version:'9.1'};
const item = (state, overrides={}) => ({
  plugin_id:'obs-multi-rtmp',state,installed:state!=='NOT_INSTALLED',
  managed:!['NOT_INSTALLED','UNMANAGED'].includes(state),
  adoptable:state==='UNMANAGED',compatible:true,revision:12, ...overrides
});
const plugin = (state, overrides={}) => parseInventory({plugins:[item(state,overrides)]})[0];
const enabled = (p,release=catalog,runtime=obs(),connected=true,busy=false) =>
  safeActions(p,release,runtime,connected,busy);

test('UNIT matrix: registry rejects duplicate and malformed identities, unknown is never actionable',()=>{
  for(const input of [null,{}, {plugins:null},{plugins:{}},{plugins:[null]},{plugins:[{plugin_id:''}]},
    {plugins:[{plugin_id:'x'},{plugin_id:'x'}]}]) {
    assert.throws(()=>parseInventory(input));
  }
  const future=plugin('FUTURE_STATE');
  assert.equal(future.state,'UNKNOWN');
  for(const value of Object.values(enabled(future))) assert.equal(value.enabled,false);
});
test('UNIT matrix: nullable versions and explicit rolled-back eligibility survive parser',()=>{
  const old=plugin('LEGACY_ADOPTED',{installed_version:null,rollback:{available:false,reason:'not_verified'}});
  assert.equal(old.installed_version,null);
  assert.equal(old.rollback_reason,'not_verified');
  assert.equal(old.rollback_available,false);
  const valid=plugin('VERIFIED',{rollback:{available:true,target_version:'8.1'},operation:{state:'IDLE'}});
  assert.equal(valid.rollback_available,true);
  assert.equal(valid.revision,12);
  assert.equal(valid.operation.state,'IDLE');
  const invalid=plugin('VERIFIED',{revision:'12',rollback:null});
  assert.equal(invalid.revision,null);
  assert.equal(invalid.rollback_available,false);
});
test('UNIT matrix: cardinality and attention deduplicate state plus restart',()=>{
  const entries=parseInventory({plugins:[
    item('NOT_INSTALLED',{plugin_id:'a',installed:false}),
    item('RESTART_REQUIRED',{plugin_id:'b',restart_required:true}),
    item('FAILED',{plugin_id:'c',restart_required:true}),
    item('VERIFIED',{plugin_id:'d'})
  ]});
  assert.deepEqual(summary([]),{managed:0,installed:0,attention:0});
  assert.deepEqual(summary(entries),{managed:4,installed:3,attention:2});
});
test('UNIT matrix: approved catalog rejects duplicates and does not infer install rights',()=>{
  assert.throws(()=>parseCatalog({plugins:null}));
  assert.throws(()=>parseCatalog({plugins:[{},{}]}));
  const empty=parseCatalog({plugins:[],source_state:'UNCONFIGURED'});
  assert.equal(empty.entries.size,0);
  assert.equal(empty.sourceState,'UNCONFIGURED');
  const parsed=parseCatalog({plugins:[{plugin_id:'obs-multi-rtmp',installable:false,compatibility:'compatible'}]});
  assert.equal(parsed.entries.get('obs-multi-rtmp').installable,false);
  assert.equal(enabled(plugin('NOT_INSTALLED'),parsed.entries.get('obs-multi-rtmp')).install.enabled,false);
});
test('UNIT matrix: install and update are disjoint across states',()=>{
  for(const state of ['UNMANAGED','INSTALLED','VERIFIED','UPDATE_AVAILABLE','RECOVERY_REQUIRED']){
    assert.equal(enabled(plugin(state)).install.enabled,false,state);
  }
  for(const state of ['NOT_INSTALLED','LEGACY_ADOPTED']) {
    assert.equal(enabled(plugin(state)).install.enabled,true,state);
    assert.equal(enabled(plugin(state)).update.enabled,false,state);
  }
  assert.equal(enabled(plugin('UPDATE_AVAILABLE')).update.enabled,true);
  assert.equal(enabled(plugin('VERIFIED')).update.enabled,false);
});
test('UNIT matrix: incompatible and unavailable release fail closed for install and update',()=>{
  for(const release of [null,{}, {...catalog,compatibility:'incompatible'}, {...catalog,installable:false},
    {...catalog,available_version:null,installable:false}]) {
    assert.equal(enabled(plugin('NOT_INSTALLED'),release).install.enabled,false);
    assert.equal(enabled(plugin('UPDATE_AVAILABLE'),release).update.enabled,
      release?.installable===true && release?.compatibility==='compatible' && Boolean(release.available_version));
  }
  assert.equal(shouldOfferInstall(plugin('NOT_INSTALLED'),{...catalog,compatibility:'incompatible'}),false);
});
test('UNIT matrix: server rollback permission required, recovery blocks even when incorrectly advertised',()=>{
  for(const state of ['VERIFIED','INSTALLED','LEGACY_ADOPTED']) {
    assert.equal(enabled(plugin(state)).rollback.enabled,false,state);
  }
  const valid=plugin('VERIFIED',{rollback:{available:true}});
  assert.equal(enabled(valid,catalog,obs('READY')).rollback.enabled,true);
  assert.equal(enabled(plugin('RECOVERY_REQUIRED',{rollback:{available:true}})).rollback.enabled,false);
});
test('UNIT matrix: streaming recording unknown OBS status disable mutating operations',()=>{
  const p=plugin('LEGACY_ADOPTED');
  for(const runtime of [obs('READY',true),obs('READY',false,true),
    {state:'STOPPED',streaming:null,recording:false},null,{state:'CRASHED',streaming:false,recording:false}]) {
    assert.equal(enabled(p,catalog,runtime).install.enabled,false);
  }
  assert.equal(enabled(p,catalog,obs('STOPPED'),false).install.enabled,false);
  assert.equal(enabled(p,catalog,obs('STOPPED'),true,true).install.enabled,false);
});
test('UNIT matrix: Adopt requires STOPPED, allowlist membership, unmanaged files and idleness',()=>{
  const p=plugin('UNMANAGED');
  assert.equal(enabled(p,null,obs()).adopt.enabled,true);
  for(const runtime of [obs('READY'),obs('STOPPED',true),obs('STOPPED',false,true),null]){
    assert.equal(enabled(p,null,runtime).adopt.enabled,false);
  }
  for(const override of [{installed:false},{adoptable:false},{state:'LEGACY_ADOPTED'}]){
    assert.equal(enabled(plugin('UNMANAGED',override),null,obs()).adopt.enabled,false);
  }
});
test('UNIT matrix: verify and restart require ready+connected and no in-flight server operation',()=>{
  const normal=plugin('INSTALLED',{restart_required:true});
  assert.equal(enabled(normal,catalog,obs('READY')).verify.enabled,true);
  assert.equal(enabled(normal,catalog,obs('READY')).restart.enabled,true);
  for(const runtime of [obs('STOPPED'),obs('READY',true),obs('READY',false,true)]) {
    assert.equal(enabled(normal,catalog,runtime).restart.enabled,false);
  }
  assert.equal(enabled(normal,catalog,obs('STOPPED')).verify.enabled,false);
  assert.equal(enabled(normal,catalog,obs('READY'),false).verify.enabled,false);
  assert.equal(enabled(normal,catalog,obs('READY'),true,true).verify.enabled,false);
  const working=plugin('INSTALLED',{restart_required:true,operation:{state:'RUNNING'}});
  assert.equal(enabled(working,catalog,obs('READY')).restart.enabled,false);
  assert.equal(enabled(working,catalog,obs('READY')).verify.enabled,false);
});
test('UNIT matrix: operator-visible unknown/recovery results are not READY',()=>{
  assert.equal(stateLabel('RECOVERY_REQUIRED'),'Recovery required');
  assert.equal(stateLabel('LEGACY_ADOPTED'),'Legacy baseline adopted');
  assert.equal(stateLabel('VERIFY_FAILED'),'Verify failed');
  assert.equal(stateLabel('OTHER_UNKNOWN'),'Unknown');
  assert.equal(enabled(plugin('RECOVERY_REQUIRED'),catalog,obs('READY')).verify.enabled,false);
  assert.equal(enabled(plugin('UNMANAGED'),catalog,obs('READY')).verify.enabled,false);
});
test('UNIT matrix: no raw backend error, credential, release URL or token in typed operator hints',()=>{
  const injected='https://attacker.invalid/?stream_key=top-secret';
  for(const error of [{code:'unknown_outcome',message:injected},
    {code:'plugin_operation_timeout',message:injected},{code:'plugin_adoption_required',message:injected},
    {code:'plugin_state_conflict',message:injected}]){
    const ui=typedError(error);
    assert.ok(ui.message.length>12);
    assert.equal(ui.message.includes('top-secret'),false);
    assert.equal(ui.message.includes('attacker.invalid'),false);
  }
  assert.equal(typedError(new Error('socket closed')).outcomeUnknown,true);
  assert.equal(typedError({code:'plugin_state_conflict'}).outcomeUnknown,false);
});
test('UNIT matrix: OBS output status is unknown when telemetry is absent',()=>{
  assert.deepEqual(runtimeFromSnapshot({runtime:{state:'STOPPED'}}),{
    state:'STOPPED',streaming:undefined,recording:undefined,websocket:false
  });
  assert.equal(enabled(plugin('UNMANAGED'),null,runtimeFromSnapshot({runtime:{state:'STOPPED'}})).adopt.enabled,false);
});
