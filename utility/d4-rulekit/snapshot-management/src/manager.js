'use strict';
const fs=require('node:fs/promises');
const path=require('node:path');
const crypto=require('node:crypto');
const Ajv=require('ajv');
const { FileSystemSnapshotStore }=require('../../browser-infra/src/snapshot/store');
const { CompatibilityResolver }=require('./resolver');
const { SnapshotError,fail,digest,canonical }=require('./trust');
const validatePackage=new Ajv({strict:true}).compile(require('../schemas/snapshot-package.schema.json'));
const PROTOCOL='d4-rulekit-snapshots/v1';
const METHODS=Object.freeze(['listInstalled','checkCompatibility','getCapabilities','importPackage','activate','getActive','switchSnapshot','rollback','compareSnapshots']);
function safeRelative(value) {
  fail(typeof value==='string' && value.length>0 && !value.includes('\\') && !value.includes(':') && !value.includes('\0') && !value.startsWith('/') && value.split('/').every(p=>p && p!=='.' && p!=='..'),'UNSAFE_SNAPSHOT_PATH');
  return value;
}
async function readJson(file) { return JSON.parse(await fs.readFile(file,'utf8')); }
async function atomic(file,value) {
  const temporary=file+'.'+crypto.randomUUID()+'.writing';
  const handle=await fs.open(temporary,'wx',0o600);
  try {await handle.writeFile(JSON.stringify(value));await handle.sync();} finally {await handle.close();}
  try {await fs.rename(temporary,file);} finally {await fs.rm(temporary,{force:true});}
}
async function inventory(root,prefix='') {
  const result=[];
  for(const entry of await fs.readdir(path.join(root,prefix),{withFileTypes:true})) {
    const relative=prefix?prefix+'/'+entry.name:entry.name;safeRelative(relative);
    fail(!entry.isSymbolicLink(),'SNAPSHOT_SYMLINK_REJECTED');
    if(entry.isDirectory()) result.push(...await inventory(root,relative));
    else {fail(entry.isFile(),'SNAPSHOT_SPECIAL_FILE_REJECTED');result.push(relative);}
  }
  return result.sort();
}

