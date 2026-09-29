const ui = window.StreamOpsUI;
const addActivity = ui.createActivityLog("#activity-log");
const screenCardDot = document.querySelector("#screen-card-dot");
const screenCardStatus = document.querySelector("#screen-card-status");
const screenCardDetail = document.querySelector("#screen-card-detail");
const steamCardDot = document.querySelector("#steam-card-dot");
const steamCardStatus = document.querySelector("#steam-card-status");
const steamCardDetail = document.querySelector("#steam-card-detail");
const obsCardDot = document.querySelector("#obs-card-dot");
const obsCardStatus = document.querySelector("#obs-card-status");
const obsCardDetail = document.querySelector("#obs-card-detail");

let lastHealthSignature = null;
let lastSteamSignature = null;
let lastObsSignature = null;

async function updateHealth() {
  try {
    const health = await ui.fetchJson("/api/v1/health");
    ui.updateNodeStatus(health);
    screenCardDot.className = health.capture_ready ? "status-dot online" : "status-dot warning";
    screenCardStatus.textContent = "Available";
    screenCardDetail.textContent = health.capture_ready ? `Capture ready via ${health.capture_backend || "Windows"}.` : "Node online; capture is not ready yet.";
    const signature = `online:${health.capture_ready}:${health.capture_backend || "unknown"}`;
    if (signature !== lastHealthSignature) {
      addActivity(
        health.capture_ready
          ? `streamops-node: online, capture ready via ${health.capture_backend || "Windows"}`
          : "streamops-node: online, capture unavailable",
        health.capture_ready ? "success" : "info",
      );
    }
    lastHealthSignature = signature;
  } catch {
    ui.updateNodeStatus(null);
    screenCardDot.className = "status-dot offline";
    screenCardStatus.textContent = "Unavailable";
    screenCardDetail.textContent = "The node health check failed.";
    if (lastHealthSignature !== "offline") addActivity("streamops-node: offline", "error");
    lastHealthSignature = "offline";
  }
}

async function updateSteam() {
  try {
    const status = await ui.fetchJson("/api/v1/steam/status");
    steamCardDot.className = status.running ? "status-dot online" : "status-dot warning";
    steamCardStatus.textContent = status.running ? "Running" : "Stopped";
    steamCardDetail.textContent = status.running
      ? `PID ${status.pid}${status.interactive ? " · Interactive" : " · Non-interactive"}`
      : status.installation_detected ? "Steam is installed but not running." : "Steam installation was not detected.";
    const signature = `${status.state}:${status.pid}`;
    if (signature !== lastSteamSignature) {
      addActivity(
        status.running ? `Steam status: running (PID ${status.pid})` : "Steam status: stopped",
        status.running ? "success" : "info",
      );
    }
    lastSteamSignature = signature;
  } catch {
    steamCardDot.className = "status-dot offline";
    steamCardStatus.textContent = "Error";
    steamCardDetail.textContent = "Steam status could not be read.";
    if (lastSteamSignature !== "error") addActivity("Steam status: error", "error");
    lastSteamSignature = "error";
  }
}


async function updateObs() {
  try {
    const status = await ui.fetchJson("/api/v1/obs/process/status");
    obsCardStatus.textContent = status.state;
    obsCardDot.className = status.state === "READY"
      ? "status-dot online"
      : status.state === "ERROR"
        ? "status-dot offline"
        : "status-dot warning";
    if (status.state === "READY") {
      obsCardDetail.textContent = `PID ${status.process.pid} · WebSocket connected`;
    } else if (status.state === "STOPPED") {
      obsCardDetail.textContent = "OBS is not running.";
    } else if (status.state === "RUNNING_NO_WEBSOCKET") {
      obsCardDetail.textContent = `PID ${status.process.pid} · WebSocket unavailable`;
    } else {
      obsCardDetail.textContent = status.error || "OBS lifecycle state requires attention.";
    }
    const signature = `${status.state}:${status.process?.pid}:${status.websocket?.connected}`;
    if (signature !== lastObsSignature) {
      addActivity(
        status.state === "READY"
          ? `OBS status: READY (PID ${status.process.pid})`
          : `OBS status: ${status.state}`,
        status.state === "READY" ? "success" : status.state === "ERROR" ? "error" : "info",
      );
    }
    lastObsSignature = signature;
  } catch {
    obsCardDot.className = "status-dot offline";
    obsCardStatus.textContent = "Error";
    obsCardDetail.textContent = "OBS status could not be read.";
    if (lastObsSignature !== "error") addActivity("OBS status: error", "error");
    lastObsSignature = "error";
  }
}

async function poll() {
  await Promise.all([updateHealth(), updateSteam(), updateObs()]);
  window.setTimeout(poll, 15000);
}

addActivity("Page loaded");
poll();
