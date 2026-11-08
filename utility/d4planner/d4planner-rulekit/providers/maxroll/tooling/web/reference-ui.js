#!/usr/bin/env node
'use strict';
// Explicit online reference command only. HTTP replay never imports or calls this tool.
const fs=require('node:fs/promises');
const path=require('node:path');
const assert=require('node:assert/strict');
const {chromium,devices}=require('../../../../browser-infra/node_modules/playwright-core');
const {FileSystemSnapshotStore}=require('../../../../browser-infra/src');
const {hash,ORIGINS}=require('./capture-ui');
const {scenarios}=require('./ui-scenarios');
const {screenshotState}=require('./visual-state');
async function reference(config){
  const store=new FileSystemSnapshotStore({rootDir:config.snapshotRoot});
  const verified=await store.verify(config.snapshotId);
  assert.equal(verified.manifestSha256,config.manifestSha256);
  const manifest=await store.load(config.snapshotId),byUrl=new Map(manifest.resources.map(r=>[r.url,r]));
  try { if((await fs.readdir(config.referenceDir)).length)throw Error('Reference directory must be empty; preserve previous evidence'); } catch(error) { if(error.code!=='ENOENT')throw error; }
  const browser=await chromium.launch({executablePath:config.chromium});
  const results=[];await fs.mkdir(config.referenceDir,{recursive:true,mode:0o700});
  try{
    for(const [name,size] of [['desktop',{width:1440,height:1100}],['mobile',{width:412,height:839}]]){
      const context=await browser.newContext({...(name==='mobile'?devices['Pixel 7']:{}),deviceScaleFactor:1,viewport:size,serviceWorkers:'block'});
      await context.route('**/*',route=>{const r=route.request(),u=new URL(r.url());
        return r.method()==='GET'&&ORIGINS.includes(u.origin)&&!(/\/users\/whoami|\/js\/sponsor\.js|^\/api\/me$/.test(u.pathname))?route.continue():route.abort('blockedbyclient');});
      const page=await context.newPage(),tasks=[],mismatches=[],errors=[],seen=new Set(),uncaptured=[];
      page.on('pageerror',e=>errors.push(e.message));
      page.on('response',r=>{const type=r.headers()['content-type']||'';
        if(/javascript|text\/css|application\/json|image\/|font\//.test(type)&&r.status()===200){
          const task=(async()=>{const expected=byUrl.get(r.url());if(!expected){uncaptured.push(r.url());return;}
            const digest=hash(await r.body());if(digest!==expected.sha256)mismatches.push({url:r.url(),expected:expected.sha256,actual:digest,classification:new URL(r.url()).hostname==='fonts.googleapis.com'?'USER_AGENT_FONT_CSS_VARIANT':'RUNTIME_DRIFT'});seen.add(r.url());})();tasks.push(task);
        }});
      await page.addLocatorHandler(page.getByText('No Thanks',{exact:true}),async locator=>locator.click());
      await page.goto(manifest.sourceUrl,{waitUntil:'domcontentloaded'});
      const observed=await scenarios(page,{checkpoint:async(label,locator)=>{
        await page.evaluate(()=>document.fonts.ready);await locator.scrollIntoViewIfNeeded();await page.mouse.move(0,0);await page.waitForTimeout(300);
        await screenshotState(page,locator,path.join(config.referenceDir,name+'-'+label+'.png'));
      }});
      await Promise.all(tasks);
      const core=[...byUrl.keys()].filter(u=>/\/assets\/export-|\/game\/data\.(?:min|enus)\.json/.test(u));
      assert(core.length>=3&&core.every(u=>seen.has(u)),'Online reference must observe captured runtime fingerprints');
      results.push({name,observed,checkedResources:seen.size,mismatches,uncaptured,errors});
      await context.close();
    }
    assert(results.every(r=>r.mismatches.every(m=>m.classification==='USER_AGENT_FONT_CSS_VARIANT')&&r.errors.length===0),'Online reference drift/runtime error');
  }finally{await browser.close();await fs.writeFile(path.join(config.referenceDir,'reference-report.json'),JSON.stringify({manifestSha256:config.manifestSha256,results},null,2),{mode:0o600});}
  console.log(JSON.stringify(results,null,2));
}
if(require.main===module)fs.readFile(process.argv[2],'utf8').then(JSON.parse).then(reference).catch(e=>{console.error(e);process.exitCode=1;});
module.exports={reference};
