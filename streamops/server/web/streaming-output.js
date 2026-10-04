(() => {
  const ui = window.StreamOpsUI;
  const liveSocket = window.StreamOpsLive;
  const stateStore = window.StreamOpsStreamingState;
  const $ = (selector) => document.querySelector(selector);
  const activity = ui.createActivityLog('#stream-activity-log');

  let snapshot = null;
  let catalog = [];
  let profiles = [];
  let profileDetail = null;
  let selectedDestinationId = stateStore?.selection?.().destination_id || null;
  let editingNewDestination = false;
  let destinationDirty = false;
  let lastDestinationSignature = null;
  let preflight = null;
  let transportConnected = liveSocket.connected;
  let busy = false;
  let pendingTransition = null;
  let lastServerState = null;
  let everConnected = false;
  let staticLoaded = false;
  let lastRuntimeSceneSignature = null;

  function setError(selector, message = '') {
    const element = $(selector);
    element.textContent = message;
    element.hidden = !message;
  }

  function publicError(error) {
    if (!error) return 'Operation failed.';
    return error.code ? `${error.code}: ${error.message}` : error.message || String(error);
  }

  function tone(element, value) {
    element.dataset.tone = value;
  }

  function stateTone(value) {
    if (value === 'LIVE') return 'ok';
    if (['STARTING', 'STOPPING'].includes(value)) return 'blue';
    if (['OBS_NOT_READY', 'RECOVERY_REQUIRED', 'RESTORE_FAILED'].includes(value)) return 'bad';
    if (value === 'IDLE') return 'neutral';
    return 'warn';
  }

  function statusTone(value) {
    return value === 'PASS' ? 'ok' : value === 'WARN' ? 'warn' : value === 'FAIL' ? 'bad' : 'neutral';
  }

  function typeLabel(value) {
    if (!value) return '--';
    return String(value)
      .split('_')
      .map((part) => part ? part[0].toUpperCase() + part.slice(1) : '')
      .join(' ');
  }

  function selectedDestination() {
    return (snapshot?.destinations || []).find((item) => item.id === selectedDestinationId) || null;
  }

  function selectedProfileId() {
    return $('#stream-profile-list').value || null;
  }

  function selectedProfileSummary() {
    const id = selectedProfileId();
    return profiles.find((item) => item.id === id)
      || (snapshot?.profile?.id === id ? snapshot.profile : null);
  }

  function destinationDescriptor(type = $('#destination-type').value) {
    return catalog.find((item) => item.type === type) || null;
  }

  function destinationLocked(destination = selectedDestination()) {
    return !!(
      destination
      && snapshot?.managed
      && snapshot?.destination?.id === destination.id
    );
  }

  function sceneDraftBlocked() {
    const meta = stateStore?.sceneDraftMeta?.();
    return !!(meta?.dirty && meta.profile_id === selectedProfileId());
  }

  function preflightMatchesSelection() {
    const destinationId = selectedDestinationId;
    const profileId = selectedProfileId();
    return !!(
      preflight
      && preflight.status === 'PASS'
      && preflight.destination_id === destinationId
      && preflight.profile_id === profileId
    );
  }

  function formatBytes(value) {
    let bytes = Number(value || 0);
    if (!Number.isFinite(bytes) || bytes < 0) bytes = 0;
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let unit = 0;
    while (bytes >= 1024 && unit < units.length - 1) {
      bytes /= 1024;
      unit++;
    }
    const digits = unit === 0 ? 0 : bytes >= 100 ? 0 : bytes >= 10 ? 1 : 2;
    return `${bytes.toFixed(digits)} ${units[unit]}`;
  }

  function formatAverageBitrate(bytes, durationMs) {
    const durationSeconds = Number(durationMs || 0) / 1000;
    if (!Number.isFinite(durationSeconds) || durationSeconds <= 0) return '--';
    const kbps = (Number(bytes || 0) * 8) / durationSeconds / 1000;
    return Number.isFinite(kbps) ? `${kbps.toFixed(kbps >= 100 ? 0 : 1)} kbps` : '--';
  }

  function invalidatePreflight() {
    preflight = null;
    stateStore?.invalidatePreflight?.();
    renderPreflight(null);
    renderButtons();
  }

  function markDestinationDirty() {
    if (!editingNewDestination) destinationDirty = true;
    else destinationDirty = true;
    invalidatePreflight();
    renderDestinationState();
  }

  function renderDestinationTypeOptions(selectedType) {
    const select = $('#destination-type');
    const current = selectedType || select.value;
    select.replaceChildren();
    for (const descriptor of catalog) {
      select.add(new Option(descriptor.label || typeLabel(descriptor.type), descriptor.type));
    }
    if (current && catalog.some((item) => item.type === current)) select.value = current;
    else if (catalog[0]) select.value = catalog[0].type;
  }

  function renderDestinationSettings(settings = {}) {
    const root = $('#destination-settings-fields');
    root.replaceChildren();
    const descriptor = destinationDescriptor();
    for (const spec of descriptor?.settings || []) {
      const label = document.createElement('label');
      label.textContent = spec.label || spec.key;
      const input = document.createElement('input');
      input.dataset.settingKey = spec.key;
      input.setAttribute('aria-label', spec.label || spec.key);
      input.required = spec.required === true;
      input.placeholder = spec.placeholder || '';
      if (spec.type === 'boolean') {
        input.type = 'checkbox';
        input.checked = settings[spec.key] === true;
      } else if (['integer', 'number'].includes(spec.type)) {
        input.type = 'number';
        input.value = settings[spec.key] ?? spec.default ?? '';
      } else {
        input.type = 'text';
        input.value = settings[spec.key] ?? spec.default ?? '';
      }
      input.addEventListener('input', markDestinationDirty);
      label.append(input);
      root.append(label);
    }

    const credential = descriptor?.credential;
    $('#credential-title').textContent = credential?.label || 'Credential';
    $('#credential-input-label').firstChild.textContent = (credential?.label || 'Credential') + ' ';
    $('#credential-input').type = credential?.type === 'password' ? 'password' : 'text';
  }

  function renderDestinationList() {
    const select = $('#destination-list');
    const destinations = snapshot?.destinations || [];
    const current = editingNewDestination ? '' : selectedDestinationId;
    select.replaceChildren();
    if (editingNewDestination) select.add(new Option('New destination (unsaved)', '', true, true));
    for (const destination of destinations) {
      select.add(new Option(destination.name, destination.id));
    }
    if (!destinations.length && !editingNewDestination) {
      const empty = new Option('No destinations', '', true, true);
      empty.disabled = true;
      select.add(empty);
    } else if (current && destinations.some((item) => item.id === current)) {
      select.value = current;
    }
  }

  function renderDestinationForm(destination, {force = false} = {}) {
    if (!force && destinationDirty) return;
    const model = destination || {
      name: '',
      type: catalog[0]?.type || '',
      enabled: true,
      settings: {},
      credential_configured: false,
    };
    $('#destination-name').value = model.name || '';
    renderDestinationTypeOptions(model.type);
    $('#destination-enabled').checked = model.enabled !== false;
    renderDestinationSettings(model.settings || {});
    $('#credential-input').value = '';
    destinationDirty = editingNewDestination;
    lastDestinationSignature = destination ? JSON.stringify(destination) : null;
    renderDestinationState();
  }

  function renderDestinationState() {
    const destination = selectedDestination();
    const locked = destinationLocked(destination);
    const configured = destination?.credential_configured === true;
    const descriptor = destinationDescriptor(destination?.type);

    $('#destination-summary-name').textContent = editingNewDestination
      ? 'New destination'
      : destination?.name || '--';
    $('#destination-summary-type').textContent = descriptor?.label || typeLabel(destination?.type || $('#destination-type').value);
    $('#destination-summary-credential').textContent = configured ? 'Configured' : 'Missing';
    $('#credential-status').textContent = configured ? 'Configured' : 'Not configured';

    const state = $('#destination-state-pill');
    if (locked) {
      state.textContent = 'LOCKED';
      tone(state, 'warn');
    } else if (destinationDirty) {
      state.textContent = 'UNSAVED';
      tone(state, 'warn');
    } else if (destination?.enabled === false) {
      state.textContent = 'DISABLED';
      tone(state, 'warn');
    } else if (destination) {
      state.textContent = 'READY';
      tone(state, configured ? 'ok' : 'warn');
    } else if (editingNewDestination) {
      state.textContent = 'NEW';
      tone(state, 'blue');
    } else {
      state.textContent = '--';
      tone(state, 'neutral');
    }
  }

  function reconcileDestinationSelection() {
    const destinations = snapshot?.destinations || [];
    if (snapshot?.managed && snapshot.destination?.id) {
      selectedDestinationId = snapshot.destination.id;
      editingNewDestination = false;
      stateStore?.updateSelection?.({
        destination_id: snapshot.destination.id,
        destination_name: snapshot.destination.name || undefined,
      });
    } else if (!editingNewDestination) {
      const remembered = stateStore?.selection?.().destination_id;
      if (!destinations.some((item) => item.id === selectedDestinationId)) {
        selectedDestinationId = destinations.some((item) => item.id === remembered)
          ? remembered
          : destinations[0]?.id || null;
      }
      const selected = destinations.find((item) => item.id === selectedDestinationId);
      if (selected) {
        stateStore?.updateSelection?.({
          destination_id: selected.id,
          destination_name: selected.name,
        });
      }
    }

    renderDestinationList();
    const selected = selectedDestination();
    const signature = selected ? JSON.stringify(selected) : null;
    if (!editingNewDestination && !destinationDirty && signature !== lastDestinationSignature) {
      renderDestinationForm(selected, {force: true});
    } else {
      renderDestinationState();
    }
  }

  function collectDestinationSettings() {
    const settings = {};
    for (const input of document.querySelectorAll('#destination-settings-fields [data-setting-key]')) {
      const key = input.dataset.settingKey;
      if (input.type === 'checkbox') settings[key] = input.checked;
      else if (input.type === 'number') settings[key] = input.value === '' ? null : Number(input.value);
      else settings[key] = input.value.trim();
      if (input.required && (settings[key] === '' || settings[key] === null)) {
        input.reportValidity();
        throw new Error(`${input.getAttribute('aria-label') || key} is required.`);
      }
    }
    return settings;
  }

  function destinationPayload() {
    const name = $('#destination-name').value.trim();
    if (!name) throw new Error('Destination name is required.');
    const type = $('#destination-type').value;
    if (!type) throw new Error('Destination type is required.');
    return {
      name,
      type,
      enabled: $('#destination-enabled').checked,
      settings: collectDestinationSettings(),
    };
  }

  function upsertDestination(destination) {
    if (!snapshot) snapshot = {state: 'IDLE', destinations: []};
    const destinations = [...(snapshot.destinations || [])];
    const index = destinations.findIndex((item) => item.id === destination.id);
    if (index >= 0) destinations[index] = destination;
    else destinations.push(destination);
    snapshot = {...snapshot, destinations};
    selectedDestinationId = destination.id;
    editingNewDestination = false;
    destinationDirty = false;
    stateStore?.updateSelection?.({
      destination_id: destination.id,
      destination_name: destination.name,
    });
    lastDestinationSignature = null;
    reconcileDestinationSelection();
  }

  async function saveDestination() {
    setError('#destination-error');
    const payload = destinationPayload();
    const result = editingNewDestination
      ? await liveSocket.request('destinations.create', {destination: payload})
      : await liveSocket.request('destinations.update', {
          destination_id: selectedDestinationId,
          destination: payload,
        });
    upsertDestination(result);
    invalidatePreflight();
    activity(`destination saved: ${result.name}`, 'success');
  }

  async function deleteDestination() {
    const destination = selectedDestination();
    if (!destination) return;
    if (!confirm(`Delete streaming destination “${destination.name}”?`)) return;
    await liveSocket.request('destinations.delete', {destination_id: destination.id});
    if (snapshot) {
      snapshot = {
        ...snapshot,
        destinations: (snapshot.destinations || []).filter((item) => item.id !== destination.id),
      };
    }
    selectedDestinationId = null;
    stateStore?.updateSelection?.({destination_id: null, destination_name: null});
    editingNewDestination = false;
    destinationDirty = false;
    lastDestinationSignature = null;
    invalidatePreflight();
    reconcileDestinationSelection();
    renderDestinationForm(selectedDestination(), {force: true});
    activity(`destination deleted: ${destination.name}`, 'success');
  }

  async function saveCredential() {
    const destination = selectedDestination();
    const input = $('#credential-input');
    if (!destination) throw new Error('Save the destination before setting a credential.');
    if (!input.value) throw new Error('Credential is required.');
    await liveSocket.request('destinations.set_credential', {
      destination_id: destination.id,
      credential: input.value,
    });
    input.value = '';
    upsertDestination({...destination, credential_configured: true});
    invalidatePreflight();
    activity(`credential saved: ${destination.name}`, 'success');
  }

  async function deleteCredential() {
    const destination = selectedDestination();
    if (!destination) return;
    await liveSocket.request('destinations.delete_credential', {destination_id: destination.id});
    $('#credential-input').value = '';
    upsertDestination({...destination, credential_configured: false});
    invalidatePreflight();
    activity(`credential removed: ${destination.name}`, 'success');
  }

  async function loadProfileDetail(profileId) {
    if (!profileId) {
      profileDetail = null;
      renderProfile();
      return;
    }
    try {
      profileDetail = await ui.fetchJson(`/api/v1/scene-profiles/${encodeURIComponent(profileId)}`);
      setError('#profile-error');
    } catch (error) {
      profileDetail = null;
      setError('#profile-error', publicError(error));
    }
    renderProfile();
  }

  async function loadProfiles({preserveSelection = true} = {}) {
    const result = await ui.fetchJson('/api/v1/scene-profiles');
    profiles = result.profiles || [];
    const select = $('#stream-profile-list');
    const remembered = preserveSelection ? (stateStore?.selection?.().profile_id || select.value) : null;
    const activeId = snapshot?.managed ? snapshot?.profile?.id : null;
    let selectedId = activeId || remembered;
    if (!profiles.some((item) => item.id === selectedId)) selectedId = profiles[0]?.id || null;

    select.replaceChildren();
    for (const profile of profiles) select.add(new Option(profile.name, profile.id));
    if (!profiles.length) {
      const empty = new Option('No saved profiles', '', true, true);
      empty.disabled = true;
      select.add(empty);
    } else {
      select.value = selectedId;
    }

    const summary = profiles.find((item) => item.id === selectedId);
    if (summary) {
      stateStore?.updateSelection?.({profile_id: summary.id, profile_name: summary.name});
    }
    await loadProfileDetail(selectedId);
  }

  function renderProfile() {
    const summary = selectedProfileSummary();
    const dirty = sceneDraftBlocked();
    const name = snapshot?.managed && snapshot.profile?.id === summary?.id
      ? snapshot.profile.name || summary?.name
      : summary?.name;
    const canvas = profileDetail?.canvas;
    $('#setup-summary-profile').textContent = name || '--';
    $('#setup-summary-canvas').textContent = canvas ? `${canvas.width}×${canvas.height}` : '--';
    $('#setup-summary-fps').textContent = canvas?.fps ?? '--';
    $('#setup-profile-name').textContent = name || '--';
    $('#setup-profile-canvas').textContent = canvas ? `${canvas.width}×${canvas.height} @ ${canvas.fps}` : '--';
    $('#setup-draft-state').textContent = dirty ? 'Unsaved changes' : 'Saved';
    $('#dirty-profile-warning').hidden = !dirty;
    $('#setup-profile-state').textContent = dirty ? 'UNSAVED' : summary ? 'SAVED' : 'MISSING';
    tone($('#setup-profile-state'), dirty ? 'warn' : summary ? 'ok' : 'bad');
    renderButtons();
  }

  function checkById(id) {
    return (preflight?.checks || []).find((item) => item.id === id) || null;
  }

  function renderPreflight(result) {
    preflight = result && Object.keys(result).length ? result : null;
    const status = preflight?.status || 'NOT RUN';
    $('#preflight-state').textContent = status;
    tone($('#preflight-state'), statusTone(status));

    const obsCheck = checkById('obs_ready');
    const profileCheck = checkById('profile_verify') || checkById('profile');
    const outputCheck = checkById('output_engine') || checkById('destination_adapter') || checkById('destination');
    $('#preflight-summary-obs').textContent = obsCheck?.status || '--';
    $('#preflight-summary-profile').textContent = profileCheck?.status || '--';
    $('#preflight-summary-output').textContent = outputCheck?.status || '--';

    const root = $('#preflight-checks');
    root.replaceChildren();
    for (const check of preflight?.checks || []) {
      const row = document.createElement('div');
      row.className = 'stream-check-row';
      row.dataset.status = check.status;
      const copy = document.createElement('div');
      const id = document.createElement('strong');
      id.textContent = check.id || '--';
      const message = document.createElement('span');
      message.textContent = check.message || '';
      copy.append(id, message);
      const badge = document.createElement('span');
      badge.className = 'check-badge ' + String(check.status || '').toLowerCase();
      badge.textContent = check.status || '--';
      row.append(copy, badge);
      root.append(row);
    }
    renderButtons();
  }

  async function runPreflight() {
    setError('#preflight-error');
    if (editingNewDestination || destinationDirty) {
      throw new Error('Save the destination before running Preflight.');
    }
    if ($('#credential-input').value) {
      throw new Error('Save or clear the pending credential before running Preflight.');
    }
    const profileId = selectedProfileId();
    if (!profileId || !selectedDestinationId) throw new Error('Select a saved profile and destination.');
    const result = await liveSocket.request('live.preflight', {
      profile_id: profileId,
      destination_id: selectedDestinationId,
    });
    renderPreflight(result);
    stateStore?.recordPreflight?.(result, profileId, selectedDestinationId);
    activity(`preflight: ${result.status}`, result.status === 'PASS' ? 'success' : 'error');
  }

  function liveDisplayState() {
    return pendingTransition || snapshot?.state || 'CONNECTING';
  }


  function runtimeSources() {
    return snapshot?.runtime_scene?.sources || [];
  }

  function runtimeMutable() {
    return !!(
      transportConnected
      && snapshot?.managed
      && snapshot?.state === 'LIVE'
      && snapshot?.output?.active
    );
  }

  function runtimeOverrideCount() {
    return Object.keys(snapshot?.runtime_scene?.overrides || {}).length;
  }

  function renderRuntimeSources({force = false} = {}) {
    const scene = snapshot?.runtime_scene;
    const sources = runtimeSources();
    const canMutate = runtimeMutable();
    const signature = JSON.stringify({
      scene: scene || null,
      can_mutate: canMutate,
    });
    const state = $('#live-sources-state');
    const stateValue = scene?.status || (snapshot?.state === 'LIVE' ? 'UNAVAILABLE' : 'IDLE');
    state.textContent = stateValue;
    tone(state, stateValue === 'PASS' ? 'ok' : stateValue === 'DRIFTED' ? 'bad' : stateValue === 'IDLE' ? 'neutral' : 'warn');

    $('#live-sources-count').textContent = String(sources.length);
    $('#live-overrides-count').textContent = String(runtimeOverrideCount());
    $('#live-sources-empty').hidden = sources.length > 0;

    if (!force && signature === lastRuntimeSceneSignature) return;
    lastRuntimeSceneSignature = signature;

    const root = $('#live-source-list');
    root.replaceChildren();

    for (const source of sources) {
      const row = document.createElement('section');
      row.className = 'live-source-row';
      row.dataset.sourceId = source.id || '';

      const heading = document.createElement('div');
      heading.className = 'live-source-heading';
      const name = document.createElement('strong');
      name.textContent = source.name || source.id || 'Source';
      const badge = document.createElement('span');
      badge.className = 'state-pill';
      const overridden = source.override && Object.keys(source.override).length > 0;
      const drifted = Array.isArray(source.drift) && source.drift.length > 0;
      badge.textContent = drifted ? 'DRIFT' : overridden ? 'RUNTIME OVERRIDE' : 'BASELINE';
      tone(badge, drifted ? 'bad' : overridden ? 'blue' : 'neutral');
      heading.append(name, badge);
      row.append(heading);

      const baselineLine = document.createElement('div');
      baselineLine.className = 'live-source-state-line';
      const baselineLabel = document.createElement('span');
      baselineLabel.textContent = 'Baseline';
      const baselineValue = document.createElement('strong');
      const baselinePosition = source.baseline?.position;
      baselineValue.textContent = (source.baseline?.visible ? 'Visible' : 'Hidden')
        + (baselinePosition ? ' · X ' + baselinePosition.x + ' · Y ' + baselinePosition.y : '');
      baselineLine.append(baselineLabel, baselineValue);
      row.append(baselineLine);

      const actualLine = document.createElement('div');
      actualLine.className = 'live-source-state-line';
      const actualLabel = document.createElement('span');
      actualLabel.textContent = 'Visible now';
      const actualValue = document.createElement('strong');
      actualValue.textContent = source.actual?.visible === true ? 'Visible' : source.actual?.visible === false ? 'Hidden' : 'Unknown';
      actualLine.append(actualLabel, actualValue);
      row.append(actualLine);

      const visibilityActions = document.createElement('div');
      visibilityActions.className = 'live-source-actions';
      const toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'source-visibility-toggle';
      toggle.textContent = source.actual?.visible ? 'Hide' : 'Show';
      toggle.disabled = !canMutate;
      toggle.addEventListener('click', () => run(
        source.actual?.visible ? 'Hide live source' : 'Show live source',
        async () => {
          const visible = !source.actual?.visible;
          await liveSocket.request('live.source.visibility', {source_id: source.id, visible});
          activity((source.name || source.id) + (visible ? ' shown' : ' hidden') + ' (runtime override)', 'success');
        },
        '#live-sources-error',
      ));
      visibilityActions.append(toggle);
      row.append(visibilityActions);

      if (source.effective?.position) {
        const position = document.createElement('div');
        position.className = 'live-source-position';

        const xLabel = document.createElement('label');
        xLabel.textContent = 'X';
        const xInput = document.createElement('input');
        xInput.type = 'number';
        xInput.step = '1';
        xInput.className = 'source-position-x';
        xInput.value = source.actual?.position?.x ?? source.effective.position.x;
        xInput.disabled = !canMutate;
        xLabel.append(xInput);

        const yLabel = document.createElement('label');
        yLabel.textContent = 'Y';
        const yInput = document.createElement('input');
        yInput.type = 'number';
        yInput.step = '1';
        yInput.className = 'source-position-y';
        yInput.value = source.actual?.position?.y ?? source.effective.position.y;
        yInput.disabled = !canMutate;
        yLabel.append(yInput);

        const apply = document.createElement('button');
        apply.type = 'button';
        apply.className = 'apply-position';
        apply.textContent = 'Apply position';
        apply.disabled = !canMutate;
        apply.addEventListener('click', () => run(
          'Move live source',
          async () => {
            const x = Number(xInput.value);
            const y = Number(yInput.value);
            if (!Number.isFinite(x) || !Number.isFinite(y)) throw new Error('X and Y must be valid numbers.');
            await liveSocket.request('live.source.position', {source_id: source.id, x, y});
            activity((source.name || source.id) + ' moved to (' + x + ', ' + y + ')', 'success');
          },
          '#live-sources-error',
        ));
        position.append(xLabel, yLabel, apply);
        row.append(position);

        const move = document.createElement('div');
        move.className = 'live-source-move';
        const stepLabel = document.createElement('label');
        stepLabel.className = 'live-source-step';
        stepLabel.textContent = 'Step';
        const stepInput = document.createElement('input');
        stepInput.type = 'number';
        stepInput.min = '1';
        stepInput.step = '1';
        stepInput.value = '10';
        stepInput.className = 'source-move-step';
        stepInput.disabled = !canMutate;
        stepLabel.append(stepInput);
        move.append(stepLabel);

        const directions = [
          ['←', -1, 0, 'Move left'],
          ['↑', 0, -1, 'Move up'],
          ['↓', 0, 1, 'Move down'],
          ['→', 1, 0, 'Move right'],
        ];
        for (const [label, xFactor, yFactor, title] of directions) {
          const button = document.createElement('button');
          button.type = 'button';
          button.textContent = label;
          button.title = title;
          button.setAttribute('aria-label', title);
          button.disabled = !canMutate;
          button.addEventListener('click', () => run(
            title,
            async () => {
              const step = Number(stepInput.value);
              if (!Number.isFinite(step) || step <= 0) throw new Error('Move step must be greater than zero.');
              const dx = xFactor * step;
              const dy = yFactor * step;
              await liveSocket.request('live.source.move', {source_id: source.id, dx, dy});
              activity((source.name || source.id) + ' moved by (' + dx + ', ' + dy + ')', 'success');
            },
            '#live-sources-error',
          ));
          move.append(button);
        }
        row.append(move);
      }

      const actions = document.createElement('div');
      actions.className = 'live-source-actions';
      const reset = document.createElement('button');
      reset.type = 'button';
      reset.className = 'source-reset-button';
      reset.textContent = 'Reset to baseline';
      reset.disabled = !canMutate || !overridden;
      reset.addEventListener('click', () => run(
        'Reset live source',
        async () => {
          await liveSocket.request('live.source.reset', {source_id: source.id});
          activity((source.name || source.id) + ' restored to profile baseline', 'success');
        },
        '#live-sources-error',
      ));
      actions.append(reset);
      row.append(actions);

      if (drifted) {
        const drift = document.createElement('p');
        drift.className = 'error-message';
        drift.textContent = 'Unexpected drift: ' + source.drift.join(', ');
        row.append(drift);
      }

      root.append(row);
    }

    $('#reset-live-sources-button').disabled = !canMutate || runtimeOverrideCount() === 0;
  }

  function renderLive() {
    const state = liveDisplayState();
    const output = snapshot?.output || {};
    const activeDestination = snapshot?.managed ? snapshot.destination : selectedDestination();
    const activeProfile = snapshot?.managed ? snapshot.profile : selectedProfileSummary();
    const uptime = ui.formatDuration(Number(output.duration_ms || 0) / 1000);

    $('#stream-page-state').textContent = state;
    tone($('#stream-page-state'), stateTone(state));
    $('#live-state-pill').textContent = state;
    tone($('#live-state-pill'), stateTone(state));

    $('#live-summary-destination').textContent = activeDestination?.name || '--';
    $('#live-summary-uptime').textContent = uptime;
    $('#live-summary-output').textContent = output.active ? 'Active' : 'Inactive';
    $('#live-destination').textContent = activeDestination?.name || '--';
    $('#live-profile').textContent = activeProfile?.name || '--';
    $('#live-output-active').textContent = output.active ? 'Yes' : 'No';
    $('#live-reconnecting').textContent = output.reconnecting ? 'Yes' : 'No';
    $('#live-uptime').textContent = uptime;
    $('#live-bytes').textContent = formatBytes(output.bytes_sent);
    $('#live-avg-bitrate').textContent = formatAverageBitrate(output.bytes_sent, output.duration_ms);
    $('#live-congestion').textContent = `${(Number(output.congestion || 0) * 100).toFixed(1)}%`;
    $('#live-skipped-frames').textContent = String(output.skipped_frames || 0);
    $('#live-total-frames').textContent = String(output.total_frames || 0);
    $('#live-active-fps').textContent = Number(output.active_fps || 0).toFixed(1);
    $('#live-cpu-usage').textContent = `${Number(output.cpu_usage || 0).toFixed(1)}%`;

    if (['RECOVERY_REQUIRED', 'RESTORE_FAILED'].includes(snapshot?.state)) {
      setError('#live-error', `${snapshot.state}: streaming recovery requires operator attention.`);
    } else if ($('#live-error').textContent?.includes('operator attention')) {
      setError('#live-error');
    }
    renderRuntimeSources();
    renderButtons();
  }

  function renderButtons() {
    const destination = selectedDestination();
    const locked = destinationLocked(destination);
    const transition = snapshot?.state;
    const mutationsDisabled = busy || !transportConnected || locked;
    const hasEditableDestination = editingNewDestination || !!destination;

    $('#destination-list').disabled = busy || !transportConnected || !!snapshot?.managed;
    $('#new-destination-button').disabled = busy || !transportConnected || !!snapshot?.managed;
    $('#delete-destination-button').disabled = mutationsDisabled || !destination || editingNewDestination;
    $('#destination-name').disabled = mutationsDisabled || !hasEditableDestination;
    $('#destination-type').disabled = mutationsDisabled || !hasEditableDestination;
    $('#destination-enabled').disabled = mutationsDisabled || !hasEditableDestination;
    for (const input of document.querySelectorAll('#destination-settings-fields input, #destination-settings-fields select')) {
      input.disabled = mutationsDisabled || !hasEditableDestination;
    }
    $('#save-destination-button').disabled = mutationsDisabled || !catalog.length || !hasEditableDestination;
    $('#credential-input').disabled = mutationsDisabled || !destination || editingNewDestination;
    $('#save-credential-button').disabled = mutationsDisabled || !destination || editingNewDestination || !$('#credential-input').value;
    $('#delete-credential-button').disabled = mutationsDisabled || !destination?.credential_configured || editingNewDestination;

    $('#stream-profile-list').disabled = busy || !!snapshot?.managed;
    $('#run-preflight-button').disabled = busy || !transportConnected || !selectedDestinationId || !selectedProfileId() || editingNewDestination || destinationDirty;

    const canStart = !busy
      && transportConnected
      && transition === 'IDLE'
      && !!destination
      && destination.enabled !== false
      && destination.credential_configured === true
      && !!selectedProfileId()
      && !sceneDraftBlocked()
      && !editingNewDestination
      && !destinationDirty
      && !$('#credential-input').value
      && preflightMatchesSelection();

    const recovery = ['RECOVERY_REQUIRED', 'RESTORE_FAILED'].includes(transition);
    const showStop = transition === 'LIVE' || recovery;
    const showStart = !['LIVE', 'STARTING', 'STOPPING'].includes(transition) && !recovery;
    $('#start-stream-button').hidden = !showStart;
    $('#stop-stream-button').hidden = !showStop;
    $('#start-stream-button').disabled = !canStart;
    $('#stop-stream-button').disabled = busy || !transportConnected;
    $('#stop-stream-button').textContent = recovery ? 'Retry Stop / Restore' : 'Stop Streaming';

    const runtimeDisabled = busy || !runtimeMutable();
    if (runtimeDisabled) {
      for (const element of document.querySelectorAll('#live-source-list button, #live-source-list input')) {
        element.disabled = true;
      }
    }
    $('#reset-live-sources-button').disabled = runtimeDisabled || runtimeOverrideCount() === 0;
  }

  async function startStreaming() {
    setError('#live-error');
    if (sceneDraftBlocked()) {
      throw new Error('Save or discard the unsaved Scene Profile changes before starting.');
    }
    if (!preflightMatchesSelection()) {
      throw new Error('Run a successful Preflight for the selected profile and destination first.');
    }
    pendingTransition = 'STARTING';
    renderLive();
    try {
      const result = await liveSocket.request('live.start', {
        profile_id: selectedProfileId(),
        destination_id: selectedDestinationId,
      });
      snapshot = {...snapshot, ...result};
      activity('stream start: ' + (result.state || 'complete'), 'success');
    } finally {
      pendingTransition = null;
      renderLive();
    }
  }

  async function stopStreaming() {
    setError('#live-error');
    pendingTransition = 'STOPPING';
    renderLive();
    try {
      const result = await liveSocket.request('live.stop', {});
      snapshot = {...snapshot, ...result};
      activity('stream stop: ' + (result.state || 'complete'), 'success');
      if (result.state === 'IDLE') invalidatePreflight();
    } finally {
      pendingTransition = null;
      renderLive();
    }
  }

  async function run(label, fn, errorSelector) {
    if (busy) return;
    busy = true;
    setError(errorSelector);
    renderButtons();
    try {
      await fn();
    } catch (error) {
      const message = publicError(error);
      setError(errorSelector, message);
      activity(`${label} failed: ${message}`, 'error');
    } finally {
      busy = false;
      renderDestinationState();
      renderProfile();
      renderLive();
      renderButtons();
    }
  }

  function renderActivitySummary() {
    const entries = [...document.querySelectorAll('#stream-activity-log .activity-entry')];
    const last = entries.at(-1);
    $('#stream-activity-last-event').textContent = last?.querySelector('span')?.textContent || 'No events';
    const warnings = entries.filter((item) => item.classList.contains('warning')).length;
    const errors = entries.filter((item) => item.classList.contains('error')).length;
    $('#stream-activity-warning-count').textContent = String(warnings);
    $('#stream-activity-error-count').textContent = `${errors} error${errors === 1 ? '' : 's'}`;
    tone($('#stream-activity-error-count'), errors ? 'bad' : 'neutral');
  }

  function reconcileManagedProfile() {
    const activeId = snapshot?.managed ? snapshot?.profile?.id : null;
    if (!activeId) return;
    const select = $('#stream-profile-list');
    if (![...select.options].some((option) => option.value === activeId)) {
      select.add(new Option(snapshot.profile?.name || 'Active profile', activeId));
    }
    if (select.value !== activeId) {
      select.value = activeId;
      stateStore?.updateSelection?.({
        profile_id: activeId,
        profile_name: snapshot.profile?.name || undefined,
      });
      loadProfileDetail(activeId);
    }
  }

  liveSocket.on('stream.snapshot', (next) => {
    snapshot = next;
    pendingTransition = null;
    if (next.state !== lastServerState) {
      activity(`stream state: ${next.state}`, ['LIVE', 'IDLE'].includes(next.state) ? 'success' : ['RECOVERY_REQUIRED', 'RESTORE_FAILED', 'OBS_NOT_READY'].includes(next.state) ? 'error' : 'info');
      lastServerState = next.state;
    }
    reconcileDestinationSelection();
    reconcileManagedProfile();
    renderProfile();
    renderLive();
  }, {replay: true});

  liveSocket.onState(({state}) => {
    transportConnected = state === 'connected';
    lastRuntimeSceneSignature = null;
    if (state === 'connected') {
      activity(everConnected ? 'live socket: reconnected' : 'live socket: connected', 'success');
      everConnected = true;
    } else if (state === 'disconnected') {
      activity('live socket: disconnected', 'warning');
    }
    renderRuntimeSources({force: true});
    renderButtons();
    if (!transportConnected) {
      const transportLabel = state === 'connecting' && !everConnected ? 'CONNECTING' : 'RECONNECTING';
      $('#stream-page-state').textContent = transportLabel;
      tone($('#stream-page-state'), 'warn');
      $('#live-state-pill').textContent = transportLabel;
      tone($('#live-state-pill'), 'warn');
    }
  }, {replay: true});

  $('#destination-list').addEventListener('change', () => {
    selectedDestinationId = $('#destination-list').value || null;
    editingNewDestination = false;
    destinationDirty = false;
    lastDestinationSignature = null;
    const destination = selectedDestination();
    if (destination) stateStore?.updateSelection?.({destination_id: destination.id, destination_name: destination.name});
    invalidatePreflight();
    renderDestinationForm(destination, {force: true});
    renderLive();
  });

  $('#new-destination-button').addEventListener('click', () => {
    editingNewDestination = true;
    selectedDestinationId = null;
    destinationDirty = true;
    stateStore?.updateSelection?.({destination_id: null, destination_name: null});
    invalidatePreflight();
    renderDestinationList();
    renderDestinationForm(null, {force: true});
    renderButtons();
  });

  $('#destination-type').addEventListener('change', () => {
    renderDestinationSettings({});
    markDestinationDirty();
  });
  $('#destination-name').addEventListener('input', markDestinationDirty);
  $('#destination-enabled').addEventListener('change', markDestinationDirty);
  $('#credential-input').addEventListener('input', renderButtons);

  $('#save-destination-button').addEventListener('click', () => run('Save destination', saveDestination, '#destination-error'));
  $('#delete-destination-button').addEventListener('click', () => run('Delete destination', deleteDestination, '#destination-error'));
  $('#save-credential-button').addEventListener('click', () => run('Save credential', saveCredential, '#destination-error'));
  $('#delete-credential-button').addEventListener('click', () => run('Remove credential', deleteCredential, '#destination-error'));

  $('#stream-profile-list').addEventListener('change', () => {
    const summary = selectedProfileSummary();
    stateStore?.updateSelection?.({
      profile_id: summary?.id || null,
      profile_name: summary?.name || null,
    });
    invalidatePreflight();
    loadProfileDetail(summary?.id || null);
  });

  $('#run-preflight-button').addEventListener('click', () => run('Preflight', runPreflight, '#preflight-error'));
  $('#start-stream-button').addEventListener('click', () => run('Start streaming', startStreaming, '#live-error'));
  $('#stop-stream-button').addEventListener('click', () => run('Stop streaming', stopStreaming, '#live-error'));
  $('#reset-live-sources-button').addEventListener('click', () => run(
    'Reset live scene',
    async () => {
      await liveSocket.request('live.scene.reset_overrides', {});
      activity('all live source overrides restored to profile baseline', 'success');
    },
    '#live-sources-error',
  ));

  window.addEventListener('streamops:streaming-selection', () => {
    renderProfile();
    renderButtons();
  });

  window.addEventListener('pageshow', () => {
    renderProfile();
    renderButtons();
    if (staticLoaded) {
      loadProfiles().catch((error) => setError('#profile-error', publicError(error)));
    }
  });

  new MutationObserver(renderActivitySummary).observe($('#stream-activity-log'), {childList: true});

  Promise.all([
    ui.fetchJson('/api/v1/stream-destination-types'),
    ui.fetchJson('/api/v1/scene-profiles'),
  ]).then(async ([typesResult, profileResult]) => {
    catalog = typesResult.types || [];
    profiles = profileResult.profiles || [];
    renderDestinationTypeOptions();
    lastDestinationSignature = null;
    reconcileDestinationSelection();

    const select = $('#stream-profile-list');
    const remembered = stateStore?.selection?.().profile_id;
    const activeId = snapshot?.managed ? snapshot?.profile?.id : null;
    let profileId = activeId || remembered;
    if (!profiles.some((item) => item.id === profileId)) profileId = profiles[0]?.id || null;
    select.replaceChildren();
    for (const profile of profiles) select.add(new Option(profile.name, profile.id));
    if (!profiles.length) {
      const empty = new Option('No saved profiles', '', true, true);
      empty.disabled = true;
      select.add(empty);
    } else {
      select.value = profileId;
      const summary = profiles.find((item) => item.id === profileId);
      stateStore?.updateSelection?.({profile_id: summary.id, profile_name: summary.name});
    }
    await loadProfileDetail(profileId);
    staticLoaded = true;
    renderDestinationState();
    renderPreflight(null);
    renderLive();
    renderButtons();
  }).catch((error) => {
    setError('#stream-page-error', publicError(error));
    activity('page setup failed: ' + publicError(error), 'error');
  });

  renderDestinationState();
  renderPreflight(null);
  renderProfile();
  renderLive();
  renderButtons();
})();
