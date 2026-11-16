'use strict';
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const {FIXTURE,withDecryptedFixture,digestFile}=require('../providers/maxroll/src/encrypted-fixture');
const RELEASE='https://github.com/Synclab-VN-dev/StreamOps/releases/tag/test-fixture/enc-e2e-20261023-r01';
function validate(config) {
 if(!config || Object.keys(config).some(k=>!['snapshot','manifestSha256','families','ageRecipient'].includes(k)) ||
 ![FIXTURE.snapshotId,RELEASE].includes(config.snapshot) || config.manifestSha256!==FIXTURE.manifestSha256 ||
 (config.ageRecipient!==undefined && config.ageRecipient!==FIXTURE.recipient) || (config.families!==undefined && (!Array.isArray(config.families)||!config.families.length))) throw Error('CONFIG_INVALID');
 return config;
}
async function main(configFile,output) {
 const config=validate(JSON.parse(fs.readFileSync(configFile,'utf8')));
 const age=process.env.AGE_BIN;
 if(!age || !process.env.AGE_IDENTITY_SECRET) throw Error('KEY_OR_AGE_MISSING');
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'catalog-ci-'));
 const run=(cmd,args)=>execFileSync(cmd,args,{stdio:'pipe',timeout:120000});
 try {
  const identity=path.join(temp,'identity');fs.writeFileSync(identity,process.env.AGE_IDENTITY_SECRET,{mode:0o600});
  run('gh',['release','download','test-fixture/enc-e2e-20261023-r01','--repo','Synclab-VN-dev/StreamOps','--dir',temp,'--pattern',FIXTURE.assetName,'--pattern',FIXTURE.checksumName]);
  await withDecryptedFixture({encrypted:path.join(temp,FIXTURE.assetName),checksum:path.join(temp,FIXTURE.checksumName),ageBin:age,identity},async source=>{
   const cli=path.resolve(__dirname,'../providers/maxroll/scripts/catalog-export.js');
   const args=['--snapshot-root',source.rootDir,'--snapshot-id',source.snapshotId,'--manifest-sha256',config.manifestSha256];
   if(config.families) args.push('--families',config.families.join(','));
   const file=path.join(temp,'catalog.json');
   const result=JSON.parse(run(process.execPath,[cli,...args,'--output',file]));
   const second=path.join(temp,'second.json');run(process.execPath,[cli,...args,'--output',second]);
   const inventory=JSON.parse(run(process.execPath,[cli,...args,'--list-families']));
   if(digestFile(file)!==digestFile(second)||JSON.stringify(inventory.families)!==JSON.stringify(result.familyCounts))throw Error('EXPORT_VERIFICATION_FAILED');
   let refused=false;try{run(process.execPath,[cli,...args,'--output',file]);}catch{refused=true;}if(!refused)throw Error('OVERWRITE_ACCEPTED');
   fs.mkdirSync(output,{recursive:true,mode:0o700});
   fs.copyFileSync(file,path.join(output,'catalog.json'),fs.constants.COPYFILE_EXCL);
   const report={schemaVersion:'rulekit-catalog-ci/v1',status:'PASS',sourceCommit:process.env.GITHUB_SHA??null,snapshotId:source.snapshotId,manifestSha256:config.manifestSha256,...result,outputEncoding:'plain-json',checks:{deterministic:true,inventory:true,overwriteRefused:true}};
   fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2)+'\n');
  });
 } finally {fs.rmSync(temp,{recursive:true,force:true});}
}
if(require.main===module)main(process.argv[2],process.argv[3]).catch(()=>{process.stderr.write('CATALOG_CI_FAILED\n');process.exitCode=1;});
module.exports={validate,RELEASE};
