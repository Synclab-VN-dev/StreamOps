// #75: pure domain model. The server remains authoritative for registry, releases and rollback.
export const STATES = new Set([
  'NOT_INSTALLED', 'UNMANAGED', 'LEGACY_ADOPTED', 'RECOVERY_REQUIRED',
  'INSTALLED', 'LOADED', 'INCOMPATIBLE', 'ERROR', 'VERIFIED',
  'UPDATE_AVAILABLE', 'RESTART_REQUIRED', 'VERIFY_FAILED', 'FAILED'
]);
const ATTENTION = new Set([
  'UPDATE_AVAILABLE', 'RESTART_REQUIRED', 'VERIFY_FAILED', 'FAILED',
  'ERROR', 'INCOMPATIBLE', 'RECOVERY_REQUIRED'
]);
export const MUTATIONS = new Set(['adopt', 'install', 'update', 'rollback']);
const ERROR_HINTS = Object.freeze({
  plugin_adopt_requires_obs_stopped: 'Stop OBS separately before adopting existing files. Never interrupt a live output.',
  plugin_adoption_required: 'This existing plugin must be adopted before installing an approved release.',
  plugin_not_installed: 'No existing plugin files were found. Refresh before proceeding.',
  plugin_recovery_required: 'Recovery is required. Preserve the backup and inspect backend status.',
  plugin_recovery_requires_obs_stopped: 'Stop OBS separately before beginning recovery.',
  plugin_state_conflict: 'Another change may be running. Refresh status; do not repeat the operation.',
  obs_busy_streaming: 'OBS is streaming. Plugin changes are blocked.',
  obs_busy_recording: 'OBS is recording. Plugin changes are blocked.',
  plugin_operation_timeout: 'The result is unknown. Refresh and reconcile before any further change.',
  plugin_verify_failed: 'Verification failed. OBS, WebSocket and plugin vendor require inspection.',
  plugin_release_unavailable: 'No approved compatible release is currently available.',
  plugin_incompatible: 'This release is incompatible with the current OBS runtime.'
});
const asObject = value => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
export function parseInventory(data) {
  if (!data || !Array.isArray(data.plugins)) throw new Error('Invalid plugin inventory contract.');
  const seen = new Set();
  return data.plugins.map(raw => {
    if (!raw || typeof raw.plugin_id !== 'string' || !raw.plugin_id.trim() || seen.has(raw.plugin_id)) {
      throw new Error('Invalid or duplicate plugin_id in inventory.');
    }
    seen.add(raw.plugin_id);
    const state = STATES.has(raw.state) ? raw.state : 'UNKNOWN';
    return Object.freeze({
      plugin_id: raw.plugin_id, display_name: raw.display_name || raw.plugin_id,
      state, installed: raw.installed === true, managed: raw.managed === true,
      adoptable: raw.adoptable === true, compatible: raw.compatible === true,
      loaded: raw.loaded === true, installed_version: raw.installed_version ?? null,
      available_version: raw.available_version ?? null, expected_version: raw.expected_version ?? null,
      restart_required: raw.restart_required === true,
      last_verification: raw.last_verification ?? null,
      // Optional future BE eligibility: absence deliberately means no Rollback.
      rollback_available: raw.rollback?.available === true || raw.rollback_available === true,
      rollback_reason: raw.rollback?.reason ?? raw.rollback_reason ?? null,
      revision: Number.isSafeInteger(raw.revision) ? raw.revision : null,
      operation: asObject(raw.operation)
    });
  });
}
export function parseCatalog(data) {
  if (!data || !Array.isArray(data.plugins)) throw new Error('Invalid approved release catalog contract.');
  const entries = new Map();
  for (const raw of data.plugins) {
    if (!raw || typeof raw.plugin_id !== 'string' || entries.has(raw.plugin_id)) {
      throw new Error('Invalid or duplicate approved release catalog entry.');
    }
    entries.set(raw.plugin_id, Object.freeze({
      plugin_id: raw.plugin_id, available_version: raw.available_version ?? null,
      installed_version: raw.installed_version ?? null,
      compatibility: raw.compatibility ?? 'unknown', installable: raw.installable === true,
      reason: raw.reason ?? null, source_commit: raw.source_commit ?? null,
      release_ref: raw.release_ref ?? null
    }));
  }
  return {entries, sourceState: data.source_state || 'UNKNOWN'};
}
export function summary(inventory) {
  return {
    managed: inventory.length, installed: inventory.filter(p => p.installed).length,
    attention: inventory.filter(p => ATTENTION.has(p.state) || p.restart_required).length
  };
}
export function runtimeFromSnapshot(snapshot) {
  const runtime = asObject(snapshot?.runtime || snapshot);
  const output = asObject(runtime.output);
  return {
    state: runtime.state || 'UNKNOWN',
    streaming: output.streaming,
    recording: output.recording,
    websocket: asObject(runtime.websocket).connected === true
  };
}
export function safeActions(plugin, release, obs, connected, busy = false) {
  const actions = {};
  const mutationBlock = !connected ? 'Plugin WebSocket disconnected or not subscribed.' 
    : plugin?.operation?.state === 'RUNNING' ? 'A plugin operation is in progress on the server.'
    : busy ? 'Another operation is in progress.'
    : !obs || obs.streaming !== false || obs.recording !== false ? 'OBS output state is unknown or active.'
    : obs.state !== 'STOPPED' && obs.state !== 'READY' ? 'OBS must be READY or STOPPED.' : null;
  const mutating = action => {
    const reason = mutationBlock || (plugin?.state === 'RECOVERY_REQUIRED'
      ? 'Recovery required; normal mutations are blocked.' : null);
    actions[action] = {enabled: !reason, reason};
  };
  mutating('adopt');
  if (plugin?.state !== 'UNMANAGED' || !plugin.installed || !plugin.adoptable) {
    actions.adopt = {enabled:false, reason:'Only an existing unmanaged, adoptable plugin can be adopted.'};
  } else if (obs?.state !== 'STOPPED') {
    actions.adopt = {enabled:false, reason:'OBS must be stopped separately before Adopt.'};
  }
  mutating('install');
  if (!release?.installable || release.compatibility !== 'compatible') {
    actions.install = {enabled:false, reason:release?.reason || 'No approved compatible release.'};
  } else if (!['NOT_INSTALLED','LEGACY_ADOPTED'].includes(plugin?.state)) {
    actions.install = {enabled:false, reason:'Install is only available for absent or adopted legacy plugins.'};
  }
  mutating('update');
  if (plugin?.state !== 'UPDATE_AVAILABLE' || !plugin.installed || !release?.installable || !release.available_version) {
    actions.update = {enabled:false, reason:release?.reason || 'No approved update.'};
  }
  mutating('rollback');
  if (plugin?.rollback_available !== true || plugin?.state === 'UNKNOWN') {
    actions.rollback = {enabled:false, reason:plugin?.rollback_reason || 'Backend has not confirmed a valid rollback baseline.'};
  }
  actions.verify = {
    enabled: Boolean(connected && !busy && plugin?.installed && obs?.state === 'READY' && obs.websocket
      && ['INSTALLED','LOADED','VERIFIED','UPDATE_AVAILABLE','RESTART_REQUIRED','VERIFY_FAILED'].includes(plugin.state)),
    reason:'Verification requires an approved installed plugin and OBS READY with WebSocket.'
  };
  actions.restart = {
    enabled: Boolean(connected && !busy && plugin?.restart_required && obs?.state === 'READY'
      && obs.streaming === false && obs.recording === false),
    reason:'Restart requires OBS READY, idle outputs and a backend restart requirement.'
  };
  return actions;
}
export function typedError(error) {
  const code = typeof error?.code === 'string' ? error.code : 'unknown_outcome';
  const message = ERROR_HINTS[code] || 'The operation could not be confirmed. Refresh backend status before proceeding.';
  return {code, message, outcomeUnknown: code === 'unknown_outcome' || code === 'plugin_operation_timeout'};
}
export function shouldOfferInstall(plugin, release) {
  return ['NOT_INSTALLED','LEGACY_ADOPTED'].includes(plugin?.state) && release?.installable === true;
}
export function stateLabel(state) {
  return ({
    NOT_INSTALLED:'Not installed', UNMANAGED:'Existing · unmanaged',
    LEGACY_ADOPTED:'Legacy baseline adopted', RECOVERY_REQUIRED:'Recovery required',
    INSTALLED:'Installed', VERIFIED:'Verified', UPDATE_AVAILABLE:'Update available',
    RESTART_REQUIRED:'Restart required', VERIFY_FAILED:'Verify failed',
    INCOMPATIBLE:'Incompatible', ERROR:'Error', FAILED:'Failed', LOADED:'Loaded'
  })[state] || 'Unknown';
}
