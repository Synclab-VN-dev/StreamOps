#!/usr/bin/env node
'use strict';
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict'),{createHash}=require('node:crypto');
const {chromium,devices}=require('../../../../browser-infra/node_modules/playwright-core');
const {FileSystemSnapshotStore}=require('../../../../browser-infra/src');
const {UI_ORIGINS}=require('./ui-package');const {mappedUrl}=require('./server');const {fullScenarios}=require('./full-scenarios');const {collectSelectable,normalizeCoverage}=require('./catalog-coverage');
const hash=b=>createHash('sha256').update(b).digest('hex');
async function run(config){
  const store=new FileSystemSnapshotStore({rootDir:config.snapshotRoot});assert.equal((await store.verify(config.snapshotId)).manifestSha256,config.manifestSha256);
  const receipt=JSON.parse(await fs.readFile(path.join(config.snapshotRoot,config.snapshotId,'ui-coverage.json')));
  const manifest=await store.load(config.snapshotId),expected=new Map(manifest.resources.map(r=>[r.url,r]));
  await fs.mkdir(config.output,{recursive:false,mode:0o700});
  const results=[],browser=await chromium.launch({executablePath:config.chromium});let failure;const artifactHashes={};
  try{for(const mobile of [false,true]){
    const size=mobile?{width:412,height:839}:{width:1440,height:1100};const name=mobile?'mobile':'desktop';
    const ctx=await browser.newContext({...(mobile?devices['Pixel 7']:{}),viewport:size,deviceScaleFactor:1,serviceWorkers:'block',acceptDownloads:true});
    if(config.online)await ctx.route('**/*',route=>{const r=route.request(),u=new URL(r.url());return r.method()==='GET'&&UI_ORIGINS.includes(u.origin)&&!(/\/users\/whoami|\/js\/sponsor\.js|^\/api\/me$/.test(u.pathname))?route.continue():route.abort('blockedbyclient');});
    ctx.setDefaultTimeout(30000);const page=await ctx.newPage(),errors=[],responses=[],attempts=[],failed=[],missing=[],fingerprints={},drift=[],tasks=[],consoleErrors=[];
    const origin=config.online?new URL(manifest.sourceUrl).origin:new URL(config.url).origin;
    page.on('console',m=>{if(m.type()==='error'){const message=m.text(),url=m.location().url;const expectedNetwork=/Failed to load resource:|Content Security Policy|Content-Security-Policy|blocked by CORS policy|net::ERR_FAILED/.test(message);consoleErrors.push({kind:expectedNetwork?'NETWORK_POLICY':'UNEXPECTED',url: url?new URL(url).origin+new URL(url).pathname:null,messageSha256:hash(message)});}});
    page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(!config.online&&new URL(r.url()).origin!==origin)attempts.push(r.url());});
    page.on('requestfailed',r=>{if(!config.online&&new URL(r.url()).origin!==origin)failed.push(r.failure()?.errorText);});
    page.on('response',r=>{
      if(config.online&&r.status()>=400)missing.push({url:r.url(),status:r.status()});
      if(!config.online){if(new URL(r.url()).origin!==origin)responses.push(r.url());if(r.status()>=400)missing.push({url:r.url(),status:r.status()});}
      else if(r.status()===200){const exp=expected.get(r.url());if(!exp){if(['script','stylesheet','image','font'].includes(r.request().resourceType()))drift.push('UNCAPTURED_ASSET '+r.url());return;}const type=r.headers()['content-type']||'';
        if(/javascript|text\/css|image\/|font\//.test(type)||r.url().includes('/game/data.'))tasks.push((async()=>{const digest=hash(await r.body());fingerprints[r.url()]=digest;if(digest!==exp.sha256&&!(receipt.fontVariants||[]).some(v=>v.url===r.url()&&v.sha256===digest))drift.push(r.url());})().catch(()=>{drift.push('RESPONSE_BODY_UNAVAILABLE '+r.url());}));}
    });
    await page.goto(config.online?manifest.sourceUrl:config.url);
    let surface=page;
    if(!config.online){for(let i=0;i<2;i++){const h=await page.locator('header').boundingBox();await page.setViewportSize({width:size.width,height:size.height+Math.ceil(h.height)});}surface=page.frames()[1];}
    await page.addLocatorHandler(config.online?page.getByText('No Thanks',{exact:true}):page.frameLocator('iframe').getByText('No Thanks',{exact:true}),l=>l.click());
    const screenshots=[];
    const observed=await fullScenarios(surface,{checkpoint:async(label,locator,{icon,tooltip,title}={})=>{
      console.log(name+' '+label);await surface.evaluate(()=>document.fonts.ready);if(!tooltip){await locator.scrollIntoViewIfNeeded();await page.mouse.move(0,0);}await page.waitForTimeout(180);
      const file=name+'-'+label+'.png';if(tooltip){
        const box=await locator.boundingBox();const bounds=config.online?{x:0,y:0,...page.viewportSize()}:await page.locator('iframe').boundingBox();
        const x=Math.max(box.x,bounds.x),y=Math.max(box.y,bounds.y);const clip={x,y,width:Math.min(box.x+box.width,bounds.x+bounds.width)-x,height:Math.min(box.y+box.height,bounds.y+bounds.height)-y};
        assert(clip.width>0&&clip.height>0,'Tooltip visible in native viewport');
        await page.screenshot({path:path.join(config.output,file),clip,animations:'disabled',scale:'css'});
        if(title)assert((await locator.innerText()).includes(title),'Tooltip identity remains stable');
      }else await locator.screenshot({path:path.join(config.output,file),animations:'disabled',scale:'css'});screenshots.push(file);
      if(icon){const iconFile=name+'-'+label+'-artwork.png';await icon.screenshot({path:path.join(config.output,iconFile),animations:'disabled',scale:'css'});screenshots.push(iconFile);
        if(!config.online){const style=await icon.getAttribute('style');await icon.evaluate(el=>el.style.backgroundImage='none');await icon.screenshot({path:path.join(config.output,'negative-'+iconFile),animations:'disabled',scale:'css'});await icon.evaluate((el,style)=>style===null?el.removeAttribute('style'):el.setAttribute('style',style),style);}}
    }});
    if(!config.online){
      await surface.getByRole('button',{name:'My Profiles',exact:true}).click();await surface.locator('input.d4t-save-name').fill('Full QA edited build');
      const downloading=page.waitForEvent('download');await surface.locator('.d4t-section-save button').last().click();const d=await downloading;assert.equal(await d.failure(),null);
      const file=path.join(config.output,name+'-edited-native.json');await d.saveAs(file);const e=JSON.parse(await fs.readFile(file));const active=e.nativeState.profiles[e.nativeState.activeProfile],item=e.nativeState.items[active.items['4']];
      assert(item.explicits?.length&&item.tempered?.length&&item.aspects?.length);assert.equal(typeof item.sockets[0],'string');assert.equal(item.sockets[1],null);
      await page.locator('#import-build').setInputFiles(file);await page.getByText('Native file loaded into this tab.',{exact:false}).waitFor();surface=page.frames()[1];await surface.getByRole('button',{name:'My Profiles',exact:true}).waitFor();
      await page.getByRole('button',{name:'Export JSON',exact:true}).click();await surface.locator('input.d4t-save-name').fill('Full QA roundtrip');
      const again=page.waitForEvent('download');await surface.locator('.d4t-section-save button').last().click();const downloaded=await again;assert.equal(await downloaded.failure(),null);
      const againFile=path.join(config.output,name+'-edited-roundtrip.json');await downloaded.saveAs(againFile);assert.deepEqual(JSON.parse(await fs.readFile(againFile)).nativeState,e.nativeState,'Complete edited native state roundtrip');
      if(!mobile){const decode=[];const images=manifest.resources.filter(r=>r.headers['content-type']?.startsWith('image/'));
        for(let offset=0;offset<images.length;offset+=32)decode.push(...await page.evaluate(async urls=>Promise.all(urls.map(async url=>{try{const image=new Image();image.src=url;await image.decode();if(!image.naturalWidth||!image.naturalHeight)throw Error('Empty image');return {url,width:image.naturalWidth,height:image.naturalHeight,status:'PASS'};}catch(e){return {url,status:'FAIL',error:e.message};}})),images.slice(offset,offset+32).map(r=>mappedUrl(r.url,origin))));
        await fs.writeFile(path.join(config.output,'image-decode.json'),JSON.stringify(decode,null,2));assert(decode.length>0&&decode.every(r=>r.status==='PASS'),'Every captured image decodes in Chromium through HTTP');}
      await page.reload();surface=page.frames()[1];await surface.getByRole('button',{name:'New Profile',exact:true}).click();
      const coverage=await collectSelectable(surface);
      const captured=JSON.parse(await fs.readFile(path.join(config.snapshotRoot,config.snapshotId,'ui-coverage.json'))).selectable;assert.deepEqual(normalizeCoverage(coverage),normalizeCoverage(captured),'HTTP native selectable model equals complete captured inventory');await fs.writeFile(path.join(config.output,name+'-selectable.json'),JSON.stringify(coverage,null,2));
      const impacting=missing.filter(r=>!(/\/api\/me$|\/users\/whoami$|\/api\/twitch|favicon|apple-touch-icon/.test(new URL(r.url).pathname)));
      assert.deepEqual(impacting,[],'No impacting HTTP misses');assert.deepEqual(responses,[]);assert.equal(attempts.length,failed.length);assert(failed.every(x=>['csp','net::ERR_BLOCKED_BY_CSP'].includes(x)));
    }else{
      await Promise.all(tasks);const core=manifest.resources.filter(r=>/\/assets\/export-|\/game\/data\.(?:min|enus)\.json/.test(r.url));assert(core.length>=3&&core.every(r=>fingerprints[r.url]===r.sha256),'Same-version online fingerprints required');assert.deepEqual(drift,[],'Online resource drift');
    }
    assert.deepEqual(errors,[]);assert.deepEqual(consoleErrors.filter(e=>e.kind==='UNEXPECTED'),[],'No unexplained browser console errors');for(const file of screenshots)artifactHashes[file]=hash(await fs.readFile(path.join(config.output,file)));results.push({name,observed,screenshots,errors,consoleErrors,externalAttempts:attempts.length,externalResponses:responses,missing,fingerprints});await ctx.close();
  }}catch(error){failure=error.message;throw error;}finally{await browser.close();await fs.writeFile(path.join(config.output,'report.json'),JSON.stringify({snapshotId:config.snapshotId,manifestSha256:config.manifestSha256,mode:config.online?'ONLINE_REFERENCE':'HTTP_REPLAY',status:failure?'FAIL':'PASS',failure,results,artifactHashes,browserClosed:!browser.isConnected(),android:'NOT_RUN'},null,2));}
}
if(require.main===module)fs.readFile(process.argv[2],'utf8').then(JSON.parse).then(run).catch(e=>{console.error(e);process.exitCode=1;});
module.exports={run};
