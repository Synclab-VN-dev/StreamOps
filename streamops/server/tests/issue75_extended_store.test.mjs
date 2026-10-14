// #75 transport fault-injection gates against the actual shared WS domain adapter.
// This is a deterministic mock with response envelope-compatible semantics.
import test from 'node:test';
import assert from 'node:assert/strict';
import {PluginStore} from '../web/obs-plugins/transport.mjs';

const deferred=()=>{
  let resolve,reject;
  const promise=new Promise((res,rej)=>{resolve=res;reject=rej;});
  return {promise,resolve,reject};
};
class FakePluginWS {
  constructor({state='UNMANAGED',release=null,revision=10}={}){
    this.connected=true; this.state=state;this.release=release;this.revision=revision;
    this.calls=[];this.byEvent=new Map();this.byState=new Set();
    this.mutationWait=null;this.mutationFailure=null;
    this.operationResult={state:'IDLE',operation_id:null};
    this.destroyed=false;
  }
  onState(fn,{replay=false}={}){
    this.byState.add(fn);
    if(replay)queueMicrotask(()=>fn({state:this.connected?'connected':'disconnected'}));
    return ()=>this.byState.delete(fn);
  }
  on(evt,fn){
    if(!this.byEvent.has(evt))this.byEvent.set(evt,new Set());
    this.byEvent.get(evt).add(fn);
    return ()=>this.byEvent.get(evt)?.delete(fn);
  }
  start(){}
  destroy(){this.destroyed=true;this.byState.clear();this.byEvent.clear();}
  transition(connected){
    this.connected=connected;
    for(const fn of this.byState)fn({state:connected?'connected':'disconnected'});
  }
  notify(revision){
    for(const fn of this.byEvent.get('obs_plugin.changed')||[])fn({
      plugin_id:'obs-multi-rtmp',revision,resources:['status','operation']
    });
  }
  status(){
    return {plugin_id:'obs-multi-rtmp',state:this.state,
      installed:this.state!=='NOT_INSTALLED',managed:!['UNMANAGED','NOT_INSTALLED'].includes(this.state),
      adoptable:this.state==='UNMANAGED',compatible:true,loaded:false,
      installed_version:this.state==='LEGACY_ADOPTED'?null:'1.0',
      revision:this.revision,operation:this.operationResult,
      rollback:{available:false,reason:'not_verified'}};
  }
  request(operation,payload={}){
    const id='request-'+(this.calls.length+1);
    this.calls.push({operation,payload,id});
    let value;
    if(operation==='obs_plugin.inventory')value=Promise.resolve({plugins:[this.status()]});
    else if(operation==='obs_plugin.available')value=Promise.resolve({plugins:this.release?[{
      plugin_id:'obs-multi-rtmp',...this.release
    }]:[],source_state:this.release?'READY':'EMPTY'});
    else if(operation==='obs_plugin.subscribe')value=Promise.resolve({
      plugin_id:payload.plugin_id,subscribed:true,revision:this.revision
    });
    else if(operation==='obs_plugin.operation_status')value=Promise.resolve({
      plugin_id:payload.plugin_id,revision:this.revision,
      operation:this.operationResult,plugin_state:this.state,
      recovery_required:this.state==='RECOVERY_REQUIRED',
      rollback:{available:false,reason:'not_verified'}
    });
    else if(/^obs_plugin\.(adopt|install|update|verify|rollback)$/.test(operation)){
      if(this.mutationWait){
        value=this.mutationWait.promise;
      }else if(this.mutationFailure){
        value=Promise.reject(this.mutationFailure);
      }else{
        const kind=operation.split('.')[1];
        this.state=kind==='adopt'?'LEGACY_ADOPTED':kind==='install'?'INSTALLED':kind==='update'?'VERIFIED':kind==='rollback'?'INSTALLED':this.state;
        this.revision++;
        this.operationResult={state:'SUCCEEDED',operation:kind,operation_id:'op-id-1'};
        value=Promise.resolve({operation:kind,result:kind==='adopt'?'adopted':'completed',state:this.state});
      }
    }else throw new Error('Unexpected request '+operation);
    value.requestId=id;
    return value;
  }
}
class FakeObs {
  constructor(){
    this.connected=true;this.restarts=0;this.failure=null;this.events=new Map();
  }
  on(event,fn,{replay=false}={}){
    if(!this.events.has(event))this.events.set(event,new Set());
    this.events.get(event).add(fn);
    if(replay&&event==='obs.snapshot')queueMicrotask(()=>fn({runtime:{
      state:'STOPPED',output:{streaming:false,recording:false},websocket:{connected:false}
    }}));
    return ()=>this.events.get(event)?.delete(fn);
  }
  onState(fn){return ()=>{};}
  request(op,payload){
    assert.equal(op,'obs.lifecycle.restart');
    assert.deepEqual(payload,{});
    this.restarts++;
    if(this.failure)return Promise.reject(this.failure);
    return Promise.resolve({state:'READY'});
  }
}
async function until(predicate,label){
  for(let i=0;i<100;i++){
    if(predicate())return;
    await new Promise(resolve=>setImmediate(resolve));
  }
  throw new Error('Missing expected transition '+label);
}
async function ready(options={}){
  const ws=new FakePluginWS(options);const obs=new FakeObs();
  const store=new PluginStore({client:ws,obsClient:obs});
  store.start();
  await until(()=>store.inventory.length===1&&store.observerReady&&!store.refreshInFlight,'initial subscription');
  return {ws,obs,store};
}
const count=(ws,operation)=>ws.calls.filter(x=>x.operation===operation).length;

