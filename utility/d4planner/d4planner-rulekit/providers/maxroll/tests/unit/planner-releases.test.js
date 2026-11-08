'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const os=require('node:os');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const {createHash}=require('node:crypto');
const {ReleaseProvisioner,select,PROTOCOL,download}=require('../../tooling/planner/releases');
const {readSelection}=require('../../tooling/planner/selection');
const {loadSnapshot}=require('../../tooling/web/server');
const hash=b=>createHash('sha256').update(b).digest('hex');
async function fixture(t) {
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'planner-release-'));t.after(()=>fs.rm(root,{recursive:true,force:true}));
  const config=JSON.parse(execFileSync(process.execPath,[path.resolve(__dirname,'../../tooling/web/activation-fixture.js'),path.join(root,'fixture')]))[0];
  const dataRoot=path.join(root,'rulekit'), stateRoot=path.join(dataRoot,'planner','state');
  await fs.mkdir(path.join(root,'private'));await fs.writeFile(path.join(root,'private','snapshot-age-identity.txt'),'test-only');
  const bytes=Buffer.from('encrypted-fixture');
  const name='ui-snapshot-1.2.3.zip.age';
  const entry={sha256:hash(bytes),bytes:bytes.length,snapshotId:config.snapshotId,manifestSha256:config.manifestSha256,uiTrust:config.uiTrust,plannerProtocolVersion:PROTOCOL};
  const metadata={schemaVersion:'d4planner-snapshot-pair/v1',version:'1.2.3',assets:{[name]:entry}};
  const release={tag_name:'d4planner-snapshots/v1.2.3',assets:[{id:1,name:'snapshot-pair.json'},{id:2,name,size:bytes.length}]};
  let downloads=0;
  const read=async url=>{
    if(url.includes('/releases?'))return Buffer.from(JSON.stringify([release]));
    if(url.endsWith('/1'))return Buffer.from(JSON.stringify(metadata));
    downloads++;return bytes;
  };
  const decrypt=async (_exe,_archive,_key,dest)=>fs.cp(config.snapshotRoot,dest,{recursive:true});
  const options={stateRoot,dataRoot,installationRoot:root,load:loadSnapshot,read,decrypt};
  return {root,config,stateRoot,entry,metadata,release,options,downloads:()=>downloads};
}
test('fresh install downloads UI, validates actual resources, atomically selects; repeated provision preserves state',async t=>{
  const f=await fixture(t), p=new ReleaseProvisioner(f.options);
  await p.ensure();const c=await readSelection(f.stateRoot,6085);assert.equal(c.snapshotId,f.config.snapshotId);
  assert.equal((await loadSnapshot(c)).uiVerification.status,'AUTOMATED_VALIDATED');
  const before=await fs.readFile(path.join(f.stateRoot,'capture-state.json'));await p.ensure();
  assert.deepEqual(await fs.readFile(path.join(f.stateRoot,'capture-state.json')),before);assert.equal(f.downloads(),1);
});
test('no compatible release, missing key, tampering and invalid receipt never activate',async t=>{
  for(const scenario of ['none','protocol','key','hash','receipt']) {
    const f=await fixture(t);let expected;
    if(scenario==='none'){f.options.read=async()=>Buffer.from('[]');expected='PLANNER_RELEASE_NOT_FOUND';}
    if(scenario==='protocol'){f.entry.plannerProtocolVersion='unknown';expected='PLANNER_RELEASE_NOT_FOUND';}
    if(scenario==='key'){await fs.unlink(path.join(f.root,'private','snapshot-age-identity.txt'));expected='PLANNER_DECRYPTION_KEY_REQUIRED';}
    if(scenario==='hash'){f.entry.sha256='0'.repeat(64);expected='PLANNER_RELEASE_UNTRUSTED';}
    if(scenario==='receipt'){await fs.appendFile(path.join(f.config.snapshotRoot,f.config.snapshotId,'ui-validation.json'),' ');expected='PLANNER_SNAPSHOT_UNTRUSTED';}
    await assert.rejects(new ReleaseProvisioner(f.options).ensure(),{code:expected});
    await assert.rejects(fs.access(path.join(f.stateRoot,'capture-state.json')));
  }
});
test('concurrent provision, cancellation, existing corrupt state and foreign lock fail closed',async t=>{
  const f=await fixture(t), parent=path.dirname(f.stateRoot);await fs.mkdir(parent,{recursive:true});
  const lock=path.join(parent,'.provision.lock');await fs.writeFile(lock,'foreign');
  await assert.rejects(new ReleaseProvisioner(f.options).ensure(),{code:'PLANNER_BUSY'});assert.equal(await fs.readFile(lock,'utf8'),'foreign');await fs.unlink(lock);
  let finish;const entered=new Promise(resolve=>{finish=resolve;});let resume;const wait=new Promise(resolve=>{resume=resolve;});
  const original=f.options.decrypt;f.options.decrypt=async(...args)=>{finish();await wait;return original(...args);};
  const controller=new AbortController();const p=new ReleaseProvisioner(f.options).ensure(controller.signal);await entered;
  await assert.rejects(new ReleaseProvisioner(f.options).ensure(),{code:'PLANNER_BUSY'});
  controller.abort();resume();await assert.rejects(p);await assert.rejects(fs.access(path.join(f.stateRoot,'capture-state.json')));
  assert.deepEqual((await fs.readdir(parent)).filter(n=>n.startsWith('.')),[]);
  await fs.mkdir(f.stateRoot);await fs.writeFile(path.join(f.stateRoot,'capture-state.json'),'corrupt');
  await assert.rejects(new ReleaseProvisioner(f.options).ensure(),{code:'PLANNER_SNAPSHOT_UNTRUSTED'});
  assert.equal(await fs.readFile(path.join(f.stateRoot,'capture-state.json'),'utf8'),'corrupt');
});
test('release selection uses semantic versions and excludes drafts, prereleases and legacy calculation-only releases',()=>{
  const r=tag_name=>({tag_name,assets:[{name:'snapshot-pair.json'}]});
  assert.deepEqual(select([r('d4planner-snapshots/v1.9.0'),r('d4planner-snapshots/v1.10.0'),{...r('d4planner-snapshots/v2.0.0'),prerelease:true},r('d4planner-snapshots/2026.10.30-r2')]).map(r=>r.tag_name),['d4planner-snapshots/v1.10.0','d4planner-snapshots/v1.9.0']);
});
test('download rejects foreign hosts before any request',async()=>{
  for(const url of ['http://api.github.com/x','https://evil.invalid/x','https://secret@api.github.com/x'])await assert.rejects(download(url,100),{code:'PLANNER_RELEASE_UNTRUSTED'});
});

