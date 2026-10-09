(() => {
  const ui = window.StreamOpsUI;
  const $ = (selector) => document.querySelector(selector);
  const STATES = new Set(['IDLE', 'STARTING', 'LIVE', 'RECONNECTING', 'STOPPING', 'FAILED']);
  const ACTIVE_STATES = new Set(['STARTING', 'LIVE', 'RECONNECTING', 'STOPPING']);
  let destinations = [];
  let obsProcess = null;
  let obsRuntime = null;
  let profiles = [];
  let selectedProfile = null;
  let preflight = null;
  let ws = null;
  let reconnectTimer = null;
  let expanded = null;
  let shuttingDown = false;
  let domainRevision = 0;
  const activity = [];
  const statsById = new Map();

  const escapeHtml = (value = '') => String(value).replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character]);
  const publicError = (error) => error?.code
    ? `${error.code}: ${error.message}`
    : (error?.error?.message || error?.message || 'Operation failed.');
  const api = (path, options = {}) => ui.fetchJson(`/api/v1/multistream${path}`, options);
  const runtimeState = (destination) => STATES.has(destination?.state) ? destination.state : 'FAILED';
  const tone = (state) => state === 'LIVE' ? 'ok'
    : (['STARTING', 'STOPPING'].includes(state) ? 'blue'
      : (state === 'FAILED' ? 'bad' : (state === 'RECONNECTING' ? 'warn' : 'neutral')));
  const destinationName = (id) => destinations.find((item) => item.destination_id === id)?.name || id || '';
  const formatTime = (timestamp) => {
    const parsed = timestamp ? new Date(timestamp) : new Date();
    return Number.isNaN(parsed.getTime()) ? new Date().toLocaleTimeString() : parsed.toLocaleTimeString();
  };
  const formatNumber = (value) => new Intl.NumberFormat().format(Number(value) || 0);
  const formatBitrate = (value) => {
    const bits = Number(value) || 0;
    return bits >= 1_000_000 ? `${(bits / 1_000_000).toFixed(1)} Mbps` : `${Math.round(bits / 1000)} Kbps`;
  };

  function addActivity(event, destination = '', level = 'neutral', timestamp = null, context = '') {
    activity.unshift({ time: formatTime(timestamp), event, destination, level, context });
    activity.splice(30);
    renderActivity();
  }

  function sharedChecks() {
    return (preflight?.checks || []).map((item) => [
      item.id,
      item.status === 'PASS',
      item.message || item.status,
    ]);
  }

  function sharedReady() {
    return preflight?.status === 'PASS'
      && preflight?.profile_id === $('#preflight-profile').value;
  }

  function configurationReady(destination) {
    return destination.enabled !== false && Boolean(destination.server_url);
  }

  function canStart(destination) {
    return sharedReady()
      && configurationReady(destination)
      && ['IDLE', 'FAILED'].includes(runtimeState(destination));
  }

  function renderSession() {
    const live = destinations.filter((destination) => runtimeState(destination) === 'LIVE').length;
    const processState = obsProcess?.state || 'UNKNOWN';
    $('#obs-state').textContent = processState === 'READY' ? '● READY' : processState;
    $('#obs-state').dataset.tone = processState === 'READY' ? 'ok' : 'bad';
    $('#obs-scene').textContent = obsRuntime?.current_scene || '--';
    $('#obs-profile').textContent = selectedProfile?.name || '--';
    $('#obs-canvas').textContent = selectedProfile?.canvas
      ? `${selectedProfile.canvas.width}×${selectedProfile.canvas.height}`
      : '--';
    $('#obs-destinations').textContent = `${destinations.length} destinations · ${live} live`;
  }

  function renderPreflight() {
    const checks = sharedChecks();
    const passed = sharedReady();
    const ran = Boolean(preflight);
    $('#preflight-pill').textContent = !ran
      ? 'NOT RUN'
      : (passed ? `${checks.length}/${checks.length} PASSED` : `${checks.filter((item) => item[1]).length}/${checks.length} FAILED`);
    $('#preflight-pill').dataset.tone = !ran ? 'neutral' : (passed ? 'ok' : 'bad');
    $('#preflight-checks').innerHTML = checks.map(([name, ok, value]) => `
      <div class="v2-check"><span>${escapeHtml(name)}</span><strong data-tone="${ok ? 'ok' : 'bad'}">${escapeHtml(value)}</strong></div>
    `).join('');
    $('#preflight-error').hidden = !ran || passed;
  }

  function stateDescription(destination, state) {
    if (state === 'LIVE') return statsById.has(destination.destination_id) ? 'Backend confirmed live · stats updated' : 'Backend confirmed live';
    if (state === 'STARTING') return 'Waiting for backend confirmation…';
    if (state === 'STOPPING') return 'Waiting for backend shutdown confirmation…';
    if (state === 'RECONNECTING') return 'Connection interrupted · recovering';
    if (state === 'FAILED') return 'Destination runtime failed';
    if (!configurationReady(destination)) return 'Destination configuration incomplete';
    return sharedReady() ? 'Ready to stream' : 'Blocked by shared preflight';
  }

  function statsMarkup(id) {
    const stats = statsById.get(id);
    if (!stats) return '<div class="v2-callout" data-tone="blue"><span>Live stats are not available yet.</span></div>';
    return `<div class="v2-stats">
      <div><span>Bitrate</span><strong>${escapeHtml(formatBitrate(stats.bitrate_bps))}</strong></div>
      <div><span>FPS</span><strong>${escapeHtml(stats.fps || 0)}</strong></div>
      <div><span>Bytes</span><strong>${escapeHtml(formatNumber(stats.total_bytes))}</strong></div>
      <div><span>Frames</span><strong>${escapeHtml(formatNumber(stats.total_frames))}</strong></div>
    </div>`;
  }

  function renderDestinations() {
    const root = $('#destination-list-v2');
    $('#destination-empty').hidden = destinations.length > 0;
    root.innerHTML = destinations.map((destination) => {
      const state = runtimeState(destination);
      const open = expanded === destination.destination_id;
      const ready = configurationReady(destination);
      const startAllowed = canStart(destination);
      const readiness = ready ? 'READY' : 'BLOCKED';
      const readinessTone = ready ? 'ok' : 'warn';
      const failure = ['FAILED', 'RECONNECTING'].includes(state)
        ? `<div class="v2-callout" data-tone="${state === 'FAILED' ? 'bad' : 'warn'}"><strong>${state === 'FAILED' ? 'Destination failed' : 'Connection interrupted'}</strong><span>${escapeHtml(stateDescription(destination, state))}</span></div>`
        : '';
      const primaryAction = ['IDLE', 'FAILED'].includes(state)
        ? `<button class="primary-button" data-action="start" ${startAllowed ? '' : 'disabled'}>${state === 'FAILED' ? 'Start again' : 'Start'}</button>`
        : `<button class="danger-button" data-action="stop" ${state === 'STOPPING' ? 'disabled' : ''}>Stop</button>`;
      return `<section class="v2-destination" data-id="${escapeHtml(destination.destination_id)}">
        <button class="v2-destination-head" data-action="expand" type="button" aria-expanded="${open}">
          <div>
            <div class="v2-title-row"><h3>${escapeHtml(destination.name)}</h3><span class="state-pill" data-tone="${tone(state)}">${state}</span><span class="state-pill" data-tone="${readinessTone}">${readiness}</span></div>
            <p>${escapeHtml(stateDescription(destination, state))}</p>
            <div class="v2-destination-summary">
              <div><span>Endpoint</span><strong title="${escapeHtml(destination.server_url || 'Missing')}">${escapeHtml(destination.server_url || 'Missing')}</strong></div>
              <div><span>Stream key</span><strong>Configured</strong></div>
              <div><span>Readiness</span><strong data-tone="${readinessTone}">${readiness === 'READY' ? 'Ready' : 'Blocked'}</strong></div>
            </div>
          </div><span aria-hidden="true">${open ? '⌃' : '⌄'}</span>
        </button>
        <div class="v2-destination-body" ${open ? '' : 'hidden'}>
          <div class="v2-info-grid">
            <div><span>Destination ID</span><strong title="${escapeHtml(destination.destination_id)}">${escapeHtml(destination.destination_id)}</strong></div>
            <div><span>Enabled</span><strong>${destination.enabled === false ? 'No' : 'Yes'}</strong></div>
            <div><span>Backend state</span><strong data-tone="${tone(state)}">${state}</strong></div>
          </div>
          ${failure}
          ${state === 'LIVE' ? statsMarkup(destination.destination_id) : ''}
          <div class="v2-destination-actions">${primaryAction}<button class="secondary-button" data-action="edit" ${ACTIVE_STATES.has(state) ? 'disabled' : ''}>Edit</button>${state === 'LIVE' ? '<button class="secondary-button" data-action="stats">Refresh stats</button>' : ''}</div>
        </div>
      </section>`;
    }).join('');
  }

  function renderActivity() {
    $('#activity-count').textContent = `${activity.filter((item) => item.level === 'bad').length} errors`;
    const latest = activity[0];
    $('#activity-last').textContent = latest
      ? `${latest.time} · ${latest.destination ? `${latest.destination} · ` : ''}${latest.event}`
      : 'No events';
    $('#activity-log-v2').innerHTML = activity.length
      ? activity.map((item) => `<li><time>${escapeHtml(item.time)}</time><span data-tone="${escapeHtml(item.level)}"><strong>${escapeHtml(item.destination ? `${item.destination} · ${item.event}` : item.event)}</strong>${item.context ? `<br>${escapeHtml(item.context)}` : ''}</span></li>`).join('')
      : '<li><time>--</time><span>No streaming activity in this browser session.</span></li>';
  }

  function render() {
    renderSession();
    renderPreflight();
    renderDestinations();
    renderActivity();
  }

  async function loadSelectedProfile() {
    const profileId = $('#preflight-profile').value;
    selectedProfile = profileId
      ? await ui.fetchJson(`/api/v1/scene-profiles/${encodeURIComponent(profileId)}`)
      : null;
    renderSession();
  }

  async function loadObs() {
    try {
      [obsProcess, obsRuntime] = await Promise.all([
        ui.fetchJson('/api/v1/obs/process/status'),
        ui.fetchJson('/api/v1/obs/status'),
      ]);
    } catch (error) {
      obsProcess = { state: 'UNAVAILABLE' };
      obsRuntime = null;
      addActivity('OBS status unavailable', '', 'bad', null, publicError(error));
    }
  }

  async function loadProfiles() {
    const result = await ui.fetchJson('/api/v1/scene-profiles');
    profiles = result.profiles || [];
    const select = $('#preflight-profile');
    select.replaceChildren(...profiles.map((profile) => new Option(profile.name, profile.id)));
    if (!profiles.length) {
      const option = new Option('No saved profiles', '');
      option.disabled = true;
      select.add(option);
    }
    const active = profiles.find((profile) => profile.obs_scene_name === obsRuntime?.current_scene);
    if (active) select.value = active.id;
    await loadSelectedProfile();
  }

  async function runPreflight() {
    const profileId = $('#preflight-profile').value;
    if (!profileId) {
      preflight = null;
      render();
      addActivity('Preflight blocked', '', 'bad', null, 'No scene profile is selected.');
      return;
    }
    try {
      preflight = await ui.fetchJson('/api/v1/live/preflight/shared', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ profile_id: profileId }),
      });
      render();
      addActivity(preflight.status === 'PASS' ? 'Preflight passed' : 'Preflight failed', 'Preflight', preflight.status === 'PASS' ? 'ok' : 'bad', null, `${sharedChecks().filter((item) => item[1]).length}/${sharedChecks().length} checks passed`);
    } catch (error) {
      preflight = null;
      render();
      addActivity('Preflight request failed', 'Preflight', 'bad', null, publicError(error));
    }
  }

  async function refreshStats(id) {
    try {
      const result = await api(`/destinations/${encodeURIComponent(id)}/stats`);
      statsById.set(id, result.stats || {});
      renderDestinations();
    } catch (error) {
      addActivity('Stats request failed', destinationName(id), 'bad', null, publicError(error));
    }
  }

  async function refreshLiveStats() {
    await Promise.all(destinations.filter((destination) => runtimeState(destination) === 'LIVE').map((destination) => refreshStats(destination.destination_id)));
  }

  async function reconcile({ recordFailure = true } = {}) {
    const revisionAtRequest = domainRevision;
    try {
      const result = await api('/destinations');
      // A domain event received after this request started is newer than its
      // response. Do not let the older REST snapshot overwrite realtime state.
      if (revisionAtRequest === domainRevision) destinations = result.destinations || [];
      $('#page-error').hidden = true;
      render();
      await refreshLiveStats();
    } catch (error) {
      $('#page-error').textContent = publicError(error);
      $('#page-error').hidden = false;
      render();
      if (recordFailure) addActivity('Destination service unavailable', '', 'bad', null, publicError(error));
    }
  }

  async function command(id, action) {
    const destination = destinations.find((item) => item.destination_id === id);
    if (!destination) return;
    try {
      const result = await api(`/destinations/${encodeURIComponent(id)}/${action}`, { method: 'POST' });
      const index = destinations.findIndex((item) => item.destination_id === id);
      destinations[index] = result;
      addActivity(`${action === 'start' ? 'Start' : 'Stop'} accepted`, destination.name, 'blue', null, `Backend state: ${runtimeState(result)}`);
      render();
    } catch (error) {
      addActivity(`${action === 'start' ? 'Start' : 'Stop'} failed`, destination.name, 'bad', null, publicError(error));
      render();
    }
  }

  function clearEditor() {
    $('#destination-credential').value = '';
    $('#editor-error').textContent = '';
    $('#editor-error').hidden = true;
  }

  function closeEditor() {
    clearEditor();
    if ($('#destination-editor').open) $('#destination-editor').close();
  }

  function openEditor(destination = null) {
    clearEditor();
    const editing = Boolean(destination);
    $('#editor-title').textContent = editing ? 'Edit destination' : 'Add destination';
    $('#destination-id').value = destination?.destination_id || '';
    $('#destination-name').value = destination?.name || '';
    $('#destination-url').value = destination?.server_url || '';
    $('#destination-enabled').checked = destination?.enabled !== false;
    $('#credential-label').textContent = editing ? 'Replace stream key' : 'Stream key';
    $('#destination-credential').required = !editing;
    $('#credential-help').textContent = editing
      ? 'Configured. Stored credential is never displayed. It is never loaded into the page; enter a value only to replace it.'
      : 'Required. The saved key will never be rendered again.';
    $('#editor-delete').hidden = !editing;
    $('#editor-save').textContent = editing ? 'Save changes' : 'Add destination';
    $('#destination-editor').showModal();
    $('#destination-name').focus();
  }

  async function saveEditor() {
    const nameInput = $('#destination-name');
    const urlInput = $('#destination-url');
    const credentialInput = $('#destination-credential');
    if (![nameInput, urlInput, credentialInput].every((input) => input.reportValidity())) return;
    const id = $('#destination-id').value.trim();
    const credential = credentialInput.value;
    const body = { name: nameInput.value.trim(), server_url: urlInput.value.trim(), enabled: $('#destination-enabled').checked };
    if (!id) {
      body.destination_id = body.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
      body.credential = credential;
      if (!body.destination_id) {
        $('#editor-error').textContent = 'Name must contain at least one Latin letter or number.';
        $('#editor-error').hidden = false;
        return;
      }
    } else if (credential) {
      body.credential = credential;
    }
    try {
      const result = await api(id ? `/destinations/${encodeURIComponent(id)}` : '/destinations', {
        method: id ? 'PATCH' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      closeEditor();
      addActivity(id ? 'Destination updated' : 'Destination created', result.name, 'ok');
      await reconcile({ recordFailure: false });
    } catch (error) {
      credentialInput.value = '';
      $('#editor-error').textContent = publicError(error);
      $('#editor-error').hidden = false;
    }
  }

  async function removeEditor() {
    const id = $('#destination-id').value;
    const name = $('#destination-name').value.trim() || id;
    if (!id || !confirm(`Delete destination “${name}”?`)) return;
    try {
      await api(`/destinations/${encodeURIComponent(id)}`, { method: 'DELETE' });
      closeEditor();
      addActivity('Destination deleted', name);
      await reconcile({ recordFailure: false });
    } catch (error) {
      $('#editor-error').textContent = publicError(error);
      $('#editor-error').hidden = false;
    }
  }

  function upsertDestination(destination) {
    if (!destination?.destination_id) return;
    const index = destinations.findIndex((item) => item.destination_id === destination.destination_id);
    if (index < 0) destinations.push(destination);
    else destinations[index] = { ...destinations[index], ...destination };
  }

  function handleDomainEvent(message) {
    domainRevision += 1;
    const id = message.destination_id;
    const name = destinationName(id);
    const data = message.data || {};
    if (message.type === 'destination.created' || message.type === 'destination.updated') {
      upsertDestination(data);
      addActivity(message.type === 'destination.created' ? 'Destination created' : 'Destination updated', data.name || name, 'ok', message.timestamp);
    } else if (message.type === 'destination.deleted') {
      destinations = destinations.filter((item) => item.destination_id !== id);
      statsById.delete(id);
      if (expanded === id) expanded = null;
      addActivity('Destination deleted', name, 'neutral', message.timestamp);
    } else if (message.type === 'destination.state_changed') {
      const destination = destinations.find((item) => item.destination_id === id);
      if (destination && STATES.has(data.state)) destination.state = data.state;
      addActivity('Runtime state changed', name, tone(data.state), message.timestamp, `${data.previous_state || 'UNKNOWN'} → ${data.state || 'UNKNOWN'}`);
      if (data.state === 'LIVE') refreshStats(id);
    } else if (message.type === 'destination.error') {
      addActivity('Destination error', name, 'bad', message.timestamp, data.message || data.code || 'Runtime error');
    } else if (message.type === 'destination.stats_updated') {
      if (data.stats) statsById.set(id, data.stats);
    } else {
      return false;
    }
    render();
    return true;
  }

  function connect() {
    if (shuttingDown) return;
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${scheme}://${location.host}/api/v1/multistream/ws`);
    ws.addEventListener('message', (event) => {
      try {
        const message = JSON.parse(event.data);
        if (message.type === 'multistream.snapshot') {
          domainRevision += 1;
          destinations = message.data?.destinations || [];
          render();
          refreshLiveStats();
          return;
        }
        handleDomainEvent(message);
      } catch (_error) {
        addActivity('Invalid realtime message', '', 'bad');
      }
    });
    ws.addEventListener('close', () => {
      if (shuttingDown) return;
      addActivity('Realtime disconnected', '', 'warn', null, 'Reconciling from the backend before reconnecting.');
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(async () => {
        await reconcile({ recordFailure: false });
        connect();
      }, 1000);
    });
    ws.addEventListener('error', () => ws.close());
  }

  $('#add-destination').addEventListener('click', () => openEditor());
  $('#editor-cancel').addEventListener('click', closeEditor);
  $('#editor-cancel-secondary').addEventListener('click', closeEditor);
  $('#destination-editor').addEventListener('close', clearEditor);
  $('#editor-save').addEventListener('click', saveEditor);
  $('#editor-delete').addEventListener('click', removeEditor);
  $('#run-preflight').addEventListener('click', runPreflight);
  $('#preflight-profile').addEventListener('change', async () => {
    preflight = null;
    try { await loadSelectedProfile(); } catch (error) { addActivity('Profile details unavailable', '', 'bad', null, publicError(error)); }
    render();
  });
  $('#destination-list-v2').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const card = button.closest('.v2-destination');
    const id = card?.dataset.id;
    const destination = destinations.find((item) => item.destination_id === id);
    if (button.dataset.action === 'expand') {
      expanded = expanded === id ? null : id;
      renderDestinations();
    } else if (button.dataset.action === 'start' || button.dataset.action === 'stop') {
      command(id, button.dataset.action);
    } else if (button.dataset.action === 'edit') {
      openEditor(destination);
    } else if (button.dataset.action === 'stats') {
      refreshStats(id);
    }
  });
  window.addEventListener('beforeunload', () => {
    shuttingDown = true;
    clearTimeout(reconnectTimer);
    if (ws) ws.close();
  });

  (async () => {
    try {
      await loadObs();
      await loadProfiles();
      await reconcile();
      render();
      connect();
      $('.stream-v2').dataset.ready = 'true';
    } catch (error) {
      $('#page-error').textContent = publicError(error);
      $('#page-error').hidden = false;
      render();
    }
  })();
})();
