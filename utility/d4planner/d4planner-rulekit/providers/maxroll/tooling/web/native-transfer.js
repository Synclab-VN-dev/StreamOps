'use strict';
const {createHash}=require('node:crypto');
const {createNativeBuildExport,validateNativeState,parsePlannerUrl,serialize,EXPORT_SCHEMA_VERSION}=require('../../src/build-export');
const digest=value=>createHash('sha256').update(serialize(value)).digest('hex');
const MAX_BYTES=8*1024*1024;
function validate(state){
  validateNativeState(state);
  if(!state.profiles[state.activeProfile])throw Error('Invalid active profile');
}
function exportBuild(payload,snapshot,config){
  if(!payload||typeof payload.data!=='string')throw Error('Native Save payload required');
  const state=JSON.parse(payload.data);validate(state);
  // Save request metadata is not build state. Never export auth/account fields.
  const response=Object.fromEntries(['name','class','season','game'].filter(k=>Object.hasOwn(payload,k)).map(k=>[k,payload[k]]));
  return createNativeBuildExport({response,state,parsedUrl:parsePlannerUrl(snapshot.manifest.sourceUrl),provenance:{
    source:'LOCAL_UI_NATIVE_SAVE',snapshotId:snapshot.manifest.snapshotId,
    snapshotManifestSha256:config.manifestSha256,runtimeVersion:snapshot.manifest.version,
    calculationStatus:'NOT_ASSESSED',canonicalConversion:{status:'UNSUPPORTED',code:'CANONICAL_EXPORT_UNSUPPORTED',reason:'Canonical export is unavailable in local UI tooling. No native fields or empty sockets are removed.'}
  }});
}
function importBuild(envelope,snapshot,config){
  if(envelope?.schemaVersion!==EXPORT_SCHEMA_VERSION||envelope.format!=='MAXROLL_NATIVE_STATE')throw Error('Native export envelope required');
  if(envelope.provenance?.snapshotId!==snapshot.manifest.snapshotId||envelope.provenance?.snapshotManifestSha256!==config.manifestSha256)throw Error('Native import snapshot mismatch');
  validate(envelope.nativeState);
  if(envelope.integrity?.algorithm!=='sha256'||digest(envelope.nativeState)!==envelope.integrity.nativeStateSha256)throw Error('Native state integrity mismatch');
  const id=parsePlannerUrl(snapshot.manifest.sourceUrl).plannerId;
  const resource=snapshot.resources.get('GET https://planners.maxroll.gg/profiles/load/d4/'+id);
  if(!resource)throw Error('Native profile loader response missing');
  const original=JSON.parse(resource.body.toString('utf8'));
  // Reuse captured loader identity. This is a tab-local import, never a saved cloud profile.
  return {...original,...Object.fromEntries(['name','class','season'].filter(k=>Object.hasOwn(envelope.loaderMetadata||{},k)).map(k=>[k,envelope.loaderMetadata[k]])),data:JSON.stringify(envelope.nativeState)};
}
async function readJson(req){
  if(!/^application\/json(?:;|$)/i.test(req.headers['content-type']||''))throw Error('JSON required');
  const chunks=[];let bytes=0;
  for await(const chunk of req){bytes+=chunk.length;if(bytes>MAX_BYTES)throw Error('Build exceeds size limit');chunks.push(chunk);}
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}
module.exports={exportBuild,importBuild,readJson,MAX_BYTES};
