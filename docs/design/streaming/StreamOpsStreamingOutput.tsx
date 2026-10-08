import { useState } from "react";
type Tone = "ok" | "warn" | "bad" | "neutral" | "blue";
function Pill({
  children,
  tone = "neutral"
}: {
  children: React.ReactNode;
  tone?: Tone;
}) {
  const map = {
    ok: "bg-emerald-50 text-emerald-700",
    warn: "bg-amber-50 text-amber-700",
    bad: "bg-red-50 text-red-700",
    blue: "bg-blue-50 text-blue-700",
    neutral: "bg-zinc-100 text-zinc-700"
  };
  return <span className={"inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-semibold " + map[tone]}>{children}</span>;
}
function Chevron({
  open
}: {
  open: boolean;
}) {
  return <span className={"text-zinc-400 transition-transform " + (open ? "rotate-180" : "")}>⌄</span>;
}
function Card({
  title,
  subtitle,
  status,
  tone = "neutral",
  summary,
  open,
  onToggle,
  children
}: {
  title: string;
  subtitle: string;
  status: string;
  tone?: Tone;
  summary: React.ReactNode;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return <section className="overflow-hidden rounded-3xl border border-black/5 bg-white shadow-sm">
    <button onClick={onToggle} className="w-full px-4 py-4 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/30">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-[15px] font-semibold text-zinc-900">{title}</h2>
            <Pill tone={tone}>{status}</Pill>
          </div>
          <p className="mt-0.5 text-xs text-zinc-500">{subtitle}</p>
        </div>
        <Chevron open={open} />
      </div>
      <div className="mt-3">{summary}</div>
    </button>
    {open && <div className="border-t border-zinc-100 px-4 pb-4 pt-3">{children}</div>}
  </section>;
}
function Summary({
  items
}: {
  items: Array<[string, string]>;
}) {
  return <div className={"grid gap-x-4 gap-y-2 " + (items.length === 3 ? "grid-cols-3" : "grid-cols-2")}>
    {items.map(([label, value]) => <div key={label} className="min-w-0">
      <p className="text-[11px] text-zinc-500">{label}</p>
      <p className="truncate text-sm font-semibold text-zinc-900">{value}</p>
    </div>)}
  </div>;
}
function StatRow({
  label,
  value,
  tone
}: {
  label: string;
  value: string;
  tone?: Tone;
}) {
  return <div className="flex items-center justify-between gap-4 border-b border-zinc-100 py-2.5 last:border-b-0">
    <span className="text-xs text-zinc-500">{label}</span>
    {tone ? <Pill tone={tone}>{value}</Pill> : <span className="text-right text-xs font-semibold text-zinc-800">{value}</span>}
  </div>;
}
function InputLabel({
  children
}: {
  children: React.ReactNode;
}) {
  return <span className="mb-1 block text-[11px] font-medium text-zinc-500">{children}</span>;
}
export const StreamOpsStreamingOutput = () => {
  const [open, setOpen] = useState({
    destination: true,
    setup: false,
    preflight: false,
    control: true,
    activity: false
  });
  const [destination, setDestination] = useState("LAN Test");
  const [profile, setProfile] = useState("livestream-d4");
  const [serverUrl, setServerUrl] = useState("rtmp://127.0.0.1:1935/live");
  const [credentialConfigured, setCredentialConfigured] = useState(true);
  const [live, setLive] = useState(false);
  const toggle = (key: keyof typeof open) => setOpen(v => ({
    ...v,
    [key]: !v[key]
  }));
  const preflightPass = credentialConfigured;
  return <main className="min-h-screen bg-[#f5f6f8] text-zinc-950">
    <div className="mx-auto w-full max-w-[760px] px-4 pb-10 pt-4 sm:px-5">
      <header className="mb-4">
        <a href="/obs" className="mb-3 inline-flex items-center gap-1 text-xs font-semibold text-zinc-500 hover:text-zinc-900">← OBS Management</a>
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-zinc-500">StreamOps</p>
            <h1 className="text-2xl font-semibold tracking-tight sm:text-[30px]">Streaming</h1>
            <p className="mt-1 text-xs text-zinc-500">Destinations, preflight, live control and output health.</p>
          </div>
          <Pill tone={live ? "ok" : preflightPass ? "blue" : "warn"}>{live ? "LIVE" : preflightPass ? "READY" : "BLOCKED"}</Pill>
        </div>
      </header>

      <div className="space-y-3">
        <Card title="Destination" subtitle="Where OBS sends the stream" status={credentialConfigured ? "CONFIGURED" : "NEEDS KEY"} tone={credentialConfigured ? "ok" : "warn"} open={open.destination} onToggle={() => toggle("destination")} summary={<Summary items={[["Name", destination], ["Type", "Custom RTMP"], ["Credential", credentialConfigured ? "Configured" : "Missing"]]} />}>
          <div className="space-y-3">
            <label className="block">
              <InputLabel>Destination</InputLabel>
              <select value={destination} onChange={e => setDestination(e.target.value)} disabled={live} className="w-full rounded-xl border border-zinc-200 bg-white px-3 py-2.5 text-sm disabled:bg-zinc-50 disabled:text-zinc-400">
                <option>LAN Test</option>
                <option>Backup RTMP</option>
              </select>
            </label>
            <label className="block">
              <InputLabel>Server URL</InputLabel>
              <input value={serverUrl} onChange={e => setServerUrl(e.target.value)} disabled={live} className="w-full rounded-xl border border-zinc-200 bg-white px-3 py-2.5 font-mono text-xs disabled:bg-zinc-50 disabled:text-zinc-400" />
            </label>
            <div className="rounded-2xl bg-zinc-50 px-3 py-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold text-zinc-800">Stream Key</p>
                  <p className="mt-0.5 text-[11px] text-zinc-500">Saved secret is never displayed again.</p>
                </div>
                <Pill tone={credentialConfigured ? "ok" : "warn"}>{credentialConfigured ? "Configured" : "Missing"}</Pill>
              </div>
              {!live && <div className="mt-3 grid grid-cols-2 gap-2">
                <button onClick={() => setCredentialConfigured(true)} className="rounded-xl border border-zinc-200 bg-white px-3 py-2.5 text-xs font-semibold">Replace credential</button>
                <button onClick={() => setCredentialConfigured(false)} className="rounded-xl border border-red-200 bg-white px-3 py-2.5 text-xs font-semibold text-red-600">Remove</button>
              </div>}
            </div>
            {!live && <div className="grid grid-cols-[1fr_auto] gap-2">
              <button className="rounded-xl bg-zinc-950 px-3 py-2.5 text-xs font-semibold text-white">Save destination</button>
              <button className="rounded-xl border border-zinc-200 bg-white px-3 py-2.5 text-xs font-semibold">•••</button>
            </div>}
            {live && <p className="rounded-xl bg-zinc-50 px-3 py-2.5 text-[11px] text-zinc-500">Destination settings are locked while this live session is active.</p>}
          </div>
        </Card>

        <Card title="Stream Setup" subtitle="Scene profile bound to this live session" status="SAVED" tone="blue" open={open.setup} onToggle={() => toggle("setup")} summary={<Summary items={[["Profile", profile], ["Canvas", "3840×2160"], ["FPS", "60"]]} />}>
          <label className="block">
            <InputLabel>Saved Scene Profile</InputLabel>
            <select value={profile} onChange={e => setProfile(e.target.value)} disabled={live} className="w-full rounded-xl border border-zinc-200 bg-white px-3 py-2.5 text-sm disabled:bg-zinc-50 disabled:text-zinc-400">
              <option>livestream-d4</option>
              <option>gaming-poc</option>
              <option>PR19 Motion + tone</option>
            </select>
          </label>
          <div className="mt-3 rounded-2xl bg-zinc-50 px-3">
            <StatRow label="Profile state" value="Saved" tone="blue" />
            <StatRow label="Verification" value="PASS" tone="ok" />
            <StatRow label="OBS scene" value="StreamOps Scene" />
          </div>
        </Card>

        <Card title="Preflight" subtitle="Required checks before streaming" status={preflightPass ? "PASS" : "FAIL"} tone={preflightPass ? "ok" : "bad"} open={open.preflight} onToggle={() => toggle("preflight")} summary={<Summary items={[["OBS", "Ready"], ["Profile", "PASS"], ["Output", preflightPass ? "Ready" : "Blocked"]]} />}>
          <div className="rounded-2xl bg-zinc-50 px-3">
            <StatRow label="OBS Runtime" value="PASS" tone="ok" />
            <StatRow label="Scene Profile" value="PASS" tone="ok" />
            <StatRow label="Destination" value="PASS" tone="ok" />
            <StatRow label="Credential" value={credentialConfigured ? "PASS" : "FAIL"} tone={credentialConfigured ? "ok" : "bad"} />
            <StatRow label="Output Engine" value="PASS" tone="ok" />
          </div>
          {!credentialConfigured && <p className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 text-[11px] text-amber-800">Configure the Stream Key before starting.</p>}
          <button className="mt-3 w-full rounded-xl border border-zinc-200 bg-white px-3 py-2.5 text-xs font-semibold">Run Preflight</button>
        </Card>

        <Card title={live ? "Live Status" : "Live Control"} subtitle={live ? "Current OBS output health" : "Start the selected destination"} status={live ? "LIVE" : preflightPass ? "READY" : "BLOCKED"} tone={live ? "ok" : preflightPass ? "ok" : "warn"} open={open.control} onToggle={() => toggle("control")} summary={live ? <Summary items={[["Destination", destination], ["Uptime", "00:12:33"], ["Avg bitrate", "8.4 Mbps"]]} /> : <Summary items={[["Destination", destination], ["Profile", profile], ["State", preflightPass ? "Ready" : "Blocked"]]} />}>
          {live ? <>
            <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
              {[["Output", "Active"], ["Avg bitrate", "8.4 Mbps"], ["Active FPS", "60.0"], ["Skipped frames", "0"], ["Reconnect", "No"], ["Congestion", "0.01"]].map(([label, value]) => <div key={label} className="rounded-2xl bg-zinc-50 px-3 py-3">
                <p className="text-[11px] text-zinc-500">{label}</p>
                <p className="mt-0.5 text-sm font-semibold">{value}</p>
              </div>)}
            </div>
            <button onClick={() => setLive(false)} className="w-full rounded-2xl border border-red-200 bg-white px-4 py-3 text-sm font-semibold text-red-600">Stop Streaming</button>
          </> : <>
            <div className="mb-3 rounded-2xl bg-zinc-50 px-3">
              <StatRow label="Destination" value={destination} />
              <StatRow label="Scene Profile" value={profile} />
              <StatRow label="Preflight" value={preflightPass ? "PASS" : "FAIL"} tone={preflightPass ? "ok" : "bad"} />
            </div>
            <button disabled={!preflightPass} onClick={() => setLive(true)} className="w-full rounded-2xl bg-zinc-950 px-4 py-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40">Start Streaming</button>
          </>}
        </Card>

        <Card title="Stream Activity" subtitle="Streaming events for this browser session" status="0 ERRORS" tone="neutral" open={open.activity} onToggle={() => toggle("activity")} summary={<Summary items={[["Last event", live ? "stream start: LIVE" : "preflight: PASS"], ["Warnings", "0"]]} />}>
          <ol className="space-y-2 text-xs">
            <li className="flex gap-3 border-b border-zinc-100 pb-2"><span className="text-zinc-400">10:16:04</span><span className="font-medium">live socket: connected</span></li>
            <li className="flex gap-3 border-b border-zinc-100 pb-2"><span className="text-zinc-400">10:16:09</span><span className="font-medium text-emerald-700">preflight: PASS</span></li>
            {live && <li className="flex gap-3"><span className="text-zinc-400">10:16:14</span><span className="font-medium text-emerald-700">stream start: LIVE</span></li>}
          </ol>
        </Card>
      </div>
    </div>
  </main>;
};