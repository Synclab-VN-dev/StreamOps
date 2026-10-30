import { runtimeLog } from "./runtime-log";
const root = document.getElementById("root");

function showBootstrapState(message: string, failed = false) {
  if (!root) return;
  root.innerHTML = `<main style="margin:16px;padding:18px;width:248px;border:1px solid rgba(255,255,255,.6);border-radius:20px;background:rgba(243,243,244,.97);box-shadow:0 14px 35px rgba(0,0,0,.14);font:12px 'Segoe UI',sans-serif;color:${failed ? "#9e4945" : "#252a31"}">${message}</main>`;
}

async function report(phase: string, _detail?: string) {
  runtimeLog(phase.includes("ERROR") || phase.includes("FAILED") || phase.includes("REJECTION") ? "ERROR" : "INFO", "webview", phase === "BOOTSTRAP_STARTED" ? "START" : phase === "APP_MOUNT_REQUESTED" ? "READY" : "ERROR");
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("report_webview_diagnostic", { phase, detail: null });
  } catch {
    // Diagnostics must never become a startup dependency.
  }
}

showBootstrapState("Starting D4Planner Equipment HUD…");
void report("BOOTSTRAP_STARTED");

window.addEventListener("error", event => {
  const detail = event.error instanceof Error ? event.error.stack ?? event.error.message : event.message;
  showBootstrapState("HUD startup failed. See the private diagnostic report.", true);
  void report("WINDOW_ERROR", detail);
});
window.addEventListener("unhandledrejection", event => {
  const detail = event.reason instanceof Error ? event.reason.stack ?? event.reason.message : String(event.reason);
  showBootstrapState("HUD startup failed. See the private diagnostic report.", true);
  void report("UNHANDLED_REJECTION", detail);
});

void import("./app-entry")
  .then(({ mount }) => {
    if (!root) throw new Error("root element is missing");
    mount(root);
    void report("APP_MOUNT_REQUESTED");
  })
  .catch(error => {
    const detail = error instanceof Error ? error.stack ?? error.message : String(error);
    showBootstrapState("HUD startup failed. See the private diagnostic report.", true);
    void report("APP_IMPORT_FAILED", detail);
  });
