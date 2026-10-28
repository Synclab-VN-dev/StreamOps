'use strict';
const {fail,canonical}=require('./trust');
const {loadCatalog}=require('../compatibility/loader');
const catalog=loadCatalog(); // Verify all execution bytes before requiring shared factories.
const {MaxrollPatchProfile}=require('../../providers/maxroll/src/patch-profile');
const {createCodecFamily}=require('../../providers/maxroll/src/canonical-codec-core');
const {createProfileFamily,REAL_MAXROLL_COMPONENT_FACTORY}=require('../../providers/maxroll/src/real-profile-core');
const {UniversalMaxrollComponentFactory}=require('../../providers/maxroll/src/universal-component-factory');
function validateCapabilities(profile,entry){
 const caps=new MaxrollPatchProfile(profile).capability();
 for(const field of ['metricIds','changeTypes'])fail(JSON.stringify([...caps[field]].sort())===JSON.stringify([...entry.capabilities[field]].sort()),'CAPABILITIES_BINDING_MISMATCH:'+field);
 fail(caps.stateModel===entry.capabilities.stateModel,'CAPABILITIES_BINDING_MISMATCH:stateModel');
}
function createStrategies(catalog){
 const strategies={};
 for(const definition of catalog.definitions){
  const codec=createCodecFamily(definition),profiles=createProfileFamily(definition);
  for(const binding of definition.bindings){
   const native=binding.family==='native-state/v1';
   strategies[binding.id]=Object.freeze({
    executionVersion:catalog.ruleKitVersion,evidenceClass:definition.evidenceClass,
    codecVersions:[definition.codecVersion],canonicalSchemas:[binding.schema],providerVersions:[binding.providerVersion],
    validateProfile(profile,entry){
     validateCapabilities(profile,entry);
     const expected=definition.identity;
     fail(entry.ruleKitVersion===catalog.ruleKitVersion,'IMPLEMENTATION_APPROVAL_MISMATCH');
     fail(profile.runtimeKind==='maxroll-ui-cdp-v1','PROFILE_RUNTIME_KIND_INCOMPATIBLE');
     fail(entry.gamePatch===expected.gamePatch&&entry.engineAsset.sha256===expected.engineAssetSha256&&entry.catalog.sha256===expected.catalogResourceSha256,binding.guardCode??'RUNTIME_BINDING_MISMATCH');
     fail(entry.snapshotId===expected.snapshotId&&entry.snapshotManifestSha256===expected.snapshotManifestSha256,'SNAPSHOT_DEFINITION_MISMATCH');
     fail(entry.engineAsset.url===`https://maxroll.gg${definition.reference.applicationAssetPath}`,'ENGINE_URL_BINDING_MISMATCH');
     if(native)fail(typeof profile.nativeRuntime?.plannerId==='string'&&profile.nativeRuntime.profileUrl===`https://planners.maxroll.gg/profiles/load/d4/${profile.nativeRuntime.plannerId}`,'NATIVE_PROFILE_IDENTITY_INVALID');
     // A signed JSON profile does not override execution-bearing bundled code.
     const expectedProfile=(native?profiles.createUniversalProfile:profiles.createCandidateProfile)({...profile,realRuntime:undefined});
     for(const key of Object.keys(profile.realRuntime??{}))fail(Object.hasOwn(expectedProfile.realRuntime,key),'EXECUTION_PROFILE_FIELD_UNKNOWN:'+key);
     for(const [key,value] of Object.entries(expectedProfile.realRuntime)){
      // Catalog-derived option enumeration is verified against actual bytes in createFactory.
      if(key==='optionReadbackDefinitions')continue;
      fail(canonical(profile.realRuntime?.[key])===canonical(value),'EXECUTION_PROFILE_MISMATCH:'+key);
     }
    },
    factory:native?undefined:REAL_MAXROLL_COMPONENT_FACTORY,
    async createFactory({profile,entry,storeRoot}){
     this.validateProfile(profile,entry);
     if(!native)return REAL_MAXROLL_COMPONENT_FACTORY;
     const entityCatalog=await codec.loadMaxrollEntityCatalog({snapshotRoot:storeRoot,snapshotId:entry.snapshotId,expectedManifestSha256:entry.snapshotManifestSha256});
     const expectedProfile=profiles.createUniversalProfile({...profile,catalog:entityCatalog,realRuntime:undefined});
     fail(canonical(profile.realRuntime.optionReadbackDefinitions)===canonical(expectedProfile.realRuntime.optionReadbackDefinitions),'EXECUTION_OPTIONS_MISMATCH');
     return new UniversalMaxrollComponentFactory({codec:new codec.BoundCanonicalCodec({catalog:entityCatalog}),plannerId:profile.nativeRuntime.plannerId,profileUrl:profile.nativeRuntime.profileUrl});
    },
   });
  }
 }
 return Object.freeze(strategies);
}
module.exports={createStrategies,STRATEGIES:createStrategies(catalog),RULEKIT_VERSION:catalog.ruleKitVersion};
