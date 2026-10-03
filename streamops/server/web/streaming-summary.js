(() => {
  const liveSocket = window.StreamOpsLive;
  const stateStore = window.StreamOpsStreamingState;
  const ui = window.StreamOpsUI;
  const $ = (selector) => document.querySelector(selector);
  let snapshot = null;

  function toneFor(state) {
    if (state === 'LIVE') return 'ok';
    if (['STARTING', 'STOPPING'].includes(state)) return 'blue';
    if (['RECOVERY_REQUIRED', 'RESTORE_FAILED', 'OBS_NOT_READY'].includes(state)) return 'bad';
    if (state === 'IDLE') return 'neutral';
    return 'warn';
  }

  function typeLabel(value) {
    if (!value) return '';
    return String(value)
      .split('_')
      .map((part) => part ? part[0].toUpperCase() + part.slice(1) : '')
      .join(' ');
  }

  function selectionContext() {
    const selection = stateStore?.selection?.() || {};
    const destinations = snapshot?.destinations || [];
    const selectedDestination = destinations.find((item) => item.id === selection.destination_id) || null;
    const destination = snapshot?.managed && snapshot?.destination
      ? snapshot.destination
      : selectedDestination;
    const profile = snapshot?.managed && snapshot?.profile
      ? snapshot.profile
      : selection.profile_id
        ? {id: selection.profile_id, name: selection.profile_name || null}
        : null;
    const preflightMatches = selection.preflight_status
      && selection.preflight_profile_id === profile?.id
      && selection.preflight_destination_id === destination?.id;
    return {
      selection,
      destination,
      profile,
      preflight: preflightMatches ? selection.preflight_status : null,
    };
  }

  function render() {
    const context = selectionContext();
    const state = snapshot?.state || 'CONNECTING';
    const destinationName = context.destination?.name || '--';
    const profileName = context.profile?.name || '--';

    $('#streaming-state-pill').textContent = state;
    $('#streaming-state-pill').dataset.tone = toneFor(state);
    $('#streaming-summary-destination').textContent = destinationName;
    $('#streaming-summary-profile').textContent = profileName;
    $('#streaming-overview-destination').textContent = context.destination
      ? destinationName + (context.destination.type ? ' · ' + typeLabel(context.destination.type) : '')
      : '--';
    $('#streaming-overview-profile').textContent = profileName;
    $('#streaming-overview-preflight').textContent = context.preflight || 'Not run';
    $('#streaming-overview-state').textContent = state;

    if (state === 'LIVE') {
      $('#streaming-summary-state-label').textContent = 'Uptime';
      $('#streaming-summary-state').textContent = ui.formatDuration((snapshot?.output?.duration_ms || 0) / 1000);
    } else {
      $('#streaming-summary-state-label').textContent = 'Status';
      $('#streaming-summary-state').textContent = state === 'CONNECTING' ? 'Connecting' : state;
    }
  }

  liveSocket.on('stream.snapshot', (next) => {
    snapshot = next;
    render();
  }, {replay: true});

  liveSocket.onState(({state}) => {
    if (state === 'connected') return;
    if (!snapshot) render();
    else {
      $('#streaming-state-pill').textContent = state === 'connecting' ? 'CONNECTING' : 'RECONNECTING';
      $('#streaming-state-pill').dataset.tone = 'warn';
    }
  }, {replay: true});

  window.addEventListener('streamops:streaming-selection', render);
  window.addEventListener('pageshow', render);
  render();
})();
