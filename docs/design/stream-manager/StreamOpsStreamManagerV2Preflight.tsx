import { useMemo, useState } from "react";
type State = "IDLE" | "STARTING" | "LIVE" | "RECONNECTING" | "STOPPING" | "FAILED";
type Destination = {
  id: string;
  name: string;
  platform: string;
  state: State;
  bitrate?: string;
  fps?: string;
  duration?: string;
  error?: string;
  credential: boolean;
};
const checks = [["OBS process", "READY"], ["WebSocket", "CONNECTED"], ["Active scene", "D4"], ["Profile", "livestream-d4"], ["Video capture", "ACTIVE"], ["Audio", "ACTIVE"]] as const;
const initial: Destination[] = [{
  id: "yt-noru",
  name: "Noru",
  platform: "YouTube",
  state: "LIVE",
  bitrate: "10.1 Mbps",
  fps: "60 FPS",
  duration: "01:23:42",
  credential: true
}, {
  id: "tw-noru",
  name: "Noru",
  platform: "Twitch",
  state: "RECONNECTING",
  error: "Connection lost · reconnecting…",
  credential: true
}, {
  id: "fb-noru",
  name: "Noru",
  platform: "Facebook",
  state: "IDLE",
  credential: true
}, {
  id: "tt-noru",
  name: "Noru",
  platform: "TikTok",
  state: "FAILED",
  error: "Receiver rejected connection",
  credential: true
}];
const stateStyle: Record<State, string> = {
  IDLE: "bg-zinc-100 text-zinc-600",
  STARTING: "bg-blue-50 text-blue-700",
  LIVE: "bg-emerald-50 text-emerald-700",
  RECONNECTING: "bg-amber-50 text-amber-700",
  STOPPING: "bg-blue-50 text-blue-700",
  FAILED: "bg-red-50 text-red-700"
};
function StatePill({
  state
}: {
  state: State;
}) {
  return <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${stateStyle[state]}`}>{state}</span>;
}
export const StreamOpsStreamManagerV2Preflight = () => {
  const [preflightOpen, setPreflightOpen] = useState(true);
  const [preflightPassed, setPreflightPassed] = useState(true);
  const [activityOpen, setActivityOpen] = useState(false);
  const [expanded, setExpanded] = useState<string | null>("fb-noru");
  const [destinations, setDestinations] = useState(initial);
  const liveCount = destinations.filter(d => d.state === "LIVE").length;
  const aggregate = useMemo(() => `${destinations.length} destinations · ${liveCount} live`, [destinations, liveCount]);
  const destinationReady = (d: Destination) => d.credential && (d.state === "IDLE" || d.state === "FAILED");
  const mutate = (id: string, next: State) => setDestinations(ds => ds.map(d => d.id === id ? {
    ...d,
    state: next,
    error: next === "FAILED" ? d.error : undefined
  } : d));
  return <main className="min-h-screen bg-[#f5f6f8] text-zinc-950">
    <div className="mx-auto w-full max-w-[860px] px-4 pb-12 pt-5 sm:px-6">
      <a href="/obs" className="text-xs font-semibold text-zinc-500">← OBS Management</a>

      <header className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-medium uppercase tracking-[.18em] text-zinc-500">StreamOps</p>
          <h1 className="text-3xl font-semibold tracking-tight">Stream Manager</h1>
          <p className="mt-1 text-sm text-zinc-500">Preflight first, then control each destination independently.</p>
        </div>
        <button className="rounded-xl bg-zinc-950 px-4 py-2.5 text-sm font-semibold text-white active:scale-[.97]">+ Add destination</button>
      </header>

      <section className="mt-5 rounded-3xl border border-black/5 bg-white p-4 shadow-sm sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-semibold">OBS session</p>
            <p className="mt-0.5 text-xs text-zinc-500">Runtime and scene shared by all destinations</p>
          </div>
          <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-semibold text-emerald-700">● READY</span>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[["Scene", "D4"], ["Profile", "livestream-d4"], ["Canvas", "3840×2160"], ["Destinations", aggregate]].map(([a, b]) => <div key={a} className="rounded-2xl bg-zinc-50 p-3">
              <p className="text-[11px] text-zinc-500">{a}</p>
              <p className="mt-1 truncate text-sm font-semibold">{b}</p>
            </div>)}
        </div>
      </section>

      <section className="mt-4 overflow-hidden rounded-3xl border border-black/5 bg-white shadow-sm">
        <button onClick={() => setPreflightOpen(v => !v)} className="w-full p-4 text-left sm:p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-base font-semibold">Preflight</h2>
                <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${preflightPassed ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>
                  {preflightPassed ? "6/6 PASSED" : "5/6 FAILED"}
                </span>
              </div>
              <p className="mt-1 text-xs text-zinc-500">Shared checks required before starting any destination.</p>
            </div>
            <span className="text-zinc-400">{preflightOpen ? "⌃" : "⌄"}</span>
          </div>
        </button>
        {preflightOpen && <div className="border-t border-zinc-100 p-4 sm:p-5">
          <div className="grid gap-2 sm:grid-cols-2">
            {checks.map(([label, value], i) => {
              const failed = !preflightPassed && i === 4;
              return <div key={label} className="flex items-center justify-between rounded-2xl bg-zinc-50 px-3 py-3">
                <span className="text-xs font-medium text-zinc-600">{label}</span>
                <span className={`text-xs font-semibold ${failed ? "text-red-700" : "text-emerald-700"}`}>{failed ? "INACTIVE" : value}</span>
              </div>;
            })}
          </div>
          {!preflightPassed && <div className="mt-3 rounded-2xl bg-red-50 p-3 text-red-800">
            <p className="text-xs font-semibold">Preflight failed</p>
            <p className="mt-1 text-xs">Video capture is inactive. Start actions are blocked until this check passes.</p>
          </div>}
          <div className="mt-4 flex flex-wrap gap-2">
            <button onClick={() => setPreflightPassed(v => !v)} className="rounded-xl border border-zinc-200 px-3 py-2 text-xs font-semibold">Demo pass/fail</button>
            <button className="rounded-xl bg-zinc-950 px-3 py-2 text-xs font-semibold text-white active:scale-[.97]">Run preflight</button>
          </div>
        </div>}
      </section>

      <div className="mt-6">
        <h2 className="text-base font-semibold">Destinations</h2>
        <p className="mt-1 text-xs text-zinc-500">Each destination has its own readiness and runtime state.</p>
      </div>

      <div className="mt-3 space-y-3">
        {destinations.map(d => {
          const open = expanded === d.id;
          const busy = d.state === "STARTING" || d.state === "STOPPING";
          const ready = destinationReady(d);
          const canStart = preflightPassed && ready;
          return <section key={d.id} className="overflow-hidden rounded-3xl border border-black/5 bg-white shadow-sm">
            <button onClick={() => setExpanded(open ? null : d.id)} className="w-full p-4 text-left sm:p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-semibold">{d.platform} · {d.name}</h3>
                    <StatePill state={d.state} />
                    {(d.state === "IDLE" || d.state === "FAILED") && <span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${canStart ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}>{canStart ? "READY" : "BLOCKED"}</span>}
                  </div>
                  <p className="mt-1 text-xs text-zinc-500">
                    {d.state === "LIVE" ? `${d.bitrate} · ${d.fps} · ${d.duration}` : d.error || (busy ? "Waiting for backend runtime confirmation…" : canStart ? "Ready to stream" : !preflightPassed ? "Blocked by shared preflight" : "Destination configuration incomplete")}
                  </p>
                </div>
                <span className="text-zinc-400">{open ? "⌃" : "⌄"}</span>
              </div>
            </button>

            {open && <div className="border-t border-zinc-100 p-4 sm:p-5">
              <div className="grid gap-2 sm:grid-cols-3">
                <div className="rounded-2xl bg-zinc-50 p-3">
                  <p className="text-[11px] text-zinc-500">Endpoint</p>
                  <p className="mt-1 truncate text-xs font-semibold">Configured</p>
                </div>
                <div className="rounded-2xl bg-zinc-50 p-3">
                  <p className="text-[11px] text-zinc-500">Stream key</p>
                  <p className="mt-1 text-xs font-semibold">{d.credential ? "Configured" : "Missing"}</p>
                </div>
                <div className="rounded-2xl bg-zinc-50 p-3">
                  <p className="text-[11px] text-zinc-500">Readiness</p>
                  <p className={`mt-1 text-xs font-semibold ${canStart ? "text-emerald-700" : "text-amber-700"}`}>{canStart ? "Ready" : "Blocked"}</p>
                </div>
              </div>

              {(d.state === "FAILED" || d.state === "RECONNECTING") && <div className={`mt-3 rounded-2xl p-3 ${d.state === "FAILED" ? "bg-red-50 text-red-800" : "bg-amber-50 text-amber-800"}`}>
                <p className="text-xs font-semibold">{d.state === "FAILED" ? "Destination failed" : "Connection interrupted"}</p>
                <p className="mt-1 text-xs">{d.error}</p>
              </div>}

              <div className="mt-4 flex flex-wrap gap-2">
                {d.state === "IDLE" || d.state === "FAILED" ? <button disabled={!canStart} onClick={() => canStart && mutate(d.id, "STARTING")} className="rounded-xl bg-zinc-950 px-4 py-2.5 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-35">{d.state === "FAILED" ? "Start again" : "Start"}</button> : <button onClick={() => mutate(d.id, "STOPPING")} disabled={d.state === "STOPPING"} className="rounded-xl border border-red-200 bg-white px-4 py-2.5 text-xs font-semibold text-red-600 disabled:opacity-40">Stop</button>}
                <button className="rounded-xl border border-zinc-200 px-4 py-2.5 text-xs font-semibold">Edit</button>
                {d.state === "STARTING" && <button onClick={() => mutate(d.id, "LIVE")} className="ml-auto rounded-xl bg-blue-50 px-3 py-2 text-[11px] font-semibold text-blue-700">Demo backend → LIVE</button>}
                {d.state === "STOPPING" && <button onClick={() => mutate(d.id, "IDLE")} className="ml-auto rounded-xl bg-blue-50 px-3 py-2 text-[11px] font-semibold text-blue-700">Demo backend → IDLE</button>}
                {d.state === "RECONNECTING" && <button onClick={() => mutate(d.id, "LIVE")} className="ml-auto rounded-xl bg-emerald-50 px-3 py-2 text-[11px] font-semibold text-emerald-700">Demo recovery → LIVE</button>}
              </div>
            </div>}
          </section>;
        })}
      </div>

      <section className="mt-4 overflow-hidden rounded-3xl border border-black/5 bg-white shadow-sm">
        <button onClick={() => setActivityOpen(v => !v)} className="w-full p-4 text-left sm:p-5">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-base font-semibold">Stream Activity</h2>
                <span className="rounded-full bg-zinc-100 px-2.5 py-1 text-[11px] font-semibold text-zinc-600">1 ERROR</span>
              </div>
              <p className="mt-1 text-xs text-zinc-500">Recent streaming events across all destinations.</p>
              {!activityOpen && <p className="mt-3 truncate text-xs"><span className="text-zinc-400">10:16:14</span><span className="ml-3 font-medium text-red-700">TikTok · connection failed</span></p>}
            </div>
            <span className="text-zinc-400">{activityOpen ? "⌃" : "⌄"}</span>
          </div>
        </button>
        {activityOpen && <div className="border-t border-zinc-100 p-4 sm:p-5">
          <ol className="space-y-2 text-xs">
            <li className="flex gap-3 border-b border-zinc-100 pb-2"><span className="shrink-0 text-zinc-400">10:16:04</span><span className="font-medium">YouTube · stream status: LIVE</span></li>
            <li className="flex gap-3 border-b border-zinc-100 pb-2"><span className="shrink-0 text-zinc-400">10:16:09</span><span className="font-medium text-amber-700">Twitch · reconnecting</span></li>
            <li className="flex gap-3 border-b border-zinc-100 pb-2"><span className="shrink-0 text-zinc-400">10:16:14</span><span className="font-medium text-red-700">TikTok · connection failed</span></li>
            <li className="flex gap-3"><span className="shrink-0 text-zinc-400">10:16:20</span><span className="font-medium text-emerald-700">Preflight · 6/6 PASSED</span></li>
          </ol>
        </div>}
      </section>
    </div>
  </main>;
};