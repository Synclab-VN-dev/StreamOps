import { useState, type ReactNode } from "react";
import { Activity, AlertTriangle, ArrowLeft, ArrowRight, ChevronDown, ChevronRight, Clock3, Gamepad2, Info, Library, Monitor, MonitorPlay, Play, Power, Radio, RefreshCw, RotateCcw, Search, Settings2, Square, Terminal, WifiOff, X } from "lucide-react";
type Proc = "RUNNING" | "STOPPED" | "STARTING" | "STOPPING" | "FAILED" | "UNKNOWN";
type Win = "FOREGROUND" | "BACKGROUND" | "NOT_DETECTED" | "UNKNOWN";
type Obs = "VERIFIED_ACTIVE" | "CONFIGURED_ONLY" | "INACTIVE" | "ERROR" | "UNKNOWN";
type StreamState = "SELECTED" | "NOT_SELECTED" | "UNKNOWN";
type Scenario = "default" | "multi" | "empty" | "unregistered" | "offline" | "session" | "black" | "startFail" | "stopTimeout" | "restartFail" | "stale" | "externalExit" | "loading";
type Game = {
  id: string;
  title: string;
  provider: string;
  genre: string;
  pid: string;
  uptime: string;
  exe: string;
  window: Win;
  obs: Obs;
  selected: StreamState;
  process: Proc;
  session: number;
};
type ActionKind = "start" | "stop" | "restart" | "force";
const games: Game[] = [{
  id: "d4",
  title: "Diablo IV",
  provider: "Steam",
  genre: "Action RPG",
  pid: "12840",
  uptime: "01:24:10",
  exe: "Diablo IV.exe",
  window: "FOREGROUND",
  obs: "CONFIGURED_ONLY",
  selected: "SELECTED",
  process: "RUNNING",
  session: 1
}, {
  id: "hk",
  title: "Hollow Knight: Silksong",
  provider: "Steam",
  genre: "Metroidvania",
  pid: "14560",
  uptime: "00:22:18",
  exe: "Silksong.exe",
  window: "BACKGROUND",
  obs: "INACTIVE",
  selected: "NOT_SELECTED",
  process: "STOPPED",
  session: 1
}, {
  id: "mc",
  title: "Minecraft",
  provider: "Standalone",
  genre: "Sandbox",
  pid: "8240",
  uptime: "00:32:41",
  exe: "javaw.exe",
  window: "BACKGROUND",
  obs: "UNKNOWN",
  selected: "NOT_SELECTED",
  process: "STOPPED",
  session: 1
}, {
  id: "er",
  title: "Elden Ring",
  provider: "Steam",
  genre: "Action RPG",
  pid: "24012",
  uptime: "00:16:24",
  exe: "eldenring.exe",
  window: "BACKGROUND",
  obs: "INACTIVE",
  selected: "NOT_SELECTED",
  process: "STOPPED",
  session: 1
}, {
  id: "hades",
  title: "Hades II",
  provider: "Steam",
  genre: "Roguelike",
  pid: "21908",
  uptime: "00:26:02",
  exe: "Hades2.exe",
  window: "NOT_DETECTED",
  obs: "UNKNOWN",
  selected: "UNKNOWN",
  process: "STOPPED",
  session: 1
}, {
  id: "wow",
  title: "World of Warcraft",
  provider: "Battle.net",
  genre: "MMORPG",
  pid: "25100",
  uptime: "00:04:12",
  exe: "Wow.exe",
  window: "BACKGROUND",
  obs: "UNKNOWN",
  selected: "NOT_SELECTED",
  process: "STOPPED",
  session: 1
}, {
  id: "fortnite",
  title: "Fortnite",
  provider: "Epic Games",
  genre: "Battle Royale",
  pid: "10882",
  uptime: "00:12:21",
  exe: "FortniteClient-Win64.exe",
  window: "NOT_DETECTED",
  obs: "INACTIVE",
  selected: "NOT_SELECTED",
  process: "STOPPED",
  session: 1
}, {
  id: "poe",
  title: "Path of Exile 2",
  provider: "Standalone",
  genre: "Action RPG",
  pid: "24118",
  uptime: "00:40:04",
  exe: "PathOfExile.exe",
  window: "UNKNOWN",
  obs: "UNKNOWN",
  selected: "UNKNOWN",
  process: "STOPPED",
  session: 1
}, {
  id: "bg3",
  title: "Baldur's Gate 3",
  provider: "Steam",
  genre: "RPG",
  pid: "24180",
  uptime: "00:00:00",
  exe: "bg3.exe",
  window: "NOT_DETECTED",
  obs: "INACTIVE",
  selected: "NOT_SELECTED",
  process: "STOPPED",
  session: 1
}, {
  id: "forza",
  title: "Forza Horizon 5",
  provider: "Steam",
  genre: "Racing",
  pid: "28190",
  uptime: "00:00:00",
  exe: "ForzaHorizon5.exe",
  window: "NOT_DETECTED",
  obs: "INACTIVE",
  selected: "NOT_SELECTED",
  process: "STOPPED",
  session: 1
}];
const scenarios: {
  id: Scenario;
  title: string;
}[] = [{
  id: "default",
  title: "Default · 1 running"
}, {
  id: "multi",
  title: "Multiple running"
}, {
  id: "empty",
  title: "No running games"
}, {
  id: "unregistered",
  title: "Empty library"
}, {
  id: "offline",
  title: "Host disconnected"
}, {
  id: "session",
  title: "Session mismatch"
}, {
  id: "black",
  title: "OBS black frames"
}, {
  id: "startFail",
  title: "Start failed · retry"
}, {
  id: "stopTimeout",
  title: "Stop timed out · reconcile"
}, {
  id: "restartFail",
  title: "Restart failed · reconcile"
}, {
  id: "stale",
  title: "Stale data · refresh"
}, {
  id: "externalExit",
  title: "External game exit"
}, {
  id: "loading",
  title: "Loading game inventory"
}];
const displayProc = (s: Proc) => ({
  RUNNING: "Running",
  STOPPED: "Stopped",
  STARTING: "Starting",
  STOPPING: "Stopping",
  FAILED: "Failed",
  UNKNOWN: "Unknown"
})[s];
const displayWin = (s: Win) => ({
  FOREGROUND: "Foreground",
  BACKGROUND: "Background",
  NOT_DETECTED: "Not detected",
  UNKNOWN: "Unknown"
})[s];
const displayObs = (s: Obs) => ({
  VERIFIED_ACTIVE: "Verified active",
  CONFIGURED_ONLY: "Configured only",
  INACTIVE: "Inactive",
  ERROR: "Capture error",
  UNKNOWN: "Unknown"
})[s];
const displaySelected = (s: StreamState) => ({
  SELECTED: "Selected",
  NOT_SELECTED: "Not selected",
  UNKNOWN: "Unknown"
})[s];
type Tone = "ok" | "warn" | "bad" | "neutral" | "blue";
function Pill({
  children,
  tone = "neutral"
}: {
  children: ReactNode;
  tone?: Tone;
}) {
  const map: Record<Tone, string> = {
    ok: "bg-emerald-50 text-emerald-700",
    warn: "bg-amber-50 text-amber-700",
    bad: "bg-red-50 text-red-700",
    neutral: "bg-zinc-100 text-zinc-600",
    blue: "bg-blue-50 text-blue-700"
  };
  return <span className={"inline-flex shrink-0 items-center rounded-full px-2.5 py-1 text-[11px] font-semibold " + map[tone]}>{children}</span>;
}
function Stat({
  label,
  value
}: {
  label: string;
  value: string | number;
}) {
  return <div className="min-w-0"><p className="text-[11px] text-zinc-500">{label}</p><p className="mt-0.5 truncate text-sm font-semibold">{value}</p></div>;
}
function GameIcon({
  title
}: {
  title: string;
}) {
  return <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600"><Gamepad2 className="h-5 w-5" aria-label={title} /></span>;
}
function TitleRow({
  icon,
  title
}: {
  icon: ReactNode;
  title: string;
}) {
  return <div className="mb-3 flex items-center gap-2 px-1"><span className="text-zinc-600">{icon}</span><h2 className="text-sm font-semibold">{title}</h2><div className="h-px flex-1 bg-zinc-200" /></div>;
}
function DetailRow({
  icon,
  label,
  value,
  tone = "neutral"
}: {
  icon: ReactNode;
  label: string;
  value: string;
  tone?: Tone;
}) {
  return <div className="flex items-center justify-between gap-2 border-b border-zinc-100 py-3 last:border-0"><div className="flex min-w-0 items-center gap-2"><span className="text-zinc-400">{icon}</span><span className="text-xs text-zinc-600">{label}</span></div><Pill tone={tone}>{value}</Pill></div>;
}
function GameDetail({
  game,
  proc,
  scenario,
  onBack,
  onAction,
  onReconcile,
  activity
}: {
  game: Game;
  proc: Proc;
  scenario: Scenario;
  onBack: () => void;
  onAction: (kind: ActionKind) => void;
  onReconcile: () => void;
  activity: string[];
}) {
  const [advanced, setAdvanced] = useState(false);
  const running = proc === "RUNNING",
    busy = proc === "STARTING" || proc === "STOPPING";
  const blocked = scenario === "offline" || scenario === "session" || scenario === "stale" || scenario === "loading" || proc === "UNKNOWN" || busy;
  const windowState: Win = scenario === "offline" || scenario === "session" ? "UNKNOWN" : !running ? "NOT_DETECTED" : game.window;
  const capture: Obs = scenario === "offline" ? "UNKNOWN" : !running ? "INACTIVE" : scenario === "black" ? "ERROR" : game.obs;
  const selected: StreamState = scenario === "offline" ? "UNKNOWN" : !running ? "NOT_SELECTED" : game.selected;
  return <aside className="rounded-3xl border border-black/5 bg-white shadow-sm lg:sticky lg:top-5" aria-label="Game details">
  <div className="flex items-center justify-between border-b border-zinc-100 p-4">
   <button onClick={onBack} className="inline-flex items-center gap-2 text-xs font-semibold text-zinc-500"><ArrowLeft className="h-4 w-4" />Back to games</button>
   <button onClick={onBack} aria-label="Close game details" className="rounded-xl p-1.5 text-zinc-400"><X className="h-4 w-4" /></button>
  </div>
  <div className="p-4">
   <div className="flex items-start gap-3"><GameIcon title={game.title} /><div className="min-w-0 flex-1"><h2 className="text-lg font-semibold tracking-tight">{game.title}</h2><p className="mt-1 text-xs text-zinc-500">{game.provider} · {game.genre}</p><div className="mt-2"><Pill tone={proc === "RUNNING" ? "ok" : proc === "FAILED" ? "bad" : proc === "UNKNOWN" ? "warn" : busy ? "blue" : "neutral"}>{displayProc(proc)}</Pill></div></div></div>
   <div className="mt-4 grid grid-cols-2 gap-2 rounded-2xl bg-zinc-50 p-3"><Stat label="PID" value={running ? game.pid : "—"} /><Stat label="Uptime" value={running ? game.uptime : "—"} /><Stat label="Windows session" value={scenario === "offline" ? "—" : String(game.session)} /><Stat label="Interactive" value={scenario === "offline" ? "Unknown" : scenario === "session" ? "No" : "Yes"} /></div>
  </div>
  {scenario === "offline" || scenario === "session" ? <div className="mx-4 mb-3 rounded-2xl border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-800"><p className="font-semibold">{scenario === "offline" ? "Host A unavailable" : "Session mismatch"}</p><p className="mt-1">Game controls are unavailable until live process and desktop session state can be verified.</p></div> : null}
  <div className="border-t border-zinc-100 p-4">
   <h3 className="text-sm font-semibold">Independent status</h3>
   <p className="mt-0.5 text-xs text-zinc-500">Process, window, OBS and streaming are verified separately.</p>
   <div className="mt-3 rounded-2xl bg-zinc-50 px-3">
    <DetailRow icon={<Monitor className="h-4 w-4" />} label="Window" value={displayWin(windowState)} tone={windowState === "FOREGROUND" ? "ok" : "neutral"} />
    <DetailRow icon={<MonitorPlay className="h-4 w-4" />} label="OBS capture" value={displayObs(capture)} tone={capture === "VERIFIED_ACTIVE" ? "ok" : capture === "ERROR" ? "bad" : capture === "CONFIGURED_ONLY" ? "warn" : "neutral"} />
    <DetailRow icon={<Radio className="h-4 w-4" />} label="Selected for stream" value={displaySelected(selected)} tone={selected === "SELECTED" ? "ok" : "neutral"} />
   </div>
   {running && capture === "CONFIGURED_ONLY" && <p className="mt-3 rounded-2xl bg-amber-50 p-3 text-xs leading-5 text-amber-800">OBS capture is configured, but valid frames have not been verified.</p>}
   {running && capture === "ERROR" && <p className="mt-3 rounded-2xl bg-red-50 p-3 text-xs leading-5 text-red-700">OBS cannot verify valid frames. The game process may still be healthy.</p>}
  </div>
  <div className="border-t border-zinc-100 p-4">
    <h3 className="text-sm font-semibold">Game controls</h3>
    <p className="mb-3 mt-0.5 text-xs text-zinc-500">Actions are simulations — no commands sent to host A.</p>
    <div className="grid grid-cols-3 gap-2">
     <button disabled={blocked || running} onClick={() => onAction("start")} className="inline-flex items-center justify-center gap-1.5 rounded-2xl bg-zinc-950 px-2 py-3 text-xs font-semibold text-white disabled:opacity-40"><Play className="h-3.5 w-3.5" />Start</button>
     <button disabled={blocked || !running} onClick={() => onAction("stop")} className="inline-flex items-center justify-center gap-1.5 rounded-2xl bg-zinc-100 px-2 py-3 text-xs font-semibold disabled:opacity-40"><Square className="h-3.5 w-3.5" />Stop</button>
     <button disabled={blocked || !running} onClick={() => onAction("restart")} className="inline-flex items-center justify-center gap-1.5 rounded-2xl border border-zinc-200 px-2 py-3 text-xs font-semibold disabled:opacity-40"><RotateCcw className="h-3.5 w-3.5" />Restart</button>
    </div>
    {busy && <p role="status" className="mt-2 text-xs text-blue-700">Operation pending — duplicate actions disabled.</p>}
    {proc === "FAILED" && <p role="alert" className="mt-2 rounded-xl bg-red-50 p-3 text-xs leading-5 text-red-700">Lifecycle operation failed. Check readiness and reconcile before retrying.</p>}
    {proc === "UNKNOWN" && <p role="alert" className="mt-2 rounded-xl bg-amber-50 p-3 text-xs leading-5 text-amber-800">Operation outcome unknown. Timeout is not proof the game stopped. Refresh the observed process state before any further action.</p>}
    <button onClick={onReconcile} disabled={scenario === "offline" || scenario === "session" || scenario === "loading" || busy} className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-xl border border-zinc-200 bg-white px-3 py-2.5 text-xs font-semibold disabled:opacity-40"><RefreshCw className="h-3.5 w-3.5" />Refresh / reconcile process</button>
  </div>
  <div className="border-t border-zinc-100 p-4">
   <h3 className="text-sm font-semibold">Related services</h3>
   <div className="mt-3 rounded-2xl bg-zinc-50 px-3">
    <DetailRow icon={<Power className="h-4 w-4" />} label={game.provider === "Steam" ? "Steam client" : game.provider + " launcher"} value={scenario === "offline" ? "Unknown" : "Ready"} tone={scenario === "offline" ? "warn" : "ok"} />
    <DetailRow icon={<MonitorPlay className="h-4 w-4" />} label="OBS Capture" value={displayObs(capture)} tone={capture === "ERROR" ? "bad" : capture === "VERIFIED_ACTIVE" ? "ok" : "warn"} />
    {game.id === "d4" && <DetailRow icon={<Settings2 className="h-4 w-4" />} label="D4Planner (optional)" value="Not linked" />}
   </div>
  </div>
  <div className="border-t border-zinc-100 p-4">
   <button onClick={() => setAdvanced(v => !v)} aria-expanded={advanced} className="flex w-full items-center justify-between text-left text-sm font-semibold"><span className="flex items-center gap-2"><Terminal className="h-4 w-4 text-zinc-500" />Advanced & recovery</span><ChevronDown className={"h-4 w-4 text-zinc-400 " + (advanced ? "rotate-180" : "")} /></button>
   {advanced && <div className="mt-3 space-y-3"><div className="rounded-2xl bg-zinc-50 p-3"><Stat label="Executable" value={game.exe} /><div className="mt-3"><Stat label="Launcher" value={game.provider} /></div></div><div className="rounded-2xl border border-red-200 bg-red-50 p-3"><p className="flex items-center gap-2 text-xs font-semibold text-red-800"><AlertTriangle className="h-4 w-4" />Force stop · last resort</p><p className="mt-1 text-xs leading-5 text-red-700">Unsaved game progress may be lost.</p><button disabled={blocked || !running} onClick={() => onAction("force")} className="mt-3 rounded-xl border border-red-200 bg-white px-3 py-2 text-xs font-semibold text-red-700 disabled:opacity-40">Force stop game</button></div></div>}
  </div>
  <div className="border-t border-zinc-100 p-4"><h3 className="text-sm font-semibold">Recent activity</h3><div className="mt-3 space-y-2 rounded-2xl bg-zinc-50 p-3">{activity.slice(0, 3).map((entry, i) => <p key={i} className="text-[11px] leading-5 text-zinc-500">{entry}</p>)}</div></div>
 </aside>;
}
export const StreamOpsGameManager = () => {
  const [scenario, setScenario] = useState<Scenario>("default");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | "running" | "stopped">("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [overrides, setOverrides] = useState<Record<string, Proc>>({});
  const [confirm, setConfirm] = useState<{
    id: string;
    kind: ActionKind;
  } | null>(null);
  const [logs, setLogs] = useState<string[]>(["10:08 · Game inventory reconciled with host A", "10:07 · Diablo IV process observed running", "10:06 · OBS source configured; frames not verified"]);
  const [activityOpen, setActivityOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [reconciled, setReconciled] = useState(false);
  const list = scenario === "unregistered" ? [] : games;
  const status = (g: Game): Proc => {
    if (scenario === "offline" || scenario === "loading") return "UNKNOWN";
    if (overrides[g.id]) return overrides[g.id];
    if (scenario === "stale" && !reconciled && g.id === "d4") return "UNKNOWN";
    if (scenario === "startFail" && g.id === "d4") return "STOPPED";
    if (scenario === "externalExit" && g.id === "d4") return "STOPPED";
    if (scenario === "multi") return ["d4", "hk", "mc"].includes(g.id) ? "RUNNING" : "STOPPED";
    if (scenario === "empty" || scenario === "unregistered") return "STOPPED";
    return g.process;
  };
  const running = list.filter(g => status(g) === "RUNNING");
  const filtered = list.filter(g => (g.title + " " + g.provider + " " + g.genre).toLowerCase().includes(query.toLowerCase()) && (filter === "all" || (filter === "running" ? status(g) === "RUNNING" : status(g) === "STOPPED")));
  const selected = list.find(g => g.id === selectedId) || null;
  const addLog = (line: string) => setLogs(v => ["10:08 · " + line, ...v].slice(0, 12));
  const switchScenario = (next: Scenario) => {
    setScenario(next);
    setOverrides({});
    setReconciled(false);
    setSelectedId(["startFail", "stopTimeout", "restartFail", "stale", "externalExit"].includes(next) ? "d4" : null);
    setFilter("all");
    setQuery("");
    addLog("Design preview: " + scenarios.find(s => s.id === next)?.title);
  };
  const action = (kind: ActionKind) => {
    if (selected) setConfirm({
      id: selected.id,
      kind
    });
  };
  const execute = () => {
    if (!confirm) return;
    const {
      id,
      kind
    } = confirm;
    const g = list.find(v => v.id === id);
    setConfirm(null);
    setOverrides(v => ({
      ...v,
      [id]: kind === "start" ? "STARTING" : "STOPPING"
    }));
    addLog((g?.title || id) + " · demo " + kind + " requested");
    window.setTimeout(() => {
      const outcome: Proc = scenario === "startFail" && kind === "start" ? "FAILED" : scenario === "stopTimeout" && kind === "stop" ? "UNKNOWN" : scenario === "restartFail" && kind === "restart" ? "FAILED" : kind === "stop" || kind === "force" ? "STOPPED" : "RUNNING";
      setOverrides(v => ({
        ...v,
        [id]: outcome
      }));
      addLog((g?.title || id) + " · demo " + kind + " → " + outcome + (outcome === "UNKNOWN" ? " (requires reconciliation)" : ""));
    }, 1100);
  };
  const refresh = () => {
    setRefreshing(true);
    addLog("Reconciling observed process state; no lifecycle mutation");
    window.setTimeout(() => {
      setOverrides(v => ({
        ...v,
        d4: scenario === "externalExit" || scenario === "startFail" ? "STOPPED" : "RUNNING"
      }));
      setReconciled(true);
      setRefreshing(false);
      addLog("Observed process state refreshed. The outcome is now confirmed by demo fixture.");
    }, 850);
  };
  return <main className="min-h-screen bg-[#f5f6f8] text-zinc-950">
 <div className={"mx-auto w-full px-4 pb-12 pt-4 sm:px-6 " + (selected ? "max-w-5xl" : "max-w-[860px]")}>
   <header className="mb-4">
    <a href="https://designs.magicpath.ai/v1/serene-winter-5786" className="mb-3 inline-flex items-center gap-1 text-xs font-semibold text-zinc-500 hover:text-zinc-950"><ArrowLeft className="h-3.5 w-3.5" />Steam Manager</a>
    <div className="flex items-start justify-between gap-3">
      <div><p className="text-xs font-medium uppercase tracking-[0.18em] text-zinc-500">StreamOps</p><h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Game Manager</h1><p className="mt-1 text-xs text-zinc-500 sm:text-sm">Monitor and manage games across your host.</p></div>
      <Pill tone={scenario === "offline" ? "bad" : "ok"}>{scenario === "offline" ? "Node offline" : "Node online"}</Pill>
    </div>
   </header>
   <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-zinc-200 bg-white px-3 py-2.5">
    <span className="inline-flex items-center gap-1.5 text-xs text-zinc-500"><Info className="h-3.5 w-3.5" />Design preview · mock data</span>
    <select aria-label="Design scenario" value={scenario} onChange={e => switchScenario(e.target.value as Scenario)} className="max-w-44 rounded-xl border border-zinc-200 bg-white px-2 py-1.5 text-xs text-zinc-700">{scenarios.map(s => <option key={s.id} value={s.id}>{s.title}</option>)}</select>
   </div>
   {(scenario === "offline" || scenario === "session" || scenario === "black" || scenario === "stale" || scenario === "startFail" || scenario === "stopTimeout" || scenario === "restartFail" || scenario === "externalExit" || scenario === "loading") && <section className={"mb-3 rounded-3xl border p-4 " + (scenario === "black" ? "border-red-200 bg-red-50" : "border-amber-200 bg-amber-50")}><div className="flex items-start gap-2"><AlertTriangle className={"mt-0.5 h-4 w-4 shrink-0 " + (scenario === "black" ? "text-red-600" : "text-amber-700")} /><div><p className="text-sm font-semibold">{scenario === "offline" ? "Host A disconnected" : scenario === "session" ? "Interactive Windows session mismatch" : scenario === "startFail" ? "Start failure preview" : scenario === "stopTimeout" ? "Stop timeout preview" : scenario === "restartFail" ? "Restart failure preview" : scenario === "stale" ? "Stale process observation" : scenario === "externalExit" ? "Game exited outside StreamOps" : scenario === "loading" ? "Loading game inventory" : "OBS video verification failed"}</p><p className="mt-1 text-xs leading-5">{scenario === "offline" ? "All process states are UNKNOWN until a new host observation." : scenario === "session" ? "Controls are unavailable until the interactive session can be reconciled." : scenario === "startFail" ? "Select Diablo IV and simulate Start to see FAILED, then refresh/reconcile." : scenario === "stopTimeout" ? "Select Diablo IV and simulate Stop to see UNKNOWN. Refresh/reconcile before retry." : scenario === "restartFail" ? "Select Diablo IV and simulate Restart to see FAILED. Reconcile before further mutations." : scenario === "stale" ? "Last cached data is not trusted; refresh before operating." : scenario === "externalExit" ? "Observed STOPPED after an exit outside StreamOps. No automatic relaunch." : scenario === "loading" ? "Loading state is a fixture; do not treat unknown as stopped." : "Game is running, but its OBS source has no verified valid frames."}</p></div></div></section>}
   <div className={"grid items-start gap-4 " + (selected ? "lg:grid-cols-[minmax(0,1fr)_360px]" : "")}>
    <div className="min-w-0 space-y-4">
      <section className="rounded-3xl border border-black/5 bg-white p-4 shadow-sm sm:p-5">
       <div className="flex items-start justify-between gap-3"><div><h2 className="text-[15px] font-semibold">Games overview</h2><p className="mt-0.5 text-xs text-zinc-500">Current game inventory and process observations</p></div><button onClick={refresh} disabled={scenario === "offline" || scenario === "loading" || refreshing} className="inline-flex items-center gap-2 rounded-xl border border-zinc-200 px-3 py-2 text-xs font-semibold disabled:opacity-40"><RefreshCw className={"h-3.5 w-3.5 " + (refreshing ? "animate-spin" : "")} />{refreshing ? "Refreshing" : "Refresh"}</button></div>
       <div className="mt-4 grid grid-cols-3 gap-3">
        <Stat label="Running" value={scenario === "offline" || scenario === "loading" ? "—" : running.length} />
        <Stat label="Registered" value={scenario === "offline" || scenario === "loading" ? "—" : list.length} />
        <Stat label="Capture verified" value={scenario === "offline" || scenario === "loading" ? "—" : "0"} />
       </div>
      </section>
      <div>
       <TitleRow title={"Running games · " + (scenario === "offline" ? "—" : running.length)} icon={<Gamepad2 className="h-4 w-4" />} />
       {scenario === "loading" ? <section className="rounded-3xl border border-black/5 bg-white p-6 text-center shadow-sm"><p className="text-sm font-semibold">Loading game sessions…</p><p className="mt-1 text-xs text-zinc-500">Waiting for host inventory. No status assumptions.</p></section> : scenario === "offline" ? <section className="rounded-3xl border border-black/5 bg-white p-6 text-center shadow-sm"><WifiOff className="mx-auto h-6 w-6 text-zinc-400" /><p className="mt-2 text-sm font-semibold">Running state unavailable</p><p className="mt-1 text-xs text-zinc-500">Reconnect host A to verify running processes.</p></section> : running.length === 0 ? <section className="rounded-3xl border border-black/5 bg-white p-6 text-center shadow-sm"><Gamepad2 className="mx-auto h-6 w-6 text-zinc-400" /><p className="mt-2 text-sm font-semibold">No games running</p><p className="mt-1 text-xs text-zinc-500">Select a registered game in the library below.</p></section> : <div className="space-y-3">{running.map(g => <button key={g.id} onClick={() => setSelectedId(g.id)} className={"flex w-full items-center gap-3 rounded-3xl border bg-white p-4 text-left shadow-sm transition-colors hover:border-zinc-300 " + (selectedId === g.id ? "border-indigo-200" : "border-black/5")}><GameIcon title={g.title} /><div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold">{g.title}</p><p className="mt-1 truncate text-xs text-zinc-500">{g.provider} · {g.genre} · {g.uptime}</p></div><div className="flex shrink-0 items-center gap-2"><Pill tone="ok">Running</Pill><ChevronRight className="h-4 w-4 text-zinc-400" /></div></button>)}</div>}
      </div>
      <div>
       <TitleRow title="Game library" icon={<Library className="h-4 w-4" />} />
       <section className="overflow-hidden rounded-3xl border border-black/5 bg-white shadow-sm">
        <div className="border-b border-zinc-100 p-4">
         <div className="flex flex-col gap-3"><div className="relative"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" /><input value={query} onChange={e => setQuery(e.target.value)} aria-label="Search games" placeholder="Search games or launchers…" className="w-full rounded-xl border border-zinc-200 bg-zinc-50 py-2.5 pl-9 pr-3 text-xs outline-offset-2" /></div>
         <div className="grid grid-cols-3 gap-2">{(["all", "running", "stopped"] as const).map(f => <button key={f} onClick={() => setFilter(f)} className={"rounded-xl px-3 py-2 text-xs font-semibold " + (filter === f ? "bg-zinc-950 text-white" : "bg-zinc-100 text-zinc-600")}>{f[0].toUpperCase() + f.slice(1)}</button>)}</div></div>
        </div>
        {filtered.length === 0 ? <div className="p-6 text-center"><p className="text-sm font-semibold">{list.length === 0 ? "No registered games" : "No matching games"}</p><p className="mt-1 text-xs text-zinc-500">{list.length === 0 ? "Library is empty in this design scenario." : "Change the search or filter."}</p></div> : <div className="divide-y divide-zinc-100">{filtered.map(g => <button key={g.id} onClick={() => setSelectedId(g.id)} className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-zinc-50"><GameIcon title={g.title} /><div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold">{g.title}</p><p className="mt-0.5 truncate text-xs text-zinc-500">{g.provider} · {g.genre}</p></div><Pill tone={status(g) === "RUNNING" ? "ok" : status(g) === "UNKNOWN" ? "warn" : status(g) === "STARTING" || status(g) === "STOPPING" ? "blue" : "neutral"}>{displayProc(status(g))}</Pill><ChevronRight className="h-4 w-4 shrink-0 text-zinc-400" /></button>)}</div>}
       </section>
      </div>
      <section className="overflow-hidden rounded-3xl border border-black/5 bg-white shadow-sm">
       <button onClick={() => setActivityOpen(v => !v)} aria-expanded={activityOpen} className="flex w-full items-center justify-between p-4 text-left"><div><h2 className="text-sm font-semibold">Activity log</h2><p className="mt-0.5 text-xs text-zinc-500">Browser session only · {logs.length} events</p></div><ChevronDown className={"h-4 w-4 text-zinc-400 " + (activityOpen ? "rotate-180" : "")} /></button>
       {activityOpen && <div className="space-y-2 border-t border-zinc-100 p-4">{logs.map((line, i) => <p key={i} className="rounded-xl bg-zinc-50 px-3 py-2 text-xs text-zinc-600">{line}</p>)}</div>}
      </section>
    </div>
    {selected && <div className="fixed inset-0 z-40 overflow-y-auto bg-[#f5f6f8] p-4 lg:static lg:z-auto lg:overflow-visible lg:bg-transparent lg:p-0"><GameDetail key={selected.id} game={selected} proc={status(selected)} scenario={scenario} onBack={() => setSelectedId(null)} onAction={action} onReconcile={refresh} activity={logs} /></div>}
   </div>
   <footer className="mt-5 text-center text-[11px] text-zinc-400">StreamOps UI Prototype · Design fixtures, not live API data</footer>
 </div>
 {confirm && (() => {
      const {
        id,
        kind
      } = confirm;
      const name = list.find(g => g.id === id)?.title || "game";
      const label = kind === "force" ? "Force stop" : kind[0].toUpperCase() + kind.slice(1);
      return <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-950/40 p-4"><div className="w-full max-w-sm rounded-3xl bg-white p-5 shadow-xl" role="dialog" aria-modal="true" aria-labelledby="game-confirm"><div className="flex items-start justify-between gap-3"><h2 className="text-base font-semibold" id="game-confirm">{label} {name}?</h2><button onClick={() => setConfirm(null)} aria-label="Close" className="text-zinc-500"><X className="h-4 w-4" /></button></div><p className="mt-2 text-xs leading-5 text-zinc-600">{kind === "force" ? "This immediately terminates the process and may cause loss of unsaved game progress. Use only when graceful stop fails." : kind === "restart" ? "The current game will stop and restart. Save progress first." : kind === "stop" ? "Gracefully stop the game. Make sure progress is saved." : "Start a simulated game session."}</p><div className="mt-3 rounded-xl bg-blue-50 p-3 text-xs text-blue-700">Design simulation only. No process on host A will change.</div><div className="mt-4 grid grid-cols-2 gap-2"><button onClick={() => setConfirm(null)} className="rounded-2xl border border-zinc-200 px-3 py-3 text-xs font-semibold">Cancel</button><button onClick={execute} className={"rounded-2xl px-3 py-3 text-xs font-semibold text-white " + (kind === "force" ? "bg-red-700" : "bg-zinc-950")}>Simulate {label.toLowerCase()}</button></div></div></div>;
    })()}
 </main>;
};