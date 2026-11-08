'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const os=require('node:os');
const path=require('node:path');
const {sha256}=require('../../../../browser-infra/src/snapshot/store');
const {verifyUiReceipt}=require('./ui-package');
const {dependencies}=require('./capture-ui');
test('dependency inventory resolves CSS import/background/border URLs without off-origin crawl',()=>{
  assert.deepEqual(dependencies('@import"theme.css"; .x{background:url(/a.webp);border-image:url(../b.png);mask:url(data:image/png;base64,AA)}', 'https://assets-ng.maxroll.gg/css/main.css'),[
    'https://assets-ng.maxroll.gg/a.webp','https://assets-ng.maxroll.gg/b.png','https://assets-ng.maxroll.gg/css/theme.css']);
});
test('UI provenance has independent exact trust pins and never asserts calculation support',async()=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'ui-trust-'));
  try{
    const id='ui-new-version';await fs.mkdir(path.join(root,id));
    const manifestHash='1'.repeat(64), resources=['engine','catalog','localization'].map(name=>({url:'https://maxroll.gg/'+name,sha256:sha256(name)}));
    const receipt={schemaVersion:'maxroll-ui-coverage/v1',status:'CAPTURED_UNVALIDATED',authorizationRef:'owner-test',calculationStatus:'NOT_ASSESSED',
      integrity:{manifestSha256:manifestHash},version:'UI-only-new-version',startedAt:'2026-11-02T00:00:00Z',finishedAt:'2026-11-02T00:01:00Z',fingerprints:Object.fromEntries(resources.map(r=>[r.url,r.sha256]))};
    const bytes=JSON.stringify(receipt);await fs.writeFile(path.join(root,id,'ui-coverage.json'),bytes);
    const config={snapshotRoot:root,snapshotId:id,manifestSha256:manifestHash,uiTrust:{schemaVersion:'maxroll-ui-trust/v1',coverageSha256:sha256(bytes),authorizationRef:'owner-test'}};
    const manifest={site:'maxroll-d4-planner-ui',version:receipt.version,resources,allowedOrigins:['https://maxroll.gg']};
    const verified={manifestSha256:manifestHash};
    // Legacy receipt/config remain readable, but the label is not a trust gate.
    const result=await verifyUiReceipt(config,manifest,verified);
    delete config.uiTrust.authorizationRef;
    assert.equal((await verifyUiReceipt(config,manifest,verified)).calculationStatus,'NOT_ASSESSED');
    assert.equal(result.calculationStatus,'NOT_ASSESSED');
    await assert.rejects(verifyUiReceipt({...config,uiTrust:{}},manifest,verified),/trust pins/);
    await assert.rejects(verifyUiReceipt({...config,manifestSha256:'0'.repeat(64)},manifest,verified),/manifest trust pin/);
    await assert.rejects(verifyUiReceipt(config,{...manifest,version:'other'},verified),/provenance/);
    await assert.rejects(verifyUiReceipt(config,{...manifest,resources:[]},verified),/fingerprint/);
    await assert.rejects(verifyUiReceipt(config,{...manifest,allowedOrigins:['https://untrusted.invalid']},verified),/origin/);
    await fs.appendFile(path.join(root,id,'ui-coverage.json'),' ');
    await assert.rejects(verifyUiReceipt(config,manifest,verified),/coverage trust pin/);
  }finally{await fs.rm(root,{recursive:true,force:true});}
});

test('real store UI package loads without calculation catalog; blob tampering fails closed',async()=>{
  const {FileSystemSnapshotStore}=require('../../../../browser-infra/src/snapshot/store');
  const {loadSnapshot}=require('./server');
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'independent-ui-'));
  try{
    const id='new-ui-not-in-calculation-catalog',store=new FileSystemSnapshotStore({rootDir:root});
    const resources=['engine','data','localization'].map(name=>({key:'GET https://maxroll.gg/'+name,method:'GET',url:'https://maxroll.gg/'+name,status:200,headers:{'content-type':'application/json'},body:Buffer.from('{}')}));
    await store.save({schemaVersion:'web-snapshot-draft/v1',snapshotId:id,sourceUrl:'https://maxroll.gg/engine',capturedAt:'2026-11-02T00:00:00Z',allowedOrigins:['https://maxroll.gg'],site:'maxroll-d4-planner-ui',version:'UI-only-new',playwrightVersion:'test',resources});
    const verified=await store.verify(id),manifest=await store.load(id);
    const receipt={schemaVersion:'maxroll-ui-coverage/v1',status:'CAPTURED_UNVALIDATED',calculationStatus:'NOT_ASSESSED',integrity:verified,version:manifest.version,startedAt:manifest.capturedAt,finishedAt:'2026-11-02T00:01:00Z',fingerprints:Object.fromEntries(manifest.resources.map(r=>[r.url,r.sha256]))};
    const bytes=JSON.stringify(receipt);await fs.writeFile(path.join(root,id,'ui-coverage.json'),bytes);
    const config={snapshotRoot:root,snapshotId:id,manifestSha256:verified.manifestSha256,uiTrust:{schemaVersion:'maxroll-ui-trust/v1',coverageSha256:sha256(bytes)}};
    const loaderPath=require.resolve('../../../../snapshot-management/compatibility/loader');
    const old=require.cache[loaderPath];
    require.cache[loaderPath]={exports:{loadCatalog(){throw Error('Calculation catalog must not be consulted');}}};
    try{const pkg=await loadSnapshot(config);assert.equal(pkg.uiVerification.calculationStatus,'NOT_ASSESSED');}
    finally{if(old)require.cache[loaderPath]=old;else delete require.cache[loaderPath];}
    const validation={schemaVersion:'maxroll-ui-validation/v1',status:'AUTOMATED_VALIDATED',snapshotId:id,manifestSha256:config.manifestSha256,coverageSha256:config.uiTrust.coverageSha256,calculationStatus:'NOT_ASSESSED'};
    const vb=JSON.stringify(validation);await fs.writeFile(path.join(root,id,'ui-validation.json'),vb);config.uiTrust.validationSha256=sha256(vb);
    assert.equal((await loadSnapshot(config)).uiVerification.status,'AUTOMATED_VALIDATED');
    await fs.appendFile(path.join(root,id,'ui-validation.json'),' ');
    await assert.rejects(loadSnapshot(config),/validation trust pin/);
    delete config.uiTrust.validationSha256;
    await fs.writeFile(path.join(root,id,manifest.resources[0].blob),'modified');
    await assert.rejects(loadSnapshot(config));
  }finally{await fs.rm(root,{recursive:true,force:true});}
});
