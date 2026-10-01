const ui = window.StreamOpsUI;
const obsSocket = window.StreamOpsObs;
const addActivity = ui.createActivityLog('#activity-log');
const panel = document.querySelector('#obs-status-panel');
const stateElement = document.querySelector('#obs-state');
const statePill = document.querySelector('#obs-state-pill');
const stateDot = document.querySelector('#obs-status-dot');
const pidElement = document.querySelector('#obs-pid');
const startedElement = document.querySelector('#obs-started');
const uptimeElement = document.querySelector('#obs-uptime');
const sessionElement = document.querySelector('#obs-session');
const activeSessionElement = document.querySelector('#obs-active-session');
const interactiveElement = document.querySelector('#obs-interactive');
const executableElement = document.querySelector('#obs-executable');
const websocketElement = document.querySelector('#obs-websocket');
const websocketEndpointElement = document.querySelector('#obs-websocket-endpoint');
const obsVersionElement = document.querySelector('#obs-version');
const websocketVersionElement = document.querySelector('#obs-websocket-version');
const streamingElement = document.querySelector('#obs-streaming');
const recordingElement = document.querySelector('#obs-recording');
const lastOperationElement = document.querySelector('#obs-last-operation');
const startButton = document.querySelector('#start-button');
const stopButton = document.querySelector('#stop-button');
const restartButton = document.querySelector('#restart-button');
const errorMessage = document.querySelector('#error-message');
const runtimeSummaryUptime = document.querySelector('#runtime-summary-uptime');
const runtimeSummaryStreaming = document.querySelector('#runtime-summary-streaming');
const runtimeSummaryRecording = document.querySelector('#runtime-summary-recording');

let operationInFlight = false;
let latestStatus = null;
let lastStatusSignature = null;
let operationErrorLocked = false;
let transportConnected = false;

function renderSnapshot(snapshot, {log = true, clearError = true} = {}) {
  const status = snapshot.runtime;
  latestStatus = status;
  ui.updateNodeStatus(snapshot.node || null);
  renderStatus(status);
  window.dispatchEvent(new CustomEvent('streamops:obs-runtime-status', {detail: status}));
  window.dispatchEvent(new CustomEvent('streamops:obs-snapshot', {detail: snapshot}));
  if (clearError && !operationErrorLocked) setError(status.error || '');
  const signature = [
    status.state, status.process?.pid, status.process?.session_id,
    status.websocket?.connected, status.output?.streaming,
    status.output?.recording, snapshot.obs?.current_scene,
  ].join(':');
  if (log && signature !== lastStatusSignature) {
    addActivity(statusSummary(status), status.state === 'READY' ? 'success' : status.state === 'ERROR' ? 'error' : 'info');
  }
  lastStatusSignature = signature;
}

function renderStatus(status) {
  const process = status.process || {};
  const websocket = status.websocket || {};
  const output = status.output || {};
  stateElement.textContent = status.state;
  statePill.dataset.tone = status.state === 'READY' ? 'ok' : status.state === 'ERROR' ? 'bad' : 'warn';
  stateDot.className = status.state === 'READY' ? 'status-dot online' : status.state === 'ERROR' ? 'status-dot offline' : 'status-dot warning';
  pidElement.textContent = process.pid ?? '--';
  startedElement.textContent = ui.formatDateTime(process.started_at);
  const formattedUptime = ui.formatDuration(process.uptime_seconds);
  uptimeElement.textContent = formattedUptime;
  runtimeSummaryUptime.textContent = formattedUptime;
  sessionElement.textContent = process.session_id ?? '--';
  activeSessionElement.textContent = process.active_console_session_id ?? '--';
  interactiveElement.textContent = process.running ? (process.interactive ? 'Yes' : 'No') : '--';
  executableElement.textContent = process.executable_path || process.expected_executable_path || '--';
  websocketElement.textContent = websocket.connected ? 'Connected' : 'Unavailable';
  websocketEndpointElement.textContent = `${websocket.host || '127.0.0.1'}:${websocket.port || 4455}`;
  obsVersionElement.textContent = websocket.obs_version || '--';
  websocketVersionElement.textContent = websocket.obs_websocket_version || '--';
  const streamingText = formatOutput(output.streaming);
  const recordingText = formatOutput(output.recording);
  streamingElement.textContent = streamingText;
  recordingElement.textContent = recordingText;
  runtimeSummaryStreaming.textContent = streamingText;
  runtimeSummaryRecording.textContent = recordingText;
  lastOperationElement.textContent = formatLastOperation(status.last_operation);
  updateButtons(status);
}

