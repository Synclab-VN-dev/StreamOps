'use strict';
// Real Chromium, loopback synthetic HTTP only. Never contacts Maxroll.
const test=require('node:test'),assert=require('node:assert/strict');
const http=require('node:http'),fs=require('node:fs/promises'),os=require('node:os'),path=require('node:path');
const {BrowserInfrastructure,FileSystemSnapshotStore,WebSnapshotManager}=require('../../src');
for(const hang of [false,true])test('real Chromium captures delayed synthetic /api/twitch; hang='+hang,{timeout:10000},async()=>{
 const directory=await fs.mkdtemp(path.join(os.tmpdir(),'capture-completion-real-'));let apiRequests=0;
 const server=http.createServer((request,response)=>{
  assert.equal(request.method,'GET');
  if(request.url==='/app'){response.writeHead(200,{'content-type':'text/html'});response.end('<!doctype html><script>setTimeout(()=>fetch("/api/twitch"),40)</script>');}
  else if(request.url==='/api/twitch'){apiRequests++;if(!hang){response.writeHead(200,{'content-type':'application/json'});setTimeout(()=>response.end('{"synthetic":true}'),80);}}
  else{response.writeHead(204);response.end();}
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const origin='http://127.0.0.1:'+server.address().port;
 const browser=new BrowserInfrastructure({executablePath:process.env.BROWSER_INFRA_CHROMIUM_PATH,headless:true,maxContexts:1,maxQueue:1});
 try{
  await browser.start();const store=new FileSystemSnapshotStore({rootDir:directory});const manager=new WebSnapshotManager({browser,store});
  const operation=manager.capture({snapshotId:'SYNTHETIC-REAL',url:origin+'/app',allowedOrigins:[origin],timeoutMs:hang?500:5000,capturePolicy:{requestHeaderPolicy:'fresh-anonymous-context',navigationWaitUntil:'domcontentloaded',settleWaitUntil:'domcontentloaded',completion:{minimumObservationMs:180,quietWindowMs:40}}});
  if(hang)await assert.rejects(operation,{code:'CAPTURE_TIMEOUT'});
  else{
   const draft=await operation;const api=draft.resources.find(r=>r.url===origin+'/api/twitch');
   assert(api,'delayed GET must be included');assert.equal(api.body.toString(),'{"synthetic":true}');assert.equal(draft.capture.completion.pendingRequests,0);
   await store.save(draft);assert.equal((await store.verify(draft.snapshotId)).valid,true);
  }
  assert.equal(apiRequests,1);
 }finally{
  await browser.stop();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));await fs.rm(directory,{recursive:true,force:true});
 }
 assert.equal(browser.getStatus().state,'stopped');assert.equal(browser.getStatus().pid,null);
});
