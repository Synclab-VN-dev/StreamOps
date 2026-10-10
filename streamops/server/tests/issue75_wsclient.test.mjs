// #75: test the actual shared WS request/response dispatcher, not just a stub.
// This catches swapped request_id, stale responses, typed error, and reconnect.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

const script=readFileSync(new URL('../web/ws-client.js',import.meta.url),'utf8');
class Socket {
  static OPEN=1;static CONNECTING=0;static CLOSING=2;static CLOSED=3;
  static created=[];
  constructor(url){
    this.url=url;this.readyState=0;this.listeners=new Map();this.sent=[];
    Socket.created.push(this);
  }
  addEventListener(name,fn){
    if(!this.listeners.has(name))this.listeners.set(name,[]);
    this.listeners.get(name).push(fn);
  }
  fire(name,value={}){for(const fn of this.listeners.get(name)||[])fn(value);}
  open(){this.readyState=1;this.fire('open');}
  send(data){if(this.readyState!==1)throw Error('closed');this.sent.push(JSON.parse(data));}
  reply(message){this.fire('message',{data:JSON.stringify(message)});}
  close(){this.readyState=3;this.fire('close');}
}
function fixture(){
  Socket.created.length=0;
  const events=[];
  const window={
    addEventListener:()=>{},dispatchEvent:e=>events.push(e.detail)
  };
  const document={addEventListener:()=>{},visibilityState:'visible'};
  const context={
    window,document,location:{protocol:'https:',host:'host.example'},
    WebSocket:Socket,CustomEvent:class {constructor(type,{detail}){this.type=type;this.detail=detail;}},
    setTimeout,clearTimeout,setInterval,clearInterval,queueMicrotask,Date,JSON
  };
  vm.runInNewContext(script,context,{filename:'ws-client.js'});
  const Client=window.StreamOpsWebSocketClient;
  const client=new Client({path:'/api/v1/obs/plugins/ws',label:'plugin',idleTimeoutMs:180000,
    connectionEvent:'streamops:plugin-connection'}).start();
  const socket=Socket.created.at(-1);
  socket.open();
  return {socket,client,events};
}
test('UNIT WS envelope: independent requests correlate reordered responses by request_id',async()=>{
  const {socket,client}=fixture();
  assert.equal(socket.url,'wss://host.example/api/v1/obs/plugins/ws');
  const a=client.request('obs_plugin.inventory',{});
  const b=client.request('obs_plugin.available',{});
  assert.equal(socket.sent.length,2);
  assert.notEqual(a.requestId,b.requestId);
  socket.reply({type:'response',request_id:b.requestId,ok:true,data:{which:'second'}});
  socket.reply({type:'response',request_id:a.requestId,ok:true,data:{which:'first'}});
  assert.equal((await a).which,'first');
  assert.equal((await b).which,'second');
  assert.equal(client.pending.size,0);
  client.destroy();
});
test('UNIT WS envelope: delayed stale response is ignored after it was already delivered',async()=>{
  const {socket,client}=fixture();
  const x=client.request('obs_plugin.inventory');
  socket.reply({type:'response',request_id:x.requestId,ok:true,data:{revision:7}});
  assert.equal((await x).revision,7);
  socket.reply({type:'response',request_id:x.requestId,ok:true,data:{revision:1}});
  assert.equal(client.pending.size,0);
  client.destroy();
});
test('UNIT WS envelope: typed backend failure preserves error code without retrying',async()=>{
  const {socket,client}=fixture();
  const p=client.request('obs_plugin.adopt',{plugin_id:'obs-multi-rtmp'});
  socket.reply({type:'response',request_id:p.requestId,ok:false,error:{
    code:'plugin_adopt_requires_obs_stopped',message:'OBS running'
  }});
  await assert.rejects(p,e=>e.code==='plugin_adopt_requires_obs_stopped');
  assert.equal(socket.sent.length,1);
  assert.equal(client.pending.size,0);
  client.destroy();
});
test('UNIT WS envelope: subscription receives actual event data, not response envelope',async()=>{
  const {socket,client}=fixture();
  const notices=[];
  const off=client.on('obs_plugin.changed',data=>notices.push(data));
  socket.reply({type:'event',event:'obs_plugin.changed',data:{
    plugin_id:'obs-multi-rtmp',revision:14,resources:['operation']
  }});
  assert.equal(notices.length,1);
  assert.equal(notices[0].revision,14);
  off();client.destroy();
});
test('UNIT WS envelope: interrupted pending request rejects; reconnect allocates fresh connection',async()=>{
  const {socket,client}=fixture();
  const pending=client.request('obs_plugin.install',{plugin_id:'obs-multi-rtmp'});
  socket.close();
  await assert.rejects(pending,/closed/);
  assert.equal(client.connected,false);
  assert.equal(client.pending.size,0);
  client.connect();
  const next=Socket.created.at(-1);
  assert.notEqual(next,socket);
  next.open();
  const second=client.request('obs_plugin.inventory');
  next.reply({type:'response',request_id:second.requestId,ok:true,data:{plugins:[]}});
  assert.equal((await second).plugins.length,0);
  client.destroy();
});


test('UNIT WS long-operation: 121s idle must not disconnect a legitimate 120s backend job',()=>{
  Socket.created.length=0;
  let now=0;
  const intervals=[];
  class ClockDate extends Date {static now(){return now;}}
  const w={addEventListener:()=>{},dispatchEvent:()=>{}};
  const context={
    window:w,document:{addEventListener:()=>{},visibilityState:'visible'},
    location:{protocol:'http:',host:'localhost:8765'},WebSocket:Socket,
    Date:ClockDate,JSON,queueMicrotask,
    setTimeout,clearTimeout,
    setInterval:(callback)=>{intervals.push(callback);return 1;},
    clearInterval:()=>{}
  };
  vm.runInNewContext(script,context,{filename:'ws-client.js'});
  const client=new w.StreamOpsWebSocketClient({
    path:'/api/v1/obs/plugins/ws',label:'long running plugin operation',
    idleTimeoutMs:180000
  }).start();
  const socket=Socket.created.at(-1);
  socket.open();
  now=121000;
  for(const watchdog of intervals)watchdog();
  assert.equal(socket.readyState,Socket.OPEN,'120s backend operation must be allowed');
  now=181000;
  for(const watchdog of intervals)watchdog();
  assert.equal(socket.readyState,Socket.CLOSED,'truly silent socket is recycled');
  client.destroy();
});
