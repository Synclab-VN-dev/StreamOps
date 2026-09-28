const ui = window.StreamOpsUI;
const sceneName = "livestream-d4";
const addActivity = ui.createActivityLog("#activity-log");
const errorMessage = document.querySelector("#error-message");
const sourceList = document.querySelector("#source-list");
const preview = document.querySelector("#scene-preview");
const previewEmpty = document.querySelector("#preview-empty");
const previewStatus = document.querySelector("#preview-status");
const buttons = [...document.querySelectorAll("button")];

function setBusy(busy) {
  buttons.forEach((button) => { button.disabled = busy; });
}

function setError(message) {
  errorMessage.textContent = message;
  errorMessage.hidden = !message;
}

function setText(selector, value) {
  const node = document.querySelector(selector);
  if (node) node.textContent = value ?? "--";
}

function statusClass(value) {
  if (value === "PASS") return "check-status pass";
  if (value === "WARN") return "check-status warn";
  if (value === "FAIL") return "check-status fail";
  return "check-status";
}

async function loadObsStatus() {
  try {
    const status = await ui.fetchJson("/api/v1/obs/status");
    setText("#obs-state", status.connected ? "Connected" : "Disconnected");
    setText("#obs-connected", status.connected ? "Yes" : "No");
    setText("#obs-version", status.obs_version || "--");
    setText("#obs-current-scene", status.current_scene || "--");
    setText("#obs-streaming", status.streaming ? "Active" : "Stopped");
    setText("#obs-recording", status.recording ? "Active" : "Stopped");
    return status;
  } catch (error) {
    setText("#obs-state", "Unavailable");
    setText("#obs-connected", "No");
    throw error;
  }
}

function renderScene(scene) {
  const verify = scene.verify || {};
  setText("#scene-name", scene.name);
  setText("#scene-output", `${scene.video.output_width}×${scene.video.output_height} @ ${scene.video.fps} FPS`);
  setText("#scene-result", verify.status || "Unknown");
  setText("#scene-check-count", `${(verify.checks || []).length} checks`);

  const checksByRole = new Map();
  (verify.checks || []).forEach((check) => {
    const match = check.id.match(/^(?:source|item|audio)\.([^.]+)\.(.+)$/);
    if (!match) return;
    const [, role] = match;
    const current = checksByRole.get(role) || [];
    current.push(check);
    checksByRole.set(role, current);
  });

  sourceList.replaceChildren();
  scene.sources.forEach((source) => {
    const checks = checksByRole.get(source.role) || [];
    const overall = checks.some((item) => item.status === "FAIL")
      ? "FAIL"
      : checks.some((item) => item.status === "WARN")
        ? "WARN"
        : checks.length ? "PASS" : "UNKNOWN";
    const row = document.createElement("div");
    row.className = "source-row";
    const label = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = source.role;
    const detail = document.createElement("span");
    detail.textContent = source.source_name;
    label.append(name, detail);
    const meta = document.createElement("div");
    meta.className = "source-meta";
    meta.textContent = `${source.media}${source.signal_required ? " · signal required" : ""}`;
    const status = document.createElement("span");
    status.className = statusClass(overall);
    status.textContent = overall;
    row.append(label, meta, status);
    sourceList.append(row);
  });
}

async function loadScene() {
  const scene = await ui.fetchJson(`/api/v1/scenes/${sceneName}`);
  renderScene(scene);
  return scene;
}

async function loadPreview() {
  const response = await fetch(`/api/v1/scenes/${sceneName}/preview?v=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(await ui.apiError(response));
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const previous = preview.dataset.objectUrl;
  preview.dataset.objectUrl = url;
  preview.src = url;
  preview.hidden = false;
  previewEmpty.hidden = true;
  previewStatus.textContent = "Current OBS scene";
  if (previous) URL.revokeObjectURL(previous);
}

async function runAction(label, action, { refreshPreview = true } = {}) {
  setError("");
  setBusy(true);
  addActivity(`${label} requested`);
  try {
    const result = await action();
    addActivity(`${label} completed${result.status ? `: ${result.status}` : ""}`, result.status === "FAIL" ? "error" : "success");
    await Promise.allSettled([loadObsStatus(), loadScene()]);
    if (refreshPreview) await loadPreview().catch(() => {});
    return result;
  } catch (error) {
    setError(error.message || `${label} failed.`);
    addActivity(`${label} failed: ${error.message}`, "error");
    throw error;
  } finally {
    setBusy(false);
  }
}

async function waitForReview(jobId) {
  let lastState = null;
  while (true) {
    const job = await ui.fetchJson(`/api/v1/scene-reviews/${jobId}`);
    if (job.state !== lastState) {
      addActivity(`Review ${job.state}`);
      lastState = job.state;
    }
    if (job.state === "completed") return job;
    if (job.state === "failed") throw new Error(job.error || "Scene review failed.");
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
  }
}

document.querySelector("#apply-button").addEventListener("click", () => {
  runAction("Apply", () => ui.fetchJson(`/api/v1/scenes/${sceneName}/apply`, { method: "POST" })).catch(() => {});
});

document.querySelector("#verify-button").addEventListener("click", () => {
  runAction("Verify", () => ui.fetchJson(`/api/v1/scenes/${sceneName}/verify`, { method: "POST" })).catch(() => {});
});

document.querySelector("#activate-button").addEventListener("click", () => {
  runAction("Activate", () => ui.fetchJson(`/api/v1/scenes/${sceneName}/activate`, { method: "POST" })).catch(() => {});
});

document.querySelector("#review-button").addEventListener("click", () => {
  runAction("Review", async () => {
    const job = await ui.fetchJson(`/api/v1/scenes/${sceneName}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ seconds: 30 }),
    });
    addActivity(`Review queued: ${job.job_id}`);
    const completed = await waitForReview(job.job_id);
    return completed.result || { status: "PASS" };
  }).catch(() => {});
});

addActivity("Page loaded");
Promise.all([loadObsStatus(), loadScene()])
  .then(() => loadPreview().catch(() => {}))
  .catch((error) => {
    setError(error.message);
    addActivity(`Initial load failed: ${error.message}`, "error");
  });
