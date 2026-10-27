'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const os=require('node:os');
const path=require('node:path');
const {SnapshotManager}=require('../src/manager');
const {FileSystemSnapshotStore}=require('../../browser-infra/src/snapshot/store');
const {digest,canonical}=require('../src/trust');
const scope={schemaVersion:'d4-rulekit-snapshot-scope/v1',policyId:'SYNTHETIC_OFFLINE',policyVersion:'1',capturePolicySha256:'c'.repeat(64),
 origins:['https://synthetic.invalid'],methods:['GET','HEAD'],
 include:[{origin:'https://synthetic.invalid',path:'/',match:'PREFIX'}],
 exclude:[{origin:'https://synthetic.invalid',path:'/telemetry',match:'PREFIX'}],
 excludedResourceTypes:['media'],navigationProfile:{id:'SYNTHETIC_NAV',version:'1',definitionSha256:'a'.repeat(64)},interactionProfile:{id:'SYNTHETIC_INTERACT',version:'1',definitionSha256:'b'.repeat(64)},
 requestHeaderPolicy:'fresh-anonymous-context',responsePolicy:'default-sanitized-json/v1',serviceWorkerPolicy:'block',
 navigationWaitUntil:'domcontentloaded',settleWaitUntil:'domcontentloaded',normalization:'whatwg-url-preserve-query/v1'};
const resource=(name,body=name,type='script')=>({url:'https://synthetic.invalid/'+name,body,resourceType:type});
const baseResources=()=>[resource('planner','SYNTHETIC DOCUMENT','document'),resource('d4.planner-BqhpPQJN.js','SYNTHETIC PLANNER'),resource('export-D12aM6KT.js','SYNTHETIC ENGINE'),resource('data.min.json?v=1','SYNTHETIC CATALOG','fetch')];
async function fixture(t){
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'rulekit-sver-'));
 const manager=new SnapshotManager({dataRoot:root});await manager.start();t.after(async()=>{await manager.close();await fs.rm(root,{recursive:true,force:true});});
 const store=new FileSystemSnapshotStore({rootDir:manager.storeRoot});
 async function save(id,resources=baseResources(),metadata={}){
  const manifest=await store.save({schemaVersion:'web-snapshot-draft/v1',snapshotId:id,sourceUrl:'https://synthetic.invalid/planner',capturedAt:'2026-10-27T00:00:00Z',allowedOrigins:['https://synthetic.invalid'],playwrightVersion:'test-only',...metadata,
   resources:resources.map(r=>({key:(r.method??'GET')+' '+new URL(r.url).href,method:r.method??'GET',url:r.url,status:r.status??200,headers:{'content-type':'text/plain'},body:r.body}))});
  const verified=await store.verify(id);
  const coverage={schemaVersion:'d4-rulekit-snapshot-coverage/v1',evidenceId:'SYNTHETIC_OFFLINE_GRAPH',manifestSha256:verified.manifestSha256,scopeFingerprint:digest(canonical(scope)),
   navigationComplete:true,interactionsComplete:true,discoveryComplete:true,pendingRequests:0,failedRequests:[],
   roots:[{method:'GET',url:manifest.sourceUrl}],nodes:resources.map(r=>({method:r.method??'GET',url:r.url,resourceType:r.resourceType})),
   edges:resources.slice(1).map(r=>({from:{method:'GET',url:manifest.sourceUrl},to:{method:r.method??'GET',url:r.url}}))};
  return {snapshotId:id,manifestSha256:verified.manifestSha256,scope:structuredClone(scope),coverage};
 }
 return {manager,store,root,save,compare:(baseline,candidate)=>manager.invoke('compareSnapshots',{baseline,candidate})};
}
test('SVER-02/04: identical content ignores snapshot ID and capture metadata',async t=>{
 const {save,compare}=await fixture(t);
 const a=await save('SYNTHETIC-A'),b=await save('SYNTHETIC-B',baseResources(),{capturedAt:'2026-10-28T12:00:00Z',browserVersion:'OTHER',playwrightVersion:'OTHER'});
 const result=await compare(a,b);
 assert.equal(result.status,'UNCHANGED');assert.equal(result.baselineFingerprint,result.candidateFingerprint);
 assert.notEqual(result.baselineFingerprint,a.manifestSha256);
 assert.deepEqual(result.diff.summary,{added:0,removed:0,modified:0});
});

