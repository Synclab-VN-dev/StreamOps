#!/usr/bin/env node
'use strict';
// Explicit opt-in private snapshot check. No route interception or offline browser mode.
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium, devices } = require('../../../../browser-infra/node_modules/playwright-core');
async function main() {
  const url = process.env.LOCAL_EDITOR_URL;
  const output = process.env.LOCAL_EDITOR_EVIDENCE;
  assert(url && output && process.env.CHROMIUM_EXECUTABLE, 'Set LOCAL_EDITOR_URL, LOCAL_EDITOR_EVIDENCE and CHROMIUM_EXECUTABLE');
  await fs.mkdir(output, { recursive: true, mode: 0o700 });
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, headless: true });
  const results = [];
  try {
    for (const mobile of [false, true]) {
      const context = await browser.newContext(mobile ? { ...devices['Pixel 7'] } : { viewport: { width: 1440, height: 1100 } });
      const page = await context.newPage();
      const runtimeErrors = [], unexpectedConsoleErrors = [];
      page.on('pageerror', error => runtimeErrors.push(error.message));
      page.on('console', message => {
        if (message.type() !== 'error') return;
        const value = message.text();
        // Expected transport/optional-ad failures; runtime errors are never allowlisted.
        if (value.includes('violates the following Content Security Policy') && value.includes('blocked')) return;
        if (value === 'Failed to load resource: the server responded with a status of 404 (Not Found)' || value === 'Failed to load resource: the server responded with a status of 405 (Method Not Allowed)') return;
        if (value.includes('/js/sponsor.js') && value.includes("MIME type ('text/html')")) return;
        unexpectedConsoleErrors.push(value);
      });
      const externalResponses = [], externalAttempts = [], externalFinished = [], externalFailures = [];
      const localOrigin = new URL(url).origin;
      const external = u => /^https?:/.test(u) && new URL(u).origin !== localOrigin;
      page.on('response', r => { if (external(r.url())) externalResponses.push(r.url()); });
      page.on('request', r => { if (external(r.url())) externalAttempts.push(r.url()); });
      page.on('requestfailed', r => { if (external(r.url())) externalFailures.push(r.failure()?.errorText); });
      page.on('requestfinished', r => { if (external(r.url())) externalFinished.push(r.url()); });
      await page.goto(url);
      // Reload exercises initialization without relying on a retained frame or UI state.
      for (let load = 0; load < 3; load++) {
        const loaded = page.frames()[1];
        await loaded.getByRole('button', { name: 'New Profile', exact: true }).waitFor({ state: 'visible' });
        const box = await page.locator('iframe').boundingBox();
        assert(box && box.width > 200 && box.height > 200, 'Nonzero usable frame area');
        assert.equal(await loaded.evaluate(() => document.readyState), 'complete');
        if (load < 2) await page.reload();
      }
      const frame = page.frames()[1];
      await frame.getByRole('button', { name: 'New Profile', exact: true }).click();
      const level = frame.locator('input[type=number][min="1"][max="70"]');
      await level.fill('69'); await level.press('Enter');
      assert.equal(await level.inputValue(), '69');
      await frame.getByText('Helm', { exact: true }).first().locator('..').locator('[class*=Slot__item]').click();
      await frame.getByText('Runic Skullcap', { exact: true }).first().click();
      const editor = frame.locator('[class*="_Dialog_"]').filter({ has: frame.locator('[class*="ItemEditor"]') });
      await editor.locator(':scope > [class*="DialogHeader"] button').click();
      const skills = frame.locator('[class*=PlannerSkillsV2]');
      await skills.getByText('List', { exact: true }).locator('..').click();
      await skills.getByText('Puncture', { exact: true }).locator('..').locator('[class*=Skill__icon]').click();
      assert.match(await skills.innerText(), /1 points spent/);
      const paragon = frame.locator('[class*=ParagonView]');
      await paragon.locator('.d4t-node[style="left: 10em; top: 13em;"]').click();
      assert.match(await paragon.innerText(), /1 points spent/);
      await page.screenshot({ path: path.join(output, mobile ? 'mobile-paragon.png' : 'desktop-paragon.png') });
      await frame.getByRole('button', { name: 'My Profiles', exact: true }).click();
      await frame.locator('input.d4t-save-name').fill('Local HTTP UAT');
      const saving = page.waitForRequest(r => r.method() === 'POST' && r.url().endsWith('/profiles/d4'));
      await frame.locator('.d4t-section-save button').last().click();
      const save = await saving;
      const payload = save.postDataJSON();
      const native = JSON.parse(payload.data);
      const profile = native.profiles[native.activeProfile];
      assert.equal(profile.level, 69);
      assert.equal(native.items[profile.items['4']].id, 'Helm_Legendary_Generic_053');
      assert.equal(profile.skillTree.steps[0].data['28'], 1);
      assert.equal(profile.paragon.steps[0].data[0].nodes['283'], 1);
      await fs.writeFile(path.join(output, mobile ? 'mobile-native-save.json' : 'desktop-native-save.json'), JSON.stringify(payload), { mode: 0o600 });
      assert.equal(new URL(save.url()).origin, localOrigin);
      assert.equal((await save.response()).status(), 405, 'Native save rejected locally (export outside this checkpoint)');
      assert.deepEqual(runtimeErrors, [], 'No uncaught JavaScript/Promise errors during actual UI edits');
      assert.deepEqual(unexpectedConsoleErrors, [], 'No unexpected browser console errors during UI edits');
      const safety = await frame.evaluate(async () => {
        const result = {};
        try { await fetch('https://example.invalid/no-egress'); result.external = false; } catch { result.external = true; }
        result.production = (await fetch('https://maxroll.gg/uncaptured-resource')).status;
        result.post = (await fetch('https://planners.maxroll.gg/profiles/d4', {method:'POST', body:'{}'})).status;
        try { new WebSocket('wss://maxroll.gg/socket'); result.websocket = false; } catch { result.websocket = true; }
        try { await navigator.serviceWorker.register('/uncaptured-sw.js'); result.worker = false; } catch { result.worker = true; }
        const image = document.createElement('img'); image.src = 'https://maxroll.gg/uncaptured-image.png'; document.body.append(image);
        return result;
      });
      assert.deepEqual(safety, {external:true, production:404, post:405, websocket:true, worker:true});
      await page.waitForTimeout(500);
      assert.equal(externalFailures.length, externalAttempts.length, 'Every external attempt failed');
      assert(externalFailures.every(reason => ['csp', 'net::ERR_BLOCKED_BY_CSP'].includes(reason)), JSON.stringify([...new Set(externalFailures)]));
      assert.deepEqual(externalResponses, [], 'No external HTTP response');
      assert.deepEqual(externalFinished, [], 'No external HTTP request completed');
      await page.screenshot({ path: path.join(output, mobile ? 'mobile.png' : 'desktop.png'), fullPage: false });
      results.push({ mobileEmulation: mobile, newProfile: true, level: 69, helm: 'Runic Skullcap', skillPoints: 1, paragonPoints: 1, saveStatus: 405,
        reloads: 2, runtimeErrors, unexpectedConsoleErrors, externalAttemptCount: externalAttempts.length, externalResponses: externalResponses.length, externalFinished: externalFinished.length, safety });
      await context.close();
    }
    const report = { browser: browser.version(), url, androidReal: 'NOT_RUN', results };
    await fs.writeFile(path.join(output, 'browser-report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
