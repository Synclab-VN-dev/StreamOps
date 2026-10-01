(() => {
/* Profile editor: the draft is local until Save, and OBS actions use saved state. */
const ui = window.StreamOpsUI;
const $ = (selector) => document.querySelector(selector);
const activity = ui.createActivityLog('#activity-log');
let draft = null, saved = null, catalog = [], inventory = {options: {}}, busy = false, obsReady = false, currentObsScene = null;
let lastVerificationResult = null, lastReviewJob = null;
let selectedSourceType = null;
const expandedSourceIds = new Set();
const sourceUiKeys = new WeakMap();
let sourceUiCounter = 0;

function dirty() { return draft && JSON.stringify(draft) !== JSON.stringify(saved); }
function error(message = '') { $('#scene-error-message').textContent = message; $('#scene-error-message').hidden = !message; }
function tone(element, value) { element.dataset.tone = value; }
function state(value) {
  $('#profile-summary-state').textContent = value;
  tone($('#profile-summary-state'), value === 'Failed' ? 'bad' : ['Modified', 'Drifted'].includes(value) ? 'warn' : ['Saved', 'Applied'].includes(value) ? 'blue' : 'neutral');
}
function updateRuntimeState() {
  const element = $('#profile-runtime-state');
  let value = 'UNKNOWN', stateTone = 'neutral';
  if (draft && obsReady && currentObsScene) {
    value = draft.obs_scene_name === currentObsScene ? 'ACTIVE' : 'INACTIVE';
    stateTone = value === 'ACTIVE' ? 'ok' : 'warn';
  }
  element.textContent = value;
  tone(element, stateTone);
}
function sourceKey(source) {
  if (source.id) return source.id;
  if (!sourceUiKeys.has(source)) sourceUiKeys.set(source, 'draft-' + (++sourceUiCounter));
  return sourceUiKeys.get(source);
}
function updateProfileSummary() {
  $('#profile-summary-name').textContent = draft?.name || '--';
  $('#profile-summary-canvas').textContent = draft ? draft.canvas.width + '×' + draft.canvas.height + ' @ ' + draft.canvas.fps : '--';
  $('#profile-summary-sources').textContent = (draft?.sources?.length || 0) + ' configured';
  $('#canvas-summary-resolution').textContent = draft ? draft.canvas.width + '×' + draft.canvas.height : '--';
  $('#canvas-summary-fps').textContent = draft?.canvas?.fps ?? '--';
  $('#canvas-summary-context').textContent = draft?.name || '--';
}
function updateSourceSummary() {
  const sources = draft?.sources || [];
  $('#source-summary-configured').textContent = String(sources.length);
  $('#source-summary-enabled').textContent = String(sources.filter((source) => source.enabled).length);
  $('#source-summary-catalog').textContent = catalog.length + ' types';
}
function changed() { state(dirty() ? 'Modified' : 'Saved'); updateProfileSummary(); updateSourceSummary(); renderCanvas(); }
function buttons() {
  document.querySelectorAll('#scene-profile-manager [data-scene-action]').forEach((button) => {
    const independent = ['new-button', 'template-button', 'refresh-inventory'].includes(button.id);
    const runtimeAction = ['apply-button', 'verify-button', 'activate-button', 'review-button', 'review-run-button'].includes(button.id);
    button.disabled = busy || (!draft && !independent) || (runtimeAction && !obsReady);
  });
  $('#profile-list').disabled = busy;
  $('#confirm-source-button').disabled = busy || !draft || !selectedSourceType;
  document.querySelectorAll('#source-picker input').forEach((input) => {input.disabled = busy || !draft;});
  document.querySelectorAll('#scene-profile-manager .source-editor input, #scene-profile-manager .source-editor select, #profile-name, #canvas-width, #canvas-height, #canvas-fps').forEach((input) => {input.disabled = busy;});
}
async function run(label, fn) {
  if (busy) return;
  busy = true; buttons(); error();
  try { await fn(); } catch (e) { state('Failed'); error(e.message); activity(`${label} failed: ${e.message}`, 'error'); }
  finally { busy = false; buttons(); }
}
async function api(path, method = 'GET', payload) {
  const response = await fetch(`/api/v1/${path}`, {method, cache: 'no-store', headers: payload === undefined ? {} : {'Content-Type': 'application/json'}, body: payload === undefined ? undefined : JSON.stringify(payload)});
  if (!response.ok) throw new Error(await ui.apiError(response));
  return response.status === 204 ? null : response.json();
}
function canDiscard() { return !dirty() || confirm('Discard unsaved changes?'); }
function setProfile(profile) {
  draft = profile ? structuredClone(profile) : null;
  saved = profile ? structuredClone(profile) : null;
  expandedSourceIds.clear();
  $('#profile-name').value = draft?.name || '';
  for (const field of ['width', 'height', 'fps']) $('#canvas-' + field).value = draft?.canvas[field] ?? '';
  $('#source-list').replaceChildren();
  setPickerOpen(false);
  state(draft ? 'Saved' : 'No profile');
  updateRuntimeState();
  updateProfileSummary(); updateSourceSummary();
  renderSources(); renderCanvas(); buttons();
}
async function listProfiles(selected = draft?.id) {
  const result = await api('scene-profiles');
  const select = $('#profile-list'); select.replaceChildren();
  if (result.profiles.length) {
    result.profiles.forEach((p) => select.add(new Option(p.name, p.id)));
    select.value = selected || '';
  } else {
    const empty = new Option('No saved profiles', '', true, true);
    empty.disabled = true;
    select.add(empty);
  }
  $('#profile-count').textContent = `${result.profiles.length} profiles`;
  $('#store-errors').textContent = result.errors.map((e) => `${e.file}: ${e.error}`).join('\n');
  if (!draft && result.profiles.length) {
    select.value = result.profiles[0].id;
    setProfile(await api('scene-profiles/' + select.value));
  }
}
function sourceDescription(capability) {
  if (capability.video && capability.audio) return 'Video source · audio available';
  return capability.video ? 'Video source' : 'Audio source';
}
function renderSourcePicker() {
  const root = $('#source-picker-options'); root.replaceChildren();
  $('#source-picker-count').textContent = catalog.length + ' types';
  if (!catalog.some((item) => item.type === selectedSourceType)) selectedSourceType = catalog[0]?.type || null;
  for (const group of ['Video', 'Audio']) {
    const items = catalog.filter((item) => (item.video ? 'Video' : 'Audio') === group);
    if (!items.length) continue;
    const section = document.createElement('fieldset'); section.className = 'source-picker-group';
    const legend = document.createElement('legend'); legend.textContent = group; section.append(legend);
    for (const capability of items) {
      const option = document.createElement('label'); option.className = 'source-picker-option'; option.dataset.sourceType = capability.type;
      const input = document.createElement('input'); input.type = 'radio'; input.name = 'source-picker-type'; input.value = capability.type;
      input.checked = capability.type === selectedSourceType;
      const copy = document.createElement('span'); copy.className = 'source-picker-copy';
      const label = document.createElement('strong'); label.textContent = capability.label;
      const detail = document.createElement('span'); detail.textContent = sourceDescription(capability);
      copy.append(label, detail);
      const inventoryFields = (capability.fields || []).filter((field) => field.inventory).map((field) => field.label);
      if (inventoryFields.length) {
        const inventoryHint = document.createElement('small'); inventoryHint.textContent = 'Inventory: ' + inventoryFields.join(', '); copy.append(inventoryHint);
      }
      input.addEventListener('change', () => {
        selectedSourceType = input.value;
        document.querySelectorAll('.source-picker-option').forEach((item) => item.classList.toggle('selected', item.dataset.sourceType === selectedSourceType));
        buttons();
      });
      option.classList.toggle('selected', input.checked);
      option.append(input, copy); section.append(option);
    }
    root.append(section);
  }
  buttons();
}
function setPickerOpen(open) {
  $('#source-picker').hidden = !open;
  $('#add-source-button').setAttribute('aria-expanded', String(open));
  $('#add-source-button').textContent = open ? 'Close source picker' : 'Add source';
}
function addSelectedSource() {
  const cap = catalog.find((item) => item.type === selectedSourceType);
  if (!draft || !cap) throw new Error('Select a source type first.');
  const source = {name: cap.label, type: cap.type, enabled: true, layer: draft.sources.length, settings: {}, transform: null, audio: null, verification: {video_signal: false, audio_signal: false, audio_threshold_db: -50, sample_seconds: 2}};
  for (const item of cap.fields || []) if (item.default !== undefined) source.settings[item.key] = item.default;
  if (cap.video) source.transform = {x: 0, y: 0, width: draft.canvas.width, height: draft.canvas.height, crop_left: 0, crop_right: 0, crop_top: 0, crop_bottom: 0};
  else if (cap.audio) source.audio = {enabled: true, muted: false, volume_db: 0, sync_offset_ms: 0, tracks: {'1': true, '2': false, '3': false, '4': false, '5': false, '6': false}};
  draft.sources.push(source); renderSources(); changed(); setPickerOpen(false);
}
function field(container, labelText, value, change, options = {}) {
  const label = document.createElement('label'); label.textContent = labelText;
  let input;
  if (options.choices) {
    input = document.createElement('select');
    input.add(new Option('Select…', ''));
    options.choices.forEach((c) => input.add(new Option(c.label ?? String(c), String(c.value ?? c))));
    if (value !== undefined && value !== '' && ![...input.options].some((o) => o.value === String(value))) input.add(new Option(`${value} (saved / unavailable)`, String(value)));
    input.value = value ?? '';
  } else {
    input = document.createElement('input'); input.type = options.type || 'text';
    if (input.type === 'checkbox') input.checked = !!value;
    else input.value = value ?? '';
  }
  input.setAttribute('aria-label', labelText);
  if (options.min !== undefined) input.min = options.min;
  if (options.max !== undefined) input.max = options.max;
  if (options.type === 'number') input.step = options.integer ? '1' : 'any';
  input.required = !!options.required;
  input.addEventListener('input', () => {
    const next = options.type === 'checkbox' ? input.checked : options.numeric ? (input.value === '' ? undefined : Number(input.value)) : input.value;
    change(next); changed();
  });
  label.append(input); container.append(label); return input;
}
function renderSources() {
  const root = $('#source-list'); root.replaceChildren();
  if (!draft) { updateSourceSummary(); return; }
  draft.sources.forEach((source, index) => {
    const cap = catalog.find((c) => c.type === source.type);
    if (!cap) return;
    const key = sourceKey(source);
    const card = document.createElement('details'); card.className = 'source-editor'; card.dataset.sourceIndex = index; card.dataset.sourceKey = key;
    card.open = expandedSourceIds.has(key);
    card.addEventListener('toggle', () => card.open ? expandedSourceIds.add(key) : expandedSourceIds.delete(key));
    const summary = document.createElement('summary'); summary.className = 'source-editor-summary';
    const title = document.createElement('div');
    const name = document.createElement('strong'); name.textContent = (index + 1) + '. ' + (source.name || cap.label);
    const meta = document.createElement('span'); meta.textContent = cap.label + ' · Layer ' + source.layer;
    title.append(name, meta);
    const enabled = document.createElement('span'); enabled.className = 'source-state ' + (source.enabled ? 'enabled' : 'disabled'); enabled.textContent = source.enabled ? 'Enabled' : 'Disabled';
    summary.append(title, enabled); card.append(summary);
    const body = document.createElement('div'); body.className = 'source-editor-body';
    field(body, 'Source name', source.name, (v) => { source.name = v; name.textContent = (index + 1) + '. ' + (v || cap.label); }, {required: true});
    field(body, 'Source enabled', source.enabled, (v) => { source.enabled = v; enabled.className = 'source-state ' + (v ? 'enabled' : 'disabled'); enabled.textContent = v ? 'Enabled' : 'Disabled'; }, {type: 'checkbox'});
    field(body, 'Layer', source.layer, (v) => { source.layer = v; meta.textContent = cap.label + ' · Layer ' + v; }, {type: 'number', numeric: true, integer: true, min: 0, max: 999});
    for (const spec of cap.fields) {
      const choices = spec.enum || (spec.inventory ? inventory.options?.[source.type]?.[spec.key] || [] : null);
      field(body, spec.label, source.settings[spec.key], (v) => { if (v === undefined || v === '') delete source.settings[spec.key]; else source.settings[spec.key] = v; }, {choices, type: spec.type === 'boolean' ? 'checkbox' : spec.type === 'integer' ? 'number' : 'text', numeric: spec.type === 'integer', integer: true, min: spec.min, max: spec.max});
    }
    if (source.transform) {
      for (const transformKey of ['x', 'y', 'width', 'height', 'crop_left', 'crop_top', 'crop_right', 'crop_bottom']) {
        field(body, transformKey.replaceAll('_', ' '), source.transform[transformKey], (v) => {source.transform[transformKey] = v;}, {type: 'number', numeric: true, integer: true, min: ['x','y'].includes(transformKey) ? -16384 : ['width','height'].includes(transformKey) ? 1 : 0, max: 16384});
      }
    }
    if (cap.audio) {
      if (cap.video) field(body, 'Configure audio', !!source.audio, (v) => {
        source.audio = v ? {enabled: true, muted: false, volume_db: 0, sync_offset_ms: 0, tracks: {'1': true, '2': false, '3': false, '4': false, '5': false, '6': false}} : null;
        if (!v) source.verification.audio_signal = false;
        renderSources();
      }, {type: 'checkbox'});
      if (source.audio) {
        field(body, 'Audio enabled', source.audio.enabled, (v) => {source.audio.enabled = v;}, {type: 'checkbox'});
        field(body, 'Muted', source.audio.muted, (v) => {source.audio.muted = v;}, {type: 'checkbox'});
        field(body, 'Volume dB', source.audio.volume_db, (v) => {source.audio.volume_db = v;}, {type: 'number', numeric: true, min: -100, max: 26});
        field(body, 'Sync offset ms', source.audio.sync_offset_ms, (v) => {source.audio.sync_offset_ms = v;}, {type: 'number', numeric: true, integer: true, min: -950, max: 20000});
        for (let track = 1; track <= 6; track++) field(body, 'Track ' + track, source.audio.tracks[track], (v) => {source.audio.tracks[track] = v;}, {type: 'checkbox'});
        field(body, 'Require audio signal', source.verification.audio_signal, (v) => {source.verification.audio_signal = v;}, {type: 'checkbox'});
        field(body, 'Audio threshold dB', source.verification.audio_threshold_db, (v) => {source.verification.audio_threshold_db = v;}, {type: 'number', numeric: true, min: -100, max: 0});
      }
    }
    if (cap.video) field(body, 'Require video signal', source.verification.video_signal, (v) => {source.verification.video_signal = v;}, {type: 'checkbox'});
    field(body, 'Sample seconds', source.verification.sample_seconds, (v) => {source.verification.sample_seconds = v;}, {type: 'number', numeric: true, min: 0.5, max: 10});
    const remove = document.createElement('button'); remove.textContent = 'Remove source'; remove.type = 'button'; remove.className = 'danger-button';
    remove.addEventListener('click', () => { expandedSourceIds.delete(key); draft.sources.splice(index, 1); renderSources(); changed(); });
    body.append(remove); card.append(body); root.append(card);
  });
  updateSourceSummary();
}
function renderCanvas() {
  const canvas = $('#profile-canvas'); canvas.replaceChildren();
  updateProfileSummary();
  if (!draft) { $('#canvas-label').textContent = '--'; return; }
  const {width, height, fps} = draft.canvas;
  canvas.style.aspectRatio = `${width}/${height}`; $('#canvas-label').textContent = `${width}×${height} @ ${fps}`;
  draft.sources.filter((s) => s.enabled && s.transform).sort((a,b) => a.layer-b.layer).forEach((source) => {
    const box = document.createElement('div'), t = source.transform;
    box.className = 'canvas-source'; box.textContent = source.name;
    Object.assign(box.style, {left: `${100*t.x/width}%`, top: `${100*t.y/height}%`, width: `${100*t.width/width}%`, height: `${100*t.height/height}%`});
    canvas.append(box);
  });
}
function validate() {
  for (const input of document.querySelectorAll('.source-editor input, #profile-name, #canvas-width, #canvas-height, #canvas-fps')) {
    if (input.checkValidity && !input.checkValidity()) {
      const sourceCard = input.closest('.source-editor');
      if (sourceCard) sourceCard.open = true;
      if (input.reportValidity) input.reportValidity();
      throw new Error('Please correct the highlighted field.');
    }
  }
  for (const source of draft.sources) {
    const cap = catalog.find((c) => c.type === source.type);
    if (cap.required_any?.length && !cap.required_any.some((key) => source.settings[key])) throw new Error(`${source.name}: select or enter ${cap.required_any.join(' or ')}.`);
  }
}
async function save(asNew = false) {
  validate();
  const payload = structuredClone(draft);
  if (asNew) {
    const name = prompt('Name for the new profile', `${draft.name} copy`);
    if (name === null) return;
    payload.name = name;
  }
  const result = await api(asNew ? 'scene-profiles' : `scene-profiles/${draft.id}`, asNew ? 'POST' : 'PUT', payload);
  setProfile(result); await listProfiles(result.id); activity(asNew ? 'Save As completed' : 'Profile saved', 'success');
}
async function preview(id) {
  const response = await fetch(`/api/v1/scene-profiles/${id}/preview`);
  if (!response.ok) throw new Error(await ui.apiError(response));
  const image = $('#scene-preview'), old = image.dataset.url;
  image.src = image.dataset.url = URL.createObjectURL(await response.blob()); image.hidden = false; $('#preview-empty').hidden = true;
  $('#preview-status').textContent = 'Preview available'; tone($('#preview-status'), 'ok'); if (old) URL.revokeObjectURL(old);
}
function displayValue(value) {
  if (value === null || value === undefined || value === '') return '--';
  if (typeof value === 'string') return value;
  try { return JSON.stringify(value); } catch { return String(value); }
}
function renderCheckList(rootSelector, checks) {
  const root = $(rootSelector); root.replaceChildren();
  for (const check of checks || []) {
    const item = document.createElement('details'); item.className = 'verification-check'; item.dataset.status = check.status;
    const summary = document.createElement('summary');
    const badge = document.createElement('span'); badge.className = 'check-badge ' + String(check.status || '').toLowerCase(); badge.textContent = check.status || '--';
    const title = document.createElement('div');
    const id = document.createElement('strong'); id.textContent = check.id || '--';
    const message = document.createElement('span'); message.textContent = check.message || '';
    title.append(id, message); summary.append(badge, title); item.append(summary);
    const diagnostics = document.createElement('div'); diagnostics.className = 'check-diagnostics';
    for (const pair of [['Expected', check.expected], ['Actual', check.actual]]) {
      const cell = document.createElement('div');
      const label = document.createElement('span'); label.textContent = pair[0];
      const value = document.createElement('code'); value.textContent = displayValue(pair[1]);
      cell.append(label, value); diagnostics.append(cell);
    }
    item.append(diagnostics); root.append(item);
  }
}
function statusCounts(checks) {
  const counts = {PASS: 0, WARN: 0, FAIL: 0};
  for (const check of checks || []) if (counts[check.status] !== undefined) counts[check.status]++;
  return counts;
}
function renderVerification(result) {
  lastVerificationResult = result && Object.keys(result).length ? result : null;
  const checks = result?.checks || [];
  const counts = statusCounts(checks);
  $('#obs-result').textContent = result?.status || '--';
  tone($('#obs-result'), result?.status === 'PASS' ? 'ok' : result?.status === 'WARN' ? 'warn' : result?.status === 'FAIL' ? 'bad' : 'neutral');
  $('#verification-ready').textContent = result?.ready_for_live === true ? 'Yes' : result?.ready_for_live === false ? 'No' : '--';
  $('#verification-generated').textContent = ui.formatDateTime(result?.generated_at);
  $('#verification-obs-version').textContent = result?.obs_version || '--';
  $('#verification-summary-ready').textContent = result?.ready_for_live === true ? 'For live' : result?.ready_for_live === false ? 'Not ready' : '--';
  $('#verification-summary-counts').textContent = checks.length ? counts.PASS + 'P · ' + counts.WARN + 'W · ' + counts.FAIL + 'F' : '0 checks';
  $('#verification-summary-time').textContent = result?.generated_at ? ui.formatDateTime(result.generated_at) : '--';
  renderCheckList('#verify-checks', checks);
}
function artifactFileName(value) {
  const parts = String(value || '').split(/[\\/]/);
  return parts[parts.length - 1] || 'artifact';
}
function artifactCanOpen(filename) {
  return /\.(?:avif|gif|jpe?g|mkv|mov|mp4|png|svg|webm|webp)$/i.test(filename);
}
function artifactUrl(jobId, key, download = false) {
  const base = `/api/v1/scene-reviews/${encodeURIComponent(jobId)}/artifacts/${encodeURIComponent(key)}`;
  return download ? base + '?download=true' : base;
}
function renderArtifacts(artifacts, jobId) {
  const root = $('#review-artifacts'); root.replaceChildren();
  const entries = Object.entries(artifacts || {});
  $('#review-artifact-count').textContent = String(entries.length);
  $('#review-summary-artifacts').textContent = String(entries.length);
  for (const [key, value] of entries) {
    const row = document.createElement('div'); row.className = 'artifact-row';
    const filename = artifactFileName(value);
    const name = document.createElement('strong'); name.textContent = filename;
    const actions = document.createElement('div'); actions.className = 'artifact-actions';
    if (jobId && artifactCanOpen(filename)) {
      const open = document.createElement('a'); open.textContent = 'Open'; open.href = artifactUrl(jobId, key);
      open.target = '_blank'; open.rel = 'noopener'; actions.append(open);
    }
    if (jobId) {
      const download = document.createElement('a'); download.textContent = 'Download'; download.href = artifactUrl(jobId, key, true);
      actions.append(download);
    }
    row.append(name, actions); root.append(row);
  }
}
function renderReview(job) {
  const previousJobId = lastReviewJob?.job_id;
  lastReviewJob = job || null;
  const result = job?.result || {};
  const checks = result.checks || [];
  const counts = statusCounts(checks);
  if (job?.job_id !== previousJobId) $('#review-result-checks').open = false;
  $('#review-state').textContent = job?.state || 'Not run';
  tone($('#review-state'), job?.state === 'completed' ? 'ok' : job?.state === 'failed' ? 'bad' : ['queued', 'running'].includes(job?.state) ? 'blue' : 'neutral');
  $('#review-summary-duration').textContent = job?.seconds ? job.seconds + 's' : '--';
  $('#review-summary-media').textContent = result.status || '--';
  const reviewError = $('#review-error'); reviewError.textContent = job?.state === 'failed' ? (job.error || 'Review failed') : ''; reviewError.hidden = !reviewError.textContent;
  $('#review-check-summary').textContent = checks.length ? counts.PASS + 'P · ' + counts.WARN + 'W · ' + counts.FAIL + 'F' : '0 checks';
  renderCheckList('#review-checks', checks);
  renderArtifacts(result.artifacts || {}, job?.job_id);
}
async function operation(name) {
  const id = draft.id;
  if (name === 'review') {
    const seconds = Number($('#review-seconds').value);
    let job;
    try {
      job = await api(`scene-profiles/${id}/review`, 'POST', {seconds});
    } catch (reviewRequestError) {
      renderReview({state: 'failed', seconds, error: reviewRequestError.message});
      throw reviewRequestError;
    }
    renderReview(job); activity(`Review queued: ${job.job_id}`);
    const jobId = job.job_id;
    do {
      await new Promise((resolve) => setTimeout(resolve, 500));
      job = await api(`scene-reviews/${jobId}`); renderReview(job);
    } while (['queued','running'].includes(job.state));
    if (job.state === 'failed') throw new Error(job.error || 'Review failed');
    const reviewResult = job.result || {};
    const structuralFail = (reviewResult.checks || []).some((check) => check.status === 'FAIL' && !check.id.startsWith('runtime.'));
    state(reviewResult.status === 'FAIL' ? (structuralFail ? 'Drifted' : 'Failed') : dirty() ? 'Modified' : 'Applied');
    activity('review: ' + (reviewResult.status || 'complete'), reviewResult.status === 'FAIL' ? 'error' : 'success');
    await preview(id).catch((e) => {$('#preview-status').textContent = e.message;});
    return;
  }
  let result = await api(`scene-profiles/${id}/${name}`, 'POST');
  if (name === 'activate') result = await api(`scene-profiles/${id}/verify`, 'POST');
  if (name === 'apply') {
    renderVerification({});
    state(dirty() ? 'Modified' : 'Applied');
    activity(`apply: ${result.changed ? 'changed' : 'no changes'}`, 'success');
  } else {
    renderVerification(result);
    const structuralFail = (result.checks || []).some((check) => check.status === 'FAIL' && !check.id.startsWith('runtime.'));
    state(result.status === 'FAIL' ? (structuralFail ? 'Drifted' : 'Failed') : dirty() ? 'Modified' : 'Applied');
    activity(`${name}: ${result.status || 'complete'}`, result.status === 'FAIL' ? 'error' : 'success');
  }
  await preview(id).catch((e) => {$('#preview-status').textContent = e.message;});
}
async function refreshInventory() {
  inventory = await api('obs/inventory');
  $('#inventory-status').textContent = inventory.errors?.length ? 'Inventory warning · ' + inventory.errors.length : 'Inventory ready';
  tone($('#inventory-status'), inventory.errors?.length ? 'warn' : 'ok');
  renderSources();
}
function bind(id, name, fn) { $(id).addEventListener('click', () => run(name, fn)); }
function setCanvasTab(tab) {
  const layout = tab === 'layout';
  $('#layout-view').hidden = !layout; $('#preview-view').hidden = layout;
  $('#layout-tab').classList.toggle('active', layout); $('#preview-tab').classList.toggle('active', !layout);
  $('#layout-tab').setAttribute('aria-selected', String(layout)); $('#preview-tab').setAttribute('aria-selected', String(!layout));
}
function updateActivitySummary() {
  const entries = [...document.querySelectorAll('#activity-log .activity-entry')];
  const last = entries.length ? entries[entries.length - 1] : null;
  $('#activity-last-event').textContent = last?.querySelector('span')?.textContent || 'No events';
  $('#activity-warning-count').textContent = String(entries.filter((item) => item.classList.contains('warning')).length);
  const errors = entries.filter((item) => item.classList.contains('error')).length;
  $('#activity-error-count').textContent = errors + ' error' + (errors === 1 ? '' : 's');
  tone($('#activity-error-count'), errors ? 'bad' : 'neutral');
}
bind('#new-button', 'New', async () => {if (!canDiscard()) return; setProfile(await api('scene-profiles', 'POST', {name: 'Untitled profile'})); await listProfiles();});
bind('#save-button', 'Save', () => save());
bind('#save-as-button', 'Save As', () => save(true));
bind('#duplicate-button', 'Duplicate', async () => {if (!canDiscard()) return; setProfile(await api(`scene-profiles/${draft.id}/duplicate`, 'POST')); await listProfiles();});
bind('#delete-button', 'Delete', async () => {if (!confirm(`Delete local profile “${draft.name}”? OBS resources are preserved.`)) return; await api(`scene-profiles/${draft.id}`, 'DELETE'); setProfile(null); await listProfiles();});
bind('#template-button', 'Template', async () => {if (!canDiscard()) return; setProfile(await api(`scene-profile-templates/${$('#template-list').value}/instantiate`, 'POST')); await listProfiles();});
bind('#refresh-inventory', 'Inventory', refreshInventory);
$('#add-source-button').addEventListener('click', () => setPickerOpen($('#source-picker').hidden));
bind('#confirm-source-button', 'Add source', async () => addSelectedSource());
for (const name of ['apply','verify','activate','review']) bind(`#${name}-button`, name, () => operation(name));
bind('#review-run-button', 'review', () => operation('review'));
$('#layout-tab').addEventListener('click', () => setCanvasTab('layout'));
$('#preview-tab').addEventListener('click', () => setCanvasTab('preview'));
$('#profile-list').addEventListener('change', () => run('Load', async () => {
  const id = $('#profile-list').value;
  if (!canDiscard()) {$('#profile-list').value = draft?.id || ''; return;}
  setProfile(await api(`scene-profiles/${id}`));
}));
$('#profile-name').addEventListener('input', () => {if (draft) {draft.name = $('#profile-name').value; changed();}});
for (const key of ['width','height','fps']) $('#canvas-'+key).addEventListener('input', () => {if (draft) {draft.canvas[key] = Number($('#canvas-'+key).value); changed();}});
window.addEventListener('beforeunload', (event) => {if (dirty()) {event.preventDefault(); event.returnValue = '';}});
window.addEventListener('streamops:obs-runtime-status', (event) => {
  const previous = obsReady;
  obsReady = event.detail?.state === 'READY';
  if (previous !== obsReady) {
    activity(obsReady ? 'OBS runtime READY · scene actions enabled' : 'OBS runtime not READY · scene actions disabled', obsReady ? 'success' : 'info');
  }
  buttons();
  updateRuntimeState();
});
window.addEventListener('streamops:obs-snapshot', (event) => {
  currentObsScene = event.detail?.obs?.current_scene || null;
  updateRuntimeState();
});

new MutationObserver(updateActivitySummary).observe($('#activity-log'), {childList: true});
setCanvasTab('layout');
renderVerification({});
renderReview(null);
updateProfileSummary();
updateSourceSummary();
buttons();
run('Load profiles', async () => {
  const [sources, templates] = await Promise.all([api('obs/source-catalog'), api('scene-profile-templates')]);
  catalog = sources.sources;
  updateSourceSummary();
  renderSourcePicker();
  templates.templates.forEach((t) => $('#template-list').add(new Option(t.name, t.id)));
  await listProfiles();
  await refreshInventory().catch((e) => {$('#inventory-status').textContent = 'Inventory error · ' + e.message; tone($('#inventory-status'), 'bad');});
  activity('Profile manager loaded');
});
})();