for(const scenario of [
 {name:'added resource',change:rows=>[...rows,resource('extra.wasm','SYNTHETIC WASM','other')],summary:{added:1,removed:0,modified:0}},
 {name:'confirmed removal',change:rows=>rows.filter(r=>!r.url.includes('D12')),summary:{added:0,removed:1,modified:0}},
 {name:'same URL different body',change:rows=>rows.map(r=>r.url.includes('D12')?{...r,body:'CHANGED ENGINE'}:r),summary:{added:0,removed:0,modified:1}},
 {name:'planner filename rename with identical bytes',change:rows=>rows.map(r=>r.url.includes('Bqhp')?{...r,url:r.url.replace('BqhpPQJN','BGP2Ak1s')}:r),summary:{added:1,removed:1,modified:0}},
 {name:'planner bytes change while engine/catalog unchanged',change:rows=>rows.map(r=>r.url.includes('Bqhp')?{...r,body:'NEW PLANNER ONLY'}:r),summary:{added:0,removed:0,modified:1}},
]) test('SVER-03: '+scenario.name,async t=>{
 const {save,compare}=await fixture(t),a=await save('A'),b=await save('B',scenario.change(baseResources()));
 const result=await compare(a,b);
 assert.equal(result.status,'NEW_VERSION_FOUND');assert.notEqual(result.baselineFingerprint,result.candidateFingerprint);
 assert.deepEqual(result.diff.summary,scenario.summary);
 for(const row of result.diff.resources){assert.equal(row.identity,row.method+' '+row.url);assert.equal(row.oldSha256===null,row.change==='ADDED');assert.equal(row.newSha256===null,row.change==='REMOVED');}
 if(scenario.name.includes('planner')) assert(result.diff.resources.every(r=>!r.url.includes('D12')&&!r.url.includes('data.min')));
});

test('SVER-01: outside-path and excluded media content do not change version',async t=>{
 const {save,compare}=await fixture(t);
 const rows=[...baseResources(),resource('telemetry/private','OLD OUTSIDE','fetch'),resource('video.mp4','OLD MEDIA','media')];
 const a=await save('A',rows),b=await save('B',rows.map(r=>r.url.includes('telemetry')||r.resourceType==='media'?{...r,body:'NEW OUTSIDE'}:r));
 const result=await compare(a,b);assert.equal(result.status,'UNCHANGED');assert.equal(result.coverage.baseline.scopedResourceCount,4);
});

test('SVER-02: canonical ordering and independently calculated SHA-256',async t=>{
 const {save,compare}=await fixture(t);const a=await save('A'),rows=baseResources();
 const b=await save('B',[rows[0],rows[3],rows[1],rows[2]]);
 b.coverage.nodes.reverse();b.coverage.edges.reverse();b.scope.methods.reverse();
 const expected=digest(canonical({domain:'d4-rulekit-snapshot-content/v1',scopeFingerprint:digest(canonical(scope)),resources:rows.map(r=>({method:'GET',url:r.url,sha256:digest(Buffer.from(r.body))})).sort((a,b)=>a.url<b.url?-1:a.url>b.url?1:0)}));
 const result=await compare(a,b);assert.equal(result.status,'UNCHANGED');assert.equal(result.baselineFingerprint,expected);
});