function updateButtons(status = latestStatus) {
  const outputActive = status?.output?.streaming === true || status?.output?.recording === true;
  startButton.disabled = !transportConnected || operationInFlight || !['STOPPED', 'RUNNING_NO_WEBSOCKET'].includes(status?.state);
  stopButton.disabled = !transportConnected || operationInFlight || status?.state !== 'READY' || outputActive;
  restartButton.disabled = !transportConnected || operationInFlight || status?.state !== 'READY' || outputActive;
}

function renderDisconnected() {
  stateElement.textContent = 'RECONNECTING';
  statePill.dataset.tone = 'warn';
  stateDot.className = 'status-dot warning';
  startButton.disabled = true;
  stopButton.disabled = true;
  restartButton.disabled = true;
  window.dispatchEvent(new CustomEvent('streamops:obs-runtime-status', {detail: null}));
}

function renderOperationState(action) {
  operationInFlight = true;
  panel.setAttribute('aria-busy', 'true');
  stateElement.textContent = action === 'stop' ? 'STOPPING' : 'STARTING';
  statePill.dataset.tone = 'warn';
  stateDot.className = 'status-dot warning';
  updateButtons();
}

function finishOperationState() {
  operationInFlight = false;
  panel.removeAttribute('aria-busy');
  updateButtons();
}

async function runOperation(action) {
  if (operationInFlight || !transportConnected) return;
  addActivity(`${capitalize(action)} requested`);
  if (action !== 'start') {
    const warning = action === 'stop'
      ? 'Stop OBS? This action is blocked automatically if streaming or recording is active.'
      : 'Restart OBS? This action is blocked automatically if streaming or recording is active.';
    if (!window.confirm(warning)) { addActivity(`${capitalize(action)} cancelled`); return; }
    addActivity(`Operator confirmed ${action}`);
  }
  renderOperationState(action);
  operationErrorLocked = false;
  setError('');
  try {
    const result = await obsSocket.request(`obs.lifecycle.${action}`);
    addActivity(`${capitalize(action)} completed: ${result.state}`, 'success');
  } catch (error) {
    operationErrorLocked = true;
    const message = error.message || `OBS ${action} failed.`;
    setError(message);
    addActivity(`${capitalize(action)} failed: ${message}`, 'error');
  } finally {
    finishOperationState();
  }
}

function statusSummary(status) {
  if (status.state === 'READY') return `OBS status: READY (PID ${status.process.pid})`;
  if (status.state === 'STOPPED') return 'OBS status: STOPPED';
  if (status.state === 'RUNNING_NO_WEBSOCKET') return `OBS status: RUNNING_NO_WEBSOCKET (PID ${status.process.pid})`;
  if (status.state === 'STARTING') return 'OBS status: STARTING';
  return `OBS status: ERROR${status.error ? ` — ${status.error}` : ''}`;
}

function formatOutput(value) {
  if (value === true) return 'Yes';
  if (value === false) return 'No';
  return 'Unknown';
}

function formatLastOperation(operation) {
  if (!operation) return '--';
  const operationError = operation.error ? ` · ${operation.error}` : '';
  return `${operation.action} · ${operation.result} · ${ui.formatDateTime(operation.timestamp)}${operationError}`;
}

function capitalize(value) { return value.charAt(0).toUpperCase() + value.slice(1); }
function setError(message) { errorMessage.textContent = message; errorMessage.hidden = !message; }

function updateLocalUptime() {
  const started = latestStatus?.process?.started_at;
  if (!started || !latestStatus?.process?.running) return;
  const formatted = ui.formatDuration(Math.max(0, Math.floor((Date.now() - new Date(started).getTime()) / 1000)));
  uptimeElement.textContent = formatted;
  runtimeSummaryUptime.textContent = formatted;
}

startButton.addEventListener('click', () => runOperation('start'));
stopButton.addEventListener('click', () => runOperation('stop'));
restartButton.addEventListener('click', () => runOperation('restart'));
obsSocket.on('obs.snapshot', (snapshot) => renderSnapshot(snapshot), {replay: true});
obsSocket.onState(({state, wasConnected}) => {
  transportConnected = state === 'connected';
  if (state === 'connected') {
    addActivity('OBS dashboard connection established', 'success');
    updateButtons();
  } else if (state === 'disconnected' || state === 'connecting') {
    renderDisconnected();
    if (wasConnected) addActivity('OBS dashboard connection lost; reconnecting', 'info');
  }
}, {replay: true});
addActivity('Page loaded');
window.setInterval(updateLocalUptime, 1000);
