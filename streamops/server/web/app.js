const ui = window.StreamOpsUI;
const screenCardDot = document.querySelector("#screen-card-dot");
const screenCardStatus = document.querySelector("#screen-card-status");
const screenCardDetail = document.querySelector("#screen-card-detail");
const steamCardDot = document.querySelector("#steam-card-dot");
const steamCardStatus = document.querySelector("#steam-card-status");
const steamCardDetail = document.querySelector("#steam-card-detail");

async function updateHealth() {
  try {
    const health = await ui.fetchJson("/api/v1/health");
    ui.updateNodeStatus(health);
    screenCardDot.className = health.capture_ready ? "status-dot online" : "status-dot warning";
    screenCardStatus.textContent = "Available";
    screenCardDetail.textContent = health.capture_ready ? `Capture ready via ${health.capture_backend || "Windows"}.` : "Node online; capture is not ready yet.";
  } catch {
    ui.updateNodeStatus(null);
    screenCardDot.className = "status-dot offline";
    screenCardStatus.textContent = "Unavailable";
    screenCardDetail.textContent = "The node health check failed.";
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
  } catch {
    steamCardDot.className = "status-dot offline";
    steamCardStatus.textContent = "Error";
    steamCardDetail.textContent = "Steam status could not be read.";
  }
}

async function poll() {
  await Promise.all([updateHealth(), updateSteam()]);
  window.setTimeout(poll, 15000);
}

poll();
