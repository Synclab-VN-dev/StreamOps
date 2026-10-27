#!/usr/bin/env node
'use strict';
// Local Rule Kit-owned provisioning/upgrade entrypoint. No network, keys,
// registry or resolver is delegated to the launcher/Backend.
const fs=require('node:fs/promises');
const path=require('node:path');
const {createProductionManager,upgradePreflight,METHODS}=require('./src');
async function main(){
 const args=process.argv.slice(2),values={};
 for(let i=0;i<args.length;i+=2){if(!args[i]?.startsWith('--')||args[i+1]===undefined)throw new Error('CLI_INPUT_INVALID');values[args[i].slice(2)]=args[i+1];}
 if(!path.isAbsolute(values['data-root']??'')||!path.isAbsolute(values['installation-root']??''))throw new Error('ABSOLUTE_CONFIG_PATHS_REQUIRED');
 let manager,result;
 try {
  if(values.operation==='upgradePreflight')result=await upgradePreflight({dataRoot:values['data-root'],installationRoot:values['installation-root'],previousInstallationRoot:values['previous-installation-root']});
  else {
   if(!METHODS.includes(values.operation))throw new Error('SNAPSHOT_METHOD_UNKNOWN');
   manager=createProductionManager({dataRoot:values['data-root'],installationRoot:values['installation-root'],workerGeneration:1});await manager.start();
   let params={};if(values['request-file'])params=JSON.parse(await fs.readFile(values['request-file'],'utf8'));
   result=await manager.invoke(values.operation,params);
  }
  const report={ok:true,protocolVersion:'d4-rulekit-snapshots/v1',result};
  if(values.report)await fs.writeFile(values.report,JSON.stringify(report));else process.stdout.write(JSON.stringify(report)+'\n');
 } finally {await manager?.close();}
}
main().catch(async error=>{
 const report={ok:false,protocolVersion:'d4-rulekit-snapshots/v1',error:{code:error.code??error.message??'SNAPSHOT_OPERATION_FAILED'}};
 const index=process.argv.indexOf('--report');if(index>=0)await fs.writeFile(process.argv[index+1],JSON.stringify(report)).catch(()=>{});
 process.stderr.write(JSON.stringify(report)+'\n');process.exitCode=1;
});