for(const scenario of [
 {name:'missing coverage',change:r=>delete r.coverage,reason:'COVERAGE_EVIDENCE_MISSING'},
 {name:'pending request',change:r=>r.coverage.pendingRequests=1,reason:'PENDING_REQUESTS'},
 {name:'unfinished discovery',change:r=>r.coverage.discoveryComplete=false,reason:'DISCOVERY_INCOMPLETE'},
 {name:'unfinished interaction',change:r=>r.coverage.interactionsComplete=false,reason:'INTERACTIONS_INCOMPLETE'},
 {name:'unknown graph edge',change:r=>r.coverage.edges.pop(),reason:'RESOURCE_GRAPH_INCOMPLETE'},
 {name:'manifest node not discovered',change:r=>r.coverage.nodes.pop(),reason:'RESOURCE_COVERAGE_MISSING'},
 {name:'discovered asset absent in manifest',change:r=>r.coverage.nodes.push({method:'GET',url:'https://synthetic.invalid/missing.js',resourceType:'script'}),reason:'RESOURCE_COVERAGE_MISSING'},
 {name:'failed request',change:r=>r.coverage.failedRequests.push({method:'GET',url:'https://synthetic.invalid/failed.js'}),reason:'IN_SCOPE_REQUEST_FAILED'},
 {name:'wrong scope evidence binding',change:r=>r.coverage.scopeFingerprint='0'.repeat(64),reason:'COVERAGE_SCOPE_BINDING_MISMATCH'},
 {name:'wrong manifest evidence binding',change:r=>r.coverage.manifestSha256='0'.repeat(64),reason:'COVERAGE_MANIFEST_BINDING_MISMATCH'},
]) test('SVER-01/04: '+scenario.name+' is UNVERIFIED, never REMOVED/UNCHANGED',async t=>{
 const {save,compare}=await fixture(t);const a=await save('A'),b=await save('B');scenario.change(b);
 const result=await compare(a,b);assert.equal(result.status,'UNVERIFIED');assert.equal(result.diff,null);
 assert(result.coverage.candidate.reasons.includes(scenario.reason));
});

test('SVER-01: scope/policy/profile mismatch is not a new content version',async t=>{
 const {save,compare}=await fixture(t),a=await save('A'),b=await save('B');
 for(const field of ['policyVersion','capturePolicySha256']){
  const candidate=structuredClone(b);candidate.scope[field]=field==='policyVersion'?'2':'f'.repeat(64);
  const result=await compare(a,candidate);assert.equal(result.status,'UNVERIFIED');assert.equal(result.reason,'SCOPE_POLICY_MISMATCH');assert.equal(result.diff,null);
 }
});

test('SVER-02: query parameters are preserved; fragment and host/default-port normalization are stable',async t=>{
 const {normalizeScope,scopeFingerprint}=require('../src/content-version');
 const {save,compare}=await fixture(t),a=await save('A');
 const renamed=baseResources().map(r=>r.url.includes('data.min')?{...r,url:r.url.replace('?v=1','?v=2')}:r);
 assert.equal((await compare(a,await save('B',renamed))).status,'NEW_VERSION_FOUND');
 const b=await save('C');b.coverage.nodes[0].url='https://SYNTHETIC.invalid:443/planner#ignored';
 assert.equal((await compare(a,b)).status,'UNCHANGED');
 assert.equal(scopeFingerprint({...scope,origins:['https://SYNTHETIC.invalid:443']}),scopeFingerprint(scope));
 assert.equal(normalizeScope(scope).normalization,'whatwg-url-preserve-query/v1');
});

test('SVER-02: duplicate discovery entries dedupe, conflicting identities reject',async t=>{
 const {save,compare}=await fixture(t),a=await save('A'),b=await save('B');
 b.coverage.nodes.push({...b.coverage.nodes[0]});assert.equal((await compare(a,b)).status,'UNCHANGED');
 b.coverage.nodes.push({...b.coverage.nodes[0],resourceType:'media'});
 await assert.rejects(compare(a,b),{code:'CONTENT_DISCOVERY_IDENTITY_CONFLICT'});
});

test('SVER-05: corrupted manifest/blob or wrong pin rejects with typed integrity errors',async t=>{
 const {save,compare,root}=await fixture(t),a=await save('A'),b=await save('B');
 await assert.rejects(compare(a,{...b,manifestSha256:'0'.repeat(64)}),{code:'CONTENT_MANIFEST_BINDING_MISMATCH'});
 const manifestFile=path.join(root,'store','B','manifest.json');const original=await fs.readFile(manifestFile);
 await fs.appendFile(manifestFile,' ');await assert.rejects(compare(a,b),{code:'INTEGRITY_MISMATCH'});
 await fs.writeFile(manifestFile,original);
 const manifest=JSON.parse(original);await fs.writeFile(path.join(root,'store','B',manifest.resources[1].blob),'CORRUPTION');
 await assert.rejects(compare(a,b),{code:'INTEGRITY_MISMATCH'});
});

