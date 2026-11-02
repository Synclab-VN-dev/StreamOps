'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const net = require('node:net');
const { chromium } = require('../../../../browser-infra/node_modules/playwright-core');
const { startServer } = require('./server');
const { resourceKey } = require('../../../../browser-infra/src/snapshot/interceptor');

test('startup errors reach localhost diagnostics; frame navigation cannot escape origin', async () => {
  assert(process.env.CHROMIUM_EXECUTABLE, 'Set CHROMIUM_EXECUTABLE to pinned Chromium');
  const probe = net.createServer(); await new Promise(r => probe.listen(0,'127.0.0.1',r));
  const port = probe.address().port; await new Promise(r => probe.close(r));
  const origin = `http://127.0.0.1:${port}`;
  const snapshot = {manifest:{snapshotId:'synthetic-only',sourceUrl:'https://maxroll.gg/d4/planner/example'},resources:new Map([
    [resourceKey('GET','https://maxroll.gg/d4/planner/example'), {status:200,headers:{'content-type':'text/html'},body:Buffer.from(`<!doctype html><head></head><body><button>New Profile</button><script>
      console.error('Synthetic console failure');
      Promise.reject(new Error('Synthetic rejected initialization'));
      setTimeout(()=>{throw new Error('Synthetic uncaught initialization')},0);
    </script></body>`)}]
  ])};
  const running = await startServer({port},{snapshot});
  const browser = await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE});
  try {
    const page = await browser.newPage(); const externalResponses=[];
    page.on('response', r=>{if(!r.url().startsWith(origin+'/'))externalResponses.push(r.url());});
    await page.goto(origin);
    await page.waitForFunction(async ()=>{
      const d=await fetch('/__local/diagnostics').then(r=>r.json());
      return ['JS_ERROR','UNHANDLED_REJECTION','CONSOLE_ERROR','FRAME_STATE'].every(k=>d.clientEvents.some(e=>e.kind===k));
    });
    const events = running.diagnostics().clientEvents;
    assert(events.some(e=>e.kind==='JS_ERROR'&&e.detail.message.includes('Synthetic uncaught')));
    assert(events.some(e=>e.kind==='UNHANDLED_REJECTION'&&e.detail.message.includes('Synthetic rejected')));
    assert(events.some(e=>e.kind==='FRAME_STATE'&&e.detail.newProfile));
    const sessions = new Set(events.map(e=>e.session)); assert.equal(sessions.size,1);
    const frame=page.frames()[1];
    const result=await frame.evaluate(()=>{
      let topBlocked=false;
      try { top.location.href='https://maxroll.gg/forbidden-top'; } catch { topBlocked=true; }
      return {topBlocked,popupBlocked:window.open('https://maxroll.gg/forbidden-popup')===null};
    });
    assert.deepEqual(result,{topBlocked:true,popupBlocked:true});
    await frame.evaluate(()=>location.assign('https://maxroll.gg/forbidden-frame'));
    await page.waitForTimeout(200);
    assert.equal(page.url(),origin+'/');
    assert.equal(frame.url(),'chrome-error://chromewebdata/');
    assert.deepEqual(externalResponses,[]);
  } finally { await browser.close(); await running.close(); }
});