test('UNIT WS: on reconnect subscribe anew and refresh only via WS',async()=>{
  const {ws,store}=await ready();
  assert.equal(count(ws,'obs_plugin.subscribe'),1);
  ws.transition(false);
  assert.equal(store.connected,false);
  assert.equal(store.observerReady,false);
  ws.transition(true);
  await until(()=>count(ws,'obs_plugin.subscribe')===2&&store.observerReady,'resubscribe');
  assert.equal(store.error,null);
  assert.equal(count(ws,'obs_plugin.inventory')>=2,true);
  store.destroy();
});
test('UNIT WS: lower/same revision invalidation never starts new read',async()=>{
  const {ws,store}=await ready();
  ws.notify(30);
  await until(()=>store.lastSeenRevision===30&&!store.refreshInFlight,'revision 30');
  const baseline=count(ws,'obs_plugin.inventory');
  ws.notify(29);ws.notify(30);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(count(ws,'obs_plugin.inventory'),baseline);
  store.destroy();
});
test('UNIT WS: no unregistered plugin ID, release source URL or custom operation may be submitted',async()=>{
  const {ws,store}=await ready({state:'NOT_INSTALLED',release:{
    available_version:'1.1',installable:true,compatibility:'compatible'
  }});
  await assert.rejects(()=>store.execute('install','unregistered-plugin'),/registry/);
  await assert.rejects(()=>store.execute('install:https://bad.invalid','obs-multi-rtmp'),/Unsupported/);
  await store.execute('install','obs-multi-rtmp');
  const req=ws.calls.find(x=>x.operation==='obs_plugin.install');
  assert.deepEqual(req.payload,{plugin_id:'obs-multi-rtmp'});
  assert.equal(JSON.stringify(req).includes('bad.invalid'),false);
  store.destroy();
});
test('UNIT WS: concurrent duplicate clicks are rejected before a second mutation',async()=>{
  const {ws,store}=await ready();
  const pending=deferred();ws.mutationWait=pending;
  const active=store.execute('adopt','obs-multi-rtmp');
  await until(()=>count(ws,'obs_plugin.adopt')===1,'first adopt');
  assert.equal(store.busy,true);
  await assert.rejects(()=>store.execute('adopt','obs-multi-rtmp'),/blocked/i);
  assert.equal(count(ws,'obs_plugin.adopt'),1);
  ws.state='LEGACY_ADOPTED';
  pending.resolve({operation:'adopt',state:'LEGACY_ADOPTED',result:'adopted'});
  await active;
  assert.equal(store.busy,false);
  assert.equal(store.unknownOutcome,false);
  assert.equal(store.inventory[0].state,'LEGACY_ADOPTED');
  store.destroy();
});
test('UNIT WS: vendor verification failure never becomes verified after read-only reconcile',async()=>{
  const {ws,store}=await ready({state:'INSTALLED'});
  store.runtime={state:'READY',streaming:false,recording:false,websocket:true};
  const error=new Error('vendor probe unavailable');error.code='plugin_verify_failed';
  ws.mutationFailure=error;
  const request=ws.request.bind(ws);
  ws.request=(operation,payload)=>{
    if(operation==='obs_plugin.verify'){
      ws.state='VERIFY_FAILED';ws.revision++;
      ws.operationResult={state:'FAILED',operation:'verify',operation_id:'failed-probe'};
    }
    return request(operation,payload);
  };
  await assert.rejects(()=>store.execute('verify','obs-multi-rtmp'),e=>e.code==='plugin_verify_failed');
  assert.equal(store.inventory[0].state,'VERIFY_FAILED');
  assert.equal(store.activity.some(e=>e.operation==='verify'&&e.result==='failed'),true);
  assert.equal(store.activity.some(e=>e.operation==='verify'&&e.result==='completed'),false);
  assert.equal(count(ws,'obs_plugin.verify'),1);
  store.destroy();
});
test('UNIT WS: backend auto-restoration cannot turn a failed update into success',async()=>{
  const {ws,store}=await ready({state:'UPDATE_AVAILABLE',release:{
    available_version:'2.0',installable:true,compatibility:'compatible'
  }});
  const error=new Error('backend restored previous baseline');error.code='plugin_update_failed';
  ws.mutationFailure=error;
  const request=ws.request.bind(ws);
  ws.request=(operation,payload)=>{
    if(operation==='obs_plugin.update'){
      ws.state='INSTALLED';ws.revision++;
      ws.operationResult={state:'FAILED',operation:'update',operation_id:'failed-update'};
    }
    return request(operation,payload);
  };
  await assert.rejects(()=>store.execute('update','obs-multi-rtmp'),e=>e.code==='plugin_update_failed');
  assert.equal(store.inventory[0].state,'INSTALLED','restored does not mean update succeeded');
  assert.equal(store.activity.some(e=>e.operation==='update'&&e.result==='failed'),true);
  assert.equal(store.activity.some(e=>e.operation==='update'&&e.result==='completed'),false);
  assert.equal(count(ws,'obs_plugin.update'),1);
  assert.equal(count(ws,'obs_plugin.rollback'),0,'FE must not double-trigger BE auto rollback');
  store.destroy();
});
test('UNIT WS: typed backend conflict reports failure, not an unknown result or auto retry',async()=>{
  const {ws,store}=await ready();
  const err=new Error('Conflict');err.code='plugin_state_conflict';
  ws.mutationFailure=err;
  await assert.rejects(()=>store.execute('adopt','obs-multi-rtmp'),e=>e.code==='plugin_state_conflict');
  assert.equal(store.unknownOutcome,false);
  assert.equal(store.activity.some(x=>x.result==='failed'&&x.error_code==='plugin_state_conflict'),true);
  assert.equal(count(ws,'obs_plugin.adopt'),1);
  store.destroy();
});
test('UNIT WS: disconnect/timeout is unknown; RUNNING operation cannot be retried',async()=>{
  const {ws,store}=await ready();
  ws.mutationFailure=new Error('Timeout while backend may still mutate.');
  await assert.rejects(()=>store.execute('adopt','obs-multi-rtmp'));
  assert.equal(store.unknownOutcome,true);
  ws.operationResult={state:'RUNNING',operation:'adopt',operation_id:'op-live'};
  await store.refresh();
  assert.equal(store.unknownOutcome,true);
  await assert.rejects(()=>store.execute('adopt','obs-multi-rtmp'),/blocked/i);
  assert.equal(count(ws,'obs_plugin.adopt'),1);
  assert.ok(count(ws,'obs_plugin.operation_status')>=1);
  store.destroy();
});
test('UNIT WS: confirmed post-baseline terminal operation reconciles without retry',async()=>{
  const {ws,store}=await ready();
  ws.mutationFailure=new Error('Connection closed');
  await assert.rejects(()=>store.execute('adopt','obs-multi-rtmp'));
  assert.equal(store.unknownOutcome,true);
  ws.mutationFailure=null;ws.state='LEGACY_ADOPTED';ws.revision=11;
  ws.operationResult={state:'SUCCEEDED',operation:'adopt',operation_id:'durable-operation-id'};
  await store.refresh();
  assert.equal(store.unknownOutcome,false);
  assert.equal(store.inventory[0].state,'LEGACY_ADOPTED');
  assert.equal(count(ws,'obs_plugin.adopt'),1);
  assert.ok(store.activity.some(x=>x.result==='reconciled-succeeded'));
  store.destroy();
});
test('UNIT WS: revision no higher than baseline cannot clear unknown result',async()=>{
  const {ws,store}=await ready();
  ws.mutationFailure=new Error('network');
  await assert.rejects(()=>store.execute('adopt','obs-multi-rtmp'));
  ws.operationResult={state:'SUCCEEDED',operation:'adopt',operation_id:'old-id'};
  ws.revision=10;
  await store.refresh();
  assert.equal(store.unknownOutcome,true);
  assert.equal(count(ws,'obs_plugin.adopt'),1);
  store.destroy();
});
test('UNIT WS: RECOVERY_REQUIRED is fail-closed and does not invent success',async()=>{
  const {ws,store}=await ready();
  ws.mutationFailure=new Error('network');
  await assert.rejects(()=>store.execute('adopt','obs-multi-rtmp'));
  ws.state='RECOVERY_REQUIRED';
  ws.revision++;
  ws.operationResult={state:'FAILED',operation:'adopt',operation_id:'op-failed'};
  await store.refresh();
  assert.equal(store.unknownOutcome,false);
  assert.equal(store.inventory[0].state,'RECOVERY_REQUIRED');
  await assert.rejects(()=>store.execute('adopt','obs-multi-rtmp'));
  assert.equal(count(ws,'obs_plugin.adopt'),1);
  store.destroy();
});
test('UNIT WS: OBS restart is a separate explicit operation; its response does not verify plugin',async()=>{
  const {ws,obs,store}=await ready({state:'RESTART_REQUIRED'});
  await store.restart();
  assert.equal(obs.restarts,1);
  assert.equal(store.inventory[0].state,'RESTART_REQUIRED');
  assert.equal(count(ws,'obs_plugin.verify'),0);
  assert.equal(store.activity.some(x=>x.operation==='obs.lifecycle.restart'&&x.result==='completed'),true);
  store.destroy();
});
test('UNIT WS: a typed rejected restart is FAILED, never an unconfirmed restart',async()=>{
  const {ws,obs,store}=await ready({state:'RESTART_REQUIRED'});
  const error=new Error('OBS streaming guard');error.code='obs_busy_streaming';
  obs.failure=error;
  await assert.rejects(()=>store.restart(),e=>e.code==='obs_busy_streaming');
  assert.equal(store.unknownOutcome,false);
  assert.equal(store.pendingMutation,null);
  assert.equal(obs.restarts,1);
  assert.equal(store.activity.some(e=>e.operation==='obs.lifecycle.restart'
    && e.result==='failed'&&e.error_code==='obs_busy_streaming'),true);
  assert.equal(store.activity.some(e=>e.operation==='obs.lifecycle.restart'&&e.result==='completed'),false);
  assert.equal(store.inventory[0].state,'RESTART_REQUIRED');
  assert.equal(count(ws,'obs_plugin.verify'),0);
  store.destroy();
});
test('UNIT WS: ambiguous OBS restart failure stays fail-closed',async()=>{
  const {obs,store}=await ready();
  obs.failure=new Error('Socket dropped during restart');
  await assert.rejects(()=>store.restart());
  assert.equal(store.unknownOutcome,true);
  assert.equal(obs.restarts,1);
  store.destroy();
});
test('UNIT WS: destroy releases observers and closes plugin WS',async()=>{
  const {ws,store}=await ready();
  assert.equal(ws.byState.size,1);
  assert.ok(ws.byEvent.get('obs_plugin.changed').size>0);
  store.destroy();
  assert.equal(ws.destroyed,true);
  assert.equal(ws.byState.size,0);
  assert.equal(ws.byEvent.size,0);
});


test('UNIT Adopt typed-error matrix: denied/recovery/timeout never falls back to Install or duplicates mutation',async()=>{
  // Explicitly cover BE's guard codes at the WS boundary. A typed rejection is
  // definitive; timeout is uncertain and must remain blocked for reconciliation.
  const codes=[
    'plugin_adopt_requires_obs_stopped',
    'plugin_adoption_required',
    'plugin_not_installed',
    'obs_busy_streaming',
    'obs_busy_recording',
    'plugin_state_conflict',
    'plugin_recovery_required',
    'plugin_adopt_failed',
    'plugin_operation_timeout'
  ];
  for(const code of codes){
    const {ws,store}=await ready();
    const error=new Error('server rejected or timed out');error.code=code;
    ws.mutationFailure=error;
    await assert.rejects(()=>store.execute('adopt','obs-multi-rtmp'),e=>e.code===code,code);
    assert.equal(store.inventory[0].state,'UNMANAGED',code);
    assert.equal(store.activity.filter(e=>e.operation==='adopt'&&e.result==='completed').length,0,code);
    assert.equal(store.activity.filter(e=>e.operation==='adopt'&&e.result==='adopted').length,0,code);
    assert.equal(count(ws,'obs_plugin.adopt'),1,code);
    assert.equal(count(ws,'obs_plugin.install'),0,code);
    assert.equal(store.unknownOutcome,code==='plugin_operation_timeout',code);
    assert.equal(store.activity.some(e=>e.operation==='adopt'&&e.error_code===code
      &&e.result===(code==='plugin_operation_timeout'?'unknown':'failed')),true,code);
    store.destroy();
  }
});

