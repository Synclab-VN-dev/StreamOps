'use strict';
const path=require('node:path');
const fs=require('node:fs/promises');
const {TrustedRegistry,fail}=require('./trust');
const {SnapshotManager,PROTOCOL,METHODS}=require('./manager');
const {STRATEGIES,RULEKIT_VERSION}=require('./strategies');
const anchors=require('./production-trust-anchors.json');
function productionRegistry() {
  if(Object.keys(anchors.keys).length===0)return null;
  fail(anchors.policyStatus==='OWNER_ANCHOR_PROVISIONED','PRODUCTION_TRUST_ACTIVATION_BLOCKED');
  return new TrustedRegistry({anchors:anchors.keys,ruleKitVersion:RULEKIT_VERSION,scope:'PRODUCTION'});
}
function createProductionManager({dataRoot,installationRoot,workerGeneration}) {
  return new SnapshotManager({dataRoot,installationRoot,workerGeneration,registry:productionRegistry(),strategies:STRATEGIES});
}
/** Read-only upgrade preflight owned by Rule Kit. Packaging only passes paths
 * and checks this API result. It never resolves profiles/registry itself. */
async function upgradePreflight({dataRoot,installationRoot,previousInstallationRoot}) {
  const manager=createProductionManager({dataRoot,installationRoot,workerGeneration:1});
  if(previousInstallationRoot) {
    const previous=JSON.parse(await fs.readFile(path.join(previousInstallationRoot,'release-manifest.json'),'utf8'));
    if(previous.ruleKit?.snapshotId && !await manager.exists(path.join(dataRoot,'selection.json'))) {
      fail(false,'LEGACY_SNAPSHOT_MIGRATION_REQUIRED');
    }
  }
  const selected=await manager.selection();
  if(!selected)return {compatible:true,calculationAvailability:'UNAVAILABLE',reason:'SNAPSHOT_NOT_SELECTED',ruleKitVersion:RULEKIT_VERSION};
  fail(manager.registry,'TRUST_POLICY_NOT_CONFIGURED');
  const envelope=JSON.parse(await fs.readFile(path.join(dataRoot,'registry.json'),'utf8'));
  const high=JSON.parse(await fs.readFile(path.join(dataRoot,'registry-high-water.json'),'utf8'));
  const checked=manager.registry.verify(envelope,high.revision);fail(checked.hash===high.sha256,'REGISTRY_STATE_INCONSISTENT');manager.registry.accept(envelope,high.revision);
  const bound=await manager.checkCompatibility({entryId:selected.entryId});
  const after=await manager.selection();fail(JSON.stringify(after)===JSON.stringify(selected),'SNAPSHOT_SELECTION_CHANGED_DURING_PREFLIGHT');
  return {compatible:true,...bound};
}
module.exports={createProductionManager,productionRegistry,upgradePreflight,SnapshotManager,PROTOCOL,METHODS,RULEKIT_VERSION};
