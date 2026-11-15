// @vitest-environment jsdom
import {expect,it,vi} from 'vitest';
import {WebHudDataSource} from './web-data-source';
import type {HudDataEvent,WebSocketLike} from '../hud-data-source';
import fixture from '../../../d4planner-be/contracts/release1/v1/fixtures/hud.partial.synthetic.json';
class Socket implements WebSocketLike {
  readyState=1;onopen:(()=>void)|null=null;onclose:(()=>void)|null=null;
  onmessage:((event:{data:string})=>void)|null=null;
  send=vi.fn();close(){this.onclose?.();}
  receive(value:unknown){this.onmessage?.({data:JSON.stringify(value)});}
}
function envelope(sequence:number,revision=12,epoch='epoch',connected=true){
  return {schemaVersion:'d4planner-hud-web/v1',type:'state',sequence,connected,
    snapshot:{schemaVersion:'d4planner-hud-db/v1',dbId:'db',epoch,hudRevision:revision,hud:{...structuredClone(fixture),hudRevision:revision}},
    runtime:{backend:{state:'READY',ready:{childInstanceId:fixture.backend.runtimeInstanceId,generation:fixture.backend.generation}},runtime:null}};
}
it('uses full WebSocket projections, deduplicates, detects rollback and never fetches a snapshot',async()=>{
  const socket=new Socket(),request=vi.fn(),events:HudDataEvent[]=[];
  const source=new WebHudDataSource('ws://127.0.0.1:6090/api/v1/hud/stream',request,()=>socket);
  const stop=await source.connect(e=>events.push(e));
  socket.receive(envelope(1));socket.receive(envelope(1));socket.receive(envelope(2,20));
  expect(events.filter(e=>e.type==='SNAPSHOT')).toHaveLength(2);
  socket.receive(envelope(3,19));
  expect(events.filter(e=>e.type==='SNAPSHOT').at(-1)).toMatchObject({snapshot:{hudRevision:20}});
  expect(events.filter(e=>e.type==='ASSESSMENT_INVALIDATED')).toHaveLength(1);
  expect(request).not.toHaveBeenCalled();expect(socket.send).not.toHaveBeenCalled();stop();
});
it('allows a new DB epoch and updates liveness even when revision is unchanged',async()=>{
  const socket=new Socket(),events:HudDataEvent[]=[];
  const source=new WebHudDataSource('ws://localhost/api/v1/hud/stream',vi.fn(),()=>socket);
  const stop=await source.connect(e=>events.push(e));
  socket.receive(envelope(1));socket.receive(envelope(2,12,'epoch',false));
  expect(events.filter(e=>e.type==='SNAPSHOT').at(-1)).toMatchObject({snapshot:{health:{scoreFreshness:'STALE'}}});
  socket.receive(envelope(3,1,'restored'));
  expect(events.filter(e=>e.type==='SNAPSHOT').at(-1)).toMatchObject({snapshot:{hudRevision:1}});
  expect(events.filter(e=>e.type==='DATABASE_RESET')).toHaveLength(2);stop();
});
it('reconnects with a fresh sequence and validates Target selection against its listed revision',async()=>{
  vi.useFakeTimers();
  const sockets:Socket[]=[],events:HudDataEvent[]=[];
  const request=vi.fn().mockResolvedValueOnce({listRevision:7,targets:[{targetId:'target',contentSha256:'abc'}]}).mockResolvedValue({status:'SELECTED'});
  const source=new WebHudDataSource('ws://localhost/api/v1/hud/stream',request,()=>{const socket=new Socket();sockets.push(socket);return socket;});
  const stop=await source.connect(event=>events.push(event));
  try{
    sockets[0].receive(envelope(9));sockets[0].close();
    await vi.advanceTimersByTimeAsync(1000);
    expect(sockets).toHaveLength(2);sockets[1].receive(envelope(1,13));
    expect(events.filter(e=>e.type==='SNAPSHOT').at(-1)).toMatchObject({snapshot:{hudRevision:13}});
    expect((await source.selectTarget({targetId:'target',expectedSha256:'abc'})).status).toBe('TARGET_CHANGED');
    await source.refreshTargets();await source.selectTarget({targetId:'target',expectedSha256:'abc'});
    expect(request).toHaveBeenLastCalledWith('/api/v1/targets/select',{targetId:'target',expectedSha256:'abc',expectedListRevision:7});
    expect((await source.selectTarget({targetId:'target',expectedSha256:'changed'})).status).toBe('TARGET_CHANGED');
  }finally{stop();vi.useRealTimers();}
});
