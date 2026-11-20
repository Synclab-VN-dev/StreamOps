'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs/promises'),os=require('node:os'),path=require('node:path');
const {classifyWindowsOwner,windowsIdentity}=require('../src/process-owner');
const {SnapshotManager}=require('../src/manager');
const before='2026-11-13T04:06:26.833Z',after='2026-11-18T08:56:43.904Z';
test('process identity distinguishes live, reused and ambiguous owners',()=>{
 const legacy={pid:4116,owner:'synthetic'};
 assert.equal(classifyWindowsOwner(legacy,Date.parse(before),null),'DEAD');
 assert.equal(classifyWindowsOwner(legacy,Date.parse(before),{startedAt:after}),'REUSED');
 assert.equal(classifyWindowsOwner(legacy,Date.parse(after),{startedAt:before}),'LIVE');
 assert.equal(classifyWindowsOwner(legacy,NaN,{startedAt:after}),'LIVE');
 const identified={...legacy,processIdentity:{startedAt:before}};
 assert.equal(classifyWindowsOwner(identified,0,{startedAt:before}),'LIVE');
 assert.equal(classifyWindowsOwner(identified,0,{startedAt:after}),'REUSED');
 assert.throws(()=>classifyWindowsOwner({...legacy,processIdentity:{}},0,{startedAt:after}),{code:'SNAPSHOT_LOCK_OWNERSHIP_UNKNOWN'});
 assert.throws(()=>classifyWindowsOwner({...legacy,processIdentity:{startedAt:after}},0,{startedAt:before}),{code:'SNAPSHOT_LOCK_OWNERSHIP_UNKNOWN'});
});
test('Windows recovers legacy reused protected PID without signaling or terminating it',{skip:process.platform!=='win32',timeout:30000},async t=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'issue213-lease-'));
 const manager=new SnapshotManager({dataRoot:root});
 t.after(async()=>{await manager.close();await fs.rm(root,{recursive:true,force:true});});
 const system=await windowsIdentity(4);assert(system);
 const lock=path.join(root,'.manager.lock');
 await fs.writeFile(lock,JSON.stringify({owner:'old-worker',pid:4}));
 const old=new Date(Date.parse(system.startedAt)-86400000);await fs.utimes(lock,old,old);
 await manager.start();assert.equal((await manager.getCapabilities()).calculationAvailability,'UNAVAILABLE');
 const owned=JSON.parse(await fs.readFile(lock,'utf8'));assert.equal(owned.pid,process.pid);assert(owned.processIdentity.startedAt);
 assert.deepEqual(await windowsIdentity(4),system,'protected process remains untouched');
 const contender=new SnapshotManager({dataRoot:root});await assert.rejects(contender.start(),{code:'SNAPSHOT_MANAGER_BUSY'});
 assert.equal(JSON.parse(await fs.readFile(lock,'utf8')).owner,owned.owner);
 await manager.close();await assert.rejects(fs.stat(lock),{code:'ENOENT'});
 await manager.start();await manager.close();
});

test('identity lookup exposes only bounded failure reasons',async()=>{
 const {execFile}=require('node:child_process'),{promisify}=require('node:util');
 const run=promisify(execFile),helper=require.resolve('../src/process-owner');
 for(const [expression,reason] of [
  ["throw Object.assign(Error('private stderr'),{killed:true})",'TIMEOUT'],
  ["throw Object.assign(Error('private stderr'),{code:'ERR_CHILD_PROCESS_STDIO_MAXBUFFER'})",'OUTPUT_LIMIT'],
  ["return {stdout:'private invalid response'}",'INVALID_RESPONSE'],
  ["throw Object.assign(Error('private path'),{code:'ENOENT'})",'QUERY_FAILED'],
 ]){
  const script=`require('node:child_process').execFile=function(){};require('node:child_process').execFile[require('node:util').promisify.custom]=async()=>{${expression}};require(${JSON.stringify(helper)}).windowsIdentity(123).catch(e=>console.log(JSON.stringify({code:e.code,message:e.message})));`;
  const {stdout}=await run(process.execPath,['-e',script]);
  assert.deepEqual(JSON.parse(stdout),{code:'SNAPSHOT_LOCK_OWNERSHIP_UNKNOWN',message:'SNAPSHOT_LOCK_OWNERSHIP_UNKNOWN:'+reason});
 }
});

test('Windows native identity survives incompatible module discovery and matches existing CIM leases',
 {skip:process.platform!=='win32',timeout:30000},async t=>{
 const {execFile}=require('node:child_process'),run=require('node:util').promisify(execFile);
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'identity-module-'));
 t.after(()=>fs.rm(root,{recursive:true,force:true}));
 const module=path.join(root,'CimCmdlets');await fs.mkdir(module);
 await fs.writeFile(path.join(module,'CimCmdlets.psd1'),"@{ModuleVersion='1.0';RootModule='bad.psm1';FunctionsToExport=@('Get-CimInstance')}");
 await fs.writeFile(path.join(module,'bad.psm1'),"throw 'incompatible module'; function Get-CimInstance {};");
 const env=Object.fromEntries(['PATH','SystemRoot','WINDIR','TEMP','TMP','PATHEXT','COMSPEC'].filter(k=>process.env[k]).map(k=>[k,process.env[k]]));
 env.PSModulePath=root;
 const helper=require.resolve('../src/process-owner');
 const script=`require(${JSON.stringify(helper)}).windowsIdentity(${process.pid}).then(v=>console.log(JSON.stringify(v))).catch(e=>{console.error(e.message);process.exitCode=1});`;
 const {stdout}=await run(process.execPath,['-e',script],{env,timeout:10000});
 const actual=JSON.parse(stdout);
 const reference=`$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; Import-Module "$PSHOME/Modules/CimCmdlets/CimCmdlets.psd1"; (CimCmdlets\\Get-CimInstance Win32_Process -Filter 'ProcessId=${process.pid}').CreationDate.ToUniversalTime().ToString('o')`;
 const expected=await run(path.join(process.env.SystemRoot,'System32/WindowsPowerShell/v1.0/powershell.exe'),
  ['-NoProfile','-NonInteractive','-EncodedCommand',Buffer.from(reference,'utf16le').toString('base64')],{timeout:10000});
 assert.equal(actual.startedAt,expected.stdout.trim());
 // Inject access denial at the native-read boundary; the real CIM fallback
 // must use the system module even with an incompatible inherited module path.
 const fallback=`const cp=require('node:child_process'),u=require('node:util'),original=u.promisify(cp.execFile);
cp.execFile=function(){};cp.execFile[u.promisify.custom]=(file,args,options)=>{
 const source=Buffer.from(args.at(-1),'base64').toString('utf16le');
 require('node:assert').ok(source.includes('$p.StartTime.ToUniversalTime()'));
 const injected=source.replace('$p.StartTime.ToUniversalTime()',"$(throw 'injected access denial')");
 return original(file,[...args.slice(0,-1),Buffer.from(injected,'utf16le').toString('base64')],options);
};`+script;
 assert.deepEqual(JSON.parse((await run(process.execPath,['-e',fallback],{env,timeout:10000})).stdout),actual);
 assert.equal(classifyWindowsOwner({processIdentity:actual},0,await windowsIdentity(process.pid)),'LIVE');
 const exited=require('node:child_process').spawn(process.execPath,['-e','']);
 await new Promise((resolve,reject)=>{exited.once('exit',resolve);exited.once('error',reject);});
 assert.equal(await windowsIdentity(exited.pid),null);
});
