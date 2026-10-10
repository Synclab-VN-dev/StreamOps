// #75: all production plugin operations go over WebSocket. REST is contract-reference only.
// P0 BE GAP: 'obs_plugin.inventory' and 'obs_plugin.available' are proposed operation
// bindings, NOT implemented in PR #52. No fallback to REST or hard-coded inventory.
// P0 BE GAP: 'obs_plugin.changed' push notification/revision are not yet implemented.
import {parseInventory, parseCatalog, runtimeFromSnapshot} from './core.mjs';
export const PROPOSED_READ_OPERATIONS = Object.freeze({
  inventory:'obs_plugin.inventory', available:'obs_plugin.available'
});
const MUTATIONS = new Set(['adopt','install','update','verify','rollback']);
export class PluginStore {
  constructor({client, obsClient, onChange}) {
    this.client = client;
    this.obsClient = obsClient;
    this.onChange = onChange || (() => {});
    this.inventory = [];
    this.catalog = new Map();
    this.catalogSourceState = 'UNKNOWN';
    this.runtime = null;
    this.connected = false;
    this.loading = true;
    this.error = null;
    this.busy = false;
    this.unknownOutcome = false;
    this.activity = [];
    this.generation = 0;
    this.refreshInFlight = false;
    this.unsubscribers = [];
    this.knownOperations = new Set();
  }
  publish() {this.onChange(this);}
  log(record) {
    this.activity.push({at:new Date().toISOString(), ...record});
    this.activity = this.activity.slice(-80);
    this.publish();
  }
  start() {
    this.unsubscribers.push(this.client.onState(({state}) => {
      this.connected = state === 'connected';
      if (this.connected) this.refresh();
      else {
        this.generation++;
        if (this.busy) this.unknownOutcome = true;
        this.publish();
      }
    }, {replay:true}));
    this.unsubscribers.push(this.client.on('obs_plugin.changed', () => this.refresh()));
    this.unsubscribers.push(this.obsClient.on('obs.snapshot', data => {
      this.runtime = runtimeFromSnapshot(data); this.publish();
    }, {replay:true}));
    this.unsubscribers.push(this.obsClient.onState(({state}) => {
      if (state !== 'connected') {this.runtime = null; this.publish();}
    }, {replay:true}));
    this.client.start();
  }
  async refresh() {
    if (!this.connected || this.refreshInFlight) return;
    this.refreshInFlight = true;
    const generation = ++this.generation;
    this.loading = this.inventory.length === 0;
    this.error = null; this.publish();
    try {
      const [inventoryData, catalogData] = await Promise.all([
        this.client.request(PROPOSED_READ_OPERATIONS.inventory),
        this.client.request(PROPOSED_READ_OPERATIONS.available)
      ]);
      const inventory = parseInventory(inventoryData);
      const catalog = parseCatalog(catalogData);
      if (generation !== this.generation) return;
      this.inventory = inventory;
      // Only backend registry members are surfaced even if a catalog has more entries.
      this.catalog = new Map(inventory.filter(p => catalog.entries.has(p.plugin_id))
        .map(p => [p.plugin_id, catalog.entries.get(p.plugin_id)]));
      this.catalogSourceState = catalog.sourceState;
      // P0: inventory alone cannot prove a timed-out transaction is no longer in flight.
      // Keep unknownOutcome true until BE exposes a read-only in-flight reconciliation contract.
    } catch (error) {
      if (generation === this.generation) {
        this.error = 'Plugin inventory unavailable. The WebSocket list/catalog contract is still required from BE #47. ' +
          (error?.message || 'Retry when available.');
      }
    } finally {
      this.refreshInFlight = false;
      this.loading = false; this.publish();
    }
  }
  async execute(operation, pluginId) {
    if (!MUTATIONS.has(operation)) throw new Error('Unsupported plugin operation.');
    if (this.busy || this.unknownOutcome || !this.connected) throw new Error('Operation blocked; refresh to reconcile.');
    if (!this.inventory.some(p => p.plugin_id === pluginId)) throw new Error('Plugin not in managed registry.');
    this.busy = true; this.publish();
    let requestId = null;
    const previous = this.inventory.find(p => p.plugin_id === pluginId)?.state || null;
    try {
      const pending = this.client.request('obs_plugin.' + operation, {plugin_id:pluginId}, 150000);
      requestId = pending.requestId || null;
      this.log({plugin_id:pluginId, operation, request_id:requestId, result:'requested', previous_state:previous});
      const data = await pending;
      this.log({plugin_id:pluginId, operation, request_id:requestId, result:data.result || 'completed',
        previous_state:previous, resulting_state:data.state || null});
      return data;
    } catch (error) {
      const uncertain = !error?.code || error.code === 'plugin_operation_timeout';
      this.unknownOutcome = uncertain;
      this.log({plugin_id:pluginId, operation, request_id:requestId,
        result:uncertain?'unknown':'failed', previous_state:previous, error_code:error.code || 'unknown_outcome'});
      throw error;
    } finally {
      this.busy = false; this.publish();
      if (this.connected) await this.refresh();
    }
  }
  async restart() {
    if (this.busy || this.unknownOutcome || !this.obsClient.connected) throw new Error('Restart blocked.');
    this.busy = true; this.publish();
    try {
      this.log({operation:'obs.lifecycle.restart', result:'requested'});
      const response = await this.obsClient.request('obs.lifecycle.restart', {}, 150000);
      this.log({operation:'obs.lifecycle.restart', result:'completed'});
      return response;
    } catch (error) {
      this.unknownOutcome = !error.code;
      this.log({operation:'obs.lifecycle.restart', result:'unknown', error_code:error.code || 'unknown_outcome'});
      throw error;
    } finally {
      this.busy = false;
      if (this.connected) await this.refresh();
      this.publish();
    }
  }
  destroy() {
    this.generation++;
    for (const dispose of this.unsubscribers) dispose();
    this.unsubscribers.length = 0;
    this.client.destroy();
  }
}
export function createPluginStore(onChange) {
  const Client = window.StreamOpsWebSocketClient;
  if (!Client || !window.StreamOpsObs) throw new Error('OBS WebSocket transport is not available.');
  const client = new Client({
    path:'/api/v1/obs/plugins/ws', label:'OBS plugin manager',
    // BE operations are bounded at 120s; silence alone must not kill a valid mutation.
    idleTimeoutMs:180000
  });
  const store = new PluginStore({client,obsClient:window.StreamOpsObs,onChange});
  store.start();
  return store;
}