test('SVER-04: comparison works without trust and cannot mutate snapshot selection/registry',async t=>{
 const {save,compare,root}=await fixture(t),a=await save('A'),b=await save('B');
 const selected=path.join(root,'selection.json');await fs.writeFile(selected,'PRIVATE-UNRELATED-STATE');
 assert.equal((await compare(a,b)).status,'UNCHANGED');
 assert.equal(await fs.readFile(selected,'utf8'),'PRIVATE-UNRELATED-STATE');
 await assert.rejects(fs.access(path.join(root,'registry.json')),{code:'ENOENT'});
});

for(const params of [{status:304},{method:'HEAD',body:''},{status:503}])
 test('SVER-05: metadata/error response cannot prove unchanged body '+JSON.stringify(params),async t=>{
 const {save,compare}=await fixture(t),a=await save('A');
 const b=await save('B',baseResources().map((r,i)=>i===1?{...r,...params}:r));
 const result=await compare(a,b);assert.equal(result.status,'UNVERIFIED');assert.equal(result.diff,null);
 assert(result.coverage.candidate.reasons.includes('CONTENT_BODY_UNCONFIRMED'));
});

test('SVER-05: raw request and response contracts use real JSON Schema validation',async t=>{
 const Ajv=require('ajv'),schema=require('../schemas/content-version.schema.json');
 const ajv=new Ajv({strict:true});ajv.addSchema(schema);
 const validate=ajv.compile({$ref:'d4-rulekit-content-version/v1#/definitions/compareResult'});
 const {save,compare}=await fixture(t),a=await save('A'),b=await save('B');
 assert(validate(await compare(a,b)),ajv.errorsText(validate.errors));
 b.coverage=null;assert(validate(await compare(a,b)),ajv.errorsText(validate.errors));
 for(const patch of [{baseline:{...a,manifestSha256:'fake'}},{candidate:{...b,storeRoot:'/arbitrary'}},{candidate:{...b,scope:{...scope,normalization:'ignore-query'}}}])
  await assert.rejects(compare(patch.baseline??a,patch.candidate??b),{code:'SNAPSHOT_CALL_SCHEMA_INVALID'});
});

test('SVER-02: manifest formatting and resource metadata do not enter fingerprint',async t=>{
 const {save,compare,root}=await fixture(t),a=await save('A'),b=await save('B');
 const file=path.join(root,'store/B/manifest.json'),manifest=JSON.parse(await fs.readFile(file,'utf8'));
 for(const resource of manifest.resources) resource.headers={'cache-control':'DIFFERENT','etag':'DIFFERENT'};
 const bytes=Buffer.from(JSON.stringify(manifest));await fs.writeFile(file,bytes);const hash=digest(bytes);
 await fs.writeFile(path.join(root,'store/B/manifest.sha256'),hash+'\n');b.manifestSha256=hash;b.coverage.manifestSha256=hash;
 assert.equal((await compare(a,b)).status,'UNCHANGED');
});

