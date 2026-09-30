(function () {
  async function apiError(response) {
    try {
      const body = await response.json();
      return body.error?.message || `Request failed (${response.status})`;
    } catch {
      return `Request failed (${response.status})`;
    }
  }

  async function fetchJson(url, options = {}) {
    const response = await fetch(url, { cache: "no-store", ...options });
    if (!response.ok) throw new Error(await apiError(response));
    return response.json();
  }

  function updateNodeStatus(health) {
    const dot = document.querySelector("#status-dot");
    const text = document.querySelector("#status-text");
    if (!dot || !text) return;
    if (!health) {
      dot.className = "status-dot offline";
      text.textContent = "Offline";
      return;
    }
    dot.className = health.capture_ready ? "status-dot online" : "status-dot warning";
    text.textContent = health.capture_ready ? "Online" : "Online, capture unavailable";
  }

  function formatDateTime(value) {
    if (!value) return "--";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
  }

  function formatDuration(totalSeconds) {
    if (!Number.isFinite(totalSeconds)) return "--";
    const seconds = Math.max(0, Math.floor(totalSeconds));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainder = seconds % 60;
    return [hours, minutes, remainder].map((part) => String(part).padStart(2, "0")).join(":");
  }

  function createActivityLog(selector) {
    const list = document.querySelector(selector);
    return function addActivity(message, level = "info") {
      if (!list) return;
      const item = document.createElement("li");
      item.className = `activity-entry ${level}`;
      const time = document.createElement("time");
      time.dateTime = new Date().toISOString();
      time.textContent = new Date().toLocaleTimeString([], { hour12: false });
      const text = document.createElement("span");
      text.textContent = message;
      item.append(time, text);
      list.append(item);
      if (item.offsetParent !== null) item.scrollIntoView({ block: "nearest" });
    };
  }

  window.StreamOpsUI = { apiError, createActivityLog, fetchJson, formatDateTime, formatDuration, updateNodeStatus };
})();
