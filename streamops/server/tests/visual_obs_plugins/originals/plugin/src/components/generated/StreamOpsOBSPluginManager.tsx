import { useState } from "react";
import { Puzzle, SlidersHorizontal, RadioTower, Camera, ChevronDown } from "lucide-react";
type Tone = "ok" | "warn" | "bad" | "neutral" | "blue";
type PluginState = "installed" | "update" | "not-installed";
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
  const [multiInstalled, setMultiInstalled] = useState(false);
  const [demoState, setDemoState] = useState<PluginState>("update");
  const [activityOpen, setActivityOpen] = useState(false);
  const [scenario, setScenario] = useState("normal");
  const [confirmAction, setConfirmAction] = useState<string | null>(null);
  const scenarios = [["normal", "Normal"], ["installing", "Installing"], ["updating", "Updating"], ["restarting", "Restarting OBS"], ["verifying", "Verifying"], ["blocked", "Live / blocked"], ["rollback", "Rolling back"], ["restored", "Rollback success"], ["rollback-failed", "Rollback failed"], ["verify-failed", "Verify failed"], ["offline", "OBS offline"], ["vendor", "Vendor unavailable"], ["empty", "Empty"], ["loading", "Loading"], ["error", "Load error"]];
  const action = (label: string) => {
    setConfirmAction(null);
    setBusy(label);
    setNotice(label + " requested");
    setTimeout(() => {
      setBusy(null);
      if (label === "Restart OBS") setRestartRequired(false);
      if (label === "Update") {
        setDemoState("installed");
        setRestartRequired(true);
      }
      if (label === "Install") {
        setMultiInstalled(true);
        setRestartRequired(true);
      }
      setNotice(label + " completed");
      setTimeout(() => setNotice(null), 1400);
    }, 700);
  };
  const stateLabel = demoState === "update" ? "Update available" : demoState === "not-installed" ? "Not installed" : restartRequired ? "Restart required" : "Verified";
  const stateTone: Tone = demoState === "update" || restartRequired ? "warn" : demoState === "not-installed" ? "neutral" : "ok";
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
          <Pill tone="ok">OBS READY</Pill>
        </div>
      </header>

      {scenario !== "normal" && <section className={"mb-3 rounded-3xl border p-4 " + (["rollback-failed", "verify-failed", "error", "vendor"].includes(scenario) ? "border-red-200 bg-red-50" : "border-amber-200 bg-amber-50")}><div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">{scenarios.find(s => s[0] === scenario)?.[1]}</h2><Pill tone={["rollback-failed", "verify-failed", "error", "vendor"].includes(scenario) ? "bad" : "warn"}>Design preview</Pill></div><p className="mt-2 text-xs leading-5">{scenario === "blocked" ? "OBS is streaming or recording. Install, Update and Rollback are disabled; running outputs will not be stopped." : scenario === "rollback-failed" ? "Recovery failed. Preserve evidence, do not retry destructive operations until OBS and backup state are checked." : scenario === "restored" ? "Update failed but the previous version was restored and verified." : scenario === "offline" ? "OBS / WebSocket unavailable. Reconnect and refresh status; do not assume the operation succeeded." : scenario === "vendor" ? "OBS is ready, but the multi-RTMP Vendor probe is unavailable." : scenario === "empty" ? "No managed plugins in the registry." : scenario === "loading" ? "Loading inventory and plugin status…" : scenario === "error" ? "Could not load plugin inventory. Retry without changing installed files." : scenario === "verify-failed" ? "Plugin verification failed. Inspect the checks and retry after fixing the cause." : scenario === "rollback" ? "Restoring the previous plugin and configuration, then verifying OBS readiness." : scenario === "restarting" ? "Expected OBS restart in progress. Waiting for WebSocket reconnection." : scenario === "verifying" ? "Checking installed version, OBS READY, WebSocket and Vendor probe." : "Operation in progress: validating package, backing up configuration and applying files."}</p>{["error", "offline", "verify-failed"].includes(scenario) && <button onClick={() => setScenario("normal")} className="mt-3 rounded-xl border border-zinc-300 bg-white px-3 py-2 text-xs font-semibold">Retry / Refresh preview</button>}</section>}
      {confirmAction && <section className="mb-3 rounded-3xl border border-blue-200 bg-blue-50 p-4"><p className="text-sm font-semibold">Confirm {confirmAction}</p><p className="mt-1 text-xs">{confirmAction === "Install" ? "Install the approved managed release of Multiple RTMP Outputs? Package integrity, platform compatibility and OBS output safety must be checked before changes." : "Check OBS is idle and preserve the current plugin configuration before proceeding."}</p><div className="mt-3 flex gap-2"><button onClick={() => action(confirmAction)} className="rounded-xl bg-zinc-950 px-4 py-2 text-xs font-semibold text-white">Confirm</button><button onClick={() => setConfirmAction(null)} className="rounded-xl bg-white px-4 py-2 text-xs font-semibold">Cancel</button></div></section>}
      {notice && <div className="mb-3 rounded-2xl border border-blue-100 bg-blue-50 px-3 py-2 text-xs font-medium text-blue-700">{notice}</div>}

      <section className="mb-3 rounded-3xl border border-black/5 bg-white p-4 shadow-sm">
        <div className="flex items-center justify-between gap-3">
          <div><h2 className="text-[15px] font-semibold">Manager overview</h2><p className="mt-0.5 text-xs text-zinc-500">Inventory from the StreamOps node</p></div>
          <button onClick={() => action("Refresh inventory")} disabled={!!busy} className="rounded-xl border border-zinc-200 px-3 py-2 text-xs font-semibold disabled:opacity-40">Refresh</button>
        </div>
        <div className="mt-4 grid grid-cols-3 gap-2">
          <Stat label="Managed" value="2" /><Stat label="Installed" value={multiInstalled ? "2" : "1"} /><Stat label="Attention" value={multiInstalled ? restartRequired ? "1" : "0" : "1"} />
        </div>
      </section>

      {restartRequired && demoState === "installed" && <section className="mb-3 rounded-3xl border border-amber-200 bg-amber-50 p-4">
        <div className="flex items-start justify-between gap-3"><div><p className="text-sm font-semibold text-amber-900">OBS restart required</p><p className="mt-1 text-xs leading-5 text-amber-800">Plugin files changed. Restart OBS before verification.</p></div><Pill tone="warn">Pending</Pill></div>
        <button onClick={() => action("Restart OBS")} disabled={!!busy} className="mt-3 w-full rounded-2xl bg-zinc-950 px-3 py-3 text-sm font-semibold text-white disabled:opacity-40">{busy === "Restart OBS" ? "Restarting…" : "Restart OBS"}</button>
      </section>}

      <div className="mb-3 flex items-center gap-2 px-1"><Puzzle className="h-4 w-4 text-zinc-600" aria-hidden="true" /><h2 className="text-sm font-semibold">Managed plugins</h2><div className="h-px flex-1 bg-zinc-200" /></div>
      <div className="space-y-3">
        <section className="overflow-hidden rounded-3xl border border-black/5 bg-white shadow-sm">
          <button onClick={() => setOpenPlugin(openPlugin === "openstream" ? null : "openstream")} className="w-full p-4 text-left">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-indigo-50"><Camera className="h-5 w-5 text-indigo-600" aria-hidden="true" /></span><h2 className="text-[15px] font-semibold">OpenStream OBS Plugin</h2><Pill tone="neutral">Design fixture</Pill><Pill tone={stateTone}>{stateLabel}</Pill></div><p className="mt-1 text-xs text-zinc-500">StreamOps camera rotation and OBS integration</p></div>
              <span className="text-zinc-400">{openPlugin === "openstream" ? "⌃" : "⌄"}</span>
            </div>
            <div className="mt-4 grid grid-cols-3 gap-2"><Stat label="Installed" value={demoState === "not-installed" ? "—" : demoState === "update" ? "1.0.1" : "1.0.2"} /><Stat label="Available" value="1.0.2" /><Stat label="OBS" value="32.2.1" /></div>
          </button>
          {openPlugin === "openstream" && <div className="border-t border-zinc-100 px-4 pb-4 pt-3">
            <div className="rounded-2xl bg-zinc-50 px-3 py-1">
              {[["Package", "openstream-obs-plugin"], ["Source", "StreamOps managed release"], ["Compatibility", "OBS 32.x · Windows x64"], ["Last verification", restartRequired ? "Pending restart" : "PASS · plugin loaded"]].map(([l, v]) => <div key={l} className="flex gap-3 border-b border-zinc-100 py-2.5 last:border-0"><span className="w-28 shrink-0 text-xs text-zinc-500">{l}</span><span className="min-w-0 flex-1 break-words text-xs font-medium">{v}</span></div>)}
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2">
              {demoState === "update" && <button onClick={() => setConfirmAction("Update")} disabled={!!busy || scenario === "blocked"} className="rounded-2xl bg-zinc-950 px-3 py-3 text-sm font-semibold text-white disabled:opacity-40">{busy === "Update" ? "Updating…" : "Update"}</button>}
              {demoState === "not-installed" && <button onClick={() => setConfirmAction("Install")} disabled={!!busy} className="rounded-2xl bg-zinc-950 px-3 py-3 text-sm font-semibold text-white disabled:opacity-40">Install</button>}
              {demoState === "installed" && !restartRequired && <button onClick={() => action("Verify")} disabled={!!busy} className="rounded-2xl bg-zinc-950 px-3 py-3 text-sm font-semibold text-white disabled:opacity-40">Verify</button>}
              <button onClick={() => setConfirmAction("Rollback")} disabled={!!busy || demoState === "not-installed" || scenario === "blocked"} className="rounded-2xl border border-zinc-200 px-3 py-3 text-sm font-semibold disabled:opacity-40">Rollback</button>
            </div>
          </div>}
        </section>

        <section className="overflow-hidden rounded-3xl border border-black/5 bg-white shadow-sm">
          <button onClick={() => setOpenPlugin(openPlugin === "multi" ? null : "multi")} className="w-full p-4 text-left">
            <div className="flex items-start justify-between gap-3"><div><div className="flex items-center gap-2"><span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-blue-50"><RadioTower className="h-5 w-5 text-blue-600" aria-hidden="true" /></span><h2 className="text-[15px] font-semibold">Multiple RTMP Outputs</h2><Pill tone={multiInstalled ? restartRequired ? "warn" : "ok" : "neutral"}>{multiInstalled ? restartRequired ? "Restart required" : "Verified" : "Not installed"}</Pill></div><p className="mt-1 text-xs text-zinc-500">Multi-destination streaming plugin</p></div><span className="text-zinc-400">{openPlugin === "multi" ? "⌃" : "⌄"}</span></div>
            <div className="mt-4 grid grid-cols-3 gap-2"><Stat label="Installed" value={multiInstalled ? "0.7.2" : "—"} /><Stat label="Available" value="0.7.2 · sample" /><Stat label="Compatibility" value="OBS 32 · x64" /></div>
          </button>
          {!multiInstalled && <div className="px-4 pb-4"><button onClick={() => setConfirmAction("Install")} disabled={!!busy || scenario === "blocked" || scenario === "offline"} className="w-full rounded-2xl bg-zinc-950 px-3 py-3 text-sm font-semibold text-white disabled:opacity-40">{busy === "Install" ? "Installing…" : "Install plugin"}</button><p className="mt-2 text-[11px] text-zinc-500">Design preview · release/version are illustrative. Real availability comes only from the server-managed registry and approved distribution source.</p></div>}
          {openPlugin === "multi" && <div className="border-t border-zinc-100 p-4"><div className="mb-3 rounded-2xl bg-zinc-50 p-3 text-xs text-zinc-600">Source: StreamOps managed distribution · Server allowlist · SHA-256 and compatibility verified before installation. No arbitrary GitHub URL.</div>{multiInstalled ? <button onClick={() => action("Verify Multiple RTMP Outputs")} disabled={!!busy || restartRequired} className="w-full rounded-2xl border border-zinc-200 px-3 py-3 text-sm font-semibold disabled:opacity-40">Verify plugin</button> : <p className="text-xs text-zinc-500">Not installed. Use Install above to start the confirmation flow.</p>}</div>}
        </section>

        <div className="flex items-center gap-2 px-1 pt-2"><SlidersHorizontal className="h-4 w-4 text-zinc-600" aria-hidden="true" /><h2 className="text-sm font-semibold">Manager tools</h2><div className="h-px flex-1 bg-zinc-200" /></div>
        <section className="overflow-hidden rounded-3xl border border-black/5 bg-white shadow-sm">
          <button onClick={() => setActivityOpen(v => !v)} className="w-full p-4 text-left">
            <div className="flex items-start justify-between gap-3">
              <div><div className="flex items-center gap-2"><h2 className="text-[15px] font-semibold">Activity Log</h2><Pill tone="neutral">0 errors</Pill></div><p className="mt-0.5 text-xs text-zinc-500">Plugin operations in this browser session</p></div>
              <span className="text-zinc-400">{activityOpen ? "⌃" : "⌄"}</span>
            </div>
            <div className="mt-4 grid grid-cols-3 gap-2">
              <Stat label="Last event" value="Verify completed" />
              <Stat label="Operations" value="5" />
              <Stat label="Errors" value="0" />
            </div>
          </button>
          {activityOpen && <div className="border-t border-zinc-100 px-4 pb-4 pt-3">
            <ol className="space-y-2">
              {[["23:31:18", "plugin.verify", "OpenStream OBS Plugin", "PASS", "ok"], ["23:31:12", "obs.restart", "OBS Runtime", "READY", "ok"], ["23:30:58", "plugin.update", "OpenStream OBS Plugin · 1.0.1 → 1.0.2", "SUCCESS", "ok"], ["23:30:42", "plugin.inventory", "2 managed plugins detected", "SUCCESS", "ok"], ["23:30:40", "plugin.manager", "Plugin Manager loaded", "SUCCESS", "ok"]].map(([time, op, detail, result, tone]) => <li key={time + op} className="rounded-2xl bg-zinc-50 px-3 py-3">
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