test('SVER-04: genuine worker IPC exposes additive method and preserves eight Application APIs',{timeout:10000},async t=>{
 const {spawn}=require('node:child_process'),{createInterface}=require('node:readline'),{once}=require('node:events');
 const {trust}=require('./helpers');const {manager,root,save}=await fixture(t),a=await save('A'),b=await save('B');await manager.close();
 const config=path.join(root,'config.json');await fs.writeFile(config,JSON.stringify({anchors:trust([]).registry.anchors,dataRoot:root}));
 const repository=path.resolve(__dirname,'../../../..');
 const child=spawn(process.execPath,[path.join(repository,'utility/d4planner/rulekit-worker/worker.js')],{
  env:{...process.env,D4_RULEKIT_WORKER_INSTANCE_ID:'sver-synthetic-worker',D4_RULEKIT_WORKER_GENERATION:'1',D4_RULEKIT_COMPOSITION_MODULE:path.join(repository,'utility/d4planner/tests/fixtures/snapshot-test-composition.js'),TEST_SNAPSHOT_CONFIG:config},stdio:['pipe','pipe','pipe']});
 t.after(()=>{if(child.exitCode===null)child.kill();});
 const lines=createInterface({input:child.stdout})[Symbol.asyncIterator]();
 const ready=JSON.parse((await lines.next()).value);
 assert.deepEqual(ready.apis,['closeSession','commitChanges','createSession','evaluate','getSession','listProviders','previewChanges','resetSession']);
 child.stdin.write(JSON.stringify({protocolVersion:'d4-rulekit-snapshots/v1',type:'request',id:'sver-compare-1',method:'compareSnapshots',params:{baseline:a,candidate:b}})+'\n');
 const response=JSON.parse((await lines.next()).value);
 assert.equal(response.type,'result');assert.equal(response.protocolVersion,'d4-rulekit-snapshots/v1');assert.equal(response.correlationId,'sver-compare-1');
 assert.equal(response.workerInstanceId,'sver-synthetic-worker');assert.equal(response.workerGeneration,1);assert.equal(response.result.status,'UNCHANGED');
 const exit=once(child,'exit');child.stdin.end();assert.equal((await exit)[0],0);
});

test('SVER-04: partial captures expose observations, never claim confirmed addition/removal',async t=>{
 const {save,compare}=await fixture(t),a=await save('A'),b=await save('B',baseResources().map(r=>({...r,url:r.url.replace('BqhpPQJN','BGP2Ak1s')})));
 a.coverage=null;b.coverage=null;
 const result=await compare(a,b);
 assert.equal(result.status,'UNVERIFIED');assert.equal(result.diff,null);
 assert.equal(result.observations.basis,'VERIFIED_CAPTURED_SETS_ONLY');
 assert.equal(result.observations.baselineOnly[0].url,'https://synthetic.invalid/d4.planner-BqhpPQJN.js');
 assert.equal(result.observations.candidateOnly[0].url,'https://synthetic.invalid/d4.planner-BGP2Ak1s.js');
 assert(!('change' in result.observations.baselineOnly[0]));
});

test('SVER-01: pending failures outside URL/type scope do not contaminate completeness',async t=>{
 const {save,compare}=await fixture(t);const rows=[...baseResources(),resource('video.mp4','MEDIA','media')];
 const a=await save('A',rows),b=await save('B',rows);
 b.coverage.failedRequests.push({method:'GET',url:'https://synthetic.invalid/video.mp4'},{method:'GET',url:'https://synthetic.invalid/telemetry/excluded'});
 assert.equal((await compare(a,b)).status,'UNCHANGED');
});

test('SVER-01/02: scope sets dedupe, origin paths cannot silently narrow/change scope',async t=>{
 const {save,compare}=await fixture(t),a=await save('A'),b=await save('B');
 b.scope.origins.push(...b.scope.origins);b.scope.methods.push('GET');b.scope.excludedResourceTypes.push('media');b.scope.include.push({...b.scope.include[0]});
 assert.equal((await compare(a,b)).status,'UNCHANGED');
 b.scope.origins=['https://synthetic.invalid/different-scope'];
 await assert.rejects(compare(a,b),{code:'CONTENT_SCOPE_ORIGIN_INVALID'});
});

test('SVER-01: actual manifest capture origins must match the claimed scope policy',async t=>{
 const {save,compare}=await fixture(t),a=await save('A'),b=await save('B',baseResources(),{allowedOrigins:['https://synthetic.invalid','https://different-scope.invalid']});
 const result=await compare(a,b);
 assert.equal(result.status,'UNVERIFIED');assert.equal(result.diff,null);
 assert(result.coverage.candidate.reasons.includes('MANIFEST_CAPTURE_ORIGINS_MISMATCH'));
});
