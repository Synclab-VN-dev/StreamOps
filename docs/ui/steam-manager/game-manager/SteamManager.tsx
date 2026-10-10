import { useState, type ReactNode } from "react";
import { Activity, ArrowLeft, ArrowRight, ChevronDown, CircleAlert, Gamepad2, Info, Power, RefreshCw, RotateCcw, X } from "lucide-react";
type Tone = "ok" | "warn" | "bad" | "neutral" | "blue";
type Scenario = "normal" | "empty" | "multi" | "stopped" | "offline" | "loading" | "error";
type Game = {
  id: string;
  name: string;
  launcher: string;
  uptime: string;
};
const sampleGames: Game[] = [{
  id: "d4",
  name: "Diablo IV",
  launcher: "Steam",
  uptime: "01:24:10"
}, {
  id: "hk",
  name: "Hollow Knight: Silksong",
  launcher: "Steam",
  uptime: "00:18:32"
}, {
  id: "mc",
  name: "Minecraft",
  launcher: "Standalone",
  uptime: "00:42:16"
}, {
  id: "hades",
  name: "Hades II",
  launcher: "Steam",
  uptime: "00:06:02"
}, {
  id: "poe",
  name: "Path of Exile 2",
  launcher: "Standalone",
  uptime: "02:12:24"
}];
const scenarios: {
  id: Scenario;
  label: string;
}[] = [{
  id: "normal",
  label: "Steam running · 1 game"
}, {
  id: "empty",
  label: "Steam running · no games"
}, {
  id: "multi",
  label: "Five games running"
}, {
  id: "stopped",
  label: "Steam stopped · external game"
}, {
  id: "offline",
  label: "Host A disconnected"
}, {
  id: "loading",
  label: "Loading game inventory"
}, {
  id: "error",
  label: "Inventory request error"
}];
const gamesLink = "https://designs.magicpath.ai/v1/sturdily-room-4179";
function Pill({
  children,
  tone = "neutral"
}: {
  children: ReactNode;
  tone?: Tone;
}) {
  const styles: Record<Tone, string> = {
    ok: "bg-emerald-50 text-emerald-700",
    warn: "bg-amber-50 text-amber-700",
    bad: "bg-red-50 text-red-700",
    neutral: "bg-zinc-100 text-zinc-700",
    blue: "bg-blue-50 text-blue-700"
  };
  return <span className={"inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-semibold " + styles[tone]}>{children}</span>;
}
function Stat({
  label,
  value
}: {
  label: string;
  value: string;
}) {
  return <div className="min-w-0"><p className="text-[11px] text-zinc-500">{label}</p><p className="mt-0.5 truncate text-sm font-semibold">{value}</p></div>;
}
function Card({
  title,
  subtitle,
  status,
  open,
  onToggle,
  summary,
  children
}: {
  title: string;
  subtitle: string;
  status?: ReactNode;
  open: boolean;
  onToggle: () => void;
  summary: ReactNode;
  children?: ReactNode;
}) {
  return <section className="overflow-hidden rounded-3xl border border-black/5 bg-white shadow-sm">
  <button type="button" onClick={onToggle} aria-expanded={open} className="w-full p-4 text-left sm:p-5">
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0"><h2 className="text-[15px] font-semibold">{title}</h2><p className="mt-0.5 text-xs text-zinc-500">{subtitle}</p></div>
      <div className="flex shrink-0 items-center gap-2">{status}<ChevronDown className={"h-4 w-4 text-zinc-400 transition-transform " + (open ? "rotate-180" : "")} aria-hidden="true" /></div>
    </div>
    <div className="mt-4">{summary}</div>
  </button>
  {open && children && <div className="border-t border-zinc-100 px-4 pb-4 pt-3 sm:px-5 sm:pb-5">{children}</div>}
 </section>;
}
export const StreamOpsSteamManager = () => {
  const [scenario, setScenario] = useState<Scenario>("normal");
  const [runtimeOpen, setRuntimeOpen] = useState(false);
  const [gamesOpen, setGamesOpen] = useState(true);
  const [activityOpen, setActivityOpen] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [confirmRestart, setConfirmRestart] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [notice, setNotice] = useState("");
  const [activities, setActivities] = useState<string[]>(["10:08 · Steam status reconciled — running", "10:07 · Game inventory refreshed", "10:06 · Browser session connected"]);
  const addActivity = (message: string) => setActivities(v => ["10:08 · " + message, ...v].slice(0, 12));
  const games = scenario === "multi" ? sampleGames : scenario === "normal" ? sampleGames.slice(0, 1) : scenario === "stopped" ? [sampleGames[2]] : [];
  const offline = scenario === "offline";
  const unknown = offline || scenario === "loading" || scenario === "error";
  const steamRunning = scenario === "normal" || scenario === "empty" || scenario === "multi";
  const registered = scenario === "multi" ? 12 : 8;
  const changeScenario = (next: Scenario) => {
    setScenario(next);
    setNotice("");
    setShowAll(false);
    setRestarting(false);
    addActivity("Design preview: " + scenarios.find(v => v.id === next)?.label);
  };
  const restart = () => {
    setConfirmRestart(false);
    setRestarting(true);
    addActivity("Demo Steam restart requested");
    window.setTimeout(() => {
      setRestarting(false);
      setNotice("Prototype restart complete. No command was sent to host A.");
      addActivity("Demo Steam restart completed");
    }, 1100);
  };
  return <main className="min-h-screen bg-[#f5f6f8] text-zinc-950">
  <div className="mx-auto w-full max-w-md px-4 pb-10 pt-4">
    <header className="mb-4">
     <a href="https://designs.magicpath.ai/v1/smart-cliff-3265" className="mb-3 inline-flex items-center gap-1 text-xs font-semibold text-zinc-500 hover:text-zinc-900"><ArrowLeft className="h-3.5 w-3.5" />Dashboard</a>
     <div className="flex items-start justify-between gap-3">
       <div><p className="text-xs font-medium uppercase tracking-[0.18em] text-zinc-500">StreamOps</p><h1 className="text-2xl font-semibold tracking-tight">Steam Manager</h1><p className="mt-1 text-xs text-zinc-500">Steam client and running games on host A</p></div>
       <Pill tone={unknown ? "bad" : steamRunning ? "ok" : "warn"}>{unknown ? "Node offline" : steamRunning ? "Steam running" : "Steam stopped"}</Pill>
     </div>
    </header>
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-zinc-200 bg-white px-3 py-2.5">
     <span className="flex items-center gap-1.5 text-xs text-zinc-500"><Info className="h-3.5 w-3.5" /> Design preview · mock data</span>
     <label className="flex items-center gap-2 text-xs font-medium"><span className="sr-only">Scenario</span><select aria-label="Design scenario" value={scenario} onChange={e => changeScenario(e.target.value as Scenario)} className="max-w-40 rounded-xl border border-zinc-200 bg-white px-2 py-1.5 text-xs text-zinc-700 outline-offset-2">{scenarios.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}</select></label>
    </div>
    {(offline || scenario === "error") && <div className="mb-3 rounded-2xl border border-red-200 bg-red-50 p-3 text-xs leading-5 text-red-700"><p className="font-semibold">Steam / game inventory unavailable</p><p className="mt-1">Unknown status must not be treated as stopped. Retry after reconnecting or recovering the inventory service.</p></div>}
    {notice && <div role="status" className="mb-3 rounded-2xl border border-blue-100 bg-blue-50 px-3 py-2.5 text-xs font-medium text-blue-700">{notice}</div>}
    <div className="space-y-3">
     <Card title="Steam Process Status" subtitle="Client lifecycle, Windows session and installation" open={runtimeOpen} onToggle={() => setRuntimeOpen(v => !v)} status={<Pill tone={unknown ? "bad" : steamRunning ? "ok" : "neutral"}>{unknown ? "UNKNOWN" : steamRunning ? "RUNNING" : "STOPPED"}</Pill>} summary={<div className="grid grid-cols-3 gap-2"><Stat label="PID" value={unknown || !steamRunning ? "—" : "6432"} /><Stat label="Uptime" value={unknown || !steamRunning ? "—" : "03:42:15"} /><Stat label="Session" value={unknown || !steamRunning ? "—" : "1"} /></div>}>
       <div className="mb-3 rounded-2xl bg-zinc-50 px-3">
        {[["Started", steamRunning ? "Today · 06:26" : "—"], ["Windows session", steamRunning ? "1 · Active console" : "—"], ["Interactive", steamRunning ? "Yes" : "—"], ["Installation", unknown ? "Unknown" : "Detected"]].map(([key, value]) => <div className="flex items-center justify-between gap-3 border-b border-zinc-100 py-3 last:border-0" key={key}><span className="text-xs text-zinc-500">{key}</span><span className="text-xs font-semibold">{value}</span></div>)}
       </div>
       <button type="button" disabled={unknown || restarting} onClick={() => setConfirmRestart(true)} className="inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-zinc-950 px-3 py-3 text-sm font-semibold text-white disabled:opacity-40"><RotateCcw className="h-4 w-4" />{restarting ? "Restarting…" : "Restart in Big Picture"}</button>
       <p className="mt-2 text-[11px] leading-4 text-zinc-500">Restarts may interrupt active games and downloads.</p>
     </Card>
     <Card title="Game Manager" subtitle="Registered games and observed sessions" open={gamesOpen} onToggle={() => setGamesOpen(v => !v)} status={<Pill tone={unknown ? "neutral" : games.length ? "ok" : "neutral"}>{unknown ? "UNKNOWN" : games.length + " running"}</Pill>} summary={<div className="grid grid-cols-2 gap-2"><Stat label="Running" value={unknown ? "—" : String(games.length)} /><Stat label="Registered" value={unknown ? "—" : String(registered)} /></div>}>
       {scenario === "loading" ? <div className="rounded-2xl bg-zinc-50 p-4 text-center"><p role="status" className="text-sm font-semibold">Loading game inventory…</p><p className="mt-1 text-xs text-zinc-500">Running count is unknown until loading completes.</p></div> : unknown ? <div className="rounded-2xl bg-zinc-50 p-4 text-center"><CircleAlert className="mx-auto mb-2 h-5 w-5 text-zinc-400" /><p className="text-sm font-semibold">Status unavailable</p><p className="mt-1 text-xs text-zinc-500">Cannot confirm running sessions.</p></div> : games.length === 0 ? <div className="rounded-2xl bg-zinc-50 p-5 text-center"><Gamepad2 className="mx-auto mb-2 h-6 w-6 text-zinc-400" /><p className="text-sm font-semibold">No games running</p><p className="mt-1 text-xs text-zinc-500">Manage registered games in your library.</p></div> : <div className="rounded-2xl bg-zinc-50 px-3">
        {games.slice(0, showAll ? games.length : 3).map(g => <div key={g.id} className="flex items-center gap-3 border-b border-zinc-100 py-3 last:border-0">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600"><Gamepad2 className="h-4 w-4" /></span>
          <div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold">{g.name}</p><p className="mt-0.5 truncate text-[11px] text-zinc-500">{g.launcher} · {g.uptime}</p></div>
          <Pill tone="ok">Running</Pill>
         </div>)}
         {games.length > 3 && <button className="w-full py-3 text-xs font-semibold text-zinc-600" onClick={() => setShowAll(v => !v)}>{showAll ? "Show less" : "+" + (games.length - 3) + " more games"}</button>}
       </div>}
       {scenario === "stopped" && <p className="mt-3 rounded-xl bg-amber-50 p-3 text-xs leading-5 text-amber-700">Steam is stopped, but a standalone game remains running. These states are independent.</p>}
       <a href={gamesLink} className="mt-3 flex w-full items-center justify-center gap-2 rounded-2xl bg-zinc-950 px-4 py-3 text-sm font-semibold text-white hover:bg-zinc-800">Manage Games <ArrowRight className="h-4 w-4" /></a>
     </Card>
     <Card title="Activity Log" subtitle="Actions in this browser session" open={activityOpen} onToggle={() => setActivityOpen(v => !v)} summary={<div className="flex items-center gap-2 text-xs text-zinc-500"><Activity className="h-4 w-4" />{activities.length} session events · latest {activities[0]?.slice(0, 5)}</div>}>
       <div className="space-y-2 rounded-2xl bg-zinc-50 p-3">{activities.map((entry, i) => <p key={i} className="border-b border-zinc-100 pb-2 text-xs leading-5 text-zinc-600 last:border-0 last:pb-0">{entry}</p>)}</div>
     </Card>
    </div>
    <p className="mt-5 text-center text-[11px] text-zinc-400">StreamOps UI Prototype · Illustrative values, not live host data</p>
  </div>
  {confirmRestart && <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-950/40 p-4">
    <div role="dialog" aria-modal="true" aria-labelledby="steam-restart-confirm" className="w-full max-w-sm rounded-3xl bg-white p-5 shadow-xl">
      <div className="flex items-start justify-between gap-3"><h2 id="steam-restart-confirm" className="text-base font-semibold">Restart Steam in Big Picture?</h2><button onClick={() => setConfirmRestart(false)} aria-label="Close" className="rounded-xl p-1 text-zinc-500"><X className="h-4 w-4" /></button></div>
      <p className="mt-2 text-xs leading-5 text-zinc-600">Active games or downloads may be interrupted. This prototype action does not contact host A.</p>
      <div className="mt-4 grid grid-cols-2 gap-2"><button className="rounded-2xl border border-zinc-200 bg-white px-3 py-3 text-sm font-semibold" onClick={() => setConfirmRestart(false)}>Cancel</button><button className="rounded-2xl bg-zinc-950 px-3 py-3 text-sm font-semibold text-white" onClick={restart}>Simulate restart</button></div>
    </div>
   </div>}
 </main>;
};