class SnapshotManager {
  constructor({dataRoot,installationRoot,registry=null,strategies={},workerGeneration=1,maxQueue=16}={}) {
    fail(path.isAbsolute(dataRoot??''),'ABSOLUTE_SNAPSHOT_DATA_ROOT_REQUIRED');
    const root=path.resolve(dataRoot);
    if(installationRoot) { const relative=path.relative(path.resolve(installationRoot),root);fail(relative.startsWith('..'+path.sep)||path.isAbsolute(relative),'SNAPSHOT_STORE_INSIDE_APPLICATION'); }
    this.dataRoot=root;this.storeRoot=path.join(root,'store');this.registry=registry;
    this.resolver=registry?new CompatibilityResolver({registry,strategies}):null;
    this.workerGeneration=workerGeneration;this.maxQueue=maxQueue;this.queued=0;
    this.owner=crypto.randomUUID();this.lock=null;this.tail=Promise.resolve();this.current=null;this.quiescing=false;this.pendingTransition=null;this.registryError=null;
  }
  async start() {
    await fs.mkdir(this.dataRoot,{recursive:true,mode:0o700});
    fail(!(await fs.lstat(this.dataRoot)).isSymbolicLink(),'SNAPSHOT_STORE_SYMLINK');
    for(const folder of ['store','profiles','staging']) {
      const target=path.join(this.dataRoot,folder);await fs.mkdir(target,{recursive:true,mode:0o700});
      fail(!(await fs.lstat(target)).isSymbolicLink(),'SNAPSHOT_STORE_SYMLINK');
    }
    await this.acquireLock();
    try {
      const registryFile=path.join(this.dataRoot,'registry.json');
      if(await this.exists(registryFile)) {
        try {
          fail(this.registry,'TRUST_POLICY_NOT_CONFIGURED');
          const envelope=await readJson(registryFile);
          const high=await readJson(path.join(this.dataRoot,'registry-high-water.json'));
          const checked=this.registry.verify(envelope,high.revision);
          fail(checked.hash===high.sha256,'REGISTRY_STATE_INCONSISTENT');
          this.registry.accept(envelope,high.revision);
        } catch(error) {this.registryError=error.code??'REGISTRY_STATE_INVALID';}
      }
      this.current=await this.selection();
      return await this.getCapabilities();
    } catch(error) {await this.close();throw error;}
  }
  async acquireLock() {
    const file=path.join(this.dataRoot,'.manager.lock');
    try {this.lock=await fs.open(file,'wx',0o600);}
    catch(error){
      if(error.code!=='EEXIST')throw error;
      fail(!(await fs.lstat(file)).isSymbolicLink(),'SNAPSHOT_LOCK_SYMLINK');
      const old=await readJson(file);
      fail(Number.isInteger(old.pid)&&old.pid>0&&typeof old.owner==='string','SNAPSHOT_LOCK_OWNERSHIP_UNKNOWN');
      let dead=false;
      try {process.kill(old.pid,0);} catch(probe){if(probe.code==='ESRCH')dead=true;else throw probe;}
      fail(dead,'SNAPSHOT_MANAGER_BUSY');
      const retired=file+'.retired-'+this.owner;
      await fs.rename(file,retired);
      const moved=await readJson(retired);
      if(moved.owner!==old.owner||moved.pid!==old.pid){
        // A competing owner won acquisition. Never delete its lease or start
        // another active manager; restore only with no-clobber semantics.
        await fs.link(retired,file).catch(()=>{});
        throw new SnapshotError('SNAPSHOT_MANAGER_BUSY');
      }
      try {this.lock=await fs.open(file,'wx',0o600);} finally {await fs.rm(retired,{force:true});}
    }
    await this.lock.writeFile(JSON.stringify({owner:this.owner,pid:process.pid}));
    fail((await readJson(file)).owner===this.owner,'SNAPSHOT_LOCK_OWNERSHIP_LOST');
  }
  async close() {
    await this.tail.catch(()=>{});
    if(this.lock) {
      await this.lock.close();this.lock=null;
      const file=path.join(this.dataRoot,'.manager.lock');
      if((await readJson(file)).owner===this.owner) await fs.unlink(file);
    }
  }
  async exists(file) {try {await fs.access(file);return true;} catch(error){if(error.code==='ENOENT')return false;throw error;}}
  async selection() {
    const file=path.join(this.dataRoot,'selection.json');
    if(!await this.exists(file))return null;
    const result=await readJson(file);
    fail(result.schemaVersion==='d4-rulekit-snapshot-selection/v1' && Number.isSafeInteger(result.selectionRevision) && result.selectionRevision>0 && typeof result.entryId==='string','SNAPSHOT_SELECTION_INVALID');
    return result;
  }
  async updateRegistry(envelope) {
    fail(this.registry,'TRUST_POLICY_NOT_CONFIGURED');
    return this.serial(async()=>{
      let minimum=this.registry.revision;
      const highFile=path.join(this.dataRoot,'registry-high-water.json');
      if(await this.exists(highFile)){const high=await readJson(highFile);minimum=Math.max(minimum,high.revision);}
      // A verified later registry left by an interrupted update is itself an
      // additional floor. Repair never silently restores an earlier revision.
      const registryFile=path.join(this.dataRoot,'registry.json');
      if(this.registryError && await this.exists(registryFile)){
        const pending=await readJson(registryFile);this.registry.verify(pending,minimum);minimum=Math.max(minimum,pending.payload.revision);
      }
      const checked=this.registry.verify(envelope,minimum);
      // If interrupted between writes, startup fails closed on inconsistent
      // registry/high-water state. It never falls back to an older registry.
      await atomic(path.join(this.dataRoot,'registry.json'),envelope);
      await atomic(path.join(this.dataRoot,'registry-high-water.json'),{revision:envelope.payload.revision,sha256:checked.hash});
      const result=this.registry.accept(envelope);this.registryError=null;
      if(this.current) {
        try {const checked=await this.checkCompatibility({entryId:this.current.entryId});fail(checked.manifestSha256===this.current.manifestSha256 && checked.profileSha256===this.current.profileSha256,'ACTIVE_BINDING_CHANGED');} catch {this.quiescing=true;}
      }
      return {...result,revocationEffective:'AFTER_VERIFIED_IMPORT',restartRequired:this.quiescing};
    });
  }
  serial(action) {
    fail(this.queued<this.maxQueue,'SNAPSHOT_QUEUE_FULL');this.queued++;
    const operation=this.tail.then(action);this.tail=operation.catch(()=>{});
    return operation.finally(()=>this.queued--);
  }
  async listInstalled() {
    const result=[];
    for(const entry of await fs.readdir(this.storeRoot,{withFileTypes:true})) {
      if(!entry.isDirectory())continue;
      try {
        const store=new FileSystemSnapshotStore({rootDir:this.storeRoot});
        const verified=await store.verify(entry.name);
        const bindings=this.registry?.envelope?this.registry.listBindings().filter(row=>row.snapshotId===entry.name):[];
        result.push({snapshotId:entry.name,integrity:'VERIFIED',manifestSha256:verified.manifestSha256,bindings});
      } catch(error) {result.push({snapshotId:entry.name,integrity:'INVALID',reason:error.code??'SNAPSHOT_READ_FAILED'});}
    }
    return result;
  }
  async checkCompatibility({entryId,storeRoot=this.storeRoot,profilePath}={}) {
    fail(this.registry && this.resolver,'TRUST_POLICY_NOT_CONFIGURED');
    const entry=this.registry.resolve(entryId);
    const store=new FileSystemSnapshotStore({rootDir:storeRoot});
    const verified=await store.verify(entry.snapshotId);
    fail(verified.manifestSha256===entry.snapshotManifestSha256,'SNAPSHOT_MANIFEST_MISMATCH');
    const file=profilePath??path.join(this.dataRoot,'profiles',entry.snapshotId+'-'+entry.profileSha256+'.json');
    const bytes=await fs.readFile(file);fail(digest(bytes)===entry.profileSha256,'PROFILE_INTEGRITY_MISMATCH');
    const profile=JSON.parse(bytes);const manifest=await store.load(entry.snapshotId);
    this.resolver.resolve(entryId,profile,manifest);
    return {entryId,snapshotId:entry.snapshotId,manifestSha256:verified.manifestSha256,profileSha256:entry.profileSha256,
      registryRevision:this.registry.revision,registrySha256:this.registry.sha256,compatibility:'VERIFIED_BINDING',evidenceClass:entry.approval.testClass,
      distribution:entry.distribution.permission};
  }
  async getActive() {
    const base={workerGeneration:this.workerGeneration,restartRequired:this.quiescing};
    if(!this.current)return {...base,active:null,calculationAvailability:'UNAVAILABLE',reason:this.registryError??'SNAPSHOT_NOT_SELECTED'};
    try {
      fail(!this.registryError,this.registryError??'REGISTRY_STATE_INVALID');
      const checked=await this.checkCompatibility({entryId:this.current.entryId});
      fail(checked.snapshotId===this.current.snapshotId && checked.manifestSha256===this.current.manifestSha256 && checked.profileSha256===this.current.profileSha256,'SNAPSHOT_SELECTION_BINDING_MISMATCH');
      return {...base,active:{...checked,selectionRevision:this.current.selectionRevision},
        calculationAvailability:this.quiescing?'UNAVAILABLE':'READY',reason:this.quiescing?'WORKER_RESTART_REQUIRED':null};
    } catch(error) {
      return {...base,active:null,configured:{entryId:this.current.entryId,selectionRevision:this.current.selectionRevision},
        calculationAvailability:'UNAVAILABLE',reason:error.code??'SNAPSHOT_CONFIGURATION_INVALID'};
    }
  }
  async getCapabilities() {
    const active=await this.getActive();
    const entry=active.active?this.registry.resolve(active.active.entryId):null;
    return {protocolVersion:PROTOCOL,...active,managementAvailability:this.registry?'READY':'BLOCKED',managementReason:this.registry?this.registryError:'TRUST_POLICY_NOT_CONFIGURED',capabilities:entry?.capabilities??null};
  }
  async importPackage({packagePath}) {
    return this.serial(async()=>{
      fail(this.registry,'TRUST_POLICY_NOT_CONFIGURED');
      fail(path.isAbsolute(packagePath??''),'ABSOLUTE_PACKAGE_PATH_REQUIRED');
      fail(!(await fs.lstat(packagePath)).isSymbolicLink(),'SNAPSHOT_SYMLINK_REJECTED');
      const pkg=await readJson(path.join(packagePath,'snapshot-package.json'));
      fail(validatePackage(pkg),'SNAPSHOT_PACKAGE_SCHEMA_INVALID');
      const entry=this.registry.resolve(pkg.entryId);
      fail(entry.snapshotId===pkg.snapshotId && entry.snapshotManifestSha256===pkg.snapshotManifestSha256 && entry.profileSha256===pkg.profileSha256,'SNAPSHOT_PACKAGE_BINDING_MISMATCH');
      const names=pkg.files.map(row=>safeRelative(row.path));
      fail(new Set(names).size===names.length,'DUPLICATE_SNAPSHOT_PACKAGE_PATH');
      const allowed=new Set(['snapshot-package.json',...names]);
      const actual=await inventory(packagePath);
      fail(actual.length===allowed.size && actual.every(name=>allowed.has(name)),'UNDECLARED_SNAPSHOT_PACKAGE_FILE');
      const stage=path.join(this.dataRoot,'staging',crypto.randomUUID());await fs.mkdir(stage,{mode:0o700});
      try {
        for(const item of pkg.files) {
          fail(item.path==='profile.json' || item.path.startsWith('snapshot/'+entry.snapshotId+'/'),'SNAPSHOT_PACKAGE_LAYOUT');
          const bytes=await fs.readFile(path.join(packagePath,item.path));
          fail(bytes.length===item.bytes && digest(bytes)===item.sha256,'SNAPSHOT_PACKAGE_FILE_INTEGRITY');
          const target=path.join(stage,item.path);await fs.mkdir(path.dirname(target),{recursive:true,mode:0o700});await fs.writeFile(target,bytes,{flag:'wx',mode:0o600});
        }
        const sourceStore=path.join(stage,'snapshot');
        const verified=await this.checkCompatibility({entryId:entry.entryId,storeRoot:sourceStore,profilePath:path.join(stage,'profile.json')});
        const manifest=await new FileSystemSnapshotStore({rootDir:sourceStore}).load(entry.snapshotId);
        const expected=new Set(['manifest.json','manifest.sha256',...manifest.resources.map(resource=>resource.blob)]);
        const snapshotFiles=await inventory(path.join(sourceStore,entry.snapshotId));
        fail(snapshotFiles.length===expected.size && snapshotFiles.every(file=>expected.has(file)),'UNDECLARED_SNAPSHOT_RESOURCE');
        const target=path.join(this.storeRoot,entry.snapshotId);
        if(await this.exists(target)) {
          const existing=await new FileSystemSnapshotStore({rootDir:this.storeRoot}).verify(entry.snapshotId);
          fail(existing.manifestSha256===entry.snapshotManifestSha256,'SNAPSHOT_ID_HASH_CONFLICT');
        } else await fs.rename(path.join(sourceStore,entry.snapshotId),target);
        const profile=path.join(this.dataRoot,'profiles',entry.snapshotId+'-'+entry.profileSha256+'.json');
        if(await this.exists(profile))fail(digest(await fs.readFile(profile))===entry.profileSha256,'PROFILE_INTEGRITY_MISMATCH');
        else await fs.copyFile(path.join(stage,'profile.json'),profile,fs.constants.COPYFILE_EXCL);
        return {...verified,installed:true,activated:false};
      } finally {await fs.rm(stage,{recursive:true,force:true});}
    });
  }
  async prepareSelection({entryId},kind='ACTIVATE') {
    return this.serial(async()=>{
      if(this.pendingTransition && this.pendingTransition.entryId===entryId && this.pendingTransition.operation===kind)return {...this.pendingTransition};
      fail(!this.quiescing,'WORKER_RESTART_REQUIRED');
      const checked=await this.checkCompatibility({entryId});
      const old=await this.selection();
      if(old?.entryId===entryId)return {restartRequired:false,active:await this.getActive()};
      const selection={schemaVersion:'d4-rulekit-snapshot-selection/v1',entryId,selectionRevision:(old?.selectionRevision??0)+1,
        snapshotId:checked.snapshotId,manifestSha256:checked.manifestSha256,profileSha256:checked.profileSha256,
        registryRevision:checked.registryRevision,registrySha256:checked.registrySha256,previous:old};
      await atomic(path.join(this.dataRoot,'selection.json'),selection);this.quiescing=true;
      this.pendingTransition={operation:kind,restartRequired:true,nextWorkerGenerationRequired:true,selectionRevision:selection.selectionRevision,entryId};
      return {...this.pendingTransition};
    });
  }
  async rollback() {
    if(this.pendingTransition?.operation==='ROLLBACK')return {...this.pendingTransition};
    const current=await this.selection();fail(current?.previous,'SNAPSHOT_ROLLBACK_NOT_AVAILABLE');
    return this.prepareSelection({entryId:current.previous.entryId},'ROLLBACK');
  }
  async compareSnapshots(params) {
    return this.serial(() => require('./content-version').compareSnapshots(this.storeRoot,params));
  }
  async invoke(method,params={}) {
    fail(METHODS.includes(method),'SNAPSHOT_METHOD_UNKNOWN');
    require('./protocol').validateCall(method,params);
    if(method==='importPackage' && params.kind==='REGISTRY')return this.updateRegistry(params.envelope);
    if(method==='activate' || method==='switchSnapshot')return this.prepareSelection(params,method);
    if(method==='rollback')return this.rollback();
    // Never permit a caller to override internal store/profile paths.
    if(method==='checkCompatibility')return this.checkCompatibility({entryId:params.entryId});
    return this[method](params);
  }
}
module.exports={SnapshotManager,PROTOCOL,METHODS,safeRelative,atomic,inventory};
