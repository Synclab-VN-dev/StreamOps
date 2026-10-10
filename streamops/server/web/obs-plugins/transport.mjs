// #75: all production plugin operations go over WebSocket. REST is contract-reference only.
// Canonical BE WS v2: #52 HEAD 37a7333c. WebUI stays WS-only, no REST fallback.
// Read operations, opt-in subscription and operation_status are implemented in BE #52.
// Server revision is process-local; subscribe again and re-fetch after reconnect.
import {parseInventory, parseCatalog, runtimeFromSnapshot, safeActions} from './core.mjs';
export const READ_OPERATIONS = Object.freeze({
  inventory:'obs_plugin.inventory', available:'obs_plugin.available'
});
const MUTATIONS = new Set(['adopt','install','update','verify','rollback']);
const PENDING_SESSION_KEY = 'streamops:obs-plugin-operation-pending';
// Store minimal metadata, never a release URL/path/config/secret. The revision
// proves freshness only in the same server process; after a restart it resets.
function readPending() {
  try {
    if (typeof sessionStorage === 'undefined') return null;
    const raw = sessionStorage.getItem(PENDING_SESSION_KEY);
    if (!raw) return null;
    if (raw === '1') return {legacy:true};
    const value = JSON.parse(raw);
    return value && typeof value === 'object' ? value : {legacy:true};
  } catch {return {legacy:true};}
}
function markPendingInSession(pending) {
  try {
    if (typeof sessionStorage === 'undefined') return;
    if (pending) sessionStorage.setItem(PENDING_SESSION_KEY,JSON.stringify(pending));
    else sessionStorage.removeItem(PENDING_SESSION_KEY);
  } catch { /* unavailable storage cannot grant mutation permissions */ }
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
    this.pendingMutation = readPending();
    this.unknownOutcome = Boolean(this.pendingMutation);
    this.observerReady = false;
    this.subscribed = new Set();
    this.lastSeenRevision = -1;
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
      if (this.connected) {
        this.subscribed.clear();
        this.observerReady = false;
        this.lastSeenRevision = -1;
        void this.refresh();
      } else {
        this.subscribed.clear();
        this.observerReady = false;
        this.generation++;
        if (this.busy) this.unknownOutcome = true;
        this.publish();
      }
    }, {replay:true}));
    this.unsubscribers.push(this.client.on('obs_plugin.changed', (notice) => {
      if (!notice || !Number.isSafeInteger(notice.revision)) return;
      if (notice.revision <= this.lastSeenRevision) return;
      this.lastSeenRevision = notice.revision;
      void this.refresh();
    }));
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
        this.client.request(READ_OPERATIONS.inventory),
        this.client.request(READ_OPERATIONS.available)
      ]);
      const inventory = parseInventory(inventoryData);
      const catalog = parseCatalog(catalogData);
      if (generation !== this.generation) return;
      this.inventory = inventory;
      // Only backend registry members are surfaced even if a catalog has more entries.
      this.catalog = new Map(inventory.filter(p => catalog.entries.has(p.plugin_id))
        .map(p => [p.plugin_id, catalog.entries.get(p.plugin_id)]));
      this.catalogSourceState = catalog.sourceState;
      // Subscribe only to registry-provided plugin IDs. BE sends no unsolicited
      // changed events until the client opts in on each fresh WS connection.
      let didSubscribe = false;
      for (const plugin of inventory) {
        if (this.subscribed.has(plugin.plugin_id)) continue;
        const ack = await this.client.request('obs_plugin.subscribe',{plugin_id:plugin.plugin_id});
        if (generation !== this.generation) return;
        if (ack?.subscribed !== true || ack.plugin_id !== plugin.plugin_id) {
          throw new Error('Plugin change notification subscription was not confirmed.');
        }
        this.subscribed.add(plugin.plugin_id);
        didSubscribe = true;
      }
      this.observerReady = this.subscribed.size === inventory.length;
      // First subscription may race with our initial list/catalog reads.
      if (didSubscribe) this.refreshQueued = true;
      if (this.unknownOutcome && this.pendingMutation?.plugin_id) {
        const pending = this.pendingMutation;
        const reconciliation = await this.client.request('obs_plugin.operation_status',
          {plugin_id:pending.plugin_id});
        if (generation !== this.generation) return;
        const serverOperation = reconciliation?.operation;
        if (reconciliation?.recovery_required === true ||
            reconciliation?.plugin_state === 'RECOVERY_REQUIRED') {
          // Known safe failure state: backend forbids normal mutation.
          this.unknownOutcome = false;
          this.pendingMutation = null;
          markPendingInSession(false);
        } else if (['SUCCEEDED','FAILED'].includes(serverOperation?.state) &&
            serverOperation.operation === pending.operation &&
            Number.isSafeInteger(pending.baseline_revision) &&
            Number.isSafeInteger(reconciliation.revision) &&
            reconciliation.revision > pending.baseline_revision &&
            serverOperation.operation_id) {
          // Explicit terminal operation observed *after* the mutation baseline.
          this.log({plugin_id:pending.plugin_id,operation:pending.operation,
            result:'reconciled-' + serverOperation.state.toLowerCase(),
            operation_id:serverOperation.operation_id});
          this.unknownOutcome = false;
          this.pendingMutation = null;
          markPendingInSession(false);
        }
        // RUNNING, IDLE, process restart or missing revision: keep fail-closed.
      }
    } catch (error) {
      if (generation === this.generation) {
        this.observerReady = false;
        this.error = 'Plugin WebSocket inventory/subscription unavailable: ' +
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
    if (this.busy || this.unknownOutcome || !this.connected || !this.observerReady) {
      throw new Error('Operation blocked; wait for subscription and read-only reconciliation.');
    }
    const plugin = this.inventory.find(p => p.plugin_id === pluginId);
    if (!plugin) throw new Error('Plugin not in managed registry.');
    const eligibility = safeActions(plugin,this.catalog.get(pluginId),this.runtime,
      this.connected && this.observerReady,this.busy || this.unknownOutcome);
    if (!eligibility[operation]?.enabled) throw new Error(eligibility[operation]?.reason || 'Backend state does not permit this action.');
    this.pendingMutation = {plugin_id:pluginId, operation,
      baseline_revision:plugin.revision};
    this.busy = true; markPendingInSession(this.pendingMutation); this.publish();
    let requestId = null;
    const previous = this.inventory.find(p => p.plugin_id === pluginId)?.state || null;
    try {
      const pending = this.client.request('obs_plugin.' + operation, {plugin_id:pluginId}, 150000);
      requestId = pending.requestId || null;
      this.log({plugin_id:pluginId, operation, request_id:requestId, result:'requested', previous_state:previous});
      const data = await pending;
      markPendingInSession(false);
      this.pendingMutation = null;
      this.unknownOutcome = false;
      this.log({plugin_id:pluginId, operation, request_id:requestId, result:data.result || 'completed',
        previous_state:previous, resulting_state:data.state || null});
      return data;
    } catch (error) {
      const uncertain = !error?.code || error.code === 'plugin_operation_timeout';
      this.unknownOutcome = uncertain;
      if (!uncertain) {
        markPendingInSession(false);
        this.pendingMutation = null;
      }
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
    this.pendingMutation = {operation:'obs.lifecycle.restart',plugin_id:null};
    this.busy = true; markPendingInSession(this.pendingMutation); this.publish();
    try {
      this.log({operation:'obs.lifecycle.restart', result:'requested'});
      const response = await this.obsClient.request('obs.lifecycle.restart', {}, 150000);
      markPendingInSession(false);
      this.pendingMutation = null;
      this.unknownOutcome = false;
      this.log({operation:'obs.lifecycle.restart', result:'completed'});
      return response;
    } catch (error) {
      this.unknownOutcome = !error.code;
      if (!this.unknownOutcome) {
        markPendingInSession(false);
        this.pendingMutation = null;
      }
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
