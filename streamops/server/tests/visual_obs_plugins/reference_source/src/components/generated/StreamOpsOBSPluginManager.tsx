import { useEffect, useRef, useState } from "react";
import { Puzzle, SlidersHorizontal, RadioTower, ChevronDown } from "lucide-react";
type Tone = "ok" | "warn" | "bad" | "neutral" | "blue";
function Pill({
  children,
  tone = "neutral"
}: {
  children: React.ReactNode;
  tone?: Tone;
}) {
  const map: Record<Tone, string> = {
    ok: "bg-emerald-50 text-emerald-700",
    warn: "bg-amber-50 text-amber-700",
    bad: "bg-red-50 text-red-700",
    blue: "bg-blue-50 text-blue-700",
    neutral: "bg-zinc-100 text-zinc-700"
  };
  return <span className={"rounded-full px-2.5 py-1 text-[11px] font-semibold " + map[tone]}>{children}</span>;
}
function Stat({
  label,
  value
}: {
  label: string;
  value: string;
}) {
  return <div><p className="text-[11px] text-zinc-500">{label}</p><p className="mt-0.5 truncate text-sm font-semibold">{value}</p></div>;
}
export const StreamOpsOBSPluginManager = () => {
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [restartRequired, setRestartRequired] = useState(true);
  const [openPlugin, setOpenPlugin] = useState<string | null>("multi");
  const [multiInstalled, setMultiInstalled] = useState(() => ["offline", "verify-failed", "rollback-failed", "recovery-required", "legacy-adopted"].includes(new URLSearchParams(window.location.search).get("state") || ""));
  const [activityOpen, setActivityOpen] = useState(false);
  const [scenario, setScenario] = useState(() => {
    // Read-only design scenario, never a production FE screenshot.
    const requested = new URLSearchParams(window.location.search).get("state") || "normal";
    return ["normal", "blocked", "loading", "empty", "offline", "verify-failed", "rollback-failed", "recovery-required", "legacy-adopted"].includes(requested) ? requested : "normal";
  });
  const [confirmAction, setConfirmAction] = useState<string | null>(null);
  // Match StreamOps FE: a native top-layer modal rather than an inline
  // confirmation card that shifts the page header and inventory down.
  const confirmDialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const modal = confirmDialogRef.current;
    if (!modal) return;
    if (confirmAction && !modal.open) modal.showModal();else if (!confirmAction && modal.open) modal.close();
  }, [confirmAction]);
  const scenarios = [["normal", "Normal"], ["installing", "Installing"], ["updating", "Updating"], ["restarting", "Restarting OBS"], ["verifying", "Verifying"], ["blocked", "Live / blocked"], ["rollback", "Rolling back"], ["restored", "Rollback success"], ["rollback-failed", "Rollback failed"], ["verify-failed", "Verify failed"], ["offline", "OBS offline"], ["vendor", "Vendor unavailable"], ["empty", "Empty"], ["loading", "Loading"], ["recovery-required", "Recovery required"], ["legacy-adopted", "Legacy adopted"], ["error", "Load error"]];
  const isOffline = scenario === "offline";
  const isLoading = scenario === "loading";
  const isEmpty = scenario === "empty";
  const isRecovery = scenario === "recovery-required" || scenario === "rollback-failed";
  const isVerifyFailed = scenario === "verify-failed";
  const isLegacy = scenario === "legacy-adopted";
  const readonlyPreview = isLoading || isEmpty || isOffline || isRecovery || scenario === "blocked";
  const displayStatus = isRecovery ? scenario === "rollback-failed" ? "Rollback failed" : "Recovery required" : isVerifyFailed ? "Verify failed" : isLegacy ? "Legacy adopted" : isOffline ? "Offline / unknown" : multiInstalled ? restartRequired ? "Restart required" : "Verified" : "Not installed";
  const displayTone: Tone = isRecovery || isVerifyFailed ? "bad" : isLegacy || isOffline ? "warn" : multiInstalled ? restartRequired ? "warn" : "ok" : "neutral";
  const action = (label: string) => {
    setConfirmAction(null);
    setBusy(label);
    setNotice(label + " requested");
    setTimeout(() => {
      setBusy(null);
      if (label === "Restart OBS") setRestartRequired(false);
      if (label === "Install") {
        setMultiInstalled(true);
        setRestartRequired(true);
      }
      setNotice(label + " completed");
      setTimeout(() => setNotice(null), 1400);
    }, 700);
  };
  return <main className="min-h-screen bg-[#f5f6f8] text-zinc-950">
    <div className="mx-auto w-full max-w-md px-4 pb-10 pt-4">
      <header className="mb-4">
        <a href="/obs" className="mb-3 inline-flex items-center gap-1 text-xs font-semibold text-zinc-500">← OBS Management</a>
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-zinc-500">StreamOps</p>
            <h1 className="text-2xl font-semibold tracking-tight">OBS Plugin Manager</h1>
            <p className="mt-1 text-xs text-zinc-500">Install, update and verify managed OBS plugins</p>
          </div>
          <Pill tone={isOffline ? "bad" : "ok"}>OBS {isOffline ? "OFFLINE" : "READY"}</Pill>
        </div>
      </header>

      {scenario !== "normal" && <section className={"mb-3 rounded-3xl border p-4 " + (["rollback-failed", "recovery-required", "verify-failed", "error", "vendor"].includes(scenario) ? "border-red-200 bg-red-50" : "border-amber-200 bg-amber-50")}><div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">{scenarios.find(s => s[0] === scenario)?.[1]}</h2><Pill tone={["rollback-failed", "recovery-required", "verify-failed", "error", "vendor"].includes(scenario) ? "bad" : "warn"}>Design preview</Pill></div><p className="mt-2 text-xs leading-5">{scenario === "blocked" ? "OBS is streaming or recording. Install, Update and Rollback are disabled; running outputs will not be stopped." : scenario === "rollback-failed" ? "Rollback failed. Recovery is required. The previous version cannot be claimed restored; preserve evidence and confirm backup integrity before any retry." : scenario === "recovery-required" ? "Recovery required after an interrupted plugin operation. Install, Update, Adopt and Rollback are blocked until the backend validates a preserved baseline." : scenario === "legacy-adopted" ? "Legacy baseline adopted and preserved. Not verified as an approved release. A separate approved-source Install and OBS restart are still required." : scenario === "restored" ? "Update failed but the previous version was restored and verified." : scenario === "offline" ? "OBS / WebSocket unavailable. Reconnect and refresh status; do not assume the operation succeeded." : scenario === "vendor" ? "OBS is ready, but the multi-RTMP Vendor probe is unavailable." : scenario === "empty" ? "No managed plugins in the registry." : scenario === "loading" ? "Loading inventory and plugin status…" : scenario === "error" ? "Could not load plugin inventory. Retry without changing installed files." : scenario === "verify-failed" ? "Plugin verification failed. Inspect the checks and retry after fixing the cause." : scenario === "rollback" ? "Restoring the previous plugin and configuration, then verifying OBS readiness." : scenario === "restarting" ? "Expected OBS restart in progress. Waiting for WebSocket reconnection." : scenario === "verifying" ? "Checking installed version, OBS READY, WebSocket and Vendor probe." : "Operation in progress: validating package, backing up configuration and applying files."}</p>{["error", "offline", "verify-failed"].includes(scenario) && <button onClick={() => setScenario("normal")} className="mt-3 rounded-xl border border-zinc-300 bg-white px-3 py-2 text-xs font-semibold">Retry / Refresh preview</button>}</section>}
      <dialog ref={confirmDialogRef} onCancel={() => setConfirmAction(null)} onClose={() => setConfirmAction(null)} aria-labelledby="plugin-confirm-title" className="m-auto w-[calc(100%-32px)] max-w-[440px] rounded-[20px] border border-zinc-200 bg-white p-0 text-zinc-900 shadow-[0_24px_80px_#09090b40] backdrop:bg-zinc-950/50">
        <div className="grid gap-3 p-[22px]">
          <h2 id="plugin-confirm-title" className="m-0 text-lg font-semibold">
            {confirmAction === "Install" ? "Install plugin?" : confirmAction === "Rollback" ? "Rollback plugin?" : `${confirmAction} plugin?`}
          </h2>
          <p className="m-0 text-xs leading-5 text-zinc-600">Multiple RTMP Outputs · obs-multi-rtmp</p>
          <p className="m-0 text-xs leading-5 text-zinc-700">
            {confirmAction === "Install" ? "Only the backend-selected approved release can be installed. Existing files/config will be handled by BE." : "Check OBS is idle and preserve the current plugin configuration before proceeding."}
          </p>
          <div className="mt-2.5 flex justify-end gap-2">
            <button type="button" onClick={() => setConfirmAction(null)} className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-xs font-semibold">Cancel</button>
            <button type="button" onClick={() => confirmAction && action(confirmAction)} className="rounded-xl bg-zinc-950 px-3 py-2 text-xs font-semibold text-white">Confirm</button>
          </div>
        </div>
      </dialog>
      {notice && <div className="mb-3 rounded-2xl border border-blue-100 bg-blue-50 px-3 py-2 text-xs font-medium text-blue-700">{notice}</div>}

      <section className="mb-3 rounded-3xl border border-black/5 bg-white p-4 shadow-sm">
        <div className="flex items-center justify-between gap-3">
          <div><h2 className="text-[15px] font-semibold">Manager overview</h2><p className="mt-0.5 text-xs text-zinc-500">Inventory from the StreamOps node</p></div>
          <button onClick={() => action("Refresh inventory")} disabled={!!busy || isLoading} className="rounded-xl border border-zinc-200 px-3 py-2 text-xs font-semibold disabled:opacity-40">Refresh</button>
        </div>
        <div className="mt-4 grid grid-cols-3 gap-2">
          <Stat label="Managed" value={isLoading || isOffline ? "—" : isEmpty ? "0" : "1"} /><Stat label="Installed" value={isLoading || isOffline ? "—" : multiInstalled ? "1" : "0"} /><Stat label="Attention" value={isLoading || isOffline ? "—" : isRecovery || isVerifyFailed ? "1" : multiInstalled && restartRequired && scenario === "normal" ? "1" : "0"} />
        </div>
      </section>

      {restartRequired && multiInstalled && scenario === "normal" && <section className="mb-3 rounded-3xl border border-amber-200 bg-amber-50 p-4">
        <div className="flex items-start justify-between gap-3"><div><p className="text-sm font-semibold text-amber-900">OBS restart required</p><p className="mt-1 text-xs leading-5 text-amber-800">Plugin files changed. Restart OBS before verification.</p></div><Pill tone="warn">Pending</Pill></div>
        <button onClick={() => action("Restart OBS")} disabled={!!busy} className="mt-3 w-full rounded-2xl bg-zinc-950 px-3 py-3 text-sm font-semibold text-white disabled:opacity-40">{busy === "Restart OBS" ? "Restarting…" : "Restart OBS"}</button>
      </section>}

      <div className="mb-3 flex items-center gap-2 px-1"><Puzzle className="h-4 w-4 text-zinc-600" aria-hidden="true" /><h2 className="text-sm font-semibold">Managed plugins</h2><div className="h-px flex-1 bg-zinc-200" /></div>
      <div className="space-y-3">
        {isLoading && <section aria-live="polite" className="rounded-3xl border border-zinc-200 bg-white p-4 shadow-sm">
          <p className="text-sm font-semibold">Loading managed plugins</p>
          <p className="mt-2 text-xs text-zinc-500">Waiting for authoritative inventory and catalog from StreamOps Node. No operation can be submitted yet.</p>
          <div className="mt-4 h-12 animate-pulse rounded-2xl bg-zinc-100" />
        </section>}
        {isEmpty && <section className="rounded-3xl border border-zinc-200 bg-white p-4 shadow-sm">
          <p className="text-sm font-semibold">No managed plugins</p>
          <p className="mt-2 text-xs text-zinc-500">The server registry is empty. No plugin card or installation source is inferred.</p>
        </section>}
        {!isLoading && !isEmpty && <section className="overflow-hidden rounded-3xl border border-black/5 bg-white shadow-sm">
          <button onClick={() => setOpenPlugin(openPlugin === "multi" ? null : "multi")} className="w-full p-4 text-left">
            <div className="flex items-start justify-between gap-3"><div><div className="flex items-center gap-2"><span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-blue-50"><RadioTower className="h-5 w-5 text-blue-600" aria-hidden="true" /></span><h2 className="text-[15px] font-semibold">Multiple RTMP Outputs</h2><Pill tone={displayTone}>{displayStatus}</Pill></div><p className="mt-1 text-xs text-zinc-500">Multi-destination streaming plugin</p></div><span className="text-zinc-400">{openPlugin === "multi" ? "⌃" : "⌄"}</span></div>
            <div className="mt-4 grid grid-cols-3 gap-2"><Stat label="Installed" value={isOffline ? "Unknown" : multiInstalled ? isLegacy ? "Legacy 0.7.2" : "0.7.2" : "—"} /><Stat label="Available" value={isOffline ? "Unavailable" : "0.7.2 · sample"} /><Stat label="Compatibility" value="OBS 32 · x64" /></div>
          </button>
          {!multiInstalled && <div className="px-4 pb-4"><button onClick={() => setConfirmAction("Install")} disabled={!!busy || readonlyPreview} className="w-full rounded-2xl bg-zinc-950 px-3 py-3 text-sm font-semibold text-white disabled:opacity-40">{busy === "Install" ? "Installing…" : "Install plugin"}</button><p className="mt-2 text-[11px] text-zinc-500">Design preview · release/version are illustrative. Real availability comes only from the server-managed registry and approved distribution source.</p></div>}
          {openPlugin === "multi" && <div className="border-t border-zinc-100 p-4">
        {(isRecovery || isVerifyFailed || isLegacy || isOffline) && <div className="mb-3 rounded-2xl border border-zinc-200 bg-zinc-50 p-3 text-xs leading-5 text-zinc-700">
          <strong>{displayStatus}</strong>
          <p className="mt-1">{isRecovery ? "Do not retry mutations until the backend confirms journal/backup integrity. A failed Rollback is not success." : isVerifyFailed ? "Verification failed. Keep the installed version visible; retry only after OBS READY and Vendor probe are confirmed." : isLegacy ? "Existing legacy files and configuration were preserved. An adopted baseline is not a verified approved release." : "Status is unknown while OBS / WebSocket is offline. Reconnect and refresh before any mutation."}</p>
        </div>}
        {isLegacy && <button onClick={() => setConfirmAction("Install")} disabled={!!busy} className="mb-3 w-full rounded-2xl bg-zinc-950 px-3 py-3 text-sm font-semibold text-white disabled:opacity-40">Install approved release</button>}
        <div className="mb-3 rounded-2xl bg-zinc-50 p-3 text-xs text-zinc-600">Source: StreamOps managed distribution · Server allowlist · SHA-256 and compatibility verified before installation. No arbitrary GitHub URL.</div>{multiInstalled ? <button onClick={() => action("Verify Multiple RTMP Outputs")} disabled={!!busy || restartRequired && scenario === "normal" || readonlyPreview || isLegacy} className="w-full rounded-2xl border border-zinc-200 px-3 py-3 text-sm font-semibold disabled:opacity-40">{isVerifyFailed ? "Retry verification" : "Verify plugin"}</button> : <p className="text-xs text-zinc-500">Not installed. Use Install above to start the confirmation flow.</p>}</div>}
        </section>}

        <div className="flex items-center gap-2 px-1 pt-2"><SlidersHorizontal className="h-4 w-4 text-zinc-600" aria-hidden="true" /><h2 className="text-sm font-semibold">Manager tools</h2><div className="h-px flex-1 bg-zinc-200" /></div>
        <section className="overflow-hidden rounded-3xl border border-black/5 bg-white shadow-sm">
          <button onClick={() => setActivityOpen(v => !v)} className="w-full p-4 text-left">
            <div className="flex items-start justify-between gap-3">
              <div><div className="flex items-center gap-2"><h2 className="text-[15px] font-semibold">Activity Log</h2><Pill tone={isRecovery || isVerifyFailed ? "bad" : "neutral"}>{isRecovery || isVerifyFailed ? "1 error" : "0 errors"}</Pill></div><p className="mt-0.5 text-xs text-zinc-500">Plugin operations in this browser session</p></div>
              <span className="text-zinc-400">{activityOpen ? "⌃" : "⌄"}</span>
            </div>
            <div className="mt-4 grid grid-cols-3 gap-2">
              <Stat label="Last event" value={isLoading || isEmpty || isOffline ? "—" : isRecovery ? "Recovery required" : isVerifyFailed ? "Verify failed" : isLegacy ? "Adopt completed" : "Verify completed"} />
              <Stat label="Operations" value={isLoading || isEmpty || isOffline ? "0" : isRecovery || isLegacy || isVerifyFailed ? "1" : "5"} />
              <Stat label="Errors" value={isRecovery || isVerifyFailed ? "1" : "0"} />
            </div>
          </button>
          {activityOpen && <div className="border-t border-zinc-100 px-4 pb-4 pt-3">
            <ol className="space-y-2">
              {[["23:31:18", "plugin.verify", "Multiple RTMP Outputs", "PASS", "ok"], ["23:31:12", "obs.restart", "OBS Runtime", "READY", "ok"], ["23:30:58", "plugin.update", "Multiple RTMP Outputs", "SUCCESS", "ok"], ["23:30:42", "plugin.inventory", "1 managed plugin detected", "SUCCESS", "ok"], ["23:30:40", "plugin.manager", "Plugin Manager loaded", "SUCCESS", "ok"]].map(([time, op, detail, result, tone]) => <li key={time + op} className="rounded-2xl bg-zinc-50 px-3 py-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0"><p className="text-xs font-semibold">{op}</p><p className="mt-1 break-words text-[11px] leading-4 text-zinc-500">{time} · {detail}</p></div>
                  <Pill tone={tone as Tone}>{result}</Pill>
                </div>
              </li>)}
            </ol>
          </div>}
        </section>
      </div>
    </div>
  </main>;
};