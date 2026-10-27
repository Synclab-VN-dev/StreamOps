'use strict';
const fs=require('node:fs/promises');const os=require('node:os');const path=require('node:path');
const assert=require('node:assert/strict');const {test}=require('node:test');
const {SnapshotManager}=require('../src/manager');
const {createPackage,trust,strategies}=require('./helpers');
const managers=new Map();
async function sandbox(t){const root=await fs.mkdtemp(path.join(os.tmpdir(),'rulekit-snapshots-'));managers.set(root,[]);t.after(async()=>{for(const manager of managers.get(root))await manager.close();managers.delete(root);await fs.rm(root,{recursive:true,force:true});});return root;}
async function start(t,root,credentials,data='owned-data',generation=1){const manager=new SnapshotManager({dataRoot:path.join(root,data),registry:credentials.registry,strategies,workerGeneration:generation});await manager.start();managers.get(root).push(manager);return manager;}
test('no snapshot is genuinely UNAVAILABLE and production trust remains blocked',async t=>{
 const root=await sandbox(t);const manager=new SnapshotManager({dataRoot:path.join(root,'no-snapshot')});await manager.start();managers.get(root).push(manager);
 const caps=await manager.getCapabilities();assert.equal(caps.calculationAvailability,'UNAVAILABLE');assert.equal(caps.active,null);assert.equal(caps.managementAvailability,'BLOCKED');
 await assert.rejects(manager.importPackage({packagePath:root}),{code:'TRUST_POLICY_NOT_CONFIGURED'});
});
test('one Rule Kit build identifies two independently verified synthetic snapshot bindings',async t=>{
 const root=await sandbox(t);const a=await createPackage(root),b=await createPackage(root,'SYNTHETIC-B');const credentials=trust([a.entry,b.entry]);
 const manager=await start(t,root,credentials);await manager.updateRegistry(credentials.envelope);
 await manager.importPackage({packagePath:a.directory});await manager.importPackage({packagePath:b.directory});
 const installed=await manager.listInstalled();assert.equal(installed.length,2);assert(installed.every(row=>row.bindings.some(binding=>binding.compatible)));
 assert.equal((await manager.checkCompatibility({entryId:a.entry.entryId})).profileSha256,a.entry.profileSha256);
 await assert.rejects(manager.checkCompatibility({entryId:'unknown'}),{code:'SNAPSHOT_COMPATIBILITY_UNKNOWN'});
 assert.equal((await manager.getCapabilities()).calculationAvailability,'UNAVAILABLE');
});
test('activate/switch/rollback require fresh worker generation and preserve unrelated database bytes',async t=>{
 const root=await sandbox(t);const a=await createPackage(root),b=await createPackage(root,'SYNTHETIC-B');const credentials=trust([a.entry,b.entry]);
 let manager=await start(t,root,credentials);await manager.updateRegistry(credentials.envelope);await manager.importPackage({packagePath:a.directory});await manager.importPackage({packagePath:b.directory});
 const db=path.join(root,'owner.sqlite');await fs.writeFile(db,'SYNTHETIC USER DB BYTES');
 const selected=await manager.invoke('activate',{entryId:a.entry.entryId});assert.equal(selected.restartRequired,true);assert.equal((await manager.getActive()).active,null);
 await manager.close();manager=await start(t,root,trustRegistry(credentials),'owned-data',2);
 assert.equal((await manager.getActive()).active.snapshotId,a.entry.snapshotId);
 await manager.invoke('switchSnapshot',{entryId:b.entry.entryId});
 assert.equal((await manager.getActive()).calculationAvailability,'UNAVAILABLE');assert.equal((await manager.getActive()).active.snapshotId,a.entry.snapshotId);
 await manager.close();manager=await start(t,root,trustRegistry(credentials),'owned-data',3);
 assert.equal((await manager.getActive()).active.snapshotId,b.entry.snapshotId);
 await manager.rollback();await manager.close();manager=await start(t,root,trustRegistry(credentials),'owned-data',4);
 assert.equal((await manager.getActive()).active.snapshotId,a.entry.snapshotId);assert.equal(await fs.readFile(db,'utf8'),'SYNTHETIC USER DB BYTES');
});
function trustRegistry(credentials){const {TrustedRegistry}=require('../src/trust');return {registry:new TrustedRegistry({anchors:credentials.registry.anchors,ruleKitVersion:'test-rulekit/v1',scope:'ISOLATED_TEST'})};}
test('corrupt resource/profile, unknown codec/strategy and revoked bindings fail closed',async t=>{
 const root=await sandbox(t);const a=await createPackage(root);const credentials=trust([a.entry]);const manager=await start(t,root,credentials);await manager.updateRegistry(credentials.envelope);
 await fs.appendFile(path.join(a.directory,'profile.json'),' ');
 await assert.rejects(manager.importPackage({packagePath:a.directory}),{code:'SNAPSHOT_PACKAGE_FILE_INTEGRITY'});
 assert.equal((await manager.listInstalled()).length,0);
 await fs.writeFile(path.join(a.directory,'profile.json'),JSON.stringify(a.profile));
 const profileMismatch={...a.entry,codecVersion:'UNKNOWN-CODEC'};
 await manager.updateRegistry(credentials.sign({...credentials.payload,revision:2,entries:[profileMismatch]}));
 await assert.rejects(manager.importPackage({packagePath:a.directory}),{code:'CODEC_STRATEGY_INCOMPATIBLE'});
 const fresh=await createPackage(root,'SYNTHETIC-C');
 await manager.updateRegistry(credentials.sign({...credentials.payload,revision:3,entries:[fresh.entry],revokedEntryIds:[fresh.entry.entryId]}));
 await assert.rejects(manager.importPackage({packagePath:fresh.directory}),{code:'COMPATIBILITY_REVOKED'});
});
test('synthetic evidence and strategies can never be used under production trust scope',async t=>{
 const root=await sandbox(t);const a=await createPackage(root);const credentials=trust([a.entry],'PRODUCTION');
 const manager=await start(t,root,credentials);await manager.updateRegistry(credentials.envelope);
 await assert.rejects(manager.importPackage({packagePath:a.directory}),{code:'SYNTHETIC_BINDING_NOT_PRODUCTION'});
});
test('imports are immutable/idempotent, reject extraneous files and never auto-activate',async t=>{
 const root=await sandbox(t);const a=await createPackage(root);const credentials=trust([a.entry]);const manager=await start(t,root,credentials);await manager.updateRegistry(credentials.envelope);
 await manager.importPackage({packagePath:a.directory});await manager.importPackage({packagePath:a.directory});
 assert.equal((await manager.listInstalled()).length,1);assert.equal((await manager.getActive()).active,null);
 await fs.writeFile(path.join(a.directory,'untrusted-secret.txt'),'not-in-manifest');
 await assert.rejects(manager.importPackage({packagePath:a.directory}),{code:'UNDECLARED_SNAPSHOT_PACKAGE_FILE'});
 assert.deepEqual(await fs.readdir(path.join(manager.dataRoot,'staging')),[]);
});
test('signed revocation invalidates active calculation and cannot be rolled back',async t=>{
 const root=await sandbox(t);const a=await createPackage(root);const credentials=trust([a.entry]);let manager=await start(t,root,credentials);
 await manager.updateRegistry(credentials.envelope);await manager.importPackage({packagePath:a.directory});await manager.invoke('activate',{entryId:a.entry.entryId});await manager.close();
 manager=await start(t,root,trustRegistry(credentials),'owned-data',2);
 const revoked=credentials.sign({...credentials.payload,revision:2,revokedEntryIds:[a.entry.entryId]});await manager.updateRegistry(revoked);
 const active=await manager.getActive();assert.equal(active.calculationAvailability,'UNAVAILABLE');assert.equal(active.active,null);assert.equal(active.reason,'COMPATIBILITY_REVOKED');
 await assert.rejects(manager.updateRegistry(credentials.sign({...credentials.payload,revision:3})),{code:'REGISTRY_REVOCATION_ROLLBACK'});
});
test('forged on-disk registry never grants calculation readiness',async t=>{
 const root=await sandbox(t);const a=await createPackage(root);const credentials=trust([a.entry]);let manager=await start(t,root,credentials);
 await manager.updateRegistry(credentials.envelope);await manager.importPackage({packagePath:a.directory});await manager.invoke('activate',{entryId:a.entry.entryId});await manager.close();
 const forged=structuredClone(credentials.envelope);forged.payload.revision=999;await fs.writeFile(path.join(root,'owned-data/registry.json'),JSON.stringify(forged));
 manager=await start(t,root,trustRegistry(credentials),'owned-data',2);
 const caps=await manager.getCapabilities();assert.equal(caps.calculationAvailability,'UNAVAILABLE');assert.equal(caps.reason,'REGISTRY_SIGNATURE_INVALID');
});
test('typed management input rejects internal path overrides and unknown methods',async t=>{
 const root=await sandbox(t);const manager=new SnapshotManager({dataRoot:path.join(root,'owned-data')});await manager.start();managers.get(root).push(manager);
 await assert.rejects(manager.invoke('unknown'),{code:'SNAPSHOT_METHOD_UNKNOWN'});
 await assert.rejects(manager.invoke('getActive',{storeRoot:'/foreign'}),{code:'SNAPSHOT_CALL_SCHEMA_INVALID'});
});
