'use strict';
// Test-only independent oracle: original recorded response → source runtime.
// Never instantiates a canonical codec or calls Provider and never opens online capture.
const fs=require('node:fs/promises');
const path=require('node:path');
const assert=require('node:assert/strict');
const {loadCatalog}=require('../../compatibility/loader');
const {createProfileFamily}=require('../../../providers/maxroll/src/real-profile-core');
const {createCodecFamily}=require('../../../providers/maxroll/src/canonical-codec-core');
const {exportMaxrollBuildFromSnapshot,listMaxrollBuildProfilesFromSnapshot}=require('../../../providers/maxroll/src/build-export');
const {verifiedSnapshot,runCapture,validateCaptureEvidence}=require('../../../providers/maxroll/src/fixture-attestation');
const {METRIC_CATALOG}=require('../../../providers/maxroll/src/metric-catalog');
const {FileSystemSnapshotStore}=require('../../../browser-infra/src');
(async()=>{
 const definition=loadCatalog().definitions.find(d=>d.definitionId===process.env.COMPATIBILITY_TEST_DEFINITION);assert.ok(definition);
 const identity=definition.identity,root=process.env.MAXROLL_AUTHORIZED_SNAPSHOT_ROOT,output=process.env.MAXROLL_B0_FIXTURE_ROOT;
 assert.ok(root&&output&&process.env.BROWSER_INFRA_CHROMIUM_PATH);
 const store=new FileSystemSnapshotStore({rootDir:root});const manifest=await store.load(identity.snapshotId);
 const options={snapshotRoot:root,snapshotId:identity.snapshotId,expectedManifestSha256:identity.snapshotManifestSha256,url:manifest.sourceUrl,sourceUrl:manifest.sourceUrl,assetUrl:`https://maxroll.gg${definition.reference.applicationAssetPath}`,assetSha256:identity.engineAssetSha256,chromiumExecutablePath:process.env.BROWSER_INFRA_CHROMIUM_PATH};
 const inventory=await listMaxrollBuildProfilesFromSnapshot(options);
 const visible=inventory.profiles.filter(row=>!row.hidden);assert.ok(visible.length>=2);
 // Catalog parser only supplies option authority, not a canonical codec/oracle output.
 const catalog=await createCodecFamily(definition).loadMaxrollEntityCatalog(options);
 const profile=createProfileFamily(definition).createUniversalProfile({snapshotId:identity.snapshotId,snapshotManifestSha256:identity.snapshotManifestSha256,sourceUrl:manifest.sourceUrl,catalog,metricCatalog:METRIC_CATALOG,authorizationRef:'ISOLATED_OFFLINE_SOURCE_OBSERVATION'});
 const snapshot=await verifiedSnapshot(options);
 const report={classification:'INDEPENDENT_OFFLINE_SOURCE_ORACLE',snapshotId:identity.snapshotId,manifestSha256:identity.snapshotManifestSha256,engineSha256:identity.engineAssetSha256,fixtures:[]};
 await fs.mkdir(output,{recursive:true,mode:0o700});
 for(const [i,name] of ['rogue-midgame','rogue-endgame'].entries()){
  const outputPath=path.join(output,name+'.json');
  const exported=await exportMaxrollBuildFromSnapshot({...options,profile:visible[i].index,outputPath});
  const fixture=JSON.parse(await fs.readFile(outputPath));assert.equal(fixture.nativeState.profiles[fixture.selection.profileIndex].class,3);
  const observed=await runCapture({options,fixture,snapshot,profile,mode:'source'});validateCaptureEvidence(observed);
  await fs.writeFile(path.join(output,name+'.stats.json'),JSON.stringify(observed,null,2)+'\n',{flag:'wx',mode:0o600});
  report.fixtures.push({name,index:visible[i].index,exportSha256:exported.sha256,rawMetricCount:observed.rawMetrics.length,cleanup:observed.cleanup,network:observed.network,mode:'source-no-response-override'});
 }
 await fs.writeFile(path.join(output,'oracle-provenance.json'),JSON.stringify(report,null,2)+'\n',{flag:'wx',mode:0o600});
 console.log(JSON.stringify({status:'PASS',fixtures:report.fixtures.length,metrics:report.fixtures.map(f=>f.rawMetricCount)}));
})().catch(e=>{console.error(e.code??e.name,e.message);process.exitCode=1;});
