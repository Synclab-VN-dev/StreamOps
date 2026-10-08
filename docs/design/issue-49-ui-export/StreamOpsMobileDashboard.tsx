import { useState } from "react";
type CardKey = "runtime" | "profile" | "sources" | "canvas" | "verification" | "review" | "stream" | "plugins" | "activity";
type Source = {
  name: string;
  type: string;
  enabled: boolean;
  layer: number;
  summary: string;
  transform?: string;
  audio?: string;
  verify?: string;
};
type SourceType = {
  id: string;
  label: string;
  group: "Video" | "Audio";
  detail: string;
  inventory?: string;
};
const runtimeRows = [["PID", "4492"], ["Started", "30/09/2026, 21:56:52"], ["Uptime", "01:24:10"], ["Windows Session", "1"], ["Active Console Session", "1"], ["Interactive", "Yes"], ["Executable", "C:\\Program Files\\obs-studio\\bin\\64bit\\obs64.exe"], ["WebSocket", "Connected"], ["WebSocket Endpoint", "127.0.0.1:4455"], ["OBS Version", "32.2.1"], ["obs-websocket Version", "5.7.4"], ["Streaming", "No"], ["Recording", "No"], ["Last Operation", "restart · success · 22:01:04"]];
const sourceCatalog: SourceType[] = [{
  id: "game_capture",
  label: "Game Capture",
  group: "Video",
  detail: "Capture fullscreen game, selected window or hotkey target",
  inventory: "Window list"
}, {
  id: "window_capture",
  label: "Window Capture",
  group: "Video",
  detail: "Capture a selected desktop window",
  inventory: "Window list"
}, {
  id: "display_capture",
  label: "Display Capture",
  group: "Video",
  detail: "Capture a monitor/display",
  inventory: "Monitor list"
}, {
  id: "video_capture_device",
  label: "Video Capture Device",
  group: "Video",
  detail: "Camera or capture card; can include audio",
  inventory: "Camera/device list"
}, {
  id: "media_stream",
  label: "Media / SRT / RTSP",
  group: "Video",
  detail: "Network media stream; video + optional audio"
}, {
  id: "browser_source",
  label: "Browser",
  group: "Video",
  detail: "URL or local HTML source; optional routed audio"
}, {
  id: "image",
  label: "Image",
  group: "Video",
  detail: "Static image file"
}, {
  id: "video_file",
  label: "Video File",
  group: "Video",
  detail: "Local video file; video + optional audio"
}, {
  id: "existing_video",
  label: "Existing OBS Video Source",
  group: "Video",
  detail: "Bind an existing OBS video input",
  inventory: "OBS input list"
}, {
  id: "audio_input",
  label: "Audio Input Device",
  group: "Audio",
  detail: "Microphone or other input device",
  inventory: "Capture devices"
}, {
  id: "application_audio",
  label: "Application Audio",
  group: "Audio",
  detail: "Capture audio from a selected application/window",
  inventory: "Window list"
}, {
  id: "audio_output",
  label: "Audio Output Capture",
  group: "Audio",
  detail: "Desktop/output device audio",
  inventory: "Render devices"
}, {
  id: "existing_audio",
  label: "Existing OBS Audio Source",
  group: "Audio",
  detail: "Bind an existing OBS audio input",
  inventory: "OBS input list"
}];
const initialSources: Source[] = [{
  name: "Diablo IV",
  type: "Game Capture",
  enabled: true,
  layer: 0,
  summary: "Fullscreen · cursor off",
  transform: "x 0 · y 0 · 3840×2160 · crop 0/0/0/0",
  verify: "Video signal required · 2s sample"
}, {
  name: "Camera",
  type: "Video Capture Device",
  enabled: true,
  layer: 1,
  summary: "USB camera · 1920×1080",
  transform: "x 2900 · y 120 · 820×460 · crop 0/0/0/0",
  audio: "Audio on · 0 dB · sync 0 ms · Track 2",
  verify: "Video + audio signal · threshold -50 dB"
}, {
  name: "Game Audio",
  type: "Application Audio",
  enabled: true,
  layer: 2,
  summary: "Diablo IV process audio",
  audio: "Enabled · 0 dB · Track 1",
  verify: "Audio signal required · threshold -50 dB"
}, {
  name: "Mic",
  type: "Audio Input Device",
  enabled: true,
  layer: 3,
  summary: "External microphone",
  audio: "Enabled · -3 dB · Track 2",
  verify: "Audio signal required · threshold -50 dB"
}];
function Chevron({
  open
}: {
  open: boolean;
}) {
  return <span className={"text-zinc-400 transition-transform " + (open ? "rotate-180" : "")}>⌄</span>;
}
function Pill({
  children,
  tone = "neutral"
}: {
  children: React.ReactNode;
  tone?: "ok" | "warn" | "bad" | "neutral" | "blue";
}) {
  const map = {
    ok: "bg-emerald-50 text-emerald-700",
    warn: "bg-amber-50 text-amber-700",
    bad: "bg-red-50 text-red-700",
    blue: "bg-blue-50 text-blue-700",
    neutral: "bg-zinc-100 text-zinc-700"
  };
  return <span className={"rounded-full px-2.5 py-1 text-[11px] font-semibold " + map[tone]}>{children}</span>;
}
function Card({
  title,
  subtitle,
  summary,
  open,
  onToggle,
  children,
  status
}: {
  title: string;
  subtitle?: string;
  summary: React.ReactNode;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
  status?: React.ReactNode;
}) {
  return <section className="overflow-hidden rounded-3xl border border-black/5 bg-white shadow-sm">
    <button onClick={onToggle} className="w-full px-4 py-4 text-left">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h2 className="text-[15px] font-semibold">{title}</h2>
            {status}
          </div>
          {subtitle && <p className="mt-0.5 text-xs text-zinc-500">{subtitle}</p>}
        </div>
        <Chevron open={open} />
      </div>
      <div className="mt-3">{summary}</div>
    </button>
    {open && <div className="border-t border-zinc-100 px-4 pb-4 pt-3">{children}</div>}
  </section>;
}
function StatRow({
  label,
  value
}: {
  label: string;
  value: string;
}) {
  return <div className="flex gap-4 border-b border-zinc-100 py-2.5 last:border-b-0">
    <div className="w-32 shrink-0 text-xs text-zinc-500">{label}</div>
    <div className="min-w-0 flex-1 break-words text-sm font-medium">{value}</div>
  </div>;
}
export const StreamOpsMobileDashboard = () => {
  const [open, setOpen] = useState<Record<CardKey, boolean>>({
    runtime: false,
    profile: false,
    sources: false,
    canvas: false,
    verification: false,
    review: false,
    stream: false,
    plugins: false,
    activity: false
  });
  const [selectedProfile, setSelectedProfile] = useState("livestream-d4");
  const [profileState, setProfileState] = useState("Applied");
  const [previewTab, setPreviewTab] = useState<"layout" | "preview">("preview");
  const [notice, setNotice] = useState<string | null>(null);
  const [profileSources, setProfileSources] = useState<Source[]>(initialSources);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [selectedSourceType, setSelectedSourceType] = useState("game_capture");
  const toggle = (key: CardKey) => setOpen(v => ({
    ...v,
    [key]: !v[key]
  }));
  const fakeAction = (label: string) => {
    setNotice(label + " requested");
    if (label === "Apply saved") setProfileState("Applied");
    if (label === "Save") setProfileState("Saved");
    setTimeout(() => setNotice(null), 1200);
  };
  const addSelectedSource = () => {
    const item = sourceCatalog.find(x => x.id === selectedSourceType);
    if (!item) return;
    const isVideo = item.group === "Video";
    const isAudioCapable = ["video_capture_device", "media_stream", "browser_source", "video_file"].includes(item.id);
    setProfileSources(current => [...current, {
      name: item.label,
      type: item.label,
      enabled: true,
      layer: current.length,
      summary: item.inventory ? "Select from " + item.inventory : "Configure source settings",
      transform: isVideo ? "x 0 · y 0 · 3840×2160 · crop 0/0/0/0" : undefined,
      audio: item.group === "Audio" || isAudioCapable ? "Audio enabled · 0 dB · Track 1" : undefined,
      verify: isVideo ? "Video signal optional · 2s sample" : "Audio signal optional · threshold -50 dB"
    }]);
    setProfileState("Modified");
    setNotice(item.label + " added to draft profile");
    setPickerOpen(false);
    setTimeout(() => setNotice(null), 1400);
  };
  const removeSource = (index: number) => {
    setProfileSources(current => current.filter((_, i) => i !== index).map((s, i) => ({
      ...s,
      layer: i
    })));
    setProfileState("Modified");
  };
  const videoCount = profileSources.filter(s => !["Audio Input Device", "Application Audio", "Audio Output Capture", "Existing OBS Audio Source"].includes(s.type)).length;
  const audioOnlyCount = profileSources.length - videoCount;
  return <main className="min-h-screen bg-[#f5f6f8] text-zinc-950">
    <div className="mx-auto w-full max-w-md px-4 pb-10 pt-4">
      <header className="mb-4 flex items-center justify-between">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-zinc-500">StreamOps</p>
          <h1 className="text-2xl font-semibold tracking-tight">OBS Management</h1>
        </div>
        <Pill tone="ok">Node online</Pill>
      </header>

      {notice && <div className="mb-3 rounded-2xl border border-blue-100 bg-blue-50 px-3 py-2 text-xs font-medium text-blue-700">{notice}</div>}

      <div className="space-y-3">
        <Card title="OBS Runtime" subtitle="Lifecycle, WebSocket and output state" status={<Pill tone="ok">READY</Pill>} open={open.runtime} onToggle={() => toggle("runtime")} summary={<div className="grid grid-cols-3 gap-2">
            <div><p className="text-[11px] text-zinc-500">Uptime</p><p className="mt-0.5 text-sm font-semibold">01:24:10</p></div>
            <div><p className="text-[11px] text-zinc-500">Streaming</p><p className="mt-0.5 text-sm font-semibold">Off</p></div>
            <div><p className="text-[11px] text-zinc-500">Recording</p><p className="mt-0.5 text-sm font-semibold">Off</p></div>
          </div>}>
          <div className="mb-3 rounded-2xl bg-zinc-50 px-3">
            {runtimeRows.map(([l, v]) => <StatRow key={l} label={l} value={v} />)}
          </div>
          <div className="grid grid-cols-3 gap-2">
            <button onClick={() => fakeAction("Start OBS")} className="rounded-2xl bg-zinc-950 px-3 py-3 text-xs font-semibold text-white">Start OBS</button>
            <button onClick={() => fakeAction("Stop OBS")} className="rounded-2xl bg-zinc-100 px-3 py-3 text-xs font-semibold">Stop OBS</button>
            <button onClick={() => fakeAction("Restart OBS")} className="rounded-2xl bg-zinc-100 px-3 py-3 text-xs font-semibold">Restart</button>
          </div>
        </Card>

        <Card title="Scene Profile" subtitle="Desired-state scene configuration" status={<Pill tone="blue">{profileState}</Pill>} open={open.profile} onToggle={() => toggle("profile")} summary={<div className="grid grid-cols-2 gap-x-4 gap-y-2">
            <div><p className="text-[11px] text-zinc-500">Profile</p><p className="truncate text-sm font-semibold">{selectedProfile}</p></div>
            <div><p className="text-[11px] text-zinc-500">Canvas</p><p className="text-sm font-semibold">3840×2160 @ 60</p></div>
            <div><p className="text-[11px] text-zinc-500">Sources</p><p className="text-sm font-semibold">{profileSources.length} configured</p></div>
            <div><p className="text-[11px] text-zinc-500">State</p><p className="text-sm font-semibold">{profileState}</p></div>
          </div>}>
          <label className="mb-3 block text-xs text-zinc-500">Profile
            <select value={selectedProfile} onChange={e => setSelectedProfile(e.target.value)} className="mt-1 w-full rounded-xl border border-zinc-200 bg-white px-3 py-2.5 text-sm text-zinc-900">
              <option>livestream-d4</option><option>gaming-poc</option><option>PR19 Motion + tone</option>
            </select>
          </label>
          <div className="mb-3 grid grid-cols-3 gap-2">
            {["Width 3840", "Height 2160", "FPS 60"].map(x => <div key={x} className="rounded-xl bg-zinc-50 px-2 py-2 text-center text-xs font-medium">{x}</div>)}
          </div>
          <div className="mb-3 grid grid-cols-3 gap-2">
            {["New", "Duplicate", "Delete", "Template", "Save", "Save As"].map(x => <button key={x} onClick={() => fakeAction(x)} className="rounded-xl border border-zinc-200 px-2 py-2 text-xs font-medium">{x}</button>)}
          </div>
          <div className="grid grid-cols-2 gap-2">
            {["Apply saved", "Verify", "Activate", "Review"].map(x => <button key={x} onClick={() => fakeAction(x)} className="rounded-2xl bg-zinc-950 px-3 py-3 text-sm font-semibold text-white">{x}</button>)}
          </div>
        </Card>

        <Card title="Sources" subtitle="Video, audio, layout and routing" status={<Pill tone="ok">Inventory ready</Pill>} open={open.sources} onToggle={() => toggle("sources")} summary={<div className="grid grid-cols-3 gap-2">
            <div><p className="text-[11px] text-zinc-500">Configured</p><p className="text-sm font-semibold">{profileSources.length}</p></div>
            <div><p className="text-[11px] text-zinc-500">Enabled</p><p className="text-sm font-semibold">{profileSources.filter(s => s.enabled).length}</p></div>
            <div><p className="text-[11px] text-zinc-500">Catalog</p><p className="text-sm font-semibold">13 types</p></div>
          </div>}>

          <div className="mb-3 flex gap-2">
            <button onClick={() => setPickerOpen(v => !v)} className="flex-1 rounded-xl bg-zinc-950 px-3 py-2.5 text-xs font-semibold text-white">
              {pickerOpen ? "Close source picker" : "Add source"}
            </button>
            <button onClick={() => fakeAction("Refresh inventory")} className="flex-1 rounded-xl border border-zinc-200 px-3 py-2.5 text-xs font-semibold">Refresh inventory</button>
          </div>

          {pickerOpen && <div className="mb-4 rounded-2xl border border-zinc-200 bg-zinc-50 p-3">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <p className="text-sm font-semibold">Add source</p>
                <p className="text-xs text-zinc-500">Choose from the complete OBS source catalog</p>
              </div>
              <Pill tone="neutral">13 types</Pill>
            </div>

            {(["Video", "Audio"] as const).map(group => <div key={group} className="mb-3 last:mb-0">
              <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-zinc-500">{group}</p>
              <div className="space-y-1.5">
                {sourceCatalog.filter(x => x.group === group).map(item => {
                  const selected = selectedSourceType === item.id;
                  return <button key={item.id} onClick={() => setSelectedSourceType(item.id)} className={"w-full rounded-xl border px-3 py-2.5 text-left transition " + (selected ? "border-zinc-950 bg-white ring-1 ring-zinc-950" : "border-zinc-200 bg-white")}>
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-xs font-semibold">{item.label}</p>
                        <p className="mt-0.5 text-[11px] leading-4 text-zinc-500">{item.detail}</p>
                        {item.inventory && <p className="mt-1 text-[10px] font-medium text-blue-600">Inventory: {item.inventory}</p>}
                      </div>
                      <span className={"mt-0.5 h-4 w-4 shrink-0 rounded-full border " + (selected ? "border-zinc-950 bg-zinc-950 shadow-[inset_0_0_0_3px_white]" : "border-zinc-300")} />
                    </div>
                  </button>;
                })}
              </div>
            </div>)}

            <button onClick={addSelectedSource} className="mt-1 w-full rounded-2xl bg-zinc-950 px-3 py-3 text-sm font-semibold text-white">
              Add selected source
            </button>
            <p className="mt-2 text-[10px] leading-4 text-zinc-500">Device, window, monitor and existing-OBS choices are populated from live inventory when available.</p>
          </div>}

          <div className="mb-2 flex items-center justify-between">
            <p className="text-xs font-semibold">Profile sources</p>
            <p className="text-[11px] text-zinc-500">{videoCount} video · {audioOnlyCount} audio-only</p>
          </div>
          <div className="space-y-2">
            {profileSources.map((s, i) => <details key={i + s.name} className="rounded-2xl border border-zinc-200 bg-zinc-50">
              <summary className="cursor-pointer list-none px-3 py-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold">{i + 1}. {s.name}</p>
                    <p className="truncate text-xs text-zinc-500">{s.type} · Layer {s.layer}</p>
                  </div>
                  <Pill tone={s.enabled ? "ok" : "neutral"}>{s.enabled ? "Enabled" : "Disabled"}</Pill>
                </div>
              </summary>
              <div className="border-t border-zinc-200 px-3 pb-3 pt-2 text-xs">
                <StatRow label="Settings" value={s.summary} />
                {s.transform && <StatRow label="Transform" value={s.transform} />}
                {s.audio && <StatRow label="Audio" value={s.audio} />}
                {s.verify && <StatRow label="Verification" value={s.verify} />}
                <div className="mt-2 grid grid-cols-2 gap-2">
                  <button onClick={() => fakeAction("Edit " + s.name)} className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-xs font-semibold">Edit source</button>
                  <button onClick={() => removeSource(i)} className="rounded-xl border border-red-200 bg-white px-3 py-2 text-xs font-semibold text-red-600">Remove source</button>
                </div>
              </div>
            </details>)}
          </div>
        </Card>

        <Card title="Canvas & Preview" subtitle="Desired layout and current OBS scene" status={<Pill tone="ok">Preview available</Pill>} open={open.canvas} onToggle={() => toggle("canvas")} summary={<div className="grid grid-cols-3 gap-2">
            <div><p className="text-[11px] text-zinc-500">Canvas</p><p className="text-sm font-semibold">4K</p></div>
            <div><p className="text-[11px] text-zinc-500">FPS</p><p className="text-sm font-semibold">60</p></div>
            <div><p className="text-[11px] text-zinc-500">Scene</p><p className="truncate text-sm font-semibold">StreamOps Scene</p></div>
          </div>}>
          <div className="mb-3 grid grid-cols-2 rounded-xl bg-zinc-100 p-1">
            {(["layout", "preview"] as const).map(t => <button key={t} onClick={() => setPreviewTab(t)} className={"rounded-lg py-2 text-xs font-semibold " + (previewTab === t ? "bg-white shadow-sm" : "text-zinc-500")}>{t === "layout" ? "Layout" : "OBS Preview"}</button>)}
          </div>
          <div className="aspect-video overflow-hidden rounded-2xl bg-zinc-950 p-3 text-white">
            {previewTab === "layout" ? <div className="relative h-full w-full border border-white/20">
              <div className="absolute inset-0 bg-white/5" />
              <div className="absolute bottom-3 right-3 h-[28%] w-[28%] border border-blue-300 bg-blue-400/20 p-1 text-[10px]">Camera</div>
              <div className="absolute left-2 top-2 text-[10px] text-white/60">Diablo IV · 3840×2160</div>
            </div> : <div className="flex h-full flex-col items-center justify-center text-center">
              <div className="mb-2 h-10 w-10 rounded-full bg-white/10" />
              <p className="text-sm font-semibold">Current OBS scene screenshot</p>
              <p className="mt-1 text-xs text-white/50">Loaded from /preview when connected</p>
            </div>}
          </div>
        </Card>

        <Card title="Verification" subtitle="Structural and runtime checks" status={<Pill tone="ok">PASS</Pill>} open={open.verification} onToggle={() => toggle("verification")} summary={<div className="grid grid-cols-3 gap-2">
            <div><p className="text-[11px] text-zinc-500">Ready</p><p className="text-sm font-semibold">For live</p></div>
            <div><p className="text-[11px] text-zinc-500">Checks</p><p className="text-sm font-semibold">18 pass</p></div>
            <div><p className="text-[11px] text-zinc-500">Failures</p><p className="text-sm font-semibold">0</p></div>
          </div>}>
          <div className="space-y-2">
            {[["PASS", "profile.schema", "Profile schema valid", "schema v1", "schema v1"], ["PASS", "scene.structure", "Managed scene matches profile", profileSources.length + " sources", profileSources.length + " sources"], ["PASS", "video.settings", "Canvas/output/FPS match", "3840×2160 @ 60", "3840×2160 @ 60"], ["PASS", "runtime.video", "Video signal detected", "non-black", "non-black"], ["PASS", "runtime.audio", "Required audio signal detected", "> -50 dB", "-18.4 dB"]].map(([st, id, msg, exp, act]) => <details key={id} className="rounded-xl bg-zinc-50 px-3 py-2.5">
              <summary className="cursor-pointer list-none text-xs"><span className="font-semibold text-emerald-700">{st}</span> · <span className="font-medium">{id}</span><div className="mt-1 text-zinc-500">{msg}</div></summary>
              <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
                <div><span className="text-zinc-400">Expected</span><div className="font-medium">{exp}</div></div>
                <div><span className="text-zinc-400">Actual</span><div className="font-medium">{act}</div></div>
              </div>
            </details>)}
          </div>
        </Card>

        <Card title="Review" subtitle="Recorded sample and media gates" status={<Pill tone="ok">Completed</Pill>} open={open.review} onToggle={() => toggle("review")} summary={<div className="grid grid-cols-3 gap-2">
            <div><p className="text-[11px] text-zinc-500">Duration</p><p className="text-sm font-semibold">30s</p></div>
            <div><p className="text-[11px] text-zinc-500">Media</p><p className="text-sm font-semibold">PASS</p></div>
            <div><p className="text-[11px] text-zinc-500">Artifacts</p><p className="text-sm font-semibold">4</p></div>
          </div>}>
          <label className="mb-3 block text-xs text-zinc-500">Review seconds
            <input defaultValue="30" type="number" min="1" max="300" className="mt-1 w-full rounded-xl border border-zinc-200 px-3 py-2.5 text-sm" />
          </label>
          <button onClick={() => fakeAction("Review")} className="mb-3 w-full rounded-2xl bg-zinc-950 px-3 py-3 text-sm font-semibold text-white">Run review</button>
          <div className="space-y-2">
            {["profile.json", "preview.png", "sample-30s.mkv", "media-analysis.json"].map(x => <div key={x} className="flex items-center justify-between rounded-xl bg-zinc-50 px-3 py-2.5 text-xs"><span className="font-medium">{x}</span><span className="text-zinc-400">artifact</span></div>)}
          </div>
        </Card>

        <Card title="Streaming" subtitle="Destinations, preflight and live output" status={<Pill tone="ok">READY</Pill>} open={open.stream} onToggle={() => toggle("stream")} summary={<div className="grid grid-cols-3 gap-2">
            <div><p className="text-[11px] text-zinc-500">Destination</p><p className="truncate text-sm font-semibold">LAN Test</p></div>
            <div><p className="text-[11px] text-zinc-500">Profile</p><p className="truncate text-sm font-semibold">{selectedProfile}</p></div>
            <div><p className="text-[11px] text-zinc-500">Status</p><p className="text-sm font-semibold">Ready</p></div>
          </div>}>
          <div className="rounded-2xl bg-zinc-50 px-3">
            <StatRow label="Destination" value="LAN Test · Custom RTMP" />
            <StatRow label="Scene Profile" value={selectedProfile} />
            <StatRow label="Preflight" value="PASS · ready to stream" />
            <StatRow label="Live state" value="IDLE" />
          </div>
          <a href="/obs/stream" className="mt-3 flex w-full items-center justify-between rounded-2xl bg-zinc-950 px-4 py-3 text-sm font-semibold text-white">
            <span>Open Streaming</span><span aria-hidden="true">→</span>
          </a>
        </Card>

        <Card title="Plugin Manager" subtitle="Managed OBS plugins and release health" status={<Pill tone="warn">1 attention</Pill>} open={open.plugins} onToggle={() => toggle("plugins")} summary={<div className="grid grid-cols-3 gap-2"><div><p className="text-[11px] text-zinc-500">Managed</p><p className="text-sm font-semibold">1</p></div><div><p className="text-[11px] text-zinc-500">Installed</p><p className="text-sm font-semibold">1</p></div><div><p className="text-[11px] text-zinc-500">Attention</p><p className="text-sm font-semibold">Update</p></div></div>}><div className="rounded-2xl bg-zinc-50 px-3"><StatRow label="Plugin" value="Multiple RTMP Outputs" /><StatRow label="Installed version" value="0.7.2 (demo)" /><StatRow label="Available" value="Check release manifest" /><StatRow label="State" value="Update available · demo" /></div><a href="/obs/plugins" className="mt-3 flex w-full items-center justify-between rounded-2xl bg-zinc-950 px-4 py-3 text-sm font-semibold text-white"><span>Open Plugin Manager</span><span aria-hidden="true">→</span></a></Card>

        <Card title="Activity Log" subtitle="Browser session events" status={<Pill tone="neutral">0 errors</Pill>} open={open.activity} onToggle={() => toggle("activity")} summary={<div className="grid grid-cols-2 gap-4">
            <div><p className="text-[11px] text-zinc-500">Last event</p><p className="truncate text-sm font-semibold">Activate completed</p></div>
            <div><p className="text-[11px] text-zinc-500">Warnings</p><p className="text-sm font-semibold">0</p></div>
          </div>}>
          <ol className="space-y-2 text-xs">
            {["23:20:14 · OBS status: READY (PID 4492)", "23:20:18 · Profile manager loaded", "23:21:02 · apply: no changes", "23:21:05 · activate: PASS", "23:21:06 · Preview refreshed"].map(x => <li key={x} className="rounded-xl bg-zinc-50 px-3 py-2.5">{x}</li>)}
          </ol>
        </Card>
      </div>
    </div>
  </main>;
};