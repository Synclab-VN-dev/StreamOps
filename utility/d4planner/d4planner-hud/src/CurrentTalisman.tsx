import { useState } from "react";
import type { HudSnapshot, TalismanItem } from "./hud-model";

export function talismanStatus(snapshot: HudSnapshot | null, offline: boolean) {
  const view = snapshot?.currentTalisman;
  const capture = snapshot?.health.captureRuntime?.state;
  const count = view?.items.length ?? 0;
  const blocked = ["BLOCKED", "CRASHED", "ERROR"].includes(capture ?? "") ||
    snapshot?.health.capture === "ERROR" || view?.sourceState === "UNAVAILABLE";
  const saved = offline || capture !== "RUNNING" || !view?.liveSession;
  if (blocked) return {badge:"CAPTURE UNAVAILABLE", description:"Capture unavailable. Showing saved observations.", saved:true};
  if (saved && count) return {badge:"SAVED · OFFLINE", description:"Last-known observations. The game is not confirmed active.", saved:true};
  if (!count && view?.comparisonObserved) return {badge:"POSITION UNKNOWN", description:"Comparison speech was observed. Equipped status is unverified.", saved};
  if (!count) return {badge:"NOT OBSERVED", description:"No equipped Talisman observed. Unobserved slots may contain items.", saved};
  return {badge:count + " CAPTURED", description:"Verified equipped observations. Additional slots may be unobserved.", saved};
}

export function CurrentTalisman({items, status, selected, onSelect}: {
  items: TalismanItem[]; status: ReturnType<typeof talismanStatus>; selected?: string; onSelect(id: string): void;
}) {
  const [open, setOpen] = useState(true);
  const charms = items.filter(i => i.kind === "charm").length;
  const seals = items.length - charms;
  return <section className="current-list talisman-list" aria-label="Current Talisman">
    <div className="current-heading"><b>CURRENT TALISMAN</b><span>{items.length && !status.saved ? "PARTIAL OBSERVATIONS" : status.badge}</span></div>
    <p className="current-notice" role="status">{status.description}</p>
    <button className="talisman-group" aria-expanded={open} onClick={()=>setOpen(!open)}>
      <b>Equipped</b><small>{items.length ? `${charms} Charm${charms===1?"":"s"} · ${seals} Seal${seals===1?"":"s"}` : "Not observed"}</small>
      <small>Only verified equipped Charms and Seals</small>
    </button>
    {open && <div className="current-slots">{items.length ? items.map(item=>
      <button className={`current-row ${selected===item.id?"selected":""}`} key={item.id} aria-pressed={selected===item.id} onClick={()=>onSelect(item.id)}>
        <span aria-hidden="true">{item.kind==="charm"?"◇":"⛨"}</span><span><b>{item.name}</b><small>{item.kind==="charm"?"Charm":"Seal"} · Equipped</small></span><span>›</span>
      </button>) : <p className="current-help">No verified equipped observations in this session.</p>}</div>}
  </section>;
}

export function TalismanDetail({item, saved, close}: {item:TalismanItem; saved:boolean; close():void}) {
  return <aside className="panel current-detail" aria-label="Current Talisman item details">
    <div className="panel-title"><b>CURRENT TALISMAN · {item.kind.toUpperCase()}</b><button aria-label="Close Talisman detail" onClick={close}>×</button></div>
    <h2>{item.name}</h2><div className="current-notice"><b>Equipped · {saved?"LAST KNOWN":"OBSERVED"}</b><p>Item Power {item.itemPower}</p></div>
    {([["Affixes",item.affixes],["Effect",item.effect?[item.effect]:[]],["Set bonus",item.setBonuses]] as const).map(([label,lines])=>
      <section key={label} className="item-properties"><h3>{label}</h3>{lines.length ? lines.map((line,i)=><p key={i}>{line}</p>) : <p>Not observed</p>}</section>)}
    <p className="current-help">Observed at · {item.observedAt}</p>
  </aside>;
}
