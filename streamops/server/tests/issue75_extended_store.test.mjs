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
