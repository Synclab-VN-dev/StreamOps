#!/usr/bin/env node
'use strict';
// Real HTTPS HUD -> authenticated relay -> frozen Planner. Supply a private
// config {hudUrl,plannerUrl,tokenFile,chromium,output}; browser must trust TLS.
// Uses existing provider scenarios without intercepting/providing resources.
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium, devices} = require('../../d4planner-rulekit/browser-infra/node_modules/playwright-core');
const {scenarios} = require('../../d4planner-rulekit/providers/maxroll/tooling/web/ui-scenarios');

async function run(config) {
  process.umask(0o077);
  assert.equal(new URL(config.plannerUrl).protocol, 'https:');
  await fs.mkdir(config.output, {recursive:false});
  const browser = await chromium.launch({executablePath:config.chromium});
  const results = []; let failure;
  try {
    for (const mobile of [false, true]) {
      const context = await browser.newContext(mobile ? devices['Pixel 7'] : {viewport:{width:1440,height:1100}});
      const responses = [], protocols = [], errors = [], external = [], bodies = [], analyticsLeaks = [];
      const allowed = new Set([new URL(config.hudUrl).origin, new URL(config.plannerUrl).origin]);
      const row = {mobileEmulation:mobile, status:'RUNNING', responses, protocols, errors, external}; results.push(row);
      context.on('request', r => {
        if (r.postData()?.includes('synthetic analytics payload must never be sent')) analyticsLeaks.push(r.url());
      });
      context.on('response', r => {
        if (!allowed.has(new URL(r.url()).origin)) external.push(r.url());
        if (r.url().startsWith(config.plannerUrl)) {
          const entry = {path:new URL(r.url()).pathname,status:r.status()}; responses.push(entry);
          if (r.status() === 429 || r.status() === 503) bodies.push(r.json().then(x => {entry.code=x.error?.code;}).catch(() => {}));
        }
      });
      context.on('page', async page => {
        page.on('pageerror', e => errors.push(e.message));
        page.on('console', m => {
          if (m.type() !== 'error') return;
          const message=m.text(), url=m.location().url;
          const csp=/Content Security Policy|Content-Security-Policy/.test(message);
          const expectedMissing=/Failed to load resource:/.test(message) && url && /\/(?:api\/me|favicon.ico|apple-touch-icon[^/]*)$/.test(new URL(url).pathname);
          if (!csp && !expectedMissing) errors.push(message);
        });
        const cdp = await context.newCDPSession(page); await cdp.send('Network.enable');
        cdp.on('Network.responseReceived', ({response:r}) => {
          if (r.url.startsWith(config.plannerUrl)) protocols.push({path:new URL(r.url).pathname,protocol:r.protocol,status:r.status});
        });
      });
      const hud = await context.newPage();
      await hud.goto(config.hudUrl);
      await hud.getByLabel('Access token').fill((await fs.readFile(config.tokenFile,'utf8')).trim());
      await hud.getByRole('button',{name:'Connect',exact:true}).click();
      await hud.getByRole('tab',{name:'Current',exact:true}).waitFor();
      await hud.getByRole('button',{name:'Open target menu'}).click();
      const opening = context.waitForEvent('page');
      await hud.getByRole('menuitem',{name:'Create Build',exact:true}).click();
      const page = await opening; await page.waitForURL(config.plannerUrl);
      const surface = page.frameLocator('iframe');
      await page.addLocatorHandler(surface.getByText('No Thanks',{exact:true}), l => l.click());
      try {
        await surface.getByRole('button',{name:'New Profile',exact:true}).waitFor({timeout:30000});
        const frame = await (await page.locator('iframe').elementHandle()).contentFrame();
        const disabled = await frame.evaluate(() => {
          const xhr=new XMLHttpRequest();let success=false;xhr.onload=()=>{success=true;};
          xhr.open('POST','https://analytics.maxroll.gg/api/event');
          xhr.send('synthetic analytics payload must never be sent');
          xhr.send('synthetic analytics payload must never be sent');
          return {status:xhr.status,success};
        });
        assert.deepEqual(disabled,{status:0,success:false});
        row.behavior = await scenarios(frame,{allClasses:false});
        const nativePayloads = [];
        page.on('request', r => {if(r.url().endsWith('/__local/export'))nativePayloads.push(r.postDataJSON());});
        async function download(name) {
          await page.getByRole('button',{name:'Export JSON',exact:true}).click();
          await surface.locator('input.d4t-save-name').fill('Relay acceptance');
          const pending = page.waitForEvent('download');
          await surface.locator('.d4t-section-save button').last().click();
          const file = await pending; assert.equal(await file.failure(),null);
          const dest = path.join(config.output,`${mobile?'mobile':'desktop'}-${name}.json`);
          await file.saveAs(dest); const value=JSON.parse(await fs.readFile(dest));
          assert.deepEqual(value.nativeState,JSON.parse(nativePayloads.at(-1).data));
          return {dest,value};
        }
        const first = await download('export');
        const native=first.value.nativeState, profile=native.profiles[native.activeProfile];
        assert.equal(native.items[profile.items['4']].power,850);
        assert.deepEqual(native.items[profile.items['4']].sockets,[null,null]);
        assert.equal(profile.skillTree.steps[0].data['28'],1);
        assert.equal(profile.paragon.steps[0].data[0].nodes['283'],1);
        await page.locator('#import-build').setInputFiles(first.dest);
        await page.getByText('Native file loaded into this tab.',{exact:false}).waitFor();
        await surface.getByRole('button',{name:'My Profiles',exact:true}).waitFor();
        const second = await download('roundtrip');
        assert.deepEqual(second.value.nativeState,first.value.nativeState);
        row.nativeRoundtrip=true;
        await page.reload();
        await surface.getByRole('button',{name:'New Profile',exact:true}).waitFor(); row.reload=true;
        await page.screenshot({path:path.join(config.output,`${mobile?'mobile':'desktop'}-planner.png`)});
        await Promise.all(bodies);
        assert(protocols.some(r=>r.protocol==='h2'&&r.status===200),'Real HTTP/2 relay traffic');
        assert.deepEqual(responses.filter(r=>r.status>=400&&!/^\/(?:api\/me|favicon.ico|apple-touch-icon[^/]*)$/.test(r.path)),[],'No dropped assets');
        row.snapshot = await page.evaluate(async()=>{
          const d=await(await fetch('/__local/diagnostics')).json();
          return {snapshotId:d.snapshotId,manifestSha256:d.manifestSha256};
        });
        assert.deepEqual(errors,[]); assert.deepEqual(external,[],'No completed external requests');
        assert.deepEqual(analyticsLeaks,[],'Analytics payload never sent, even to localhost');
        row.status='PASS';
      } finally {
        await Promise.all(bodies);
        await context.close();
      }
    }
  } catch(error) {failure=error.message; throw error;}
  finally {
    await browser.close();
    await fs.writeFile(path.join(config.output,'report.json'),JSON.stringify({status:failure?'FAIL':'PASS',failure,results,classification:'REAL_PLANNER_HTTPS_RELAY_SYNTHETIC_NATIVE_HOST',android:'NOT_RUN',ci:'CI_NOT_CHECKED'},null,2));
  }
}
fs.readFile(process.argv[2],'utf8').then(JSON.parse).then(run).catch(e=>{console.error(e);process.exitCode=1;});
