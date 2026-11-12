// @vitest-environment jsdom
import {afterEach,expect,it,vi} from 'vitest';
import {act,cleanup,fireEvent,render,screen,within} from '@testing-library/react';
import App from './App';
import empty from '../../d4planner-be/contracts/release1/v1/fixtures/hud.no-data.synthetic.json';
import type {CurrentItem,HudSnapshot} from './hud-model';
import type {HudDataEvent,IHudDataSource} from './hud-data-source';
vi.mock('@tauri-apps/api/core',()=>({invoke:vi.fn().mockResolvedValue(undefined)}));
afterEach(cleanup);
const chest:CurrentItem={fingerprint:'old',slotFamily:'chest',slotIndex:null,name:'Old Chest',itemType:'Chest Armor',itemPower:900,rarity:null,baseStats:[],affixes:['+100 Intelligence'],effects:[],observedAt:'2026-11-11T00:00:00Z',confidence:'HIGH'};
function snapshot(items:CurrentItem[]=[],sourceState:'READY'|'UNAVAILABLE'|'BUSY'='READY'):HudSnapshot {
 return {...empty,health:{...empty.health,captureRuntime:{state:'WAITING_FOR_GAME',detail:'Waiting for game'}},currentEquipment:{sourceState,identity:'UNVERIFIED',revision:1,items}} as HudSnapshot;
}
function mount(initial:HudSnapshot){
 let notify:(event:HudDataEvent)=>void=()=>{};let revision=initial.hudRevision;
 const source={connect:async(listener:typeof notify)=>{notify=listener;listener({type:'CONNECTION',state:'CONNECTED'});listener({type:'SNAPSHOT',snapshot:initial});return ()=>{};},refreshTargets:async()=>{},selectTarget:vi.fn()} as IHudDataSource;
 render(<App dataSource={source}/>);
 return (next:HudSnapshot)=>act(()=>notify({type:'SNAPSHOT',snapshot:{...next,hudRevision:++revision}}));
}
it('F1 missing source on first run has no saved-data claim and recovers when data arrives',async()=>{
 const update=mount(snapshot([],'UNAVAILABLE'));
 expect(await screen.findByText('No Equipment yet')).toBeTruthy();
 expect(screen.queryByText('LAST KNOWN')).toBeNull();
 expect(screen.getByText('Equipment source unavailable')).toBeTruthy();
 update(snapshot([chest]));
 expect(screen.getByRole('button',{name:/Chest Old Chest/})).toBeTruthy();
 expect(screen.queryByText('Equipment source unavailable')).toBeNull();
});
it.each(['BUSY','UNAVAILABLE'] as const)('F1 %s retains saved items and honest source status',async(state)=>{
 const update=mount(snapshot([chest]));await screen.findByText('Old Chest');
 update(snapshot([chest],state));
 expect(screen.getByText('LAST KNOWN')).toBeTruthy();
 expect(screen.getByText(state==='BUSY'?'Equipment source busy':'Equipment source unavailable')).toBeTruthy();
 expect(screen.getByText('Old Chest')).toBeTruthy();
 update(snapshot([chest]));expect(screen.queryByText(/Equipment source (busy|unavailable)/)).toBeNull();
});
it('F2 detail follows slot replacement, changed affixes, absence and recovery',async()=>{
 const update=mount(snapshot([chest]));
 fireEvent.click(await screen.findByRole('button',{name:/Chest Old Chest/}));
 const panel=()=>within(screen.getByRole('complementary',{name:'Current equipment detail'}));
 const replacement={...chest,fingerprint:'new',name:'New Chest'};
 update(snapshot([replacement]));expect(panel().getByRole('heading',{name:'New Chest'})).toBeTruthy();
 update(snapshot([{...replacement,fingerprint:'new-affixes',affixes:['+200 Intelligence']}]));expect(panel().getByText('+200 Intelligence')).toBeTruthy();
 update(snapshot([]));expect(panel().getByRole('heading',{name:'Chest'})).toBeTruthy();expect(panel().getByText('UNKNOWN · Not observed')).toBeTruthy();
 update(snapshot([chest]));expect(panel().getByRole('heading',{name:'Old Chest'})).toBeTruthy();
});
it('F2 initially unobserved slot detail populates when equipment arrives',async()=>{
 const update=mount(snapshot());fireEvent.click(await screen.findByRole('button',{name:/Chest Not observed/}));
 update(snapshot([chest]));expect(within(screen.getByRole('complementary')).getByRole('heading',{name:'Old Chest'})).toBeTruthy();
});
it('F2 indexed rings follow their own position without selecting the other ring',async()=>{
 const ring=(index:number):CurrentItem=>({...chest,slotFamily:'ring',slotIndex:index,fingerprint:`r${index}`,name:`Ring ${index} item`});
 const update=mount(snapshot([ring(1),ring(2)]));fireEvent.click(await screen.findByRole('button',{name:/Ring 1 Ring 1 item/}));
 update(snapshot([{...ring(1),fingerprint:'r1-new',name:'Replacement Ring'},ring(2)]));
 expect(within(screen.getByRole('complementary')).getByRole('heading',{name:'Replacement Ring'})).toBeTruthy();
});
it('F2 unresolved ring never adopts another ring when its observation disappears',async()=>{
 const ring=(id:string):CurrentItem=>({...chest,slotFamily:'ring',slotIndex:null,fingerprint:id,name:`Ring ${id}`});
 const update=mount(snapshot([ring('a'),ring('b')]));fireEvent.click(await screen.findByRole('button',{name:/Ring · position unknown Ring a/}));
 update(snapshot([ring('b'),ring('c')]));
 const panel=within(screen.getByRole('complementary'));
 expect(panel.getByRole('heading',{name:'Ring · position unknown'})).toBeTruthy();
 expect(panel.queryByText('Ring b')).toBeNull();expect(panel.getByText('UNKNOWN · Not observed')).toBeTruthy();
 update(snapshot([ring('a'),ring('b')]));expect(panel.getByRole('heading',{name:'Ring a'})).toBeTruthy();
});
