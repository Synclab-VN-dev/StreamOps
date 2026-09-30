(() => {
/* Profile editor: the draft is local until Save, and OBS actions use saved state. */
const ui = window.StreamOpsUI;
const $ = (selector) => document.querySelector(selector);
const activity = ui.createActivityLog('#activity-log');
let draft = null, saved = null, catalog = [], inventory = {options: {}}, busy = false, obsReady = false;

function dirty() { return draft && JSON.stringify(draft) !== JSON.stringify(saved); }
function error(message = '') { $('#scene-error-message').textContent = message; $('#scene-error-message').hidden = !message; }
function state(value) { $('#editor-state').textContent = value; }
function changed() { state(dirty() ? 'Modified' : 'Saved'); renderCanvas(); }
function buttons() {
  document.querySelectorAll('#scene-profile-manager button').forEach((button) => {
    const independent = ['new-button', 'template-button', 'refresh-inventory'].includes(button.id);
    const runtimeAction = ['apply-button', 'verify-button', 'activate-button', 'review-button'].includes(button.id);
    button.disabled = busy || (!draft && !independent) || (runtimeAction && !obsReady);
  });
  $('#profile-list').disabled = busy;
  document.querySelectorAll('#scene-profile-manager .source-editor input, #scene-profile-manager .source-editor select, #profile-name, [id^="canvas-"] input').forEach((input) => {input.disabled = busy;});
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
  $('#profile-name').value = draft?.name || '';
  for (const field of ['width', 'height', 'fps']) $('#canvas-' + field).value = draft?.canvas[field] ?? '';
  $('#source-list').replaceChildren();
  state(draft ? 'Saved' : 'No profile');
  renderSources(); renderCanvas(); buttons();
}
async function listProfiles(selected = draft?.id) {
  const result = await api('scene-profiles');
  const select = $('#profile-list'); select.replaceChildren();
  result.profiles.forEach((p) => select.add(new Option(p.name, p.id)));
  select.value = selected || '';
  $('#profile-count').textContent = `${result.profiles.length} profiles`;
  $('#store-errors').textContent = result.errors.map((e) => `${e.file}: ${e.error}`).join('\n');
  if (!draft && result.profiles.length) {
    select.value = result.profiles[0].id;
    setProfile(await api('scene-profiles/' + select.value));
  }
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
  if (!draft) return;
  draft.sources.forEach((source, index) => {
    const cap = catalog.find((c) => c.type === source.type);
    const card = document.createElement('fieldset'); card.className = 'source-editor'; card.dataset.sourceIndex = index;
    const legend = document.createElement('legend'); legend.textContent = `${index + 1}. ${cap.label}`; card.append(legend);
    field(card, 'Source name', source.name, (v) => {source.name = v;}, {required: true});
    field(card, 'Source enabled', source.enabled, (v) => {source.enabled = v;}, {type: 'checkbox'});
    field(card, 'Layer', source.layer, (v) => {source.layer = v;}, {type: 'number', numeric: true, integer: true, min: 0, max: 999});
    for (const spec of cap.fields) {
      const choices = spec.enum || (spec.inventory ? inventory.options?.[source.type]?.[spec.key] || [] : null);
      field(card, spec.label, source.settings[spec.key], (v) => {
        if (v === undefined || v === '') delete source.settings[spec.key]; else source.settings[spec.key] = v;
      }, {choices, type: spec.type === 'boolean' ? 'checkbox' : spec.type === 'integer' ? 'number' : 'text', numeric: spec.type === 'integer', integer: true, min: spec.min, max: spec.max});
    }
    if (source.transform) {
      for (const key of ['x', 'y', 'width', 'height', 'crop_left', 'crop_top', 'crop_right', 'crop_bottom']) {
        field(card, key.replaceAll('_', ' '), source.transform[key], (v) => {source.transform[key] = v;}, {type: 'number', numeric: true, integer: true, min: ['x','y'].includes(key) ? -16384 : ['width','height'].includes(key) ? 1 : 0, max: 16384});
      }
    }
    if (cap.audio) {
      if (cap.video) field(card, 'Configure audio', !!source.audio, (v) => {
        source.audio = v ? {enabled: true, muted: false, volume_db: 0, sync_offset_ms: 0, tracks: {'1': true, '2': false, '3': false, '4': false, '5': false, '6': false}} : null;
        if (!v) source.verification.audio_signal = false;
        renderSources();
      }, {type: 'checkbox'});
      if (source.audio) {
        field(card, 'Audio enabled', source.audio.enabled, (v) => {source.audio.enabled = v;}, {type: 'checkbox'});
        field(card, 'Muted', source.audio.muted, (v) => {source.audio.muted = v;}, {type: 'checkbox'});
        field(card, 'Volume dB', source.audio.volume_db, (v) => {source.audio.volume_db = v;}, {type: 'number', numeric: true, min: -100, max: 26});
        field(card, 'Sync offset ms', source.audio.sync_offset_ms, (v) => {source.audio.sync_offset_ms = v;}, {type: 'number', numeric: true, integer: true, min: -950, max: 20000});
        for (let track = 1; track <= 6; track++) field(card, `Track ${track}`, source.audio.tracks[track], (v) => {source.audio.tracks[track] = v;}, {type: 'checkbox'});
        field(card, 'Require audio signal', source.verification.audio_signal, (v) => {source.verification.audio_signal = v;}, {type: 'checkbox'});
        field(card, 'Audio threshold dB', source.verification.audio_threshold_db, (v) => {source.verification.audio_threshold_db = v;}, {type: 'number', numeric: true, min: -100, max: 0});
      }
    }
    if (cap.video) field(card, 'Require video signal', source.verification.video_signal, (v) => {source.verification.video_signal = v;}, {type: 'checkbox'});
    field(card, 'Sample seconds', source.verification.sample_seconds, (v) => {source.verification.sample_seconds = v;}, {type: 'number', numeric: true, min: 0.5, max: 10});
    const remove = document.createElement('button'); remove.textContent = 'Remove source';
    remove.addEventListener('click', () => {draft.sources.splice(index, 1); renderSources(); changed();}); card.append(remove); root.append(card);
  });
}
function renderCanvas() {
  const canvas = $('#profile-canvas'); canvas.replaceChildren();
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
  for (const input of document.querySelectorAll('.source-editor input, #profile-name, [id^="canvas-"]')) {
    if (input.reportValidity && !input.reportValidity()) throw new Error('Please correct the highlighted field.');
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
  $('#preview-status').textContent = 'Current OBS state'; if (old) URL.revokeObjectURL(old);
}
function renderChecks(result) {
  const root = $('#verify-checks'); root.replaceChildren();
  for (const check of result.checks || []) {
    const item = document.createElement('li'); item.textContent = `${check.status} · ${check.id}: ${check.message}`; item.dataset.status = check.status; root.append(item);
  }
  $('#obs-result').textContent = result.status || '--';
}
async function operation(name) {
  const id = draft.id;
  let result = await api(`scene-profiles/${id}/${name}`, 'POST', name === 'review' ? {seconds: Number($('#review-seconds').value)} : undefined);
  if (name === 'review') {
    activity(`Review queued: ${result.job_id}`);
    const jobId = result.job_id;
    do {
      await new Promise((resolve) => setTimeout(resolve, 500));
      result = await api(`scene-reviews/${jobId}`);
      $('#review-state').textContent = result.state;
    } while (['queued','running'].includes(result.state));
    renderChecks(result.result || {});
    if (result.state === 'failed') throw new Error(result.error || 'Review failed');
    result = result.result;
  } else if (name === 'activate') {
    result = await api(`scene-profiles/${id}/verify`, 'POST');
  }
  if (name === 'apply') {
    renderChecks({});
    state(dirty() ? 'Modified' : 'Applied');
    activity(`apply: ${result.changed ? 'changed' : 'no changes'}`, 'success');
  } else {
    renderChecks(result);
    const structuralFail = (result.checks || []).some((c) => c.status === 'FAIL' && !c.id.startsWith('runtime.'));
    state(result.status === 'FAIL' ? (structuralFail ? 'Drifted' : 'Failed') : dirty() ? 'Modified' : 'Applied');
    activity(`${name}: ${result.status || 'complete'}`, result.status === 'FAIL' ? 'error' : 'success');
  }
  await preview(id).catch((e) => {$('#preview-status').textContent = e.message;});
}
async function refreshInventory() {
  inventory = await api('obs/inventory');
  $('#inventory-status').textContent = inventory.errors?.length ? inventory.errors.join(' · ') : 'Inventory loaded';
  renderSources();
}
function bind(id, name, fn) { $(id).addEventListener('click', () => run(name, fn)); }
bind('#new-button', 'New', async () => {if (!canDiscard()) return; setProfile(await api('scene-profiles', 'POST', {name: 'Untitled profile'})); await listProfiles();});
bind('#save-button', 'Save', () => save());
bind('#save-as-button', 'Save As', () => save(true));
bind('#duplicate-button', 'Duplicate', async () => {if (!canDiscard()) return; setProfile(await api(`scene-profiles/${draft.id}/duplicate`, 'POST')); await listProfiles();});
bind('#delete-button', 'Delete', async () => {if (!confirm(`Delete local profile “${draft.name}”? OBS resources are preserved.`)) return; await api(`scene-profiles/${draft.id}`, 'DELETE'); setProfile(null); await listProfiles();});
bind('#template-button', 'Template', async () => {if (!canDiscard()) return; setProfile(await api(`scene-profile-templates/${$('#template-list').value}/instantiate`, 'POST')); await listProfiles();});
bind('#refresh-inventory', 'Inventory', refreshInventory);
bind('#add-source-button', 'Add source', async () => {
  const cap = catalog.find((c) => c.type === $('#source-type').value);
  const source = {name: cap.label, type: cap.type, enabled: true, layer: draft.sources.length, settings: {}, transform: null, audio: null, verification: {video_signal: false, audio_signal: false, audio_threshold_db: -50, sample_seconds: 2}};
  for (const field of cap.fields) if (field.default !== undefined) source.settings[field.key] = field.default;
  if (cap.video) source.transform = {x: 0, y: 0, width: draft.canvas.width, height: draft.canvas.height, crop_left: 0, crop_right: 0, crop_top: 0, crop_bottom: 0};
  else if (cap.audio) source.audio = {enabled: true, muted: false, volume_db: 0, sync_offset_ms: 0, tracks: {'1': true, '2': false, '3': false, '4': false, '5': false, '6': false}};
  draft.sources.push(source); renderSources(); changed();
});
for (const name of ['apply','verify','activate','review']) bind(`#${name}-button`, name, () => operation(name));
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
});

buttons();
run('Load profiles', async () => {
  const [sources, templates] = await Promise.all([api('obs/source-catalog'), api('scene-profile-templates')]);
  catalog = sources.sources;
  catalog.forEach((c) => $('#source-type').add(new Option(c.label, c.type)));
  templates.templates.forEach((t) => $('#template-list').add(new Option(t.name, t.id)));
  await listProfiles();
  await refreshInventory().catch((e) => {$('#inventory-status').textContent = e.message;});
  activity('Profile manager loaded');
});
})();
