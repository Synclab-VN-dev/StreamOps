'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {buildIndex}=require('../compatibility/build-index');
const {loadCatalog}=require('../compatibility/loader');
const root=path.resolve(__dirname,'../..');
test('tracked discovery resolves D12; exact implementation identity is not legacy approval',()=>{
 const index=buildIndex({root});const catalog=loadCatalog({root,index});
 assert.equal(catalog.definitions.length,index.modules.length);
 assert.equal(catalog.definitions[0].identity.snapshotId,'maxroll-20261023T034150Z');
 assert.match(catalog.ruleKitVersion,/^rulekit-execution\/sha256:[a-f0-9]{64}$/);
 assert.notEqual(catalog.ruleKitVersion,'rulekit-snapshot-management/1.0.0');
});
const cp=require('node:child_process');
const {TrustedRegistry}=require('../src/trust');
const {trust}=require('./helpers');
const {CompatibilityResolver}=require('../src/resolver');
function sandbox(t){
 const directory=fs.mkdtempSync(path.join(os.tmpdir(),'compat-framework-'));
 t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));
 const index=buildIndex({root});
 for(const row of index.files){const dest=path.join(directory,row.path);fs.mkdirSync(path.dirname(dest),{recursive:true});fs.copyFileSync(path.join(root,row.path),dest);}
 cp.execFileSync('git',['init','-q',directory]);cp.execFileSync('git',['add','.'],{cwd:directory});return directory;
}
function signedEntry(version){return {entryId:'isolated',status:'APPROVED',ruleKitVersion:version,providerId:'maxroll',providerVersion:'test',codecVersion:'test',canonicalSchemaVersion:'test',strategyId:'test',profileId:'test',profileSha256:'a'.repeat(64),snapshotId:'test',snapshotManifestSha256:'a'.repeat(64),gamePatch:'test',sourceUrl:'https://test.invalid',engineAsset:{url:'https://test.invalid/e',sha256:'a'.repeat(64)},catalog:{url:'https://test.invalid/c',sha256:'b'.repeat(64)},capabilities:{stateModel:'stateful',metricIds:[],changeTypes:[]},approval:{reference:'ISOLATED_TEST',evidenceSha256:'c'.repeat(64),testClass:'SYNTHETIC_TEST_ONLY'},distribution:{permission:'PRIVATE_ONLY',reference:'test'}};}
for(const changed of ['snapshot-management/compatibility/versions/maxroll-20261023.js','providers/maxroll/src/canonical-codec-core.js']){
 test('changed implementation + regenerated index cannot reuse signed approval: '+changed,t=>{
  const directory=sandbox(t),before=buildIndex({root:directory});
  const signed=trust([signedEntry(before.ruleKitVersion)]);
  const old=new TrustedRegistry({anchors:{TEST_ONLY:{publicKey:signed.publicKey}},ruleKitVersion:before.ruleKitVersion,scope:'ISOLATED_TEST'});
  old.accept(signed.envelope);assert.equal(old.resolve('isolated').entryId,'isolated');
  const changedPath=path.join(directory,changed);
  const original=fs.readFileSync(changedPath,'utf8');
  const mutation=changed.includes('/versions/')?original.replace('expectedRawMetrics: 50','expectedRawMetrics: 51'):original.replace("const CANONICAL_SCHEMA_VERSION='d4-build/v1'","const CANONICAL_SCHEMA_VERSION='d4-build/v2'");
  assert.notEqual(mutation,original);fs.writeFileSync(changedPath,mutation);
  assert.throws(()=>loadCatalog({root:directory,index:before}),{code:'EXECUTION_BYTES_MISMATCH'});
  const after=buildIndex({root:directory});assert.notEqual(after.ruleKitVersion,before.ruleKitVersion);
  const replacement=new TrustedRegistry({anchors:{TEST_ONLY:{publicKey:signed.publicKey}},ruleKitVersion:after.ruleKitVersion,scope:'ISOLATED_TEST'});
  replacement.accept(signed.envelope);assert.throws(()=>replacement.resolve('isolated'),{code:'RULEKIT_VERSION_INCOMPATIBLE'});
  const resolver=new CompatibilityResolver({registry:old,strategies:{test:{executionVersion:after.ruleKitVersion}}});
  assert.throws(()=>resolver.resolve('isolated',{},{}),{code:'IMPLEMENTATION_APPROVAL_MISMATCH'});
 });
}
test('B then third C: each addition is exactly one tracked module, shared sources unchanged',t=>{
 const directory=sandbox(t);const baseline=buildIndex({root:directory});
 for(const id of ['synthetic-b','synthetic-c']){
  const file='snapshot-management/compatibility/versions/'+id+'.js';
  fs.writeFileSync(path.join(directory,file),`'use strict';\nconst base=require('./maxroll-20261023');\nconst {deepFreeze}=require('../contracts');\nmodule.exports=deepFreeze({...base,definitionId:'${id}',identity:{...base.identity,snapshotId:'${id}'},evidenceClass:'SYNTHETIC_TEST_ONLY',bindings:base.bindings.map(b=>({...b,id:'${id}-'+b.family.replace('/','-')}))});\n`);
  // Untracked files are never discovered or executed.
  const untracked=buildIndex({root:directory});assert.ok(!untracked.modules.includes(file));
  cp.execFileSync('git',['add',file],{cwd:directory});
  const index=buildIndex({root:directory});const catalog=loadCatalog({root:directory,index});
  const definition=catalog.definitions.find(d=>d.definitionId===id);assert.ok(definition);
  const {createStrategies}=require('../src/strategies');
  const {createProfileFamily}=require('../../providers/maxroll/src/real-profile-core');
  const {METRIC_CATALOG}=require('../../providers/maxroll/src/metric-catalog');
  const strategies=createStrategies(catalog),binding=definition.bindings.find(b=>b.family==='ui-cdp/v1');
  const profile=createProfileFamily(definition).createCandidateProfile({snapshotId:definition.identity.snapshotId,snapshotManifestSha256:definition.identity.snapshotManifestSha256,sourceUrl:'https://synthetic.invalid/planner',authorizationRef:'ISOLATED_TEST',metricCatalog:METRIC_CATALOG});
  const entry={...signedEntry(catalog.ruleKitVersion),strategyId:binding.id,providerVersion:binding.providerVersion,codecVersion:definition.codecVersion,canonicalSchemaVersion:binding.schema,snapshotId:definition.identity.snapshotId,snapshotManifestSha256:definition.identity.snapshotManifestSha256,gamePatch:definition.identity.gamePatch,sourceUrl:profile.sourceUrl,engineAsset:{url:profile.assetUrl,sha256:profile.assetSha256},catalog:{url:'https://synthetic.invalid/catalog',sha256:definition.identity.catalogResourceSha256},capabilities:profile.capability()};
  entry.capabilities={stateModel:entry.capabilities.stateModel,metricIds:entry.capabilities.metricIds,changeTypes:entry.capabilities.changeTypes};
  const signed=trust([entry]);const registry=new TrustedRegistry({anchors:{TEST_ONLY:{publicKey:signed.publicKey}},ruleKitVersion:catalog.ruleKitVersion,scope:'ISOLATED_TEST'});registry.accept(signed.envelope);
  const manifest={snapshotId:entry.snapshotId,sourceUrl:entry.sourceUrl,resources:[entry.engineAsset,entry.catalog]};
  const resolver=new CompatibilityResolver({registry,strategies});
  assert.equal(resolver.resolve(entry.entryId,profile,manifest).strategy.factory.runtimeKind,'maxroll-ui-cdp-v1');
  assert.throws(()=>resolver.resolve(entry.entryId,{...profile,realRuntime:{...profile.realRuntime,captureExpression:'evil()'}},manifest),{code:'EXECUTION_PROFILE_MISMATCH:captureExpression'});
  assert.throws(()=>resolver.resolve(entry.entryId,{...profile,realRuntime:{...profile.realRuntime,discoverMetricCatalog:true}},manifest),{code:'EXECUTION_PROFILE_FIELD_UNKNOWN:discoverMetricCatalog'});
  assert.throws(()=>resolver.resolve(entry.entryId,profile,{...manifest,resources:[]}),{code:'SNAPSHOT_ASSET_BINDING_MISMATCH'});
  for(const row of baseline.files)assert.equal(index.files.find(r=>r.path===row.path).sha256,row.sha256);
  const additions=index.files.filter(row=>!untracked.files.some(old=>old.path===row.path));assert.deepEqual(additions.map(row=>row.path),[file]);
 }
 assert.equal(loadCatalog({root:directory,index:buildIndex({root:directory})}).definitions.length,baseline.modules.length+2);
});
test('duplicate registration rejected; no manual registry edit',t=>{
 const directory=sandbox(t),file='snapshot-management/compatibility/versions/duplicate.js';
 fs.writeFileSync(path.join(directory,file),"module.exports=require('./maxroll-20261023');\n");cp.execFileSync('git',['add',file],{cwd:directory});
 assert.throws(()=>loadCatalog({root:directory,index:buildIndex({root:directory})}),{code:'DUPLICATE_DEFINITION'});
});
test('symlink tracked module rejected before execution',t=>{
 const directory=sandbox(t),file='snapshot-management/compatibility/versions/link.js';
 fs.symlinkSync('maxroll-20261023.js',path.join(directory,file));cp.execFileSync('git',['add',file],{cwd:directory});
 assert.throws(()=>buildIndex({root:directory}),{code:'BUILD_SYMLINK_REJECTED'});
});
test('tampered index identity and unsafe module paths rejected',()=>{
 const index=buildIndex({root});
 assert.throws(()=>loadCatalog({root,index:{...index,executionSha256:'0'.repeat(64)}}),{code:'INDEX_IDENTITY_INVALID'});
 assert.throws(()=>loadCatalog({root,index:{...index,modules:['../external.js']}}),{code:'INDEX_MODULE_SET_MISMATCH'});
});
test('unknown module contract rejected after tracked discovery',t=>{
 const directory=sandbox(t),file='snapshot-management/compatibility/versions/unknown.js';
 fs.writeFileSync(path.join(directory,file),"module.exports={contractVersion:'UNKNOWN'};\n");cp.execFileSync('git',['add',file],{cwd:directory});
 assert.throws(()=>loadCatalog({root:directory,index:buildIndex({root:directory})}),{code:'DEFINITION_CONTRACT_INVALID'});
});
test('modified module is rejected before executing its replacement body',t=>{
 const directory=sandbox(t),index=buildIndex({root:directory});
 fs.writeFileSync(path.join(directory,index.modules[0]),"throw new Error('UNVERIFIED_CODE_EXECUTED');\n");
 assert.throws(()=>loadCatalog({root:directory,index}),{code:'EXECUTION_BYTES_MISMATCH'});
});
test('regenerated index may not relabel cached implementation in the same worker',t=>{
 const directory=sandbox(t);loadCatalog({root:directory,index:buildIndex({root:directory})});
 fs.appendFileSync(path.join(directory,'providers/maxroll/src/canonical-codec-core.js'),'\n// changed execution\n');
 assert.throws(()=>loadCatalog({root:directory,index:buildIndex({root:directory})}),{code:'EXECUTION_RESTART_REQUIRED'});
});
