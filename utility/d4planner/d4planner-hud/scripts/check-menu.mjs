// Targeted HUD/browser QA. Native calls are mocked; this is not Windows E2E evidence.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {preview} from 'vite';
import {execFileSync} from 'node:child_process';

const hud = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(path.join(hud, '../d4planner-rulekit/browser-infra/package.json'));
const {chromium} = require('playwright-core');
const [output, executablePath] = process.argv.slice(2);
if (!output || !executablePath) throw Error('Usage: node scripts/check-menu.mjs <private-output> <chromium> (run npm run build first)');
await fs.mkdir(output, {recursive: true});
const fixture = JSON.parse(await fs.readFile(path.join(hud, '../d4planner-be/contracts/release1/v1/fixtures/hud.partial.synthetic.json')));
fixture.context.target.buildDisplayName = 'Charge Bolt';
fixture.score.value = 78;
const targets = ['Charge Bolt', 'Firewall', 'Chain Lightning'].map((displayName, i) => ({
  targetId: i ? `menu-${i}` : fixture.context.target.targetId, displayName,
  contentSha256: String(i + 1).repeat(64), byteLength: 100, validation: 'VALID', errorCodes: [],
}));
const head = execFileSync('git', ['rev-parse', 'HEAD'], {cwd: hud, encoding: 'utf8'}).trim();
const report = {head, classification: 'BROWSER_WITH_NATIVE_MOCK', golden: 'BLOCKED_OWNER_APPROVAL', status: 'RUNNING', cases: []};
const server = await preview({root: hud, configFile: path.join(hud, 'vite.config.ts'), preview: {host: '127.0.0.1', port: 0, strictPort: true}});
let browser;
try {
  browser = await chromium.launch({headless: true, executablePath});
  for (const viewport of [{width: 1200, height: 630}, {width: 280, height: 560}]) {
    const page = await browser.newPage({viewport, deviceScaleFactor: 1});
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.addInitScript(({fixture, targets}) => {
      window.__menuTest = {calls: [], targets, selections: [], outcome: 'pending'};
      const test = window.__menuTest;
      window.__TAURI_INTERNALS__ = {invoke: (command, args) => {
        test.calls.push({command, args});
        if (command === 'open_local_planner') return test.outcome === 'pending'
          ? new Promise(resolve => { test.finish = resolve; }) : Promise.reject(test.outcome);
        return Promise.resolve();
      }};
      let listener;
      window.__D4PLANNER_HUD_DATA_SOURCE__ = {
        async connect(next) { listener = next; next({type: 'CONNECTION', state: 'CONNECTED'}); next({type: 'SNAPSHOT', snapshot: fixture}); return () => {}; },
        async refreshTargets() { listener({type: 'TARGETS', targets: test.targets}); },
        async selectTarget(request) { test.selections.push(request); return {status: 'ACTIVATED', ...request, contentSha256: request.expectedSha256, selectionRevision: 8}; },
      };
    }, {fixture, targets});
    const url = `http://127.0.0.1:${server.httpServer.address().port}/`;
    await page.goto(url);
    // Match MagicPath's white canvas beneath the transparent HUD, not a game image.
    await page.addStyleTag({content: 'html { background: white !important; }'});
    const openMenu = () => page.getByRole('button', {name: 'Open target menu'}).click();
    await openMenu();
    const menu = page.getByRole('menu', {name: 'HUD actions'});
    const create = menu.getByRole('menuitem', {name: 'Create Build', exact: true});
    await create.waitFor();
    assert.deepEqual(await menu.getByRole('menuitem').allTextContents(), [
      'Create BuildOpen Local Planner', 'Charge Bolt  ✓', 'Firewall', 'Chain Lightning',
      'Report IssueOpen report window', ' Collect Logs',
    ]);
    const box = await menu.boundingBox(); assert.equal(box.width, 218); assert.ok(box.x >= 0 && box.x + box.width <= viewport.width);
    const prefix = String(viewport.width);
    await menu.screenshot({path: path.join(output, `${prefix}-actual-menu.png`)});
    await create.screenshot({path: path.join(output, `${prefix}-actual-create.png`)});
    await menu.getByRole('menuitem', {name: 'Report Issue', exact: true}).screenshot({path: path.join(output, `${prefix}-actual-report.png`)});
    await fs.writeFile(path.join(output, `${prefix}-menu.json`), JSON.stringify(await menu.evaluate(el => ({
      html: el.outerHTML, box: el.getBoundingClientRect().toJSON(),
      styles: [el, ...el.querySelectorAll('*')].map(e => ({tag: e.tagName, text: e.textContent, box: e.getBoundingClientRect().toJSON(),
        style: Object.fromEntries(['width','height','padding','margin','fontFamily','fontSize','fontWeight','lineHeight','letterSpacing','color','backgroundColor','border','borderRadius','boxShadow'].map(k => [k, getComputedStyle(e)[k]]))})),
    })), null, 2));
    await create.dblclick();
    const pending = menu.getByRole('menuitem', {name: 'Opening Planner…', exact: true});
    assert.equal(await pending.isDisabled(), true);
    assert.equal(await page.evaluate(() => window.__menuTest.calls.filter(c => c.command === 'open_local_planner').length), 1);
    await pending.screenshot({path: path.join(output, `${prefix}-pending.png`)});
    await page.evaluate(() => window.__menuTest.finish());
    await menu.waitFor({state: 'hidden'});
    for (const [code, message] of [['PLANNER_SNAPSHOT_UNAVAILABLE', 'snapshot is unavailable'], ['PLANNER_PORT_CONFLICT', 'port is in use']]) {
      await page.evaluate(code => { window.__menuTest.outcome = code; }, code);
      await openMenu(); await create.click();
      const error = page.getByRole('alert').filter({hasText: message}); await error.waitFor();
      assert.equal(await menu.count(), 0);
      assert.equal(await error.evaluate(e => { const b=e.getBoundingClientRect(); return document.elementFromPoint(b.x+b.width/2,b.y+b.height/2)===e; }), true);
      await error.screenshot({path: path.join(output, `${prefix}-${code}.png`)});
    }
    await openMenu(); await menu.getByRole('menuitem', {name: 'Collect Logs', exact: true}).click();
    const panel = page.getByRole('complementary', {name: 'Report Issue'});
    // The real native window expands; match that declared extent in this browser fixture.
    await page.setViewportSize({width: 656, height: 620});
    assert.equal(await panel.getByRole('button', {name: 'Collect Logs', exact: true}).getAttribute('aria-pressed'), 'true');
    assert.equal(await panel.getByRole('checkbox', {name: 'FE', exact: true}).isChecked(), true);
    await panel.getByRole('button', {name: 'Report Issue', exact: true}).click();
    await panel.getByRole('textbox', {name: /^Title/}).fill('Preserved menu draft');
    await openMenu(); await menu.getByRole('menuitem', {name: 'Collect Logs', exact: true}).click();
    await openMenu(); await menu.getByRole('menuitem', {name: 'Report Issue', exact: true}).click();
    assert.equal(await panel.getByRole('textbox', {name: /^Title/}).inputValue(), 'Preserved menu draft');
    await page.getByRole('button', {name: 'Close report'}).click();
    await page.setViewportSize(viewport);
    await openMenu(); await menu.getByRole('menuitem', {name: 'Firewall', exact: true}).click();
    assert.deepEqual(await page.evaluate(() => window.__menuTest.selections), [{targetId: 'menu-1', expectedSha256: '2'.repeat(64)}]);
    await page.evaluate(() => { const t=window.__menuTest; t.targets=Array.from({length: 60}, (_,i) => ({...t.targets[0], targetId: `long-${i}`, displayName:`Long target ${i}`})); });
    await openMenu();
    assert.ok((await menu.boundingBox()).y + (await menu.boundingBox()).height <= viewport.height);
    await menu.getByRole('menuitem', {name: 'Collect Logs', exact: true}).click();
    assert.equal(await panel.getByRole('button', {name: 'Collect Logs', exact: true}).getAttribute('aria-pressed'), 'true');
    const calls = await page.evaluate(() => window.__menuTest.calls);
    assert.ok(!calls.some(c => ['drag_overlay','collect_issue_report','submit_issue_report','start_backend','restart_backend'].includes(c.command)));
    // Tauri core normalizes omitted application args to an empty object.
    for (const call of calls.filter(c => c.command === 'open_local_planner')) assert.deepEqual(call.args, {});
    assert.deepEqual(errors, []);
    report.cases.push({viewport, status:'PASS', expected:'v15 menu, click, pending/error, preserved Support state, Target selection, scroll reachability', actual:'all assertions passed', nativeCalls:'mocked; installed VM evidence remains separate'});
    await page.close();
  }
  report.status = 'PASS';
} catch (error) {
  report.status = 'FAIL'; report.error = String(error); process.exitCode = 1;
  const page = browser?.contexts().at(-1)?.pages().at(-1);
  if (page) {
    await page.screenshot({path: path.join(output, 'failure.png')});
    await fs.writeFile(path.join(output, 'failure.html'), await page.content());
  }
}
finally {
  await browser?.close();
  await new Promise(resolve => server.httpServer.close(resolve));
  await fs.writeFile(path.join(output, 'browser-report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
}
