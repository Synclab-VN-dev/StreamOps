'use strict';
const crypto=require('node:crypto');
function check(value,code){if(!value){const error=new Error(code);error.code=code;throw error;}}
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
function canonical(value){if(value===null||typeof value!=='object')return JSON.stringify(value);if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';}
function deepFreeze(value){if(value&&typeof value==='object'&&!Object.isFrozen(value)){Object.values(value).forEach(deepFreeze);Object.freeze(value);}return value;}
function validateDefinition(value){
 check(value?.contractVersion==='compatibility-definition/v1','DEFINITION_CONTRACT_INVALID');
 check(/^[a-zA-Z0-9._-]+$/.test(value.definitionId),'DEFINITION_ID_INVALID');
 for(const key of ['snapshotManifestSha256','engineAssetSha256','catalogResourceSha256'])check(/^[a-f0-9]{64}$/.test(value.identity?.[key]),'DEFINITION_BINDING_INVALID');
 check(typeof value.identity.snapshotId==='string'&&typeof value.codecVersion==='string','DEFINITION_BINDING_INVALID');
 check(Array.isArray(value.bindings)&&value.bindings.length>0,'DEFINITION_BINDINGS_EMPTY');
 for(const b of value.bindings)check(/^[a-zA-Z0-9._-]+$/.test(b.id)&&['ui-cdp/v1','native-state/v1'].includes(b.family)&&typeof b.providerVersion==='string'&&typeof b.schema==='string','DEFINITION_FAMILY_INVALID');
 check(['REAL_PROVIDER','SYNTHETIC_TEST_ONLY'].includes(value.evidenceClass),'DEFINITION_EVIDENCE_INVALID');
 check(value.reference&&value.candidateStrategy&&value.sharedOptions&&value.optionRules&&typeof value.runtimeDefaults==='function','DEFINITION_CONFIGURATION_MISSING');
 check(value.reference.applicationAssetSha256===value.identity.engineAssetSha256&&value.reference.gamePatch===value.identity.gamePatch,'DEFINITION_REFERENCE_MISMATCH');
 return deepFreeze(value);
}
module.exports={check,hash,canonical,deepFreeze,validateDefinition};
