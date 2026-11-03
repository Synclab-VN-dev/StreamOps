#!/usr/bin/env node
'use strict';
const fs=require('node:fs/promises'),path=require('node:path'),net=require('node:net'),assert=require('node:assert/strict');
const {execFile}=require('node:child_process'),{promisify}=require('node:util'),{createHash}=require('node:crypto');
const exec=promisify(execFile),sha=b=>createHash('sha256').update(b).digest('hex');
const {audit}=require('./resource-audit');const {startServer}=require('./server');
const root=path.resolve(__dirname,'../../../..'),provider=path.resolve(__dirname,'../..');
async function freePort(){const s=net.createServer();await new Promise((r,j)=>{s.once('error',j);s.listen(0,'127.0.0.1',r);});const port=s.address().port;await new Promise(r=>s.close(r));return port;}
async function run(config){
  process.umask(0o077);const output=path.resolve(config.output);await fs.mkdir(output,{recursive:false,mode:0o700});
  const head=(await exec('git',['rev-parse','HEAD'],{cwd:__dirname})).stdout.trim();
  const dirty=(await exec('git',['status','--porcelain'],{cwd:__dirname})).stdout.trim();
  const connect=net.Socket.prototype.connect;let outboundAttempts=0;
  // Observe the server process without blocking or supplying any network response. Browser tests run in child processes.
  net.Socket.prototype.connect=function(...args){outboundAttempts++;return connect.apply(this,args);};
  const phases={},startedAt=new Date().toISOString();let running;
  const env={...process.env,CHROMIUM_EXECUTABLE:config.chromium,BROWSER_INFRA_CHROMIUM_PATH:config.chromium};
  async function phase(name,fn){const start=Date.now();try{const result=await fn();phases[name]={status:'PASS',durationMs:Date.now()-start,...result};}catch(error){phases[name]={status:'FAIL',durationMs:Date.now()-start,error:error.message};}console.log(name+': '+phases[name].status);}
  async function command(name,bin,args,cwd=__dirname,extraEnv={}){
    let result;try{result=await exec(bin,args,{cwd,env:{...env,...extraEnv},timeout:600000,maxBuffer:16*1024*1024});}catch(e){result=e;throw e;}finally{if(result)await fs.writeFile(path.join(output,name+'.log'),(result.stdout||'')+(result.stderr||''));}
    return {command:[bin,...args],evidence:name+'.log'};
  }
  try{
    await phase('git-clean',async()=>{assert.equal(dirty,'','Final acceptance requires a clean committed HEAD');return {head};});
    await phase('reference',async()=>{
      const bytes=await fs.readFile(path.join(config.referenceDir,'report.json'));assert.equal(sha(bytes),config.referenceReportSha256,'Pinned reference report');const report=JSON.parse(bytes);
      assert.equal(report.status,'PASS');assert.equal(report.mode,'ONLINE_REFERENCE');assert.equal(report.manifestSha256,config.manifestSha256);assert.equal(report.results.length,2);
      assert(Object.keys(report.artifactHashes).length>=210);
      for(const [file,digest]of Object.entries(report.artifactHashes)){assert.equal(path.basename(file),file);assert.equal(sha(await fs.readFile(path.join(config.referenceDir,file))),digest,'Unmodified online reference '+file);}
      return {evidence:config.referenceDir};
    });
    await phase('resource',async()=>{const report=await audit(config);await fs.writeFile(path.join(output,'resource-audit.json'),JSON.stringify(report,null,2));assert.equal(report.status,'PASS');return {groups:report.groups,selectableEntities:report.selectableEntities,evidence:'resource-audit.json'};});
    const serverConfig={...config,port:await freePort()};delete serverConfig.output;
    await fs.writeFile(path.join(output,'server-config.json'),JSON.stringify(serverConfig));
    await phase('server',async()=>{running=await startServer(serverConfig);return {port:serverConfig.port};});
    const webTests=(await fs.readdir(__dirname)).filter(f=>f.endsWith('.test.js')).map(f=>path.join(__dirname,f));
    await phase('unit-security',()=>command('unit-security','node',['--test',...webTests]));
    // Ordinary HTTP browser, no Playwright interception or online fallback. Reference is already frozen.
    if(running){
      const browserConfig={...serverConfig,online:false,url:`http://127.0.0.1:${serverConfig.port}/`,output:path.join(output,'http')};
      await fs.writeFile(path.join(output,'browser-config.json'),JSON.stringify(browserConfig));
      await phase('browser',()=>command('browser','node',['full-ui-check.js',path.join(output,'browser-config.json')]));
      await fs.writeFile(path.join(output,'export-config.json'),JSON.stringify({...browserConfig,evidenceDir:path.join(output,'export')}));
      await phase('export',()=>command('export','node',['export-check.js',path.join(output,'export-config.json')]));
      if(phases.reference.status==='PASS'&&phases.browser.status==='PASS')await phase('visual',()=>command('visual','python3',['full-visual-check.py',config.referenceDir,path.join(output,'http')]));
      await fs.writeFile(path.join(output,'diagnostics.json'),JSON.stringify(running.diagnostics(),null,2));
    }
    await phase('lifecycle',()=>command('lifecycle','python3',['lifecycle-check.py'],__dirname,{LOCAL_EDITOR_CONFIG:path.join(output,'server-config.json')}));
    for(const component of ['application','providers/maxroll','browser-infra','snapshot-management'])await phase(component,()=>command(component.replaceAll('/','-'),'npm',['test'],path.join(root,component)));
    await phase('calculation-real',async()=>{
      assert(config.calculation,'Pinned unchanged calculation fixture configuration required');const c=config.calculation;
      return command('calculation-real','npm',['run','test:real'],provider,{MAXROLL_AUTHORIZED_SNAPSHOT_ROOT:c.snapshotRoot,MAXROLL_AUTHORIZED_SNAPSHOT_ID:c.snapshotId,MAXROLL_AUTHORIZED_MANIFEST_SHA256:c.manifestSha256,MAXROLL_SNAPSHOT_AUTHORIZATION_REF:c.authorizationRef,MAXROLL_SOURCE_URL:c.sourceUrl,MAXROLL_REAL_PROFILE_ID:c.profileId});
    });
  }finally{
    await phase('git-clean-final',async()=>{assert.equal((await exec('git',['rev-parse','HEAD'],{cwd:__dirname})).stdout.trim(),head,'HEAD must remain unchanged throughout acceptance');assert.equal((await exec('git',['status','--porcelain'],{cwd:__dirname})).stdout.trim(),'','Repository must remain clean throughout acceptance');return {head};});
    net.Socket.prototype.connect=connect;
    await phase('server-network',async()=>{assert.equal(outboundAttempts,0,'Replay server makes no outbound TCP connection');return {outboundAttempts};});
    if(running)await phase('cleanup',async()=>{const port=running.server.address().port;await running.close();const s=net.createServer();await new Promise((r,j)=>{s.once('error',j);s.listen(port,'127.0.0.1',r);});await new Promise(r=>s.close(r));return {portReleased:true};});
    const definitions=[
      ['FULL-01','UI integrity and provenance',['git-clean','git-clean-final','resource','server']],['FULL-02','Selectable entity and static dependency closure',['resource','browser','export']],
      ['FULL-03','Equipment artwork coverage and image decode',['resource','browser','export','visual']],['FULL-04','Picker/editor/equipped/tooltip and modifiers',['browser','visual']],
      ['FULL-05','Skill allocation/refund/icons',['resource','browser','export','visual']],['FULL-06','Paragon nodes/glyph/board/rotate/pan/zoom',['resource','browser','export','visual']],
      ['FULL-07','Profiles/classes/levels',['browser','export']],['FULL-08','Native UI export and actual download',['browser','export']],
      ['FULL-09','Lossless native import/export and rejection',['browser','export','unit-security']],['FULL-10','Desktop/mobile emulation interactions',['browser','export']],
      ['FULL-11','Pinned same-version online visual comparison and negative mutations',['reference','visual']],['FULL-12','Client/server offline boundaries',['browser','export','unit-security','server-network']],
      ['FULL-13','Reload/restart/port isolation/cleanup',['browser','lifecycle','cleanup']],['FULL-14','Existing calculation regressions',['application','providers/maxroll','browser-infra','snapshot-management','calculation-real']]
    ];
    const ledger=definitions.map(([id,expected,deps])=>({id,expected,status:deps.some(d=>phases[d]?.status==='FAIL')?'FAIL':deps.every(d=>phases[d]?.status==='PASS')?'PASS':'NOT_RUN',actual:deps.map(d=>({phase:d,...phases[d]})),owner:'F AUTO'}));
    const automated=ledger.every(r=>r.status==='PASS');ledger.push({id:'FULL-15',expected:'One final real Android handoff after every automated gate passes',status:automated?'PASS':'BLOCKED',actual:{readiness:automated,android:'NOT_RUN'},owner:'F AUTO readiness / Owner MAN device'});
    const report={schemaVersion:'maxroll-full-acceptance/v1',head,dirty:!!dirty,startedAt,finishedAt:new Date().toISOString(),snapshotId:config.snapshotId,manifestSha256:config.manifestSha256,status:automated?'AUTOMATED_PASS':'FAIL',android:'NOT_RUN',ci:'CI_NOT_CHECKED',phases,ledger};
    await fs.writeFile(path.join(output,'acceptance.json'),JSON.stringify(report,null,2));
    await fs.writeFile(path.join(output,'acceptance.md'),`# Local full acceptance\n\nHEAD: ${head}; dirty: ${!!dirty}\n\n${report.status}; Android MAN NOT_RUN; CI_NOT_CHECKED\n\n| ID | Expected | Actual | Owner |\n|---|---|---|---|\n`+ledger.map(r=>`| ${r.id} | ${r.expected} | ${r.status} | ${r.owner} |`).join('\n')+'\n\nDetails and evidence: acceptance.json; raw private files must not be published.\n');
    if(!automated)process.exitCode=1;
  }
}
if(require.main===module)fs.readFile(process.argv[2],'utf8').then(JSON.parse).then(run).catch(e=>{console.error(e);process.exitCode=1;});
module.exports={run};
