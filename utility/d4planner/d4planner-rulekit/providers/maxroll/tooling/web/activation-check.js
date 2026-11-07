#!/usr/bin/env node
'use strict';
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const {loadSnapshot}=require('./server');
async function main(){
  const config=JSON.parse(await fs.readFile(process.argv[3],'utf8'));
  if(process.argv[2]==='verify'){
    const snapshot=await loadSnapshot(config);
    assert.equal(snapshot.uiVerification.status,'AUTOMATED_VALIDATED','UI validation receipt required for activation');
    console.log(JSON.stringify({snapshotId:config.snapshotId,manifestSha256:config.manifestSha256,version:snapshot.manifest.version}));
  }else if(process.argv[2]==='health'){
    // Actual native UI downloads/imports on desktop and mobile, ordinary HTTP, no interception.
    await require('./export-check').run(config);
  }else throw Error('Unknown activation check');
}
if(require.main===module)main().catch(e=>{console.error(e.message);process.exitCode=1;});
