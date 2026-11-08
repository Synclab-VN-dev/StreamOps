'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),os=require('node:os');
const {run,state,consistent,loadConfig}=require('../../tooling/capture-workflow');
async function fixture(t,{drift=false,gateFailure=false,incomplete=false}={}){
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'capture-workflow-'));t.after(()=>fs.rm(root,{recursive:true,force:true}));
 const c={stateRoot:path.join(root,'state'),uiRoot:path.join(root,'ui'),calculationRoot:path.join(root,'calc'),chromium:'/synthetic/browser',sourceUrl:'https://maxroll.gg/d4/planner/fixture'};
 const calls=[];let starts=0,stops=0;
 const deps={loadConfig:async()=>c,browserFactory:opts=>{assert.deepEqual(opts.launchOptions,{handleSIGINT:false,handleSIGTERM:false,handleSIGHUP:false});return {start:async()=>starts++,stop:async()=>stops++};},
 calculation:{capture:async o=>{calls.push('calculation');await fs.mkdir(o.output,{recursive:true});return {validation:'PATCH_DRIFT'};}},
 captureUi:async o=>{calls.push('ui');if(incomplete)throw Error('Missing native category model');await fs.mkdir(path.join(o.snapshotRoot,o.snapshotId),{recursive:true});await fs.writeFile(path.join(o.snapshotRoot,o.snapshotId,'ui-coverage.json'),'{}');},
 identity:async(root)=>({integrity:{manifestSha256:'a'.repeat(64)},identity:{version:'same-label',fingerprints:{engine:drift&&root===c.uiRoot?'changed':'engine',game:'game',localization:'localization'}}}),
 audit:async()=>({status:'PASS'}),command:async(_bin,args)=>{const config=JSON.parse(await fs.readFile(args[1]));if(gateFailure)throw Error('Visual regression');await fs.mkdir(config.output,{recursive:true});await fs.writeFile(path.join(config.output,config.online?'report.json':'acceptance.json'),JSON.stringify({status:config.online?'PASS':'AUTOMATED_PASS',scope:'ui',head:'synthetic',finishedAt:new Date().toISOString()}));}};
 return {c,deps,calls,counts:()=>({starts,stops})};
}
test('coordinated capture uses one browser, separate immutable IDs, full gates and no calculation promotion',async t=>{
 const f=await fixture(t),r=await run({mode:'all'},f.deps);assert.equal(r.consistency,'PASS');assert.deepEqual(f.calls,['calculation','ui']);assert.deepEqual(f.counts(),{starts:1,stops:1});
 const d=await state(f.c.stateRoot,{operation:'read'});assert.equal(d.activeUi,null);assert.equal(d.runs[r.runId].status,'COMPLETE');
 const [calculation,ui]=r.packages;assert.notEqual(calculation.snapshotId,ui.snapshotId);assert.equal(calculation.runId,ui.runId);assert.equal(calculation.compatibility,'PATCH_DRIFT');assert.equal(ui.validationStatus,'VALIDATED');
 assert.equal(d.packages[calculation.snapshotId].validationStatus,'CAPTURED_UNVALIDATED');assert(d.packages[ui.snapshotId].validationSha256);
});
test('same patch label with different runtime bytes cannot publish a coordinated pair',async t=>{
 const f=await fixture(t,{drift:true});await assert.rejects(run({mode:'all'},f.deps),e=>e.code==='CONSISTENCY_FAILED');
 const d=await state(f.c.stateRoot,{operation:'read'});assert.equal(Object.values(d.runs)[0].status,'FAILED');assert.equal(d.activeUi,null);assert(Object.values(d.packages).every(p=>p.validationStatus!=='VALIDATED'));
 assert.equal(consistent({version:'v',fingerprints:{a:'1'}},{version:'v',fingerprints:{a:'2'}}),false);
});
for(const option of ['gateFailure','incomplete'])test('UI failure remains in history and cannot select '+option,async t=>{
 const f=await fixture(t,{[option]:true});await assert.rejects(run({mode:'ui'},f.deps));const d=await state(f.c.stateRoot,{operation:'read'});assert.equal(Object.values(d.packages)[0].validationStatus,'UNSUPPORTED_VERSION');assert.equal(d.activeUi,null);assert.equal(f.counts().stops,1);
});
test('calculation without output gets unique names and remains unvalidated across concurrent runs',async t=>{
 const f=await fixture(t);const results=await Promise.all([run({},f.deps),run({},f.deps)]);assert.notEqual(results[0].runId,results[1].runId);const d=await state(f.c.stateRoot,{operation:'read'});assert.equal(Object.keys(d.runs).length,2);assert.equal(Object.keys(d.packages).length,2);assert.equal(d.activeUi,null);
});

test('capture config and UI trust no longer require or emit authorizationRef',async t=>{
 const f=await fixture(t);f.c.chromium=process.execPath;const file=path.join(path.dirname(f.c.stateRoot),'config.json');
 await fs.writeFile(file,JSON.stringify({...f.c,schemaVersion:'maxroll-capture-config/v1'}),{mode:0o600});
 const config=await loadConfig(file);assert.equal(config.authorizationRef,undefined);
 const capture=f.deps.captureUi;f.deps.captureUi=async options=>{assert(!Object.hasOwn(options,'authorizationRef'));return capture(options);};
 const r=await run({mode:'all'},f.deps);assert.equal(r.status,'COMPLETE');
 const d=await state(f.c.stateRoot,{operation:'read'});
 assert(!Object.hasOwn(d.packages[r.packages.find(p=>p.kind==='ui').snapshotId].config.uiTrust,'authorizationRef'));
});
