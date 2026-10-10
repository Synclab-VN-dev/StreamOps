import {createPluginStore} from './transport.mjs';
import {safeActions, stateLabel, summary, typedError} from './core.mjs';

const byId = id => document.getElementById(id);
const text = (tag, className, content) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined && content !== null) node.textContent = String(content);
  return node;
};
let pendingAction = null, expandedId = null;
const dialog = byId('plugin-confirm-dialog');
const store = createPluginStore(render);
function notify(message, error = false) {
  const element = byId('plugin-notice');
  element.textContent = message;
  element.dataset.tone = error ? 'bad' : 'info';
  element.hidden = !message;
}
function confirmAction(action, plugin) {
  const actions = safeActions(plugin, store.catalog.get(plugin.plugin_id), store.runtime,
    store.connected, store.busy || store.unknownOutcome);
  if (!actions[action]?.enabled) {
    notify(actions[action]?.reason || 'Operation blocked by current backend state.', true);
    return;
  }
  pendingAction = {action, id:plugin.plugin_id, name:plugin.display_name};
  byId('plugin-confirm-title').textContent = action === 'adopt' ? 'Adopt existing plugin?' :
    action === 'restart' ? 'Restart OBS?' : action.charAt(0).toUpperCase() + action.slice(1) + ' plugin?';
  const details = {
    adopt:'OBS must already be STOPPED. StreamOps will snapshot the existing legacy plugin and config. Adopt does not install an approved release, start OBS or verify the plugin.',
    install:'Only the backend-selected approved release can be installed. Existing files/config will be handled by BE.',
    update:'Update is a transaction distinct from Install. The backend owns backup, validation and recovery.',
    rollback:'Rollback changes plugin files. Only proceed if the backend confirmed a valid backup.',
    verify:'The backend will verify OBS readiness, the loaded plugin and applicable Vendor API.',
    restart:'OBS must be idle. Restart does not mean the plugin is verified; inspect status and Verify afterwards.'
  };
  byId('plugin-confirm-detail').textContent = details[action] || '';
  byId('plugin-confirm-identity').textContent = plugin.display_name + ' · ' + plugin.plugin_id;
  if (typeof dialog.showModal === 'function') dialog.showModal(); else dialog.setAttribute('open','');
}
function closeDialog() {
  pendingAction = null;
  dialog.close?.();
  dialog.removeAttribute('open');
}
byId('plugin-confirm-cancel').addEventListener('click', closeDialog);
dialog.addEventListener('cancel', () => {pendingAction = null;});
byId('plugin-confirm-submit').addEventListener('click', async () => {
  const requested = pendingAction;
  if (!requested) return;
  const plugin = store.inventory.find(p => p.plugin_id === requested.id);
  if (!plugin) {closeDialog(); notify('Plugin is no longer in the registry.',true); return;}
  const current = safeActions(plugin,store.catalog.get(plugin.plugin_id),store.runtime,
    store.connected,store.busy || store.unknownOutcome);
  if (!current[requested.action]?.enabled) {
    closeDialog(); notify(current[requested.action]?.reason || 'State changed. Refresh first.',true); return;
  }
  closeDialog();
  notify(requested.action + ' requested. Await backend result…');
  try {
    if (requested.action === 'restart') await store.restart();
    else await store.execute(requested.action,requested.id);
    notify('Backend confirmed ' + requested.action + '. Current state is being reconciled.');
  } catch (error) {
    const failure = typedError(error);
    notify(failure.code + ': ' + failure.message, true);
  }
});
byId('plugin-refresh').addEventListener('click', () => store.refresh());

function statusTone(state) {
  return ['ERROR','FAILED','VERIFY_FAILED','RECOVERY_REQUIRED'].includes(state) ? 'bad' :
    ['UNMANAGED','LEGACY_ADOPTED','UPDATE_AVAILABLE','RESTART_REQUIRED','INCOMPATIBLE'].includes(state) ? 'warn' :
    state === 'VERIFIED' ? 'ok' : 'neutral';
}
function stat(container, label, value) {
  const box = text('div','plugin-stat');
  box.append(text('span','',label),text('strong','',value));
  container.append(box);
}
function actionButton(plugin, action, label, eligibility) {
  const button = text('button','plugin-action',label);
  button.type = 'button'; button.dataset.operation = action;
  button.disabled = !eligibility?.enabled;
  if (button.disabled) button.title = eligibility?.reason || 'Action unavailable';
  button.addEventListener('click',() => confirmAction(action,plugin));
  return button;
}
function renderPlugin(plugin) {
  const release = store.catalog.get(plugin.plugin_id);
  const eligible = safeActions(plugin,release,store.runtime,store.connected,
    store.busy || store.unknownOutcome);
  const card = text('article','plugin-card');
  card.dataset.pluginId = plugin.plugin_id;
  const header = text('button','plugin-card-header');
  header.type = 'button'; header.setAttribute('aria-expanded',String(expandedId === plugin.plugin_id));
  header.setAttribute('aria-controls','plugin-detail-' + plugin.plugin_id.replace(/[^a-zA-Z0-9_-]/g,'_'));
  const left = text('span','plugin-heading');
  const icon = text('span','plugin-symbol'); icon.setAttribute('aria-hidden','true');
  icon.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="13" r="2"/><path d="M7.76 7.76a6 6 0 0 0 0 8.48m8.48-8.48a6 6 0 0 1 0 8.48M4.93 4.93a10 10 0 0 0 0 14.14m14.14-14.14a10 10 0 0 1 0 14.14M12 15v7"/></svg>';
  const heading = text('span','plugin-heading-text');
  heading.append(text('strong','',plugin.display_name),text('small','',plugin.plugin_id));
  left.append(icon,heading);
  const right = text('span','plugin-card-meta');
  const pill = text('span','plugin-pill',stateLabel(plugin.state));
  pill.dataset.tone = statusTone(plugin.state);
  right.append(pill,text('span','plugin-chevron',expandedId === plugin.plugin_id ? '⌃' : '⌄'));
  header.append(left,right);
  header.addEventListener('click',() => {expandedId = expandedId === plugin.plugin_id ? null : plugin.plugin_id; render();});
  card.append(header);
  const mini = text('div','plugin-mini-details');
  mini.append(
    text('span','', 'Installed: ' + (plugin.installed_version || (plugin.installed ? 'version unknown' : '—'))),
    text('span','', 'Available: ' + (release?.available_version || '—'))
  );
  card.append(mini);
  if (expandedId !== plugin.plugin_id) return card;
  const details = text('div','plugin-detail');
  details.id = header.getAttribute('aria-controls');
  const grid = text('div','plugin-detail-grid');
  stat(grid,'Compatibility',release?.compatibility || (plugin.compatible ? 'Compatible' : 'Unknown'));
  stat(grid,'Managed baseline',plugin.managed ? 'Yes' : 'No');
  stat(grid,'OBS restart',plugin.restart_required ? 'Required' : 'Not requested');
  stat(grid,'Last verification',plugin.last_verification || 'Not verified');
  if (release?.source_commit) stat(grid,'Source commit',release.source_commit);
  if (release?.release_ref) stat(grid,'Release ref',release.release_ref);
  details.append(grid);
  const actions = text('div','plugin-action-row');
  const offered = [];
  if (plugin.state === 'UNMANAGED') offered.push(['adopt','Adopt existing']);
  if (['NOT_INSTALLED','LEGACY_ADOPTED'].includes(plugin.state)) offered.push(['install','Install plugin']);
  if (plugin.state === 'UPDATE_AVAILABLE') offered.push(['update','Update plugin']);
  if (plugin.restart_required) offered.push(['restart','Restart OBS']);
  if (plugin.installed && !['UNMANAGED','LEGACY_ADOPTED'].includes(plugin.state)) offered.push(['verify','Verify']);
  if (plugin.installed && plugin.managed) offered.push(['rollback','Rollback']);
  for (const [action,label] of offered) {
    const button = actionButton(plugin,action,label,eligible[action]);
    if (action === 'adopt' || action === 'install') button.classList.add('plugin-primary');
    actions.append(button);
    if (button.disabled && (action === 'adopt' || action === 'rollback')) {
      actions.append(text('small','plugin-disabled-reason',eligible[action]?.reason));
    }
  }
  details.append(actions);
  if (plugin.state === 'UNMANAGED') details.append(text('p','plugin-warning',
    'Existing files are not managed by StreamOps. Stop OBS separately, then Adopt; never overwrite unmanaged files.'));
  if (plugin.state === 'LEGACY_ADOPTED') details.append(text('p','plugin-warning',
    'Legacy baseline is now adopted, not an approved/verified installed release.'));
  if (plugin.state === 'RECOVERY_REQUIRED') details.append(text('p','plugin-warning',
    'Recovery required. Preserve backup evidence and follow backend recovery guidance.'));
  if (release?.reason) details.append(text('p','plugin-reason','Approved release: ' + release.reason));
  card.append(details);
  return card;
}
function render() {
  const counts = summary(store.inventory);
  byId('plugin-managed-count').textContent = store.loading ? '—' : String(counts.managed);
  byId('plugin-installed-count').textContent = store.loading ? '—' : String(counts.installed);
  byId('plugin-attention-count').textContent = store.loading ? '—' : String(counts.attention);
  const obs = store.runtime;
  const obsState = byId('plugin-obs-state');
  obsState.textContent = obs?.state || 'OBS unavailable';
  obsState.dataset.tone = obs?.state === 'READY' ? 'ok' : 'warn';
  byId('plugin-refresh').disabled = !store.connected || store.busy || store.loading;
  const banner = byId('plugin-connection-warning');
  const message = store.unknownOutcome ? 'Previous operation outcome is unknown. Only read-only reconciliation is safe.'
    : store.error ? store.error
    : !store.connected ? 'Plugin WebSocket disconnected. Awaiting connection.'
    : store.loading ? 'Loading plugin inventory and release catalog…' : '';
  banner.textContent = message; banner.hidden = !message;
  const list = byId('plugin-list');
  list.replaceChildren();
  if (!store.loading && store.inventory.length === 0) {
    list.append(text('p','plugin-empty',store.error ? 'Inventory is unavailable; no plugins are inferred.' : 'No plugins in the managed registry.'));
  } else {
    for (const plugin of store.inventory) list.append(renderPlugin(plugin));
  }
  byId('plugin-release-source').textContent = 'Release catalog: ' + store.catalogSourceState;
  const activity = byId('plugin-activity');
  activity.replaceChildren();
  if (!store.activity.length) activity.append(text('li','plugin-empty','No operations in this browser session.'));
  for (const entry of store.activity.slice().reverse()) {
    const li = text('li','plugin-activity-entry');
    li.append(text('time','',new Date(entry.at).toLocaleTimeString()),
      text('span','',entry.operation + ' · ' + entry.result +
        (entry.plugin_id ? ' · ' + entry.plugin_id : '') +
        (entry.error_code ? ' · ' + entry.error_code : '') +
        (entry.request_id ? ' · ' + entry.request_id : '')));
    activity.append(li);
  }
}
window.addEventListener('pagehide',() => store.destroy(),{once:true});
window.addEventListener('pageshow',event => {if (event.persisted) location.reload();});
render();
