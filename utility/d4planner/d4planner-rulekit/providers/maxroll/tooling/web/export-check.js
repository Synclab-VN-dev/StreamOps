#!/usr/bin/env node
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const {chromium,devices}=require('../../../../browser-infra/node_modules/playwright-core');
const {scenarios}=require('./ui-scenarios');
async function run(config){
  await fs.mkdir(config.evidenceDir,{recursive:true,mode:0o700});
  const browser=await chromium.launch({executablePath:config.chromium});const results=[];
  try{for(const mobile of [false,true]){
    const context=await browser.newContext({...(mobile?devices['Pixel 7']:{viewport:{width:1440,height:1100}}),acceptDownloads:true});
    context.setDefaultTimeout(30000);const page=await context.newPage();const errors=[],external=[],payloads=[],externalAttempts=[],externalFailures=[];
    page.on('request',r=>{if(new URL(r.url()).origin!==new URL(config.url).origin)externalAttempts.push(r.url());});
    page.on('requestfailed',r=>{if(new URL(r.url()).origin!==new URL(config.url).origin)externalFailures.push(r.failure()?.errorText);});
    page.on('pageerror',e=>errors.push(e.message));
    page.on('response',r=>{if(new URL(r.url()).origin!==new URL(config.url).origin)external.push(r.url());});
    page.on('request',r=>{if(r.url().endsWith('/__local/export'))payloads.push(r.postDataJSON());});
    await page.goto(config.url);let frame=page.frames()[1];
    await page.addLocatorHandler(page.frameLocator('iframe').getByText('No Thanks',{exact:true}),l=>l.click());

    async function download(suffix){
      await page.getByRole('button',{name:'Export JSON',exact:true}).click();
      await frame.locator('input.d4t-save-name').fill('Local native export');
      const pending=page.waitForEvent('download');
      await frame.locator('.d4t-section-save button').last().click();
      const file=await pending;
      assert.equal(await file.failure(),null);
      assert.equal(file.suggestedFilename(),'maxroll-native-build.json');
      const target=path.join(config.evidenceDir,(mobile?'mobile':'desktop')+'-'+suffix+'.json');
      await file.saveAs(target);const exported=JSON.parse(await fs.readFile(target,'utf8'));
      assert.deepEqual(exported.nativeState,JSON.parse(payloads.at(-1).data),'Every native field equals actual UI Save serializer output');
      return {exported,target};
    }
    await frame.getByRole('button',{name:'My Profiles',exact:true}).waitFor();
    const rich=await download('captured-profile');
    await frame.locator('[class*=profiles_ProfileDialog]').locator(':scope > [class*=DialogHeader] button').last().click();
    const previous=rich.exported.nativeState.activeProfile,alternate=previous===0?1:0;
    await frame.locator('[class*=sets_SetOption__name]').nth(alternate).click();
    const switched=await download('switched-profile');assert.equal(switched.exported.nativeState.activeProfile,alternate,'Native profile selection changes the serialized active profile');
    await frame.locator('[class*=profiles_ProfileDialog]').locator(':scope > [class*=DialogHeader] button').last().click();
    await frame.locator('[class*=sets_SetOption__name]').nth(previous).click();
    await page.locator('#import-build').setInputFiles(rich.target);
    await page.getByText('Native file loaded into this tab.',{exact:false}).waitFor();
    frame=page.frames()[1];await frame.locator('[class*=PlannerEquipment]').first().waitFor();
    const richAgain=await download('captured-profile-roundtrip');
    assert.deepEqual(richAgain.exported.nativeState,rich.exported.nativeState,'Complete multi-profile native state round-trip');
    await page.reload();frame=page.frames()[1];
    await scenarios(frame,{allClasses:false});
    const card=frame.locator('[class*=Slot__item]').first(),icon=card.locator('[class*=Slot__image]').first();
    await card.scrollIntoViewIfNeeded();await page.mouse.move(0,0);
    const artwork=await icon.evaluate(async el=>{const url=getComputedStyle(el).backgroundImage.slice(5,-2);const image=new Image();image.src=url;await image.decode();return {url,width:image.naturalWidth,height:image.naturalHeight};});
    assert.equal(new URL(artwork.url).origin,new URL(config.url).origin);assert(artwork.width>0&&artwork.height>0);
    const stem=path.join(config.evidenceDir,mobile?'mobile':'desktop');
    await card.screenshot({path:stem+'-card.png',animations:'disabled',scale:'css'});
    const originalStyle=await icon.getAttribute('style');
    await icon.evaluate(el=>el.style.backgroundImage='none');
    await card.screenshot({path:stem+'-card-missing.png',animations:'disabled',scale:'css'});
    await icon.evaluate((el,style)=>el.setAttribute('style',style),originalStyle);
    const first=await download('export');const native=first.exported.nativeState,profile=native.profiles[native.activeProfile];
    const item=native.items[profile.items['4']];assert.equal(item.id,'Helm_Legendary_Generic_053');assert.equal(item.power,850);assert.deepEqual(item.sockets,[null,null]);
    assert.equal(profile.skillTree.steps[0].data['28'],1);assert.equal(profile.paragon.steps[0].data[0].nodes['283'],1);
    assert.equal(first.exported.provenance.canonicalConversion.status,'UNSUPPORTED');
    await page.locator('#import-build').setInputFiles(first.target);
    await page.getByText('Native file loaded into this tab.',{exact:false}).waitFor();frame=page.frames()[1];
    await frame.locator('[class*=PlannerEquipment]').first().waitFor();
    const second=await download('roundtrip');
    assert.deepEqual(second.exported.nativeState,first.exported.nativeState,'Native load/save round-trip retains complete serialized state');
    const diag=await (await page.request.get(config.url+'__local/diagnostics')).json();
    assert(!JSON.stringify(diag).includes('Helm_Legendary_Generic_053'),'No raw native state in diagnostics');
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    assert.equal(externalAttempts.length,externalFailures.length);assert(externalFailures.every(reason=>['csp','net::ERR_BLOCKED_BY_CSP'].includes(reason)));
    const wrong=structuredClone(first.exported);wrong.provenance.snapshotManifestSha256='0'.repeat(64);
    await page.locator('#import-build').setInputFiles({name:'wrong-snapshot.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(wrong))});
    await page.getByText('Import rejected:',{exact:false}).waitFor();
    for(const [name,buffer] of [['invalid.json',Buffer.from('{invalid')],['tampered.json',Buffer.from(JSON.stringify({...first.exported,nativeState:{...first.exported.nativeState,activeProfile:999}}))],['hash-mismatch.json',Buffer.from(JSON.stringify({...first.exported,integrity:{algorithm:'sha256',nativeStateSha256:'0'.repeat(64)}}))]]){
      await page.getByRole('button',{name:'Export JSON',exact:true}).click();
      await page.locator('#import-build').setInputFiles({name,mimeType:'application/json',buffer});await page.getByText('Import rejected:',{exact:false}).waitFor();
    }
    results.push({profileSwitch:true,richProfiles:rich.exported.nativeState.profiles.length,richItems:Object.keys(rich.exported.nativeState.items).length,mobileEmulation:mobile,download:true,equipment:true,emptySockets:true,skills:true,paragon:true,roundtrip:true,rejectedWrongSnapshot:true,rejectedInvalidAndTampered:true,externalAttempts:externalAttempts.length,errors,external});await context.close();
  }}finally{await browser.close();await fs.writeFile(path.join(config.evidenceDir,'export-report.json'),JSON.stringify({results,android:'NOT_RUN'},null,2));}
  console.log(JSON.stringify(results));
}
if(require.main===module)fs.readFile(process.argv[2],'utf8').then(JSON.parse).then(run).catch(e=>{console.error(e);process.exitCode=1;});
module.exports={run};
