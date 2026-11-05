'use strict';
// Synthetic native stores exercise verification, not real-provider approval.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const {FileSystemSnapshotStore} = require('../../browser-infra/src/snapshot/store');
const {identity} = require('../../providers/maxroll/tooling/capture-workflow');
const {verify} = require('../release/verify');
const sha = b => crypto.createHash('sha256').update(b).digest('hex');
async function json(file,value) {const bytes=JSON.stringify(value);await fs.writeFile(file,bytes);return bytes;}

test('new native pair verifies without any Registry/profile and preserves NOT_ASSESSED', async () => {
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'release-native-store-'));
  try {
    const store=new FileSystemSnapshotStore({rootDir:root});
    const packages=[];
    for(const kind of ['calculation','ui']) {
      const snapshotId='fresh-'+kind;
      const resources=['assets/export-new.js','game/data.min.json','game/data.enus.json'].map(name=>({
        key:'GET https://maxroll.gg/'+name,method:'GET',url:'https://maxroll.gg/'+name,status:200,
        headers:{'content-type':'application/json'},body:Buffer.from('{}')}));
      await store.save({schemaVersion:'web-snapshot-draft/v1',snapshotId,sourceUrl:'https://maxroll.gg/d4/planner/test',
        capturedAt:'2026-11-05T00:00:00Z',allowedOrigins:['https://maxroll.gg'],
        site:kind==='ui'?'maxroll-d4-planner-ui':'maxroll-d4-planner',version:'NEW_RUNTIME',playwrightVersion:'test',resources});
      const actual=await identity(root,snapshotId);
      packages.push({kind,snapshotId,snapshotRoot:root,manifestSha256:actual.integrity.manifestSha256,
        identity:actual.identity,runId:'new-run',validationStatus:kind==='ui'?'VALIDATED':'CAPTURED_UNVALIDATED',compatibility:'PATCH_DRIFT'});
    }
    const ui=packages[1];
    const uiAcceptance=path.join(root,'acceptance.json');
    const acceptance=await json(uiAcceptance,{status:'AUTOMATED_PASS',scope:'ui',head:'a'.repeat(40),
      snapshotId:ui.snapshotId,manifestSha256:ui.manifestSha256});
    const coverage=await json(path.join(root,ui.snapshotId,'ui-coverage.json'),{
      schemaVersion:'maxroll-ui-coverage/v1',status:'CAPTURED_UNVALIDATED',authorizationRef:'test-authorization',
      calculationStatus:'NOT_ASSESSED',integrity:await store.verify(ui.snapshotId),version:'NEW_RUNTIME',
      startedAt:'2026-11-05T00:00:00Z',finishedAt:'2026-11-05T00:01:00Z',fingerprints:ui.identity.fingerprints});
    const receipt={schemaVersion:'maxroll-ui-validation/v1',status:'AUTOMATED_VALIDATED',snapshotId:ui.snapshotId,
      manifestSha256:ui.manifestSha256,coverageSha256:sha(coverage),calculationStatus:'NOT_ASSESSED',
      captureRunId:'new-run',head:'a'.repeat(40),acceptanceSha256:sha(acceptance)};
    const receiptFile=path.join(root,ui.snapshotId,'ui-validation.json');await json(receiptFile,receipt);
    // Python rewrites reports with sorted object keys after extraction. JSON key order
    // must not change the result of comparing the same exact resource fingerprints.
    for(const item of packages) item.identity={fingerprints:Object.fromEntries(
      Object.entries(item.identity.fingerprints).reverse()),version:item.identity.version};
    const report=path.join(root,'report.json');await json(report,{status:'COMPLETE',mode:'all',consistency:'PASS',runId:'new-run',packages});
    const config={report,uiAcceptance,source:'a'.repeat(40),authorizationRef:'test-authorization'};
    const result=await verify(config);
    assert.equal(result.calculationIntegrity,'VERIFIED');
    assert.equal(result.calculationReferenceStatus,'PATCH_DRIFT');
    assert.equal(result.ruleKitReadiness,'NOT_ASSESSED');
    assert.equal(result.uiValidation,'AUTOMATED_VALIDATED');
    await json(receiptFile,{...receipt,captureRunId:'other-run'});
    await assert.rejects(verify(config),error=>error.code==='BLOCKED_UI_PROVENANCE');
    await json(receiptFile,receipt);
    const manifest=await store.load(packages[0].snapshotId);
    await fs.writeFile(path.join(root,packages[0].snapshotId,manifest.resources[0].blob),'corrupt');
    await assert.rejects(verify(config));
  } finally {await fs.rm(root,{recursive:true,force:true});}
});
