'use strict';
const runtimeLog = require('../../d4-rulekit/runtime-logging/src/logger');
const fs=require('node:fs/promises');
const path=require('node:path');
const {D4RuleKitApplication}=require('../../d4-rulekit/application/src');
const {BrowserInfrastructure,WebSnapshotManager,FileSystemSnapshotStore}=require('../../d4-rulekit/browser-infra/src');
const {MaxrollProvider}=require('../../d4-rulekit/providers/maxroll/src/provider');
const {MaxrollPatchProfile}=require('../../d4-rulekit/providers/maxroll/src/patch-profile');
const {createProductionManager}=require('../../d4-rulekit/snapshot-management/src');
const {SnapshotError}=require('../../d4-rulekit/snapshot-management/src/trust');
async function createManagedComposition(env){
 const dataRoot=env.D4_RULEKIT_DATA_ROOT;
 if(!path.isAbsolute(dataRoot??'')||!path.isAbsolute(env.D4_RULEKIT_INSTALLATION_ROOT??''))throw new Error('Rule Kit absolute data/installation paths required');
 const manager=createProductionManager({dataRoot,installationRoot:env.D4_RULEKIT_INSTALLATION_ROOT,workerGeneration:Number(env.D4_RULEKIT_WORKER_GENERATION)||1});
 let browser;
 try {
  await manager.start();
  browser=new BrowserInfrastructure({logger:runtimeLog.browserEvent,executablePath:env.D4_RULEKIT_CHROMIUM_EXECUTABLE||undefined,headless:true,maxContexts:Number(env.D4_RULEKIT_MAX_CONTEXTS)||2,maxQueue:Number(env.D4_RULEKIT_BROWSER_MAX_QUEUE)||16,contextOptions:{serviceWorkers:'block'}});
  await browser.start();
  const active=await manager.getActive();let provider;
  if(active.active){
   const entry=manager.registry.resolve(active.active.entryId);
   const bytes=await fs.readFile(path.join(dataRoot,'profiles',entry.snapshotId+'-'+entry.profileSha256+'.json'),'utf8');
   const profile=new MaxrollPatchProfile(JSON.parse(bytes));
   const snapshots=new WebSnapshotManager({browser,store:new FileSystemSnapshotStore({rootDir:manager.storeRoot})});
   const strategy=manager.resolver.strategies[entry.strategyId];
   provider=new MaxrollProvider({browser,snapshots,profile,componentFactory:strategy.createFactory?await strategy.createFactory({profile,entry,storeRoot:manager.storeRoot}):strategy.factory});
  }else{
   provider={id:'maxroll',version:'maxroll-provider/unconfigured',available:false,
    getCapabilities:()=>({version:'maxroll-unavailable/v1',stateModel:'stateful',metricIds:[],changeTypes:[]}),
    createSession:async()=>{throw new SnapshotError('PROVIDER_UNAVAILABLE');}};
  }
  const application=new D4RuleKitApplication({providers:[provider],maxSessions:Number(env.D4_RULEKIT_MAX_SESSIONS)||8,sessionTtlMs:Number(env.D4_RULEKIT_SESSION_TTL_MS)||1800000,operationTimeoutMs:Number(env.D4_RULEKIT_OPERATION_TIMEOUT_MS)||15000,cleanupTimeoutMs:Number(env.D4_RULEKIT_CLEANUP_TIMEOUT_MS)||5000});
  return {application,snapshotManagement:manager,calculationAvailability:active.calculationAvailability,calculationReason:active.reason,
   close:async()=>{try{await browser.stop();}finally{await manager.close();}}};
 }catch(error){await browser?.stop().catch(()=>{});await manager.close();throw error;}
}
module.exports={createManagedComposition};
