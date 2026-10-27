'use strict';
const {fail}=require('./trust');
// Existing D12 codec guards remain intact. A registry cannot turn an unknown
// codec/runtime into an implementation. Strategies are Rule Kit code, not JS
// constructors supplied by profile JSON or the Backend.
const {MaxrollPatchProfile}=require('../../providers/maxroll/src/patch-profile');
const {REAL_MAXROLL_COMPONENT_FACTORY}=require('../../providers/maxroll/src/real-profile');
const {D12_COMPATIBILITY,CODEC_VERSION,MaxrollD12CanonicalCodec,loadMaxrollEntityCatalog}=require('../../providers/maxroll/src/canonical-codec');
const {UniversalMaxrollComponentFactory}=require('../../providers/maxroll/src/universal-component-factory');
function validateCapabilities(profile,entry){
 const caps=new MaxrollPatchProfile(profile).capability();
 for(const field of ['metricIds','changeTypes'])fail(JSON.stringify([...caps[field]].sort())===JSON.stringify([...entry.capabilities[field]].sort()),'CAPABILITIES_BINDING_MISMATCH:'+field);
 fail(caps.stateModel===entry.capabilities.stateModel,'CAPABILITIES_BINDING_MISMATCH:stateModel');
}
const STRATEGIES=Object.freeze({
  'maxroll-ui-cdp-D12-v1':Object.freeze({
    evidenceClass:'REAL_PROVIDER',
    codecVersions:[CODEC_VERSION],canonicalSchemas:['maxroll-build/rogue-l50-v1'],
    providerVersions:['maxroll-provider/3.2.1.73552-D12aM6KT-candidate-v1'],
    validateProfile(profile,entry){
      validateCapabilities(profile,entry);
      fail(profile.runtimeKind==='maxroll-ui-cdp-v1','PROFILE_RUNTIME_KIND_INCOMPATIBLE');
      fail(entry.gamePatch===D12_COMPATIBILITY.gamePatch && entry.engineAsset.sha256===D12_COMPATIBILITY.engineAssetSha256 && entry.catalog.sha256===D12_COMPATIBILITY.catalogResourceSha256,'D12_RUNTIME_GUARD_MISMATCH');
      // Original canonical codec guards are not widened. A separate evidence-
      // bound entry can reuse this UI strategy; it does not authorize a newer
      // canonical codec or universal-build capability automatically.
    },
    factory:REAL_MAXROLL_COMPONENT_FACTORY,
  }),
  'maxroll-native-D12-v1':Object.freeze({
    evidenceClass:'REAL_PROVIDER',codecVersions:[CODEC_VERSION],canonicalSchemas:['d4-build/v1'],
    providerVersions:['maxroll-provider/3.2.1.73552-D12aM6KT-universal-v1'],
    validateProfile(profile,entry){
      validateCapabilities(profile,entry);
      fail(entry.snapshotId===D12_COMPATIBILITY.snapshotId && entry.snapshotManifestSha256===D12_COMPATIBILITY.snapshotManifestSha256 && entry.engineAsset.sha256===D12_COMPATIBILITY.engineAssetSha256 && entry.catalog.sha256===D12_COMPATIBILITY.catalogResourceSha256,'D12_CANONICAL_GUARD_MISMATCH');
      fail(profile.runtimeKind==='maxroll-ui-cdp-v1' && typeof profile.nativeRuntime?.plannerId==='string' && profile.nativeRuntime.profileUrl===`https://planners.maxroll.gg/profiles/load/d4/${profile.nativeRuntime.plannerId}`,'NATIVE_PROFILE_IDENTITY_INVALID');
    },
    async createFactory({profile,entry,storeRoot}){
      const catalog=await loadMaxrollEntityCatalog({snapshotRoot:storeRoot,snapshotId:entry.snapshotId,expectedManifestSha256:entry.snapshotManifestSha256});
      return new UniversalMaxrollComponentFactory({codec:new MaxrollD12CanonicalCodec({catalog}),plannerId:profile.nativeRuntime.plannerId,profileUrl:profile.nativeRuntime.profileUrl});
    },
  }),
});
module.exports={STRATEGIES,RULEKIT_VERSION:'rulekit-snapshot-management/1.0.0'};
