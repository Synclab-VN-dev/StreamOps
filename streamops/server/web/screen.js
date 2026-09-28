const ui = window.StreamOpsUI;
const addActivity = ui.createActivityLog("#activity-log");
const preview = document.querySelector("#preview");
const emptyState = document.querySelector("#empty-state");
const captureTime = document.querySelector("#capture-time");
const captureResolution = document.querySelector("#capture-resolution");
const captureButton = document.querySelector("#capture-button");
const errorMessage = document.querySelector("#error-message");

let currentImageUrl = null;
let hasCapture = false;
let lastHealthState = null;

async function updateHealth() {
  let nextState;
  try {
    const health = await ui.fetchJson("/api/v1/health");
    ui.updateNodeStatus(health);
    nextState = health.capture_ready ? "ready" : "unavailable";
    if (nextState !== lastHealthState) {
      addActivity(
        health.capture_ready ? "Node health: online, capture ready" : "Node health: online, capture unavailable",
        health.capture_ready ? "success" : "info",
      );
    }
  } catch {
    ui.updateNodeStatus(null);
    nextState = "offline";
    if (nextState !== lastHealthState) addActivity("Node health: offline", "error");
  }
  lastHealthState = nextState;
}

async function loadLatest(url = `/api/v1/screen/latest?v=${Date.now()}`) {
  const response = await fetch(url, { cache: "no-store" });
  if (response.status === 404) {
    if (!hasCapture) showEmptyState();
    return false;
  }
  if (!response.ok) throw new Error(await ui.apiError(response));

  const blob = await response.blob();
  const nextUrl = URL.createObjectURL(blob);
  const loader = new Image();
  try {
    await new Promise((resolve, reject) => {
      loader.onload = resolve;
      loader.onerror = () => reject(new Error("The captured image could not be displayed."));
      loader.src = nextUrl;
    });
  } catch (error) {
    URL.revokeObjectURL(nextUrl);
    throw error;
  }

  const previousUrl = currentImageUrl;
  currentImageUrl = nextUrl;
  preview.src = nextUrl;
  preview.hidden = false;
  emptyState.hidden = true;
  hasCapture = true;
  captureButton.textContent = "Capture Again";
  const capturedAt = response.headers.get("X-Captured-At");
  captureTime.textContent = capturedAt ? `Captured ${ui.formatDateTime(capturedAt)}` : "Captured just now";
  const width = response.headers.get("X-Image-Width");
  const height = response.headers.get("X-Image-Height");
  captureResolution.textContent = width && height ? `${width} x ${height}` : "--";
  if (previousUrl) URL.revokeObjectURL(previousUrl);
  return true;
}

async function captureScreen() {
  setError("");
  addActivity("Capture requested");
  captureButton.disabled = true;
  captureButton.textContent = "Capturing...";
  try {
    const result = await ui.fetchJson("/api/v1/screen/capture", { method: "POST" });
    await loadLatest(result.latest_url);
    addActivity(`Capture completed ${result.width}x${result.height}`, "success");
  } catch (error) {
    const message = error.message || "Screen capture failed.";
    setError(message);
    addActivity(`Capture failed: ${message}`, "error");
  } finally {
    captureButton.disabled = false;
    captureButton.textContent = hasCapture ? "Capture Again" : "Capture Screen";
  }
}

function showEmptyState() {
  preview.hidden = true;
  emptyState.hidden = false;
  captureTime.textContent = "Waiting for first capture";
  captureResolution.textContent = "--";
}

function setError(message) {
  errorMessage.textContent = message;
  errorMessage.hidden = !message;
}

async function pollHealth() {
  await updateHealth();
  window.setTimeout(pollHealth, 15000);
}

captureButton.addEventListener("click", captureScreen);
addActivity("Page loaded");
pollHealth();
loadLatest().catch((error) => {
  setError(error.message);
  addActivity(`Latest capture failed: ${error.message}`, "error");
});
