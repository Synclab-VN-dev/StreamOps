(() => {
  const SELECTION_KEY = 'streamops.streaming.selection.v1';
  const SCENE_DRAFT_KEY = 'streamops.scene-draft.v1';

  function read(key) {
    try {
      const raw = sessionStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  }

  function write(key, value) {
    try {
      if (value === null) sessionStorage.removeItem(key);
      else sessionStorage.setItem(key, JSON.stringify(value));
    } catch {
      // Session storage is an optimization for cross-page UX only.
    }
  }

  function selection() {
    const value = read(SELECTION_KEY);
    return value && typeof value === 'object' ? value : {};
  }

  function updateSelection(patch) {
    const current = selection();
    const next = {...current, ...patch};
    for (const key of Object.keys(next)) {
      if (next[key] === undefined || next[key] === null || next[key] === '') delete next[key];
    }
    if (JSON.stringify(current) === JSON.stringify(next)) return current;
    write(SELECTION_KEY, next);
    window.dispatchEvent(new CustomEvent('streamops:streaming-selection', {detail: next}));
    return next;
  }

  function invalidatePreflight() {
    const current = selection();
    delete current.preflight_status;
    delete current.preflight_profile_id;
    delete current.preflight_destination_id;
    delete current.preflight_at;
    write(SELECTION_KEY, current);
    window.dispatchEvent(new CustomEvent('streamops:streaming-selection', {detail: current}));
    return current;
  }

  function recordPreflight(result, profileId, destinationId) {
    return updateSelection({
      preflight_status: result?.status || 'FAIL',
      preflight_profile_id: profileId,
      preflight_destination_id: destinationId,
      preflight_at: new Date().toISOString(),
    });
  }

  function captureSceneDraft(draft, saved) {
    if (!draft || !saved || !saved.id) {
      write(SCENE_DRAFT_KEY, null);
      return;
    }
    const savedJson = JSON.stringify(saved);
    const dirty = JSON.stringify(draft) !== savedJson;
    write(SCENE_DRAFT_KEY, {
      profile_id: saved.id,
      profile_name: draft.name || saved.name || null,
      dirty,
      saved_json: savedJson,
      draft: dirty ? structuredClone(draft) : null,
      updated_at: new Date().toISOString(),
    });
  }

  function sceneDraftMeta() {
    const value = read(SCENE_DRAFT_KEY);
    if (!value || typeof value !== 'object') return null;
    return {
      profile_id: value.profile_id || null,
      profile_name: value.profile_name || null,
      dirty: value.dirty === true,
      updated_at: value.updated_at || null,
    };
  }

  function restoreSceneDraft(savedProfile) {
    const value = read(SCENE_DRAFT_KEY);
    if (
      !value
      || value.dirty !== true
      || !savedProfile
      || value.profile_id !== savedProfile.id
      || !value.draft
    ) return null;

    if (value.saved_json !== JSON.stringify(savedProfile)) {
      write(SCENE_DRAFT_KEY, null);
      return {stale: true, draft: null};
    }
    return {stale: false, draft: structuredClone(value.draft)};
  }

  function clearSceneDraft() {
    write(SCENE_DRAFT_KEY, null);
  }

  window.StreamOpsStreamingState = {
    selection,
    updateSelection,
    invalidatePreflight,
    recordPreflight,
    captureSceneDraft,
    sceneDraftMeta,
    restoreSceneDraft,
    clearSceneDraft,
  };
})();
