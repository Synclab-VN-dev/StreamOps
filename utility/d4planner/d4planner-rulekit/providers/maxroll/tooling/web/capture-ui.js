#!/usr/bin/env node
'use strict';
const fs=require('node:fs/promises');
const path=require('node:path');
const {createHash}=require('node:crypto');
const {BrowserInfrastructure,FileSystemSnapshotStore,WebSnapshotManager}=require('../../../../browser-infra/src');
const {scenarios}=require('./ui-scenarios');
const {fullScenarios}=require('./full-scenarios');
const {devices}=require('../../../../browser-infra/node_modules/playwright-core');
const {moduleDependencies,htmlDependencies}=require('./resource-dependencies');
const {assertClassCoverage,collectSelectable,entityDependencies,auxiliaryDependencies,profileDependencies}=require('./catalog-coverage');
const {UI_ORIGINS:ORIGINS}=require('./ui-package');
const hash=b=>createHash('sha256').update(b).digest('hex');
function dependencies(text,base) {
  const urls=new Set();
  for (const pattern of [/url\(\s*["']?([^"'()]+)["']?\s*\)/g, /@import\s*["']([^"']+)["']/g]) {
    for (const match of text.matchAll(pattern)) {
      try {const u=new URL(match[1].trim(),base);if(ORIGINS.includes(u.origin))urls.add(u.href);}catch{}
    }
  }
  return [...urls];
}
async function capture(config, {browser: sharedBrowser} = {}) {
  for(const key of ['snapshotRoot','snapshotId','chromium','evidenceDir'])if(!config[key])throw Error('Required: '+key);
  const output=path.join(config.snapshotRoot,config.snapshotId);
  try {await fs.access(output);throw Error('Capture output already exists');}catch(e){if(e.code!=='ENOENT')throw e;}
  await fs.mkdir(config.evidenceDir,{recursive:true,mode:0o700});
  const browser=sharedBrowser || new BrowserInfrastructure({executablePath:config.chromium,headless:true,maxContexts:2,maxQueue:1,
    contextOptions:{serviceWorkers:'block',viewport:{width:1440,height:1100}}});
  const store=new FileSystemSnapshotStore({rootDir:config.snapshotRoot,limits:{maxResources:6000,maxResourceBytes:64*1024*1024,maxTotalBytes:512*1024*1024}});
  let nativeData,nativeProfile;
  const queue=new Set(),observed=new Set(),attempted=new Set(),fingerprints=new Map(),tasks=new Set(),responseHashes=new Map();
  const coverage={schemaVersion:'maxroll-ui-coverage/v1',startedAt:new Date().toISOString(),
    calculationStatus:'NOT_ASSESSED',scenarios:{},dependencies:[],unavailableDependencies:[],references:[],errors:[],status:'CAPTURING'};
  const manager=new WebSnapshotManager({store,browser:{withLease:(options,fn)=>browser.withLease(options,async lease=>{
    const page=lease.page;
        page.on('pageerror',e=>coverage.errors.push(e.message));
        const cdp=await page.context().newCDPSession(page);await cdp.send('Network.enable');await cdp.send('Network.setCacheDisabled',{cacheDisabled:true});
        page.on('response',r=>{
          observed.add(r.url());
          const task=(async()=>{
            const type=r.headers()['content-type']||'';
            if(r.url().includes('/profiles/load/d4/')&&r.status()===200)nativeProfile=JSON.parse((await r.json()).data);
            if(config.comprehensive&&r.status()===200){
              if(type.includes('javascript'))for(const url of moduleDependencies(await r.text(),r.url()))queue.add(url);
              if(type.includes('text/html'))for(const url of htmlDependencies(await r.text(),r.url()))queue.add(url);
            }
            if(type.includes('text/css'))for(const url of dependencies(await r.text(),r.url()))queue.add(url);
            if(/\/game\/data\.min\.json/.test(r.url())&&r.status()===200){const data=await r.json();nativeData=data;for(const node of Object.values(data.paragonNodes||{}))if(Number.isInteger(node.iconMask)&&node.iconMask>0)queue.add(new URL('/d4-tools/images/webp/'+node.iconMask+'.webp','https://assets-ng.maxroll.gg').href);}
            if(/\/assets\/export-|\/game\/data\.(?:min|enus)\.json/.test(r.url())&&r.status()===200)fingerprints.set(r.url(),hash(await r.body()));
          })().catch(e=>coverage.errors.push('Inventory '+r.url()+': '+e.message));
          tasks.add(task);task.finally(()=>tasks.delete(task));
        });
    await page.addLocatorHandler(page.getByText('No Thanks',{exact:true}),async locator=>locator.click());
    try {return await fn(lease);} catch(error) {
      await page.screenshot({path:path.join(config.evidenceDir,'failure.png')}).catch(()=>{});
      await fs.writeFile(path.join(config.evidenceDir,'failure-body.txt'),await page.locator('body').innerText().catch(()=>''));
      throw error;
    }
  })}});
  try {
    if(!sharedBrowser)await browser.start();
    const draft=await manager.capture({snapshotId:config.snapshotId,site:'maxroll-d4-planner-ui',version:'CAPTURED_UNVALIDATED',
      url:config.sourceUrl || 'https://maxroll.gg/d4/planner/',signal:config.signal,allowedOrigins:ORIGINS,timeoutMs:480000,maxResources:6000,maxResourceBytes:64*1024*1024,maxTotalBytes:512*1024*1024,
      capturePolicy:{responsePolicy:response=>{const digest=hash(response.body);const prior=responseHashes.get(response.url);if(prior&&prior!==digest)console.error('CONFLICT',response.url,prior,digest);responseHashes.set(response.url,digest);},requestHeaderPolicy:'fresh-anonymous-context',navigationWaitUntil:'domcontentloaded',settleWaitUntil:'domcontentloaded',
        completion:{minimumObservationMs:1000,quietWindowMs:1000},allowResource:({url,resourceType,method})=>method==='GET'&&resourceType!=='media'&&!/\/users\/whoami|\/js\/sponsor\.js|^\/api\/me$/.test(new URL(url).pathname)},
      interact:async({page})=>{
        // Include already-loaded CSS, then inspect computed backgrounds/borders/pseudo-elements at each state.
        async function inventory(){
          const urls=await page.evaluate(()=>{
            const urls=new Set();
            for(const e of document.querySelectorAll('*')){
              if(e.matches('img,source')){if(e.currentSrc||e.src)urls.add(e.currentSrc||e.src);for(const part of (e.srcset||'').split(',')){const v=part.trim().split(/\s+/)[0];if(v)urls.add(new URL(v,document.baseURI).href);}}
              for(const pseudo of [null,'::before','::after']){const s=getComputedStyle(e,pseudo);for(const v of [s.backgroundImage,s.borderImageSource,s.maskImage])for(const m of v.matchAll(/url\(["']?([^"')]+)["']?\)/g))urls.add(new URL(m[1],document.baseURI).href);}
            }
            for(const s of document.styleSheets)if(s.href)urls.add(s.href);
            return [...urls];
          });
          for(const url of urls)if(ORIGINS.includes(new URL(url).origin))queue.add(url);
          for(let round=0;round<24;round++){
            await Promise.all([...tasks]);
            const pending=[...queue].filter(u=>!observed.has(u)&&!attempted.has(u));if(!pending.length)break;
            coverage.dependencies.push(...pending);for(const url of pending)attempted.add(url);
            for(let i=0;i<pending.length;i+=8){const outcomes=await page.evaluate(async urls=>Promise.all(urls.map(async url=>{try{const r=await fetch(url,{credentials:'omit',cache:'no-store',mode:'cors'});await r.arrayBuffer();return {url,status:r.status};}catch{return {url,status:'FETCH_FAILED'};}})),pending.slice(i,i+8));coverage.unavailableDependencies.push(...outcomes.filter(r=>r.status!==200));}
          }
          await page.waitForTimeout(400);
        }
        await page.getByRole('button',{name:'New Profile',exact:true}).waitFor({timeout:45000});
        coverage.version=(await page.locator('body').innerText()).match(/Game version:\s*([\d.]+)/)?.[1];
        // Capture the loaded profile's images before New Profile replaces its DOM.
        await page.waitForTimeout(1500);await inventory();
        await page.evaluate(()=>window.scrollTo(0,document.body.scrollHeight));await inventory();
        await page.evaluate(()=>window.scrollTo(0,0));
        coverage.scenarios.desktop=await scenarios(page,{checkpoint:async(label,locator)=>{
          await inventory();await locator.scrollIntoViewIfNeeded();await page.mouse.move(0,0);await page.waitForTimeout(300);
          const file='desktop-'+label+'.png';await locator.screenshot({path:path.join(config.evidenceDir,file),animations:'disabled',scale:'css'});
          coverage.references.push({viewport:'desktop',state:label,file});
        }});
        if(config.comprehensive){
          coverage.scenarios.full=await fullScenarios(page);
          // Google Fonts varies CSS and immutable WOFF URLs by browser UA. Discover the mobile
          // response in a separate clean lease, then capture its font bodies in this package.
          coverage.fontVariants=await browser.withLease({},async lease=>{
            const mobile=lease.page,cdp=await mobile.context().newCDPSession(mobile);
            await cdp.send('Network.enable');await cdp.send('Network.setCacheDisabled',{cacheDisabled:true});
            await cdp.send('Network.setUserAgentOverride',{userAgent:devices['Pixel 7'].userAgent});
            await mobile.context().route('**/*',route=>route.request().method()==='GET'&&new URL(route.request().url()).hostname==='fonts.googleapis.com'?route.continue():route.abort());
            const variants=[];
            for(const url of [...observed].filter(url=>new URL(url).hostname==='fonts.googleapis.com')){
              const response=await mobile.goto(url);if(response.status()!==200)throw Error('Mobile font stylesheet unavailable');
              const bytes=await response.body(),urls=dependencies(bytes.toString(),url);
              if(!urls.length)throw Error('Mobile font stylesheet has no font dependencies');
              variants.push({url,userAgent:devices['Pixel 7'].userAgent,sha256:hash(bytes),dependencies:urls});for(const font of urls)queue.add(font);
            }return variants;
          });
          coverage.selectable=await collectSelectable(page);
          if(!nativeData)throw Error('Native catalog absent');
          assertClassCoverage(nativeData,coverage.selectable);
          coverage.entityDependencies=entityDependencies(nativeData,coverage.selectable);
          coverage.auxiliaryDependencies=auxiliaryDependencies(nativeData);
          if(!nativeProfile)throw Error('Captured native profile missing');
          coverage.profileDependencies=profileDependencies(nativeData,nativeProfile);
          for(const row of coverage.profileDependencies)for(const image of row.images)queue.add(image.url);
          for(const row of coverage.entityDependencies)for(const image of row.images)queue.add(image.url);
          for(const row of coverage.auxiliaryDependencies)queue.add(row.url);
          await inventory();
        }
        coverage.scenarios.mobile={mode:'PENDING_SEPARATE_CLEAN_PROFILE_REFERENCE'};
        await Promise.all([...tasks]);
        const before=new Map(fingerprints);
        await page.evaluate(async urls=>{for(const url of urls)await fetch(url,{credentials:'omit',cache:'no-store',mode:'cors'}).then(r=>r.arrayBuffer());},[...before.keys()]);
        await Promise.all([...tasks]);
        if(before.size<3||[...before].some(([url,digest])=>fingerprints.get(url)!==digest))throw Error('UI fingerprint missing or changed during capture');
        coverage.fingerprints=Object.fromEntries(before);
      }});
    if(coverage.errors.length)throw Error('Capture runtime/inventory errors: '+coverage.errors.join('; '));
    await manager.save({...draft,version:coverage.version});
    const verified=await manager.verify(config.snapshotId);
    coverage.status='CAPTURED_UNVALIDATED';coverage.finishedAt=new Date().toISOString();coverage.integrity=verified;coverage.completion=draft.capture?.completion;
    await fs.writeFile(path.join(output,'ui-coverage.json'),JSON.stringify(coverage,null,2),{flag:'wx',mode:0o600});
    console.log(JSON.stringify({snapshotId:config.snapshotId,...verified,status:coverage.status}));
    return coverage;
  }catch(error){coverage.status='FAILED';coverage.failure=error.message;throw error;}
  finally{if(!sharedBrowser)await browser.stop();coverage.cleanup=browser.getStatus();await fs.writeFile(path.join(config.evidenceDir,'capture-report.json'),JSON.stringify(coverage,null,2),{mode:0o600});}
}
if(require.main===module)fs.readFile(process.argv[2],'utf8').then(JSON.parse).then(capture).catch(e=>{console.error(e);process.exitCode=1;});
module.exports={capture,dependencies,ORIGINS,hash};
