// Synthetic local lifecycle fixtures only. Never represent native UI acceptance.
'use strict';
const fs=require('node:fs/promises'),path=require('node:path');
const {FileSystemSnapshotStore,sha256}=require('../../../../browser-infra/src/snapshot/store');
(async()=>{
 const root=process.argv[2],store=new FileSystemSnapshotStore({rootDir:root}),configs=[];
 for(const id of ['fixture-a','fixture-b','fixture-c']){
  const resources=['engine','data','locale'].map(name=>({key:'GET https://maxroll.gg/'+name,method:'GET',url:'https://maxroll.gg/'+name,status:200,headers:{'content-type':'text/html'},body:Buffer.from('<html><head></head><body>SYNTHETIC '+id+'</body></html>')}));
  await store.save({schemaVersion:'web-snapshot-draft/v1',snapshotId:id,sourceUrl:'https://maxroll.gg/engine',capturedAt:'2026-01-01T00:00:00Z',allowedOrigins:['https://maxroll.gg'],site:'maxroll-d4-planner-ui',version:'SYNTHETIC',playwrightVersion:'test',resources});
  const v=await store.verify(id),m=await store.load(id);
  const receipt={schemaVersion:'maxroll-ui-coverage/v1',status:'CAPTURED_UNVALIDATED',authorizationRef:'SYNTHETIC_TEST_ONLY',calculationStatus:'NOT_ASSESSED',integrity:v,version:m.version,startedAt:m.capturedAt,finishedAt:m.capturedAt,fingerprints:Object.fromEntries(m.resources.map(r=>[r.url,r.sha256]))};
  const bytes=JSON.stringify(receipt);await fs.writeFile(path.join(root,id,'ui-coverage.json'),bytes);
  const config={snapshotRoot:root,snapshotId:id,manifestSha256:v.manifestSha256,uiTrust:{schemaVersion:'maxroll-ui-trust/v1',coverageSha256:sha256(bytes),authorizationRef:receipt.authorizationRef}};
  const validation=JSON.stringify({schemaVersion:'maxroll-ui-validation/v1',status:'AUTOMATED_VALIDATED',snapshotId:id,manifestSha256:v.manifestSha256,coverageSha256:sha256(bytes),calculationStatus:'NOT_ASSESSED'});
  await fs.writeFile(path.join(root,id,'ui-validation.json'),validation);config.uiTrust.validationSha256=sha256(validation);configs.push(config);
 }console.log(JSON.stringify(configs));
})().catch(e=>{console.error(e);process.exitCode=1;});
