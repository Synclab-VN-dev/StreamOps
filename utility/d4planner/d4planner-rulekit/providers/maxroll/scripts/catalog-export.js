#!/usr/bin/env node
'use strict';
const { listMaxrollCatalogFamilies, exportMaxrollGameDataCatalog } = require('../src/catalog-export');
function parseArguments(args) {
 const options = {};
 const flags = {'--snapshot-root':'snapshotRoot','--snapshot-id':'snapshotId',
 '--manifest-sha256':'expectedManifestSha256','--output':'outputPath','--families':'families'};
 for(let i=0;i<args.length;i++) {
  if(args[i]==='--list-families') { if(options.listFamilies) throw Error('duplicate flag'); options.listFamilies=true; continue; }
  const key=flags[args[i]];
  if(!key || options[key]!==undefined || !args[i+1] || args[i+1].startsWith('--')) throw Error('invalid arguments');
  options[key]=key==='families'?args[++i].split(','):args[++i];
 }
 if(options.listFamilies && options.outputPath) throw Error('list does not accept output');
 return options;
}
async function main() {
 const options=parseArguments(process.argv.slice(2));
 const result=await (options.listFamilies?listMaxrollCatalogFamilies:exportMaxrollGameDataCatalog)(options);
 process.stdout.write(JSON.stringify(result,null,2)+'\n');
}
if(require.main===module) main().catch(error=>{
 // Error messages may contain filesystem paths or source content; print only a code.
 process.stderr.write((/^[A-Z_]+$/.test(error.code ?? '')?error.code:'CATALOG_EXPORT_FAILED')+'\n');
 process.exitCode=1;
});
module.exports={parseArguments};
