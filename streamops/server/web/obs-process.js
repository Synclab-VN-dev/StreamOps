const ui = window.StreamOpsUI;
const addActivity = ui.createActivityLog("#activity-log");
const panel = document.querySelector("#obs-status-panel");
const stateElement = document.querySelector("#obs-state");
const stateDot = document.querySelector("#obs-status-dot");
const pidElement = document.querySelector("#obs-pid");
const startedElement = document.querySelector("#obs-started");
const uptimeElement = document.querySelector("#obs-uptime");
const sessionElement = document.querySelector("#obs-session");
const activeSessionElement = document.querySelector("#obs-active-session");
const interactiveElement = document.querySelector("#obs-interactive");
const executableElement = document.querySelector("#obs-executable");
const websocketElement = document.querySelector("#obs-websocket");
const websocketEndpointElement = document.querySelector("#obs-websocket-endpoint");
const obsVersionElement = document.querySelector("#obs-version");
const websocketVersionElement = document.querySelector("#obs-websocket-version");
const streamingElement = document.querySelector("#obs-streaming");
const recordingElement = document.querySelector("#obs-recording");
const lastOperationElement = document.querySelector("#obs-last-operation");
const startButton = document.querySelector("#start-button");
const stopButton = document.querySelector("#stop-button");
const restartButton = document.querySelector("#restart-button");
const errorMessage = document.querySelector("#error-message");

let operationInFlight = false;
let statusRequestInFlight = null;
let lastStatusSignature = null;
let latestStatus = null;

async function updateHealth() {
  try {
    ui.updateNodeStatus(await ui.fetchJson("/api/v1/health"));
  } catch {
    ui.updateNodeStatus(null);
  }
}

async function updateObsStatus({ log = true, force = false, clearError = true } = {}) {
  if (operationInFlight && !force) return;
  if (statusRequestInFlight) {
    await statusRequestInFlight;
    if (!force) return;
  }
  const request = fetchAndRenderStatus({ log, clearError, force });
  statusRequestInFlight = request;
  try {
    await request;
  } finally {
    if (statusRequestInFlight === request) statusRequestInFlight = null;
  }
}

async function fetchAndRenderStatus({ log, clearError, force }) {
  try {
    const status = await ui.fetchJson("/api/v1/obs/process/status");
    if (operationInFlight && !force) return;
    latestStatus = status;
    renderStatus(status);
    if (clearError) setError(status.error || "");
    const signature = [
      status.state,
      status.process?.pid,
      status.process?.session_id,
      status.websocket?.connected,
      status.output?.streaming,
      status.output?.recording,
    ].join(":");
    if (log && signature !== lastStatusSignature) {
      addActivity(statusSummary(status), status.state === "READY" ? "success" : status.state === "ERROR" ? "error" : "info");
    }
    lastStatusSignature = signature;
  } catch (error) {
    if (operationInFlight && !force) return;
    latestStatus = null;
    renderErrorState();
    const message = error.message || "OBS status failed.";
    if (clearError) setError(message);
    if (log && lastStatusSignature !== "error") addActivity(`OBS status failed: ${message}`, "error");
    lastStatusSignature = "error";
  }
}

function renderStatus(status) {
  const process = status.process || {};
  const websocket = status.websocket || {};
  const output = status.output || {};
  stateElement.textContent = status.state;
  stateDot.className = status.state === "READY"
    ? "status-dot online"
    : status.state === "ERROR"
      ? "status-dot offline"
      : "status-dot warning";
  pidElement.textContent = process.pid ?? "--";
  startedElement.textContent = ui.formatDateTime(process.started_at);
  uptimeElement.textContent = ui.formatDuration(process.uptime_seconds);
  sessionElement.textContent = process.session_id ?? "--";
  activeSessionElement.textContent = process.active_console_session_id ?? "--";
  interactiveElement.textContent = process.running ? (process.interactive ? "Yes" : "No") : "--";
  executableElement.textContent = process.executable_path || process.expected_executable_path || "--";
  websocketElement.textContent = websocket.connected ? "Connected" : "Unavailable";
  websocketEndpointElement.textContent = `${websocket.host || "127.0.0.1"}:${websocket.port || 4455}`;
  obsVersionElement.textContent = websocket.obs_version || "--";
  websocketVersionElement.textContent = websocket.obs_websocket_version || "--";
  streamingElement.textContent = formatOutput(output.streaming);
  recordingElement.textContent = formatOutput(output.recording);
  lastOperationElement.textContent = formatLastOperation(status.last_operation);
  updateButtons(status);
}

