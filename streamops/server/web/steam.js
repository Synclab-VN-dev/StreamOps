const ui = window.StreamOpsUI;
const addActivity = ui.createActivityLog("#activity-log");
const stateElement = document.querySelector("#steam-state");
const stateDot = document.querySelector("#steam-status-dot");
const pidElement = document.querySelector("#steam-pid");
const startedElement = document.querySelector("#steam-started");
const uptimeElement = document.querySelector("#steam-uptime");
const sessionElement = document.querySelector("#steam-session");
const interactiveElement = document.querySelector("#steam-interactive");
const installationElement = document.querySelector("#steam-installation");
const restartButton = document.querySelector("#restart-button");
const errorMessage = document.querySelector("#error-message");

let restartInFlight = false;
let lastStatusSignature = null;
let statusRequestInFlight = false;

async function updateHealth() {
  try {
    ui.updateNodeStatus(await ui.fetchJson("/api/v1/health"));
  } catch {
    ui.updateNodeStatus(null);
  }
}

async function updateSteamStatus({ log = true } = {}) {
  if (statusRequestInFlight) return;
  statusRequestInFlight = true;
  try {
    const status = await ui.fetchJson("/api/v1/steam/status");
    renderStatus(status);
    setError("");
    const signature = `${status.state}:${status.pid}:${status.interactive}:${status.installation_detected}`;
    if (log && signature !== lastStatusSignature) {
      addActivity(
        status.running ? `Steam status: running (PID ${status.pid})` : "Steam status: stopped",
        status.running ? "success" : "info",
      );
    }
    lastStatusSignature = signature;
  } catch (error) {
    renderErrorState();
    const message = error.message || "Steam status failed.";
    setError(message);
    if (log && lastStatusSignature !== "error") addActivity(`Steam status failed: ${message}`, "error");
    lastStatusSignature = "error";
  } finally {
    statusRequestInFlight = false;
  }
}

function renderStatus(status) {
  stateElement.textContent = status.running ? "Running" : "Stopped";
  stateDot.className = status.running ? "status-dot online" : "status-dot warning";
  pidElement.textContent = status.pid ?? "--";
  startedElement.textContent = ui.formatDateTime(status.started_at);
  uptimeElement.textContent = ui.formatDuration(status.uptime_seconds);
  sessionElement.textContent = status.session_id ?? "--";
  interactiveElement.textContent = status.running ? (status.interactive ? "Yes" : "No") : "--";
  installationElement.textContent = status.installation_detected ? "Detected" : "Not detected";
  restartButton.disabled = restartInFlight || !status.installation_detected;
}

function renderErrorState() {
  stateElement.textContent = "Error";
  stateDot.className = "status-dot offline";
  for (const element of [pidElement, startedElement, uptimeElement, sessionElement, interactiveElement]) {
    element.textContent = "--";
  }
  installationElement.textContent = "Unknown";
  restartButton.disabled = true;
}

async function restartSteam() {
  addActivity("Restart requested");
  if (!window.confirm("Restart Steam in Big Picture Mode? Active games or downloads may be interrupted.")) {
    addActivity("Restart cancelled");
    return;
  }
  addActivity("Operator confirmed restart");
  restartInFlight = true;
  restartButton.disabled = true;
  restartButton.textContent = "Restarting...";
  setError("");
  try {
    const result = await ui.fetchJson("/api/v1/steam/restart", { method: "POST" });
    addActivity(`Restart completed (PID ${result.pid})`, "success");
  } catch (error) {
    const message = error.message || "Steam restart failed.";
    setError(message);
    addActivity(`Restart failed: ${message}`, "error");
  } finally {
    restartInFlight = false;
    restartButton.textContent = "Restart in Big Picture";
    await updateSteamStatus();
  }
}

function setError(message) {
  errorMessage.textContent = message;
  errorMessage.hidden = !message;
}

async function poll() {
  await Promise.all([updateHealth(), updateSteamStatus()]);
  window.setTimeout(poll, 15000);
}

restartButton.addEventListener("click", restartSteam);
addActivity("Page loaded");
poll();
