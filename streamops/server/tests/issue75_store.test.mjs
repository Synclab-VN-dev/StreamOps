import test from 'node:test';
import assert from 'node:assert/strict';
import {PluginStore} from '../web/obs-plugins/transport.mjs';

class FakeWs {
  constructor() {
    this.connected = true;
    this.status = 'UNMANAGED';
    this.calls = [];
    this.failMutation = false;
    this.listeners = new Map();
  }
  onState(callback, options) {
    if (options?.replay) queueMicrotask(() => callback({state:'connected'}));
    return () => {};
  }
  on(event,callback) {
    this.listeners.set(event,callback);
    return () => this.listeners.delete(event);
  }
  start() {}
  destroy() {}
  request(operation,payload) {
    this.calls.push({operation,payload});
    let promise;
    if (operation === 'obs_plugin.inventory') promise = Promise.resolve({
      plugins:[{plugin_id:'obs-multi-rtmp',display_name:'Multiple RTMP Outputs',
        state:this.status,installed:true,managed:this.status !== 'UNMANAGED',
        adoptable:this.status === 'UNMANAGED',compatible:true}]
    });
    else if (operation === 'obs_plugin.available') promise = Promise.resolve({
      plugins:[],source_state:'EMPTY'
    });
    else if (operation === 'obs_plugin.adopt' && this.failMutation) {
      promise = Promise.reject(new Error('Connection lost while applying adoption.'));
    } else if (operation === 'obs_plugin.adopt') {
      this.status = 'LEGACY_ADOPTED';
      promise = Promise.resolve({operation:'adopt',result:'adopted',state:'LEGACY_ADOPTED'});
    } else throw new Error('Unexpected ' + operation);
    promise.requestId = 'mock-request-' + this.calls.length;
    return promise;
  }
}
const fakeObs = () => ({
  connected:true,
  on() {return () => {};},
  onState() {return () => {};},
  request() {throw Error('OBS lifecycle must not be called for Adopt');}
});
async function readyStore() {
  const client = new FakeWs();
  const store = new PluginStore({client,obsClient:fakeObs()});
  store.runtime = {state:'STOPPED',streaming:false,recording:false,websocket:false};
  store.start();
  await new Promise(resolve => setImmediate(resolve));
  return {client,store};
}
test('independent mock WS inventory/catalog renders only registry and adoption operation tracks id', async () => {
  const {client,store} = await readyStore();
  assert.equal(store.error,null);
  assert.equal(store.inventory.length,1);
  assert.equal(store.inventory[0].state,'UNMANAGED');
  assert.equal(store.catalog.size,0);
  await store.execute('adopt','obs-multi-rtmp');
  const calls = client.calls.filter(call => call.operation === 'obs_plugin.adopt');
  assert.equal(calls.length,1);
  assert.deepEqual(calls[0].payload,{plugin_id:'obs-multi-rtmp'});
  assert.equal(store.inventory[0].state,'LEGACY_ADOPTED');
  assert.equal(store.activity[0].request_id,calls.length ? 'mock-request-3' : null);
  assert.equal(store.activity[1].result,'adopted');
  assert.equal(client.calls.filter(call => call.operation === 'obs.lifecycle.stop').length,0);
  store.destroy();
});
test('unknown outcome blocks further mutation even after status refresh, until BE reconciliation exists', async () => {
  const {client,store} = await readyStore();
  client.failMutation = true;
  await assert.rejects(() => store.execute('adopt','obs-multi-rtmp'));
  assert.equal(store.unknownOutcome,true);
  await store.refresh();
  assert.equal(store.unknownOutcome,true);
  await assert.rejects(() => store.execute('adopt','obs-multi-rtmp'),/Operation blocked/);
  assert.equal(client.calls.filter(call=>call.operation==='obs_plugin.adopt').length,1);
  store.destroy();
});
