#!/usr/bin/env node
'use strict';
const fs=require('node:fs/promises');
const path=require('node:path');
const assert=require('node:assert/strict');
const {chromium,devices}=require('../../../../browser-infra/node_modules/playwright-core');
const {scenarios}=require('./ui-scenarios');
const {screenshotState}=require('./visual-state');
async function verify(config){
  const browser=await chromium.launch({executablePath:config.chromium});
  const results=[];
  await fs.mkdir(config.evidenceDir,{recursive:true,mode:0o700});
  try{
    for(const [name,size] of [['desktop',{width:1440,height:1100}],['mobile',{width:412,height:839}]]){
      const context=await browser.newContext({...(name==='mobile'?devices['Pixel 7']:{}),deviceScaleFactor:1,viewport:size});
      const page=await context.newPage(),errors=[],missing=[],external=[],blocked=[],consoleErrors=[],externalAttempts=[];
      const origin=new URL(config.url).origin;
      page.on('request',r=>{if(new URL(r.url()).origin!==origin)externalAttempts.push(r.url());});
      page.on('pageerror',e=>errors.push(e.message));
      page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text());});
      page.on('response',r=>{const u=new URL(r.url());if(u.origin!==origin)external.push({url:r.url(),status:r.status()});if(r.status()>=400)missing.push({url:u.pathname,status:r.status()});});
      page.on('requestfailed',r=>blocked.push({url:r.url(),reason:r.failure()?.errorText}));
      await page.goto(config.url);
      // Match the online reference's INNER viewport, not the wrapper's viewport.
      for(let i=0;i<2;i++){const header=await page.locator('header').boundingBox();await page.setViewportSize({width:size.width,height:size.height+Math.ceil(header.height)});}
      const frame=page.frames()[1];
      await page.addLocatorHandler(page.frameLocator('iframe').getByText('No Thanks',{exact:true}),async locator=>locator.click());
      const screenshots=[];
      const observed=await scenarios(frame,{checkpoint:async(label,locator)=>{
        await frame.evaluate(()=>document.fonts.ready);await locator.scrollIntoViewIfNeeded();await page.mouse.move(0,0);await page.waitForTimeout(300);
        const file=name+'-'+label+'.png';await screenshotState(frame,locator,path.join(config.evidenceDir,file));screenshots.push(file);
      }});
      for(let reload=0;reload<2;reload++){
        await page.reload();
        const reloaded=page.frames()[1];
        await reloaded.getByRole('button',{name:'New Profile',exact:true}).click({timeout:45000});
        await reloaded.locator('[class*="header_ClassOption"]').first().click();
        await reloaded.getByText('Rogue',{exact:true}).last().click();
      }
      observed.reloads=2;
      assert.deepEqual(errors,[],'No React/JavaScript failures');
      assert.deepEqual(external,[],'No external HTTP responses during replay');
      const externalFailures=blocked.filter(r=>new URL(r.url).origin!==origin);
      assert.equal(externalFailures.length,externalAttempts.length,'Every external attempt failed');
      assert(externalFailures.every(r=>['csp','net::ERR_BLOCKED_BY_CSP'].includes(r.reason)),'External attempts blocked by client CSP');
      const impacting=missing.filter(r=>!r.url.endsWith('/users/whoami')&&!r.url.includes('/api/twitch')&&r.url!=='/api/me'&&!/favicon|apple-touch-icon/.test(r.url));
      results.push({name,observed,screenshots,errors,consoleErrors,missing,impacting,external,externalAttempts,blocked});
      await context.close();
    }
  }finally{await browser.close();await fs.writeFile(path.join(config.evidenceDir,'http-ui-report.json'),JSON.stringify({results,android:'NOT_RUN_NEW_PACKAGE'},null,2),{mode:0o600});}
  console.log(JSON.stringify(results.map(({name,observed,errors,impacting,external})=>({name,observed,errors,impacting,external})),null,2));
  assert(results.every(r=>r.impacting.length===0),'Replay missing resources affect UI scope');
}
if(require.main===module)fs.readFile(process.argv[2],'utf8').then(JSON.parse).then(verify).catch(e=>{console.error(e);process.exitCode=1;});
module.exports={verify};
