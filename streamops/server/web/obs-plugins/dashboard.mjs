// OBS Dashboard: read plugin summary on explicit request. The main OBS page
// keeps its established one-WS-per-domain sockets until the operator opens
// Plugin Manager or specifically requests a summary (issue #75 regression gate).
import {createPluginStore} from './transport.mjs';
import {summary} from './core.mjs';

let store = null;
let started = false;
const trigger = document.getElementById('plugin-dashboard-load');
const pill = document.getElementById('plugin-dashboard-state');
const managed = document.getElementById('plugin-dashboard-managed');
const installed = document.getElementById('plugin-dashboard-installed');
const attention = document.getElementById('plugin-dashboard-attention');

function render() {
  const loaded = store !== null;
  const counts = summary(store?.inventory || []);
  const failure = store?.error || '';
  const connected = store?.connected || false;
  const fetching = loaded && store.loading;
  pill.textContent = failure ? 'Unavailable'
    : !started ? 'On request'
    : !connected ? 'Connecting'
    : fetching ? 'Loading'
    : counts.attention ? counts.attention + ' need attention'
    : 'No alerts';
  pill.dataset.tone = failure || (started && (!connected || counts.attention)) ? 'warn' : 'neutral';
  managed.textContent = fetching || !loaded || failure ? '—' : String(counts.managed);
  installed.textContent = fetching || !loaded || failure ? '—' : String(counts.installed);
  attention.textContent = fetching || !loaded || failure ? '—' : String(counts.attention);
  trigger.disabled = fetching;
  trigger.textContent = started ? 'Refresh summary' : 'Load summary';
  // Keep the card accurate without implying missing BE data is an empty registry.
  trigger.title = failure || (started ? 'Refresh plugin inventory and release status' : 'Connect to plugin manager on demand');
}

trigger.addEventListener('click', () => {
  if (!started) {
    started = true;
    store = createPluginStore(render);
    store.start();
  } else if (store?.connected) {
    void store.refresh();
  }
  render();
});
window.addEventListener('pagehide', () => {
  store?.destroy();
}, {once:true});
window.addEventListener('pageshow', event => {
  if (event.persisted) location.reload();
});
render();
