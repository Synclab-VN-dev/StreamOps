// #75: all production plugin operations go over WebSocket. REST is contract-reference only.
// P0 BE GAP: 'obs_plugin.inventory' and 'obs_plugin.available' are proposed operation
// bindings, NOT implemented in PR #52. No fallback to REST or hard-coded inventory.
// P0 BE GAP: 'obs_plugin.changed' push notification/revision are not yet implemented.
import {parseInventory, parseCatalog, runtimeFromSnapshot, safeActions} from './core.mjs';
export const PROPOSED_READ_OPERATIONS = Object.freeze({
  inventory:'obs_plugin.inventory', available:'obs_plugin.available'
});
const MUTATIONS = new Set(['adopt','install','update','verify','rollback']);
const PENDING_SESSION_KEY = 'streamops:obs-plugin-operation-pending';
// Preserve uncertain mutation state across page refresh within this tab.
function pendingInSession() {
  try {return typeof sessionStorage !== 'undefined' && sessionStorage.getItem(PENDING_SESSION_KEY) === '1';}
  catch {return false;}
}
function markPendingInSession(pending) {
  try {
    if (typeof sessionStorage === 'undefined') return;
    if (pending) sessionStorage.setItem(PENDING_SESSION_KEY,'1');
    else sessionStorage.removeItem(PENDING_SESSION_KEY);
  } catch { /* storage may be unavailable; backend remains the final mutation guard */ }
}
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
    this.unknownOutcome = pendingInSession();
    this.activity = [];
    this.generation = 0;
    this.refreshInFlight = false;
    this.refreshQueued = false;
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
    if (!this.connected) return;
    if (this.refreshInFlight) {this.refreshQueued = true; return;}
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
      if (this.refreshQueued && this.connected) {
        this.refreshQueued = false;
        void this.refresh();
      }
    }
  }
  async execute(operation, pluginId) {
    if (!MUTATIONS.has(operation)) throw new Error('Unsupported plugin operation.');
    if (this.busy || this.unknownOutcome || !this.connected) throw new Error('Operation blocked; refresh to reconcile.');
    const plugin = this.inventory.find(p => p.plugin_id === pluginId);
    if (!plugin) throw new Error('Plugin not in managed registry.');
    const eligibility = safeActions(plugin,this.catalog.get(pluginId),this.runtime,this.connected,this.busy || this.unknownOutcome);
    if (!eligibility[operation]?.enabled) throw new Error(eligibility[operation]?.reason || 'Backend state does not permit this action.');
    this.busy = true; markPendingInSession(true); this.publish();
    let requestId = null;
    const previous = this.inventory.find(p => p.plugin_id === pluginId)?.state || null;
    try {
      const pending = this.client.request('obs_plugin.' + operation, {plugin_id:pluginId}, 150000);
      requestId = pending.requestId || null;
      this.log({plugin_id:pluginId, operation, request_id:requestId, result:'requested', previous_state:previous});
      const data = await pending;
      markPendingInSession(false);
      this.unknownOutcome = false;
      this.log({plugin_id:pluginId, operation, request_id:requestId, result:data.result || 'completed',
        previous_state:previous, resulting_state:data.state || null});
      return data;
    } catch (error) {
      const uncertain = !error?.code || error.code === 'plugin_operation_timeout';
      this.unknownOutcome = uncertain;
      if (!uncertain) markPendingInSession(false);
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
    this.busy = true; markPendingInSession(true); this.publish();
    try {
      this.log({operation:'obs.lifecycle.restart', result:'requested'});
      const response = await this.obsClient.request('obs.lifecycle.restart', {}, 150000);
      markPendingInSession(false);
      this.unknownOutcome = false;
      this.log({operation:'obs.lifecycle.restart', result:'completed'});
      return response;
    } catch (error) {
      this.unknownOutcome = !error.code;
      if (!this.unknownOutcome) markPendingInSession(false);
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
  // IMPORTANT: do not start synchronously. connect() emits "connecting" and
  // calls onChange immediately; page modules first need to bind their store.
  return new PluginStore({client,obsClient:window.StreamOpsObs,onChange});
}