function updateButtons(status) {
  const streaming = status.output?.streaming === true;
  const recording = status.output?.recording === true;
  const outputActive = streaming || recording;
  startButton.disabled = operationInFlight || !["STOPPED", "RUNNING_NO_WEBSOCKET"].includes(status.state);
  stopButton.disabled = operationInFlight || status.state !== "READY" || outputActive;
  restartButton.disabled = operationInFlight || status.state !== "READY" || outputActive;
}

function renderErrorState() {
  stateElement.textContent = "ERROR";
  stateDot.className = "status-dot offline";
  for (const element of [
    pidElement, startedElement, uptimeElement, sessionElement, activeSessionElement,
    interactiveElement, executableElement, websocketElement, websocketEndpointElement,
    obsVersionElement, websocketVersionElement, streamingElement, recordingElement,
    lastOperationElement,
  ]) {
    element.textContent = "--";
  }
  startButton.disabled = true;
  stopButton.disabled = true;
  restartButton.disabled = true;
}

function renderOperationState(action) {
  operationInFlight = true;
  panel.setAttribute("aria-busy", "true");
  stateElement.textContent = action === "stop" ? "Stopping" : "STARTING";
  stateDot.className = "status-dot warning";
  startButton.disabled = true;
  stopButton.disabled = true;
  restartButton.disabled = true;
}

function finishOperationState() {
  operationInFlight = false;
  panel.removeAttribute("aria-busy");
  if (latestStatus) updateButtons(latestStatus);
}

async function runOperation(action) {
  if (operationInFlight) return;
  addActivity(`${capitalize(action)} requested`);
  if (action !== "start") {
    const warning = action === "stop"
      ? "Stop OBS? This action is blocked automatically if streaming or recording is active."
      : "Restart OBS? This action is blocked automatically if streaming or recording is active.";
    if (!window.confirm(warning)) {
      addActivity(`${capitalize(action)} cancelled`);
      return;
    }
    addActivity(`Operator confirmed ${action}`);
  }
  renderOperationState(action);
  setError("");
  let failed = false;
  try {
    const result = await ui.fetchJson(`/api/v1/obs/process/${action}`, { method: "POST" });
    addActivity(`${capitalize(action)} completed: ${result.state}`, "success");
  } catch (error) {
    failed = true;
    const message = error.message || `OBS ${action} failed.`;
    setError(message);
    addActivity(`${capitalize(action)} failed: ${message}`, "error");
  } finally {
    await updateObsStatus({ force: true, clearError: !failed });
    finishOperationState();
  }
}

function statusSummary(status) {
  if (status.state === "READY") return `OBS status: READY (PID ${status.process.pid})`;
  if (status.state === "STOPPED") return "OBS status: STOPPED";
  if (status.state === "RUNNING_NO_WEBSOCKET") return `OBS status: RUNNING_NO_WEBSOCKET (PID ${status.process.pid})`;
  if (status.state === "STARTING") return "OBS status: STARTING";
  return `OBS status: ERROR${status.error ? ` — ${status.error}` : ""}`;
}

function formatOutput(value) {
  if (value === true) return "Yes";
  if (value === false) return "No";
  return "Unknown";
}

function formatLastOperation(operation) {
  if (!operation) return "--";
  const error = operation.error ? ` · ${operation.error}` : "";
  return `${operation.action} · ${operation.result} · ${ui.formatDateTime(operation.timestamp)}${error}`;
}

function capitalize(value) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function setError(message) {
  errorMessage.textContent = message;
  errorMessage.hidden = !message;
}

async function poll() {
  await Promise.all([updateHealth(), updateObsStatus()]);
  window.setTimeout(poll, 5000);
}

startButton.addEventListener("click", () => runOperation("start"));
stopButton.addEventListener("click", () => runOperation("stop"));
restartButton.addEventListener("click", () => runOperation("restart"));
addActivity("Page loaded");
poll();
