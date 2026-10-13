import { useState } from "react";
import { Zap, Shield, Gem, ChevronRight, ChevronDown, ChevronUp, X, Pin, CheckCircle2, AlertTriangle, XCircle, HelpCircle, SlidersHorizontal, Sparkles, Wrench } from "lucide-react";
type View = "equipment" | "charms" | null;
type Status = "pass" | "fail" | "warn" | "unknown";
const items: {
  equipment: [string, string, Status][];
  charms: [string, string, Status][];
} = {
  equipment: [["Gloves", "Wrong core effect", "fail"], ["Ring", "Crit Chance low", "warn"], ["Amulet", "Weak affixes", "warn"], ["Head", "Matched", "pass"]],
  charms: [["Charm slot 1", "Matched", "pass"], ["Charm slot 2", "Missing synergy", "warn"], ["Charm slot 3", "Matched", "pass"], ["Other effects", "Not verified", "unknown"]]
};
const affixes: {
  current: string;
  value: string;
  target: string;
  required: string;
  status: Status;
  reason: string;
}[] = [{
  current: "Attack Speed",
  value: "+9.4%",
  target: "Attack Speed",
  required: "≥8%",
  status: "pass",
  reason: "Correct type · Value met"
}, {
  current: "Crit Damage",
  value: "+42%",
  target: "Crit Chance",
  required: "≥8%",
  status: "fail",
  reason: "Wrong attribute type"
}, {
  current: "Core Skills",
  value: "+1",
  target: "Core Skills",
  required: "+2",
  status: "warn",
  reason: "Correct type · Low value"
}];
const statusIcon = (s: Status) => s === "pass" ? <CheckCircle2 size={16} className="shrink-0 text-[#34865a]" /> : s === "fail" ? <XCircle size={16} className="shrink-0 text-[#bb5b56]" /> : s === "warn" ? <AlertTriangle size={16} className="shrink-0 text-[#b77d36]" /> : <HelpCircle size={16} className="shrink-0 text-[#92969a]" />;
export const D4PlannerCompactBuildHUD = () => {
  const [expanded, setExpanded] = useState(true),
    [selected, setSelected] = useState<View>(null),
    [item, setItem] = useState<string | null>(null),
    [affixOpen, setAffixOpen] = useState(false),
    [effectOpen, setEffectOpen] = useState(false),
    [showAll, setShowAll] = useState(false),
    [pinned, setPinned] = useState(false);
  const resetCompare = () => {
    setItem(null);
    setAffixOpen(false);
    setEffectOpen(false);
    setShowAll(false);
  };
  const chooseSection = (s: View) => {
    setSelected(selected === s ? null : s);
    resetCompare();
  };
  const chooseItem = (name: string) => {
    setItem(name);
    setAffixOpen(false);
    setEffectOpen(false);
    setShowAll(false);
  };
  return <main className="min-h-[550px] w-full bg-transparent p-4 font-sans text-[#252a31]"><div className="flex w-max max-w-full items-start gap-3">
 <section className="w-[248px] shrink-0 overflow-hidden rounded-[20px] border border-white/50 bg-[#f3f3f4]/95 shadow-[0_14px_35px_rgba(0,0,0,.14)] backdrop-blur-xl">
 <button onClick={() => {
          setExpanded(!expanded);
          if (expanded) {
            setSelected(null);
            resetCompare();
          }
        }} aria-expanded={expanded} className="block w-full px-4 pb-3 pt-4 text-left hover:bg-black/[.025] focus:outline-none focus:ring-2 focus:ring-inset focus:ring-blue-400/40"><div className="flex items-center justify-between gap-2"><span className="flex items-center gap-1.5"><Zap size={17} className="text-[#2587bd]" /><strong className="text-[12px]">CHARGE BOLT</strong></span><span className="text-[10px] text-[#23794d]">● LIVE</span></div><div className="mt-3 flex items-center justify-between"><span className="text-[29px] font-semibold leading-none">78<span className="ml-1 text-[12px] font-normal text-[#747980]">/100</span></span><span className="text-[10px] text-[#a45c30]">⚠ 3 issues</span><ChevronDown size={15} className={"text-[#8a8e93] transition-transform " + (expanded ? "rotate-180" : "")} /></div>{!expanded && <div className="mt-3 border-t border-black/10 pt-2"><div className="text-[9px] tracking-wider text-[#8a8d92]">NEXT UPGRADE</div><div className="mt-1 text-[11px]"><span className="text-[#b55a56]">✕ Gloves</span> · Change effect</div></div>}</button>
 {expanded && <div className="border-t border-black/[.08] px-4 pb-4 pt-2">{[{
            id: "equipment" as const,
            name: "Equipment",
            Icon: Shield,
            score: "8/10",
            issue: "2 issues"
          }, {
            id: "charms" as const,
            name: "Charms",
            Icon: Gem,
            score: "6/8",
            issue: "2 issues"
          }].map(({
            id,
            name,
            Icon,
            score,
            issue
          }) => <button key={id} onClick={() => chooseSection(id)} aria-pressed={selected === id} className={"my-1 flex w-full items-center gap-2.5 rounded-xl px-1 py-3 text-left focus:outline-none focus:ring-2 focus:ring-blue-400/40 " + (selected === id ? "bg-[#dcebf3]" : "hover:bg-black/[.045]")}><Icon size={19} className="shrink-0 text-[#6e7378]" /><span className="min-w-0 flex-1"><span className="block text-[13px] font-semibold">{name}</span><span className="mt-0.5 block text-[11px] text-[#a45c30]">{issue}</span></span><span className="text-[12px] text-[#70757b]">{score}</span><ChevronRight size={15} className="text-[#a0a4a8]" /></button>)}<button onClick={() => setPinned(!pinned)} className="mt-3 flex items-center gap-1 text-[10px] text-[#8b8f94]"><Pin size={12} />{pinned ? "Pinned" : "Pin overlay"}</button></div>}</section>
 {expanded && selected && <aside className="w-[252px] shrink-0 rounded-[20px] border border-white/60 bg-[#f3f3f4]/95 p-4 shadow-[0_14px_35px_rgba(0,0,0,.14)] backdrop-blur-xl"><div className="mb-1 flex items-center justify-between"><div className="flex items-center gap-2">{selected === "equipment" ? <Shield size={19} className="text-[#6e7378]" /> : <Gem size={19} className="text-[#6e7378]" />}<h3 className="text-[14px] font-semibold">{selected === "equipment" ? "Equipment" : "Charms"}</h3></div><button onClick={() => {
            setSelected(null);
            resetCompare();
          }} aria-label="Close section" className="rounded-md p-1 text-[#7b8086] hover:bg-black/5"><X size={17} /></button></div><p className="mb-3 text-[10px] text-[#8b8f94]">Charge Bolt · Select an item</p>{items[selected].map(([name, detail, status]) => <button key={name} onClick={() => chooseItem(name)} className={"flex w-full items-start gap-2 rounded-lg border-b border-black/[.07] px-1 py-3 text-left hover:bg-black/5 " + (item === name ? "bg-[#dcebf3]" : "")}>{statusIcon(status)}<div className="flex-1"><div className="text-[12px] font-medium">{name}</div><div className="text-[10px] text-[#8b8f94]">{detail}</div></div><ChevronRight size={14} className="text-[#9b9fa4]" /></button>)}<p className="mt-3 text-[10px] text-[#8b8f94]">Example data · Unknown is not a failure</p></aside>}
 {expanded && selected && item && <aside className="w-[330px] shrink-0 rounded-[20px] border border-white/60 bg-[#f3f3f4]/95 p-4 shadow-[0_14px_35px_rgba(0,0,0,.14)] backdrop-blur-xl" aria-label="Item comparison"><div className="flex items-start justify-between"><div><h3 className="text-[15px] font-semibold">{item} <span className="text-[#b45f5a]">✕</span></h3><p className="mt-1 text-[10px] text-[#858a90]">Current vs Charge Bolt target · Demo</p></div><button onClick={() => setItem(null)} aria-label="Close item comparison" className="rounded p-1 text-[#8b8f94] hover:bg-black/5"><X size={17} /></button></div>
 <div className="mt-4 space-y-2">
 <section className="overflow-hidden rounded-xl border border-black/[.07] bg-white/75"><button aria-expanded={affixOpen} onClick={() => setAffixOpen(!affixOpen)} className="w-full p-3 text-left"><div className="flex items-center gap-2"><SlidersHorizontal size={17} className="text-[#777e85]" /><b className="flex-1 text-[13px]">Affixes</b><span className="text-[10px] text-[#ad7133]">2 issues</span>{affixOpen ? <ChevronUp size={15} /> : <ChevronDown size={15} />}</div><p className="mt-2 text-[10px] text-[#747980]">✓ 2 matched · ✕ 1 wrong type</p><p className="mt-1 text-[10px] text-[#b77d36]">⚠ 1 low value</p></button>
 {affixOpen && <div className="border-t border-black/[.07] p-2.5"><div className="mb-3 flex items-center justify-between"><span className="text-[10px] font-semibold text-[#6e747a]">CURRENT ↔ TARGET</span><div className="flex rounded-lg bg-[#e9eaec] p-0.5" role="group" aria-label="Affix filter"><button onClick={() => setShowAll(false)} aria-pressed={!showAll} className={"rounded-md px-2 py-1 text-[10px] " + (!showAll ? "bg-white font-semibold shadow-sm" : "text-[#777e85]")}>Issues only</button><button onClick={() => setShowAll(true)} aria-pressed={showAll} className={"rounded-md px-2 py-1 text-[10px] " + (showAll ? "bg-white font-semibold shadow-sm" : "text-[#777e85]")}>All</button></div></div>
 <div className="max-h-[310px] space-y-2 overflow-y-auto">{affixes.filter(a => showAll || a.status !== "pass").map(a => <div key={a.current} className="rounded-lg border border-black/[.06] bg-[#f7f7f8] p-2.5"><div className="mb-2 flex items-center gap-1.5">{statusIcon(a.status)}<span className={"text-[10px] font-semibold " + (a.status === "fail" ? "text-[#b45f5a]" : a.status === "warn" ? "text-[#a36e31]" : "text-[#34865a]")}>{a.reason}</span></div><div className="grid grid-cols-2 gap-2"><div className="min-w-0"><div className="mb-1 text-[9px] uppercase tracking-wide text-[#92969b]">Current</div><p className="break-words text-[11px] font-medium">{a.current}</p><p className={"mt-1 text-[15px] font-semibold " + (a.status === "fail" ? "text-[#b45f5a]" : "")}>{a.value}</p></div><div className="min-w-0 border-l border-black/10 pl-2"><div className="mb-1 text-[9px] uppercase tracking-wide text-[#92969b]">Target</div><p className="break-words text-[11px] font-medium">{a.target}</p><p className="mt-1 text-[15px] font-semibold">{a.required}</p></div></div>{a.status === "fail" && <p className="mt-2 text-[9px] text-[#b45f5a]">Different types — values cannot be compared.</p>}</div>)}</div></div>}</section>
 <section className="rounded-xl border border-black/[.07] bg-white/75"><button aria-expanded={effectOpen} onClick={() => setEffectOpen(!effectOpen)} className="w-full p-3 text-left"><div className="flex items-center gap-2"><Sparkles size={17} className="text-[#777e85]" /><b className="flex-1 text-[13px]">Effects</b><span className="text-[10px] text-[#b45f5a]">1 issue</span>{effectOpen ? <ChevronUp size={15} /> : <ChevronDown size={15} />}</div><p className="mt-2 text-[10px] text-[#b45f5a]">✕ Core effect mismatch</p><p className="mt-1 text-[10px] text-[#858a90]">Expected: Charge Bolt core effect</p></button>{effectOpen && <div className="border-t border-black/[.07] p-3"><p className="text-[9px] text-[#8b8f94]">CURRENT EFFECT</p><p className="mt-1 text-[11px]">Overwhelming Currents</p><p className="mt-3 text-[9px] text-[#8b8f94]">TARGET EFFECT</p><p className="mt-1 text-[11px]">Required Charge Bolt core effect</p><p className="mt-2 text-[10px] text-[#b45f5a]">Wrong effect type; roll comparison unavailable</p></div>}</section>
 </div><div className="mt-3 rounded-xl bg-white/65 p-3"><div className="flex items-center gap-1.5 text-[9px] text-[#858a90]"><Wrench size={13} /> RECOMMENDATION</div><p className="mt-1 text-[12px] font-semibold">KEEP ITEM · CHANGE EFFECT</p></div></aside>}
 </div></main>;
};