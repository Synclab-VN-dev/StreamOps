// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import App from './App';
import empty from '../../d4planner-be/contracts/release1/v1/fixtures/hud.no-data.synthetic.json';
import type { HudDataEvent, IHudDataSource } from './hud-data-source';
import type { HudSnapshot } from './hud-model';
const native = vi.hoisted(()=>({invoke:vi.fn().mockResolvedValue(undefined)}));
vi.mock('@tauri-apps/api/core', () => native);
afterEach(cleanup);
it('shows an observed item without Target, retains it offline, and opens its actual details', async () => {
  let notify: (e: HudDataEvent) => void = () => {};
  const snapshot = {...empty, currentEquipment: {sourceState:'READY', identity:'UNVERIFIED', revision:1, items:[{
    fingerprint:'fixture-chest', slotFamily:'chest', slotIndex:null, name:'Synthetic Chest', itemType:'Unique Chest Armor', itemPower:900,
    rarity:'Unique', baseStats:['2805 Armor'], affixes:['+101 Intelligence'], effects:['Example effect'], observedAt:'2026-11-11T00:00:00Z', confidence:'HIGH'
  }]}} as unknown as HudSnapshot;
  const source = {connect: async (listener: typeof notify) => {notify=listener; listener({type:'SNAPSHOT',snapshot}); return () => {};}, refreshTargets:async()=>{}, selectTarget:vi.fn()} as IHudDataSource;
  render(<App dataSource={source}/>);
  fireEvent.click(await screen.findByRole('button',{name:/Chest Synthetic Chest/}));
  expect(screen.getByText('Item Power 900')).toBeTruthy();
  const extents = native.invoke.mock.calls.filter(([command])=>command==='set_overlay_extent').map(([,args])=>args);
  expect(extents.at(-1).width).toBeGreaterThanOrEqual(627);
  expect(extents.every(args=>args.height<=640)).toBe(true);
  expect(screen.getByText('+101 Intelligence')).toBeTruthy();
  expect(screen.getByText('Identity unverified')).toBeTruthy();
  expect(screen.getAllByText('Not observed', {exact:true})[0]).toBeTruthy();
  act(()=>notify({type:'CONNECTION',state:'DISCONNECTED'}));
  expect(screen.getByText(/Saved · Last-known/)).toBeTruthy();
  expect(screen.getByText('Item Power 900')).toBeTruthy();
  fireEvent.click(screen.getByRole('tab',{name:'Compare'}));
  expect(screen.getByText('Choose a Target Build')).toBeTruthy();
});
it('updates Current on a newer DB read and retains observations while capture is blocked', async () => {
  let notify: (e: HudDataEvent) => void = () => {};
  const initial = {...empty, currentEquipment:{sourceState:'READY',identity:'UNVERIFIED',revision:null,items:[]}} as unknown as HudSnapshot;
  const source = {connect:async(listener: typeof notify)=>{notify=listener;listener({type:'CONNECTION',state:'CONNECTED'});listener({type:'SNAPSHOT',snapshot:initial});return ()=>{};},refreshTargets:async()=>{},selectTarget:vi.fn()} as IHudDataSource;
  render(<App dataSource={source}/>);
  expect(await screen.findByText('No Equipment yet')).toBeTruthy();
  const updated: HudSnapshot = {...initial,hudRevision:initial.hudRevision+1,health:{...initial.health,capture:'ERROR',captureRuntime:{state:'BLOCKED',detail:'Dependency unavailable'}},currentEquipment:{sourceState:'READY',identity:'UNVERIFIED',revision:1,items:[{fingerprint:'ring',slotFamily:'ring',slotIndex:null,name:'Unresolved ring',itemType:'Ring',itemPower:900,rarity:null,baseStats:[],affixes:[],effects:[],observedAt:'2026-11-11T00:00:00Z',confidence:'HIGH'}]}};
  act(()=>notify({type:'SNAPSHOT',snapshot:updated}));
  expect(screen.getByText('Capture unavailable')).toBeTruthy();
  expect(screen.getByRole('button',{name:'Open Runtime Manager →'})).toBeTruthy();
  expect(screen.getByText('Ring · position unknown')).toBeTruthy();
  expect(screen.getByText('Unresolved ring')).toBeTruthy();
  // A lower revision cannot erase newer observations.
  act(()=>notify({type:'SNAPSHOT',snapshot:initial}));
  expect(screen.getByText('Unresolved ring')).toBeTruthy();
});
it('uses BE topology, reidentifies layout on a new snapshot and retains legacy fallback', async () => {
  const {CurrentList, equipmentSlots} = await import('./CurrentEquipment');
  const snapshot = {...empty,currentEquipment:{sourceState:'READY',identity:'UNVERIFIED',revision:1,items:[],
    layout:{status:'VERIFIED',slots:['helm','ranged','main_hand','off_hand']}}} as unknown as HudSnapshot;
  const props={offline:false,selected:null,onSelect:vi.fn(),onRuntime:vi.fn()};
  const {rerender}=render(<CurrentList snapshot={snapshot} {...props}/>);
  expect(screen.getByRole('button',{name:/Ranged/})).toBeTruthy();
  expect(screen.getByText('Layout · Verified slot layout')).toBeTruthy();
  const changed={...snapshot,currentEquipment:{...snapshot.currentEquipment!,layout:{status:'VERIFIED' as const,slots:['main_hand','off_hand']}}};
  rerender(<CurrentList snapshot={changed} {...props}/>);
  expect(screen.queryByRole('button',{name:/Ranged/})).toBeNull();
  expect(screen.getByRole('button',{name:/Main Hand/})).toBeTruthy();
  const unknown={...snapshot,currentEquipment:{...snapshot.currentEquipment!,layout:{status:'UNKNOWN' as const,slots:['helm']}}};
  rerender(<CurrentList snapshot={unknown} {...props}/>);
  expect(screen.getByText('Layout · Not yet identified')).toBeTruthy();
  expect(screen.queryByRole('button',{name:/Main Hand/})).toBeNull();
  expect(equipmentSlots(null)).toHaveLength(10);
});
