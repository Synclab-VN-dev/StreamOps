'use strict';
// Contract negatives use synthetic manifest/profile containers, never real-compatibility proof.
const {test}=require('node:test'),assert=require('node:assert/strict');
const {loadCatalog}=require('../compatibility/loader');
const {createProfileFamily}=require('../../providers/maxroll/src/real-profile-core');
const {METRIC_CATALOG}=require('../../providers/maxroll/src/metric-catalog');
const {trust}=require('./helpers');
const {TrustedRegistry,digest}=require('../src/trust');
const {CompatibilityResolver}=require('../src/resolver');
const {STRATEGIES,RULEKIT_VERSION}=require('../src/strategies');
function fixture(mutate=()=>{}){
 const d=loadCatalog().definitions.find(d=>d.definitionId==='maxroll-20261027');assert.ok(d);
 const b=d.bindings.find(b=>b.family==='native-state/v1');
 const profile=createProfileFamily(d).createUniversalProfile({snapshotId:d.identity.snapshotId,snapshotManifestSha256:d.identity.snapshotManifestSha256,sourceUrl:'https://synthetic.invalid/fixture',authorizationRef:'ISOLATED_TEST',metricCatalog:METRIC_CATALOG,nativeRuntime:{plannerId:'synthetic',profileUrl:'https://planners.maxroll.gg/profiles/load/d4/synthetic'}});
 const caps=profile.capability();
 const entry={entryId:'dfjs-test',status:'APPROVED',ruleKitVersion:RULEKIT_VERSION,providerId:'maxroll',providerVersion:b.providerVersion,codecVersion:d.codecVersion,canonicalSchemaVersion:b.schema,strategyId:b.id,profileId:'dfjs-test',profileSha256:digest(Buffer.from(JSON.stringify(profile))),snapshotId:d.identity.snapshotId,snapshotManifestSha256:d.identity.snapshotManifestSha256,gamePatch:d.identity.gamePatch,sourceUrl:profile.sourceUrl,engineAsset:{url:profile.assetUrl,sha256:profile.assetSha256},catalog:{url:'https://synthetic.invalid/catalog',sha256:d.identity.catalogResourceSha256},capabilities:{stateModel:caps.stateModel,metricIds:caps.metricIds,changeTypes:caps.changeTypes},approval:{reference:'ISOLATED_TEST',evidenceSha256:'a'.repeat(64),testClass:'SYNTHETIC_TEST_ONLY'},distribution:{permission:'PRIVATE_ONLY',reference:'TEST_ONLY'}};
 mutate(entry);
 const signed=trust([entry]);const registry=new TrustedRegistry({anchors:{TEST_ONLY:{publicKey:signed.publicKey}},ruleKitVersion:RULEKIT_VERSION,scope:'ISOLATED_TEST'});registry.accept(signed.envelope);
 return {d,profile,entry,registry,signed,resolver:new CompatibilityResolver({registry,strategies:STRATEGIES}),manifest:{snapshotId:entry.snapshotId,sourceUrl:entry.sourceUrl,resources:[entry.engineAsset,entry.catalog]}};
}
test('Dfjs resolves from automatic index, only native family is declared',()=>{const f=fixture();assert.equal(f.d.bindings.length,1);assert.equal(f.resolver.resolve(f.entry.entryId,f.profile,f.manifest).strategy.executionVersion,RULEKIT_VERSION);assert.equal(f.profile.realRuntime.itemProjection.authority.startsWith('sha256:'+f.d.identity.engineAssetSha256+':'),true);});
test('Dfjs rejects wrong engine/catalog/profile/codec/runtime and unknown entry',()=>{
 for(const mutate of [e=>e.engineAsset.sha256='0'.repeat(64),e=>e.catalog.sha256='0'.repeat(64),e=>e.codecVersion='unknown',e=>e.strategyId='unknown',e=>e.snapshotManifestSha256='0'.repeat(64)]){const f=fixture(mutate);assert.throws(()=>f.resolver.resolve(f.entry.entryId,f.profile,f.manifest),e=>typeof e.code==='string');}
 const f=fixture();assert.throws(()=>f.resolver.resolve('missing',f.profile,f.manifest),{code:'SNAPSHOT_COMPATIBILITY_UNKNOWN'});
 assert.throws(()=>f.resolver.resolve(f.entry.entryId,{...f.profile,realRuntime:{...f.profile.realRuntime,inputStateReadbackExpression:'({})'}},f.manifest),{code:'EXECUTION_PROFILE_MISMATCH:inputStateReadbackExpression'});
 assert.throws(()=>f.resolver.resolve(f.entry.entryId,f.profile,{...f.manifest,resources:[]}),{code:'SNAPSHOT_ASSET_BINDING_MISMATCH'});
});
test('Dfjs unsigned, revoked and stale implementation approvals fail closed',()=>{
 const f=fixture();const tampered=structuredClone(f.signed.envelope);tampered.payload.entries[0].approval.reference='forged';assert.throws(()=>f.registry.verify(tampered),{code:'REGISTRY_SIGNATURE_INVALID'});
 const revoked=structuredClone(f.signed.payload);revoked.revision=2;revoked.revokedEntryIds=[f.entry.entryId];f.registry.accept(f.signed.sign(revoked));assert.throws(()=>f.resolver.resolve(f.entry.entryId,f.profile,f.manifest),{code:'COMPATIBILITY_REVOKED'});
 const stale=fixture(e=>e.ruleKitVersion='rulekit-snapshot-management/1.0.0');assert.throws(()=>stale.resolver.resolve(stale.entry.entryId,stale.profile,stale.manifest),{code:'RULEKIT_VERSION_INCOMPATIBLE'});
});
