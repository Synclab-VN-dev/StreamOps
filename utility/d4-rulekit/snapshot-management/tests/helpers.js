'use strict';
const crypto=require('node:crypto');
const fs=require('node:fs/promises');
const path=require('node:path');
const {FileSystemSnapshotStore}=require('../../browser-infra/src/snapshot/store');
const {TrustedRegistry,digest,canonical}=require('../src/trust');
const {inventory}=require('../src/manager');
async function createPackage(root,id='SYNTHETIC-A') {
  const directory=path.join(root,id+'-package');await fs.mkdir(directory,{recursive:true});
  const sourceUrl='https://synthetic.invalid/'+id;
  const engineUrl=sourceUrl+'/engine.js',catalogUrl=sourceUrl+'/catalog.json';
  const engine=Buffer.from('SYNTHETIC ENGINE '+id),catalog=Buffer.from('{"synthetic":true,"id":"'+id+'"}');
  const store=new FileSystemSnapshotStore({rootDir:path.join(directory,'snapshot')});
  await store.save({schemaVersion:'web-snapshot-draft/v1',snapshotId:id,sourceUrl,capturedAt:'2026-10-27T00:00:00Z',allowedOrigins:['https://synthetic.invalid'],site:'SYNTHETIC_TEST_ONLY',version:'test/v1',browserVersion:'test-browser',playwrightVersion:'1.64.1',resources:[{key:'GET '+engineUrl,method:'GET',url:engineUrl,status:200,headers:{'content-type':'application/javascript'},body:engine},{key:'GET '+catalogUrl,method:'GET',url:catalogUrl,status:200,headers:{'content-type':'application/json'},body:catalog}]});
  const verified=await store.verify(id);
  const profile={runtimeKind:'SYNTHETIC_TEST_ONLY',providerVersion:'1.0.0',snapshotId:id,snapshotManifestSha256:verified.manifestSha256,gamePatch:'SYNTHETIC-PATCH',sourceUrl,assetUrl:engineUrl,assetSha256:digest(engine),supportedBuildSchemaVersion:'synthetic-build/v1'};
  const bytes=Buffer.from(JSON.stringify(profile));await fs.writeFile(path.join(directory,'profile.json'),bytes);
  const entry={entryId:id,status:'APPROVED',ruleKitVersion:'test-rulekit/v1',providerId:'test.synthetic',providerVersion:profile.providerVersion,codecVersion:'SYNTHETIC-codec/v1',canonicalSchemaVersion:profile.supportedBuildSchemaVersion,strategyId:'SYNTHETIC-STRATEGY',profileId:id+'-profile',profileSha256:digest(bytes),snapshotId:id,snapshotManifestSha256:verified.manifestSha256,gamePatch:profile.gamePatch,sourceUrl,engineAsset:{url:engineUrl,sha256:digest(engine)},catalog:{url:catalogUrl,sha256:digest(catalog)},capabilities:{stateModel:'stateful',changeTypes:['equipment.replace'],metricIds:['equipment-count']},approval:{reference:'TEST_ONLY_UNSIGNED_DISTRIBUTION_NOT_AUTHORIZED',evidenceSha256:digest(Buffer.from(id)),testClass:'SYNTHETIC_TEST_ONLY'},distribution:{permission:'PRIVATE_ONLY',reference:'TEST_ONLY'}};
  const files=[];for(const file of await inventory(directory)){const content=await fs.readFile(path.join(directory,file));files.push({path:file,bytes:content.length,sha256:digest(content)});}
  await fs.writeFile(path.join(directory,'snapshot-package.json'),JSON.stringify({schemaVersion:'d4-rulekit-snapshot-package/v1',packageVersion:'TEST_ONLY/v1',entryId:id,snapshotId:id,snapshotManifestSha256:verified.manifestSha256,profileSha256:digest(bytes),files}));
  return {directory,entry,profile};
}
function trust(entries,scope='ISOLATED_TEST') {
  const pair=crypto.generateKeyPairSync('ed25519');
  const publicKey=pair.publicKey.export({type:'spki',format:'pem'});
  const registry=new TrustedRegistry({anchors:{TEST_ONLY:{publicKey,minimumRegistryRevision:1}},ruleKitVersion:'test-rulekit/v1',scope});
  const payload={schemaVersion:'d4-rulekit-compatibility-registry/v1',revision:1,issuedAt:'2026-01-01T00:00:00Z',expiresAt:'2035-01-01T00:00:00Z',entries,revokedEntryIds:[],revokedKeyIds:[]};
  const sign=value=>({schemaVersion:'d4-rulekit-registry-envelope/v1',keyId:'TEST_ONLY',payload:value,signature:crypto.sign(null,Buffer.from(canonical(value)),pair.privateKey).toString('base64')});
  const envelope=sign(payload);
  return {registry,envelope,sign,payload,publicKey};
}
const strategies={'SYNTHETIC-STRATEGY':{evidenceClass:'SYNTHETIC_TEST_ONLY',codecVersions:['SYNTHETIC-codec/v1'],canonicalSchemas:['synthetic-build/v1'],providerVersions:['1.0.0'],validateProfile(profile){if(profile.runtimeKind!=='SYNTHETIC_TEST_ONLY')throw new Error('Invalid test profile');}}};
module.exports={createPackage,trust,strategies};
