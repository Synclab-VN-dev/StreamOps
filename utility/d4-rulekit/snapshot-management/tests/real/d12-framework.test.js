'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {createHarness}=require('./d12-harness');
test(`${process.env.COMPATIBILITY_TEST_DEFINITION??'maxroll-20261023'} signed isolated binding → generic factory → real offline Provider`, {timeout:180000},async()=>{
 const {browser,provider,build,expected,identity}=await createHarness();
 let session;
 try{
  await browser.start();
  session=await provider.createSession({build,buildSchemaVersion:'d4-build/v1',snapshotId:identity.snapshotId,snapshotManifestSha256:identity.snapshotManifestSha256,timeoutMs:60000});
  const result=await session.evaluate({build,changes:[],buildSchemaVersion:'d4-build/v1',timeoutMs:60000});
  assert.equal(result.metrics.length,50);assert.equal(result.provenance.networkReplay.transportOffline,true);
  const expectedRows=expected.rawMetrics??expected.metrics;
  assert.ok(Array.isArray(expectedRows),'independent fixture metrics required');
  const byId=new Map(expectedRows.map(row=>[row.metricId??row.id,row.rawValue??row.raw]));
  for(const metric of result.metrics){assert.ok(byId.has(metric.id),metric.id);assert.equal(metric.rawValue,byId.get(metric.id));}
 }finally{try{await session?.close();}finally{await browser.stop();}}
 assert.equal(browser.getStatus().state,'stopped');assert.equal(browser.getMetrics().currentContexts,0);
});
const {spawn}=require('node:child_process');
const path=require('node:path');
const readline=require('node:readline');
test(`${process.env.COMPATIBILITY_TEST_DEFINITION??'maxroll-20261023'} eight APIs through managed worker → signed resolver → real Chromium → cleanup`,{timeout:180000},async()=>{
 const h=await createHarness();
 const child=spawn(process.execPath,[path.resolve(__dirname,'../../../../d4planner/rulekit-worker/worker.js')],{env:{...process.env,D4_RULEKIT_COMPOSITION_MODULE:path.join(__dirname,'d12-harness.js'),D4_RULEKIT_WORKER_INSTANCE_ID:'isolated-framework-worker',D4_RULEKIT_WORKER_GENERATION:'1'},stdio:['pipe','pipe','pipe'],detached:process.platform!=='win32'});
 const pending=new Map();let sequence=0;
 const exit=new Promise(resolve=>child.once('exit',(code,signal)=>resolve({code,signal})));
 const ready=new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('worker READY timeout')),15000);pending.set('READY',{resolve:r=>{clearTimeout(timer);resolve(r);},reject});});
 const input=readline.createInterface({input:child.stdout});
 input.on('line',line=>{const row=JSON.parse(line);const waiter=pending.get(row.type==='READY'?'READY':row.correlationId);if(waiter){pending.delete(row.type==='READY'?'READY':row.correlationId);row.type==='error'?waiter.reject(new Error(row.error.code)):waiter.resolve(row);}});
 child.stderr.resume();
 const call=(method,params={})=>new Promise((resolve,reject)=>{const id=String(++sequence);const timer=setTimeout(()=>{pending.delete(id);reject(new Error('IPC timeout: '+method));},65000);pending.set(id,{resolve:row=>{clearTimeout(timer);resolve(row.result);},reject:error=>{clearTimeout(timer);reject(error);}});child.stdin.write(JSON.stringify({protocolVersion:'d4-rulekit-ipc/v1',type:'request',id,method,params})+'\n');});
 try{
  const status=await ready;assert.equal(status.pid,child.pid);assert.equal(status.apis.length,8);assert.equal(status.health.ready,true);
  const called=new Set();
  const invoke=async(method,params)=>{called.add(method);return call(method,params);};
  const providers=await invoke('listProviders');assert.equal(providers.length,1);
  const created=await invoke('createSession',{contractVersion:'d4-rulekit-application/v1',providerId:h.provider.id,providerVersion:h.provider.version,build:h.build,buildSchemaVersion:'d4-build/v1',snapshotId:h.identity.snapshotId,snapshotManifestSha256:h.identity.snapshotManifestSha256,timeoutMs:60000});
  const result=await invoke('evaluate',{sessionId:created.sessionId,options:{timeoutMs:60000}});
  const expected=new Map(h.expected.rawMetrics.map(row=>[row.metricId,row.rawValue]));assert.equal(result.metrics.length,50);
  for(const row of result.metrics){assert.ok(expected.has(row.id));assert.equal(row.rawValue,expected.get(row.id));}
  assert.equal(result.provenance.provider.runtimeAttestation.profileReadback.calculationOptions.status,'EXACT');
  const sessionId=created.sessionId;
  const vector=(rows,expected)=>{assert.equal(rows.length,expected.length);assert.deepEqual(rows.map(r=>[r.id,r.rawValue]).sort(),expected.map(r=>[r.metricId,r.rawValue]).sort());};
  assert.equal((await invoke('getSession',{sessionId})).revision,0);
  const changes=[{type:'build.replace',build:h.alternateBuild}];
  const preview=await invoke('previewChanges',{sessionId,request:{expectedRevision:0,changes,timeoutMs:60000}});
  vector(preview.before,h.expected.rawMetrics);vector(preview.after,h.alternateExpected.rawMetrics);
  assert.notEqual(preview.baseBuildFingerprint,preview.candidateBuildFingerprint);
  for(const delta of preview.delta)assert.equal(delta.delta,delta.after-delta.before);
  assert.equal((await invoke('getSession',{sessionId})).revision,0);
  vector((await invoke('evaluate',{sessionId,options:{bypassCache:true,timeoutMs:60000}})).metrics,h.expected.rawMetrics);
  const committed=await invoke('commitChanges',{sessionId,request:{expectedRevision:0,changes,previewToken:preview.previewToken,timeoutMs:60000}});
  assert.equal(committed.session.revision,1);vector(committed.result.metrics,h.alternateExpected.rawMetrics);
  await assert.rejects(invoke('commitChanges',{sessionId,request:{expectedRevision:0,changes,timeoutMs:60000}}));
  const reset=await invoke('resetSession',{sessionId,options:{expectedRevision:1,timeoutMs:60000}});assert.equal(reset.revision,2);
  const restored=await invoke('evaluate',{sessionId,options:{bypassCache:true,timeoutMs:60000}});vector(restored.metrics,h.expected.rawMetrics);assert.equal(restored.inputFingerprint,result.inputFingerprint);
  await invoke('closeSession',{sessionId});await assert.rejects(invoke('getSession',{sessionId}));
  assert.deepEqual([...called].sort(),[...status.apis].sort());
 }finally{
  child.stdin.end(JSON.stringify({protocolVersion:'d4-rulekit-ipc/v1',type:'shutdown'})+'\n');
  let timer;const stopped=await Promise.race([exit,new Promise(resolve=>{timer=setTimeout(()=>resolve(null),15000);})]);clearTimeout(timer);
  if(!stopped){if(process.platform!=='win32')process.kill(-child.pid,'SIGKILL');else child.kill('SIGKILL');await exit;throw new Error('owned worker cleanup timeout');}
  input.close();assert.equal(stopped.code,0);
 }
});