test('UNIT OBS restart: expected transient plugin WS reconnect stays pending until explicit restart ack',async()=>{
  const {ws,obs,store}=await ready({state:'RESTART_REQUIRED'});
  const gate=deferred();
  obs.request=(operation,payload)=>{
    assert.equal(operation,'obs.lifecycle.restart');
    assert.deepEqual(payload,{});
    obs.restarts++;
    return gate.promise;
  };
  const task=store.restart();
  await until(()=>store.busy&&obs.restarts===1,'restart dispatched');
  ws.transition(false);
  assert.equal(store.connected,false);
  assert.equal(store.unknownOutcome,true,'transient disconnect during mutation must be fail closed');
  ws.transition(true);
  await until(()=>store.observerReady&&!store.refreshInFlight,'fresh inventory after reconnect');
  assert.equal(store.activity.some(e=>e.operation==='obs.lifecycle.restart'&&e.result==='completed'),false);
  assert.equal(store.inventory[0].state,'RESTART_REQUIRED','reconnect is not plugin verification');
  gate.resolve({state:'READY'});
  await task;
  assert.equal(store.unknownOutcome,false,'explicit lifecycle response closes pending restart');
  assert.equal(store.activity.filter(e=>e.operation==='obs.lifecycle.restart'&&e.result==='completed').length,1);
  assert.equal(count(ws,'obs_plugin.verify'),0);
  store.destroy();
});

test('UNIT OBS reconnect: unexpected plugin WS disconnection during Adopt remains UNKNOWN, never retries',async()=>{
  const {ws,store}=await ready();
  const gate=deferred();
  ws.mutationWait=gate;
  const task=store.execute('adopt','obs-multi-rtmp');
  await until(()=>count(ws,'obs_plugin.adopt')===1,'Adopt dispatched');
  ws.operationResult={state:'RUNNING',operation:'adopt',operation_id:'unknown-running'};
  ws.transition(false);
  gate.reject(new Error('Unexpected socket closure'));
  await assert.rejects(task);
  assert.equal(store.unknownOutcome,true);
  ws.transition(true);
  await until(()=>store.observerReady&&!store.refreshInFlight,'read only reconnect');
  assert.equal(store.unknownOutcome,true,'backend RUNNING is not terminal');
  await assert.rejects(()=>store.execute('adopt','obs-multi-rtmp'),/blocked/i);
  assert.equal(count(ws,'obs_plugin.adopt'),1,'no duplicate Adopt');
  assert.equal(count(ws,'obs_plugin.install'),0,'no alternate fallback mutation');
  assert.ok(count(ws,'obs_plugin.operation_status')>=1);
  store.destroy();
});