test('transport bounds response size and removes PAT on approved asset redirects', async t=>{
  const original=global.fetch;t.after(()=>{global.fetch=original;});const requests=[];
  global.fetch=async(url,options)=>{requests.push({url:String(url),options});return requests.length===1?
    new Response(null,{status:302,headers:{location:'https://release-assets.githubusercontent.com/fixture'}}):new Response('data');};
  assert.equal((await download('https://api.github.com/repos/example/repo/releases/assets/1',4,undefined,'test-token')).toString(),'data');
  assert.equal(requests[0].options.headers.Authorization,'Bearer test-token');assert.equal(requests[1].options.headers.Authorization,undefined);
  global.fetch=async()=>new Response('oversize');await assert.rejects(download('https://api.github.com/x',2),{code:'PLANNER_RELEASE_UNTRUSTED'});
  global.fetch=async()=>new Response(null,{status:403});await assert.rejects(download('https://api.github.com/x',10),{code:'PLANNER_RELEASE_ACCESS_DENIED'});
  global.fetch=async()=>new Response(null,{status:302,headers:{location:'https://evil.invalid/token'}});
  await assert.rejects(download('https://api.github.com/x',10),{code:'PLANNER_RELEASE_UNTRUSTED'});
});

test('a competitor publishing state during validation cannot be overwritten', async t=>{
  const f=await fixture(t);const load=f.options.load;
  f.options.load=async config=>{const result=await load(config);await fs.mkdir(f.stateRoot,{recursive:true});await fs.writeFile(path.join(f.stateRoot,'capture-state.json'),'competing-state');return result;};
  await assert.rejects(new ReleaseProvisioner(f.options).ensure(),{code:'PLANNER_SNAPSHOT_UNTRUSTED'});
  assert.equal(await fs.readFile(path.join(f.stateRoot,'capture-state.json'),'utf8'),'competing-state');
  assert.deepEqual(await fs.readdir(path.join(path.dirname(f.stateRoot),'releases')),[]);
});
