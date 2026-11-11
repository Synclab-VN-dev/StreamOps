import type { CurrentItem, HudSnapshot } from './hud-model';
export const slots = [['helm','Helm'],['chest','Chest'],['gloves','Gloves'],['pants','Pants'],['boots','Boots'],['main_hand','Main Hand'],['off_hand','Off Hand'],['ring-1','Ring 1'],['ring-2','Ring 2'],['amulet','Amulet']];

export function currentItems(snapshot: HudSnapshot | null): CurrentItem[] {
  if (snapshot?.currentEquipment) return snapshot.currentEquipment.items;
  // Older persisted HUDs can still show observed names, without inventing missing details.
  return (snapshot?.equipment ?? []).flatMap(row => row.currentItem ? [{
    fingerprint:row.currentItem.itemId, slotFamily:row.slotId.replace('main-hand','main_hand').replace('off-hand','off_hand'), slotIndex:null,
    name:row.currentItem.displayName, itemType:'Observed item', itemPower:null, rarity:null,
    baseStats:[], affixes:[], effects:[], observedAt:row.currentItem.observedAt, confidence:'UNKNOWN'
  }] : []);
}
export function CurrentList({snapshot, offline, selected, onSelect, onRuntime}: {
  snapshot: HudSnapshot | null; offline: boolean; selected: string | null;
  onSelect(id: string): void; onRuntime(): void;
}) {
  const items = currentItems(snapshot);
  const state = snapshot?.health.captureRuntime?.state;
  const blocked = snapshot?.health.capture === 'ERROR' || state === 'BLOCKED' || state === 'ERROR' || state === 'CRASHED';
  const unavailable = snapshot?.currentEquipment?.sourceState === 'UNAVAILABLE' || snapshot?.currentEquipment?.sourceState === 'BUSY';
  const saved = offline || blocked || unavailable || state !== 'RUNNING';
  const label = offline ? 'Saved · Last-known' : blocked ? 'Capture unavailable' : unavailable ? 'Saved · Source unavailable' : items.length ? 'Observed equipment' : 'No Equipment yet';
  const unresolved = items.filter(item => item.slotFamily === 'ring' && item.slotIndex === null);
  const rows = slots.map(([id,label])=>({id,label,item:items.find(item => (item.slotFamily==='ring' ? `ring-${item.slotIndex}` : item.slotFamily)===id)}));
  return <section className="current-list" aria-label="Current Equipment">
    <div className="current-heading"><b>CURRENT EQUIPMENT</b><span>{saved ? 'LAST KNOWN' : 'CAPTURE RUNNING'}</span></div>
    <div className={`current-notice ${blocked || unavailable ? 'warning' : ''}`} role="status"><b>{label}</b>
      <p>{items.length ? `${items.length} item${items.length===1?'':'s'} observed. No Target required.` : 'Open Diablo IV → Inventory → highlight each equipped tooltip.'}</p>
      {blocked && <button onClick={onRuntime}>Open Runtime Manager →</button>}
      {items.length > 0 && <p>Character ownership is not verified. Saved items may be from an earlier session.</p>}
    </div>
    <div className="observed-count">{items.length} items observed</div>
    <div className="current-slots">{rows.map(({id,label,item}) => <button key={id} className={`current-row ${selected===(item?.fingerprint??id)?'selected':''}`} onClick={()=>onSelect(item?.fingerprint??id)}>
      <span className={item?'observed':'unknown'}>{item?'✓':'◌'}</span><span><b>{label}</b><small>{item?.name??'Not observed'}</small></span><span>›</span>
    </button>)}{unresolved.map(item=><button key={item.fingerprint} className="current-row" onClick={()=>onSelect(item.fingerprint)}><span>✓</span><span><b>Ring · position unknown</b><small>{item.name}</small></span><span>›</span></button>)}</div>
    <p className="current-help">Not observed does not mean unequipped. Only explicit evidence can confirm an empty slot.</p>
  </section>;
}
export function CurrentDetail({item, slot, offline, onClose}: {item?:CurrentItem; slot:string; offline:boolean; onClose():void}) {
 return <aside className="panel current-detail" aria-label="Current equipment detail">
  <div className="panel-title"><b>CURRENT EQUIPMENT</b><button aria-label="Close current equipment detail" onClick={onClose}>×</button></div>
  <h2>{item?.name??slots.find(([id])=>id===slot)?.[1]??'Unknown slot'}</h2>
  {item ? <><div className="current-notice"><b>{offline?'LAST KNOWN':'OBSERVED'} · {item.confidence} CONFIDENCE</b><p>{item.itemType}</p>{item.itemPower!==null&&<strong>Item Power {item.itemPower}</strong>}</div>
    {([['Base stats',item.baseStats],['Affixes',item.affixes],['Effects',item.effects]] as const).map(([title,lines])=><section className="item-properties" key={title}><h3>{title}</h3>{lines.length?lines.map((line,i)=><p key={i}>{line}</p>):<p>Not observed</p>}</section>)}
    <p className="current-help">Observed at · {item.observedAt}</p><p className="current-help">Character ownership unverified. This observation is not proof that the character is currently active.</p></>
    : <div className="current-notice"><b>UNKNOWN · Not observed</b><p>No trusted observation identifies this slot. Highlight its equipped tooltip in Diablo IV.</p></div>}
 </aside>;
}
