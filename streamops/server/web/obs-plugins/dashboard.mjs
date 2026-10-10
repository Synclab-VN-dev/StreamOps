// OBS Dashboard: identical store/selectors as the dedicated plugin page, no fixture inventory.
import {createPluginStore} from './transport.mjs';
import {summary} from './core.mjs';
const store = createPluginStore(render);
function render() {
  const node = document.getElementById('plugin-dashboard-state');
  if (!node) return;
  const counts = summary(store.inventory);
  node.textContent = store.error ? 'Inventory unavailable' :
    !store.connected ? 'Connecting' : store.loading ? 'Loading' :
    counts.attention ? counts.attention + ' need attention' : 'No alerts';
  node.dataset.tone = store.error || !store.connected || counts.attention ? 'warn' : 'ok';
  document.getElementById('plugin-dashboard-managed').textContent = store.loading ? '—' : String(counts.managed);
  document.getElementById('plugin-dashboard-installed').textContent = store.loading ? '—' : String(counts.installed);
  document.getElementById('plugin-dashboard-attention').textContent = store.loading ? '—' : String(counts.attention);
}
window.addEventListener('pagehide',() => store.destroy(),{once:true});
window.addEventListener('pageshow',event => {if (event.persisted) location.reload();});
render();
