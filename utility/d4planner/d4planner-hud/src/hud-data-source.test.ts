// @vitest-environment jsdom
import { expect, it, vi } from 'vitest';
import { TauriHudDataSource, type WebSocketLike, type HudDataEvent } from './hud-data-source';
import type { invoke } from '@tauri-apps/api/core';
import fixture from '../../d4planner-be/contracts/release1/v1/fixtures/hud.partial.synthetic.json';
class Socket implements WebSocketLike {
  readyState=1; onopen:(()=>void)|null=null; onclose:(()=>void)|null=null;
  onmessage:((event:{data:string})=>void)|null=null;
  sent:Record<string,any>[]=[];
  send(data:string){this.sent.push(JSON.parse(data));}
  close(){this.onclose?.();}
  receive(data:unknown){this.onmessage?.({data:JSON.stringify(data)});}
}
function model(revision=12, epoch='epoch') {
  return {schemaVersion:'d4planner-hud-db/v1',dbId:'db',epoch,hudRevision:revision,hud:{...structuredClone(fixture),hudRevision:revision}};
}
it('renders persisted DB without bootstrap, BE or Node and never starts Backend',async()=>{
  const native=vi.fn(async(name:string)=>{if(name==='read_hud_database')return model();throw new Error('OFFLINE');});
  const events:HudDataEvent[]=[];
  const source=new TauriHudDataSource(native as typeof invoke,()=>{throw new Error('no socket');},[]);
  const stop=await source.connect(event=>events.push(event));
  const snapshot=events.find(event=>event.type==='SNAPSHOT');
  expect(snapshot?.type==='SNAPSHOT' && snapshot.snapshot.score.value).toBe(fixture.score.value);
  expect(snapshot?.type==='SNAPSHOT' && snapshot.snapshot.health.scoreFreshness).toBe('STALE');
  expect(native.mock.calls.map(call=>call[0])).not.toContain('start_backend');
  expect(native.mock.calls.map(call=>call[0])).not.toContain('restart_backend');stop();
});
it('rereads latest SQLite on notification, reconnect and explicit refresh without rollback',async()=>{
  let value=model(); const events:HudDataEvent[]=[]; const socket=new Socket();
  const native=vi.fn(async(name:string)=>name==='read_hud_database'?value:name==='get_backend_status'?{state:'READY',ready:{childInstanceId:fixture.backend.runtimeInstanceId,generation:fixture.backend.generation}}:{endpoint:'ws://127.0.0.1:30001',credential:'x'.repeat(32),origin:'tauri://localhost'});
  const source=new TauriHudDataSource(native as typeof invoke,()=>socket,[]);
  const stop=await source.connect(event=>events.push(event)); await vi.waitFor(()=>expect(socket.onopen).not.toBeNull());
  socket.onopen?.(); socket.receive({protocolVersion:'d4planner-notify/v1',type:'hello.accepted',correlationId:socket.sent[0].messageId});
  await source.refresh();
  value=model(20);
  for(const revision of [15,15,10])socket.receive({protocolVersion:'d4planner-notify/v1',type:'hud.committed',messageId:'n'+revision,dbId:'db',epoch:'epoch',hudRevision:revision});
  await source.refresh();
  expect(events.filter(e=>e.type==='SNAPSHOT').at(-1)).toMatchObject({snapshot:{hudRevision:20}});
  value=model(19);await source.refresh();
  expect(events.filter(e=>e.type==='SNAPSHOT').at(-1)).toMatchObject({snapshot:{hudRevision:20}});
  value=model(2,'restored'); await source.refresh();
  expect(events.filter(e=>e.type==='SNAPSHOT').at(-1)).toMatchObject({snapshot:{hudRevision:2}});
  expect(socket.sent.map(x=>x.type)).toEqual(['hello']);stop();
});
it('routes Target commands through native managed IPC and rereads on timeout',async()=>{
  const native=vi.fn(async(name:string,args?:any)=>{
    if(name==='read_hud_database')return model();
    if(name==='backend_command'&&args.method==='target.list')return {listRevision:3,targets:[{targetId:'target-a',contentSha256:'a'.repeat(64)}]};
    throw new Error('CONTROL_TIMEOUT');
  });
  const source=new TauriHudDataSource(native as typeof invoke,()=>new Socket(),[]);
  const stop=await source.connect(()=>{});await source.refreshTargets();
  await expect(source.selectTarget({targetId:'target-a',expectedSha256:'a'.repeat(64)})).rejects.toThrow('CONTROL_TIMEOUT');
  expect(native).toHaveBeenCalledWith('backend_command',{method:'target.select',params:{targetId:'target-a',expectedSha256:'a'.repeat(64),expectedListRevision:3}});
  expect(native.mock.calls.filter(x=>x[0]==='read_hud_database').length).toBeGreaterThan(1);stop();
});
it('missing or invalid DB does not fabricate HUD data',async()=>{
  let value:any=null;const events:HudDataEvent[]=[];
  const native=vi.fn(async(name:string)=>{if(name==='read_hud_database')return value;throw new Error('OFFLINE');});
  const source=new TauriHudDataSource(native as typeof invoke,()=>new Socket(),[]);
  const stop=await source.connect(e=>events.push(e));
  expect(events.some(e=>e.type==='SNAPSHOT')).toBe(false);
  value={...model(),hud:{score:100}};await source.refresh();
  expect(events.some(e=>e.type==='SNAPSHOT')).toBe(false);stop();
});
