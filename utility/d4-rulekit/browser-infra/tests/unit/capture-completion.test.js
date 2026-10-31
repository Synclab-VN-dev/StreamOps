'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {WebSnapshotManager}=require('../../src');
function fixture({lateFailure=false,neverRespond=false}={}){
 const page=new EventEmitter();let routeHandler;const timers=[];
 const later=(ms,fn)=>{const timer=setTimeout(fn,ms);timers.push(timer);};
 const context={addInitScript:async()=>{},route:async(_pattern,handler)=>{routeHandler=handler;},unroute:async()=>{routeHandler=null;},browser:()=>({version:()=> 'SYNTHETIC'})};
 async function dispatch(url,type='document',delay=0){
  const req={method:()=> 'GET',url:()=>url,resourceType:()=>type,headers:()=>({}),redirectedFrom:()=>null};
  const route={request:()=>req,abort:async()=>{},continue:async()=>{
   if(neverRespond && type==='fetch')return;
   if(lateFailure && type==='fetch'){later(3,()=>page.emit('requestfailed',req));return;}
   later(delay,()=>{page.emit('response',{request:()=>req,url:()=>url,status:()=>200,allHeaders:async()=>({'content-type':'text/plain'}),body:async()=>Buffer.from('SYNTHETIC '+type)});page.emit('requestfinished',req);});
  }};
  if(routeHandler)await routeHandler(route);
 }
 page.goto=async()=>{await dispatch('https://synthetic.invalid/app');};page.waitForLoadState=async()=>{};page.close=async()=>{};
 const browser={withLease:async(_options,fn)=>fn({page,context})};
 const manager=new WebSnapshotManager({browser,store:{save(){},load(){},verify(){},list(){},loadPackage(){}}});
 return {page,manager,late:()=>later(20,()=>void dispatch('https://synthetic.invalid/api/twitch','fetch',10)),cleanup:()=>timers.forEach(clearTimeout)};
}
const options={snapshotId:'SYNTHETIC-COMPLETION',url:'https://synthetic.invalid/app',allowedOrigins:['https://synthetic.invalid'],timeoutMs:300,
 capturePolicy:{navigationWaitUntil:'domcontentloaded',settleWaitUntil:'domcontentloaded',completion:{minimumObservationMs:60,quietWindowMs:15}}};
test('capture completion includes delayed in-scope GET after DOM/interact settled',async t=>{
 const f=fixture();t.after(f.cleanup);
 const result=await f.manager.capture({...options,interact:async()=>{f.late();}});
 assert(result.resources.some(r=>r.url==='https://synthetic.invalid/api/twitch'),'late GET /api/twitch must be captured, not excluded');
 assert.equal(result.capture.completion.pendingRequests,0);
 assert.equal(result.capture.completion.failedRequests.length,0);
 assert(result.capture.completion.nodes.some(n=>n.url.endsWith('/api/twitch')));
 assert.equal(f.page.listenerCount('response'),0);
});
test('completion timeout is bounded and removes listeners instead of returning partial success',async t=>{
 const f=fixture({neverRespond:true});t.after(f.cleanup);
 await assert.rejects(f.manager.capture({...options,timeoutMs:80,interact:async()=>{f.late();}}),{code:'CAPTURE_TIMEOUT'});
 assert.equal(f.page.listenerCount('response'),0);assert.equal(f.page.listenerCount('requestfailed'),0);assert.equal(f.page.listenerCount('requestfinished'),0);
});
test('failed in-scope request cannot be reported complete',async t=>{
 const f=fixture({lateFailure:true});t.after(f.cleanup);
 await assert.rejects(f.manager.capture({...options,interact:async()=>{f.late();}}),{code:'RESOURCE_MISSING'});
});
