'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const os=require('node:os');
const crypto=require('node:crypto');
const {spawn}=require('node:child_process');
const {once}=require('node:events');
const {fields}=require('../../runtime-logging/src/startup');
const {clean}=require('../../runtime-logging/src/logger');
const Ajv=require('../../snapshot-management/node_modules/ajv/dist/2020');
const validate=new Ajv({strict:true,allowUnionTypes:true}).compile(require('../../../d4planner-be/contracts/runtime-logging/v1/log.schema.json').properties.fields);

test('startup diagnostics use closed vocabularies and discard private error text',()=>{
 const result=fields(Object.assign(new Error('PRIVATE path token payload'),{code:'EPERM'}),'SNAPSHOT_MANAGER');
 assert.deepEqual(result,{errorCode:'STARTUP_FAILED',startupStage:'SNAPSHOT_MANAGER',startupReason:'ACCESS_DENIED'});
 assert.deepEqual(clean({...result,message:'PRIVATE',stderr:'PRIVATE'}),result);
 assert.deepEqual(clean({startupStage:'PRIVATE',startupReason:'PRIVATE'}),{});
 assert.equal(fields({code:'constructor'}).startupReason,'UNKNOWN');
});

for(const scenario of ['busy','invalid-selection',...(process.platform==='win32'?['protected-owner']:[])]) {
 test(`real bootstrap preserves ${scenario} startup diagnostic without READY or lock theft`,{timeout:15000},async t=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'issue213-'));
  const data=path.join(root,'data'),logs=path.join(root,'logs','run');
  await fs.mkdir(data);await fs.mkdir(logs,{recursive:true});await fs.mkdir(path.join(root,'logs','.control'));
  await fs.writeFile(path.join(logs,'rulekit.log'),'');
  const marker='PRIVATE_DIAGNOSTIC_MUST_NOT_ESCAPE';
  const lock=JSON.stringify({pid:scenario==='protected-owner'?4:process.pid,owner:marker});
  if(scenario==='invalid-selection')await fs.writeFile(path.join(data,'selection.json'),JSON.stringify({schemaVersion:marker}));
  else await fs.writeFile(path.join(data,'.manager.lock'),lock);
  const env=Object.fromEntries(Object.entries(process.env).filter(([key])=>!key.startsWith('D4_')));
  const child=spawn(process.execPath,[path.resolve(__dirname,'../src/runtime/bootstrap.js'),path.resolve(__dirname,'../../../d4planner-be/src/d4planner/rulekit/worker.js')],{
   env:{...env,D4_RULEKIT_DATA_ROOT:data,D4_RULEKIT_INSTALLATION_ROOT:path.join(root,'installation'),D4_RULEKIT_WORKER_INSTANCE_ID:'startup-test',D4_RULEKIT_WORKER_GENERATION:'1',D4_LOG_DIR:logs,D4_LOG_RUN_ID:crypto.randomUUID()},stdio:['pipe','pipe','pipe']});
  t.after(async()=>{if(child.exitCode===null){const exit=once(child,'exit');child.kill();await exit;}await fs.rm(root,{recursive:true,force:true});});
  let stdout='',stderr='';child.stdout.on('data',x=>stdout+=x);child.stderr.on('data',x=>stderr+=x);
  const [code]=await once(child,'exit');assert.equal(code,1);assert.equal(stdout,'');
  const raw=await fs.readFile(path.join(logs,'rulekit.log'),'utf8');assert(!raw.includes(marker));assert(!raw.includes(data));
  const rows=raw.trim().split('\n').map(JSON.parse);for(const row of rows)assert(validate(row.fields),JSON.stringify(validate.errors));
  const failure=rows.find(row=>row.fields.startupStage==='SNAPSHOT_MANAGER');assert(failure,stderr+raw);
  assert.equal(failure.fields.startupReason,scenario==='busy'?'MANAGER_BUSY':scenario==='protected-owner'?'MANAGER_BUSY':'INVALID_SELECTION');
  assert(!rows.some(row=>row.tag==='browser'),'failure occurs before Chromium');
  if(scenario!=='invalid-selection')assert.equal(await fs.readFile(path.join(data,'.manager.lock'),'utf8'),lock);
  else await assert.rejects(fs.stat(path.join(data,'.manager.lock')),{code:'ENOENT'});
  assert(!stderr.includes(marker));
 });
}
