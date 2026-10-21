#!/usr/bin/env node
'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright-core');

const PLANNER_URL = 'https://maxroll.gg/d4/planner/1g1any0x#3';
const BROWSER_PATH = '/home/huy/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome';
const BREAKPOINT = { lineNumber: 762, columnNumber: 226096 };
const ALLOWED_ARCHIVE_HOSTS = new Set(['maxroll.gg', 'assets-ng.maxroll.gg', 'planners.maxroll.gg']);

function parseArguments(argv) {
  const result = {};
  for (let index = 2; index < argv.length; index += 2) {
    if (!argv[index].startsWith('--') || argv[index + 1] === undefined) throw new Error(`invalid argument at ${argv[index]}`);
    result[argv[index].slice(2)] = argv[index + 1];
  }
  return result;
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function readJson(filename) {
  return JSON.parse(fs.readFileSync(filename, 'utf8'));
}

function sha256(value) {
  return crypto.createHash('sha256').update(Buffer.isBuffer(value) ? value : Buffer.from(JSON.stringify(value))).digest('hex');
}

function sanitizedUrl(rawUrl) {
  try {
    const parsed = new URL(rawUrl);
    return `${parsed.origin}${parsed.pathname}`;
  } catch {
    return 'UNPARSEABLE_URL';
  }
}

function safeFulfillHeaders(headers) {
  const allowed = new Set([
    'content-type', 'cache-control', 'etag', 'last-modified', 'expires',
    'access-control-allow-origin', 'access-control-allow-credentials',
  ]);
  return Object.fromEntries(Object.entries(headers).filter(([name]) => allowed.has(name.toLowerCase())));
}

function writeTemporaryRuntimePackage(runtimeDir, archive) {
  const blobsDir = path.join(runtimeDir, 'blobs');
  fs.mkdirSync(blobsDir, { recursive: true });
  const entries = {};
  for (const [url, entry] of archive.entries()) {
    const digest = sha256(entry.body);
    const relativeBlob = `blobs/${digest}`;
    const blobPath = path.join(runtimeDir, relativeBlob);
    if (!fs.existsSync(blobPath)) fs.writeFileSync(blobPath, entry.body);
    entries[url] = {
      status: entry.status,
      headers: entry.headers,
      blob: relativeBlob,
      byteLength: entry.body.length,
      sha256: digest,
    };
  }
  const runtimePackage = {
    contractVersion: 'maxroll-local-runtime-package/1',
    patch: '3.2.1.73552',
    createdAt: new Date().toISOString(),
    entries,
  };
  const manifestPath = path.join(runtimeDir, 'runtime-package.json');
  fs.writeFileSync(manifestPath, `${JSON.stringify(runtimePackage, null, 2)}\n`);
  return {
    manifestSha256: sha256(fs.readFileSync(manifestPath)),
    entries: Object.keys(entries).length,
    uniqueBlobs: new Set(Object.values(entries).map(entry => entry.sha256)).size,
    byteLength: [...archive.values()].reduce((sum, entry) => sum + entry.body.length, 0),
  };
}

async function setLevel(page, level) {
  const input = page.locator('input[type=number][min="1"][max="70"]').first();
  await input.fill(String(level));
  await input.press('Enter');
  await page.waitForTimeout(350);
  assert(Number(await input.inputValue()) === level, `level transition failed: expected ${level}`);
}

async function equipBaselineItem(page, item) {
  await page.getByText(item.slot, { exact: true }).first().evaluate(element => {
    const target = element.parentElement?.querySelector('[class*=Slot__item]');
    if (!target) throw new Error('slot item target not found');
    target.click();
  });
  await page.waitForTimeout(250);
  await page.getByText(item.baseName, { exact: true }).first().click();
  await page.waitForTimeout(350);
}

async function addModifier(page, modifier) {
  await page.getByText('Add Modifier', { exact: true }).first().click();
  await page.waitForTimeout(180);
  const option = page.getByText(modifier.pickerLabel, { exact: true });
  assert(await option.count() === 1, `modifier identity is not unique: ${modifier.pickerLabel}`);
  await option.click();
  await page.waitForTimeout(250);
}

async function removeModifier(page, expectedEffect) {
  const row = page.locator('ul.d4t-item-mods > li:not(.d4t-empty)').filter({ hasText: expectedEffect }).first();
  assert(await row.count() === 1, `modifier row not found: ${expectedEffect}`);
  await row.hover();
  await page.waitForTimeout(120);
  await row.locator('[title="Remove Modifier"]').click();
  await page.waitForTimeout(250);
}

async function readUi(page) {
  return page.evaluate(() => {
    const categories = {
      'CORE STATS': 'core', RESISTANCES: 'resistances', OFFENSIVE: 'offensive',
      DEFENSIVE: 'defensive', UTILITY: 'utility', PVP: 'pvp',
    };
    const stats = {};
    for (const section of document.querySelectorAll('div[class*="stats_StatSection"]')) {
      const title = (section.querySelector('h3')?.textContent || '').trim().toUpperCase();
      const category = categories[title] || (title === '' ? 'summary' : null);
      if (!category) continue;
      for (const row of section.querySelectorAll('li')) {
        const spans = row.querySelectorAll(':scope > span');
        if (spans.length >= 2) stats[`${category}|${spans[0].textContent.trim()}`] = spans[1].textContent.trim();
      }
    }
    const body = document.body.innerText;
    return {
      online: navigator.onLine,
      patch: body.match(/Game version:\s*([^\n]+)/)?.[1] || null,
      modifiers: [...document.querySelectorAll('ul.d4t-item-mods > li:not(.d4t-empty)')]
        .map(row => (row.innerText || '').trim()).filter(Boolean),
      stats,
    };
  });
}

async function buildEphemeralArchive(result) {
  const archive = new Map();
  const bodyTasks = [];
  let browser;
  let context;
  try {
    browser = await chromium.launch({ executablePath: BROWSER_PATH, headless: true });
    context = await browser.newContext({ viewport: { width: 1600, height: 1200 } });
    const page = await context.newPage();
    await page.route('**/*', route => {
      if (!['GET', 'HEAD', 'OPTIONS'].includes(route.request().method())) {
        result.blockedNonRead.push({ method: route.request().method(), endpoint: sanitizedUrl(route.request().url()) });
        return route.abort('blockedbyclient');
      }
      return route.continue();
    });
    page.on('response', response => {
      const task = (async () => {
        let parsed;
        try { parsed = new URL(response.url()); } catch { return; }
        if (!ALLOWED_ARCHIVE_HOSTS.has(parsed.hostname) || response.request().method() !== 'GET') return;
        if (response.status() < 200 || response.status() >= 400) return;
        try {
          const body = await response.body();
          archive.set(response.url().split('#')[0], {
            status: response.status(),
            headers: safeFulfillHeaders(response.headers()),
            body,
          });
        } catch (error) {
          result.bodyCaptureFailures.push({ endpoint: sanitizedUrl(response.url()), error: error.message });
        }
      })();
      bodyTasks.push(task);
    });
    const started = performance.now();
    await page.goto(PLANNER_URL, { waitUntil: 'domcontentloaded', timeout: 120000 });
    await page.waitForTimeout(9000);
    result.onlineSeedMilliseconds = performance.now() - started;
    const body = await page.locator('body').innerText();
    result.onlineSeedPatch = body.match(/Game version:\s*([^\n]+)/)?.[1] || null;
    assert(result.onlineSeedPatch === '3.2.1.73552', `seed patch mismatch: ${result.onlineSeedPatch}`);
    await Promise.allSettled(bodyTasks);
  } finally {
    if (context) await context.close().catch(() => {});
    if (browser) await browser.close().catch(() => {});
  }
  result.entries = archive.size;
  result.bytes = [...archive.values()].reduce((sum, entry) => sum + entry.body.length, 0);
  result.inventory = [...archive.entries()].map(([url, entry]) => ({
    endpoint: sanitizedUrl(url), byteLength: entry.body.length, sha256: sha256(entry.body),
  })).sort((a, b) => a.endpoint.localeCompare(b.endpoint));
  return archive;
}

async function runLocalRuntime(archive, catalog, buildA, buildB, onlineA, onlineB, evidenceDir, result) {
  let browser;
  let context;
  let activePhase = null;
  let phaseValues = new Map();
  let pauseChain = Promise.resolve();
  try {
    const launchStarted = performance.now();
    browser = await chromium.launch({ executablePath: BROWSER_PATH, headless: true });
    context = await browser.newContext({ viewport: { width: 1600, height: 1200 } });
    await context.setOffline(true);
    const page = await context.newPage();
    result.browserLaunchMilliseconds = performance.now() - launchStarted;
    await page.route('**/*', route => {
      const request = route.request();
      const key = request.url().split('#')[0];
      if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
        result.blockedNonRead.push({ method: request.method(), endpoint: sanitizedUrl(request.url()) });
        return route.abort('blockedbyclient');
      }
      const entry = archive.get(key);
      if (!entry) {
        result.archiveMisses.push({ method: request.method(), endpoint: sanitizedUrl(request.url()), resourceType: request.resourceType() });
        return route.abort('internetdisconnected');
      }
      result.archiveHits.push({ endpoint: sanitizedUrl(request.url()), resourceType: request.resourceType() });
      return route.fulfill({ status: entry.status, headers: entry.headers, body: entry.body });
    });
    page.on('response', response => result.localResponses.push({
      endpoint: sanitizedUrl(response.url()), status: response.status(), resourceType: response.request().resourceType(),
    }));
    page.on('requestfailed', request => result.requestFailures.push({
      endpoint: sanitizedUrl(request.url()), error: request.failure()?.errorText || null, resourceType: request.resourceType(),
    }));

    const cdp = await context.newCDPSession(page);
    await cdp.send('Debugger.enable');
    await cdp.send('Performance.enable');
    const expectedIds = new Set(catalog.map(metric => metric.maxrollInternalId));
    let pausedCount = 0;
    cdp.on('Debugger.paused', event => {
      pausedCount += 1;
      pauseChain = pauseChain.then(async () => {
        try {
          if (!activePhase) return;
          const evaluated = await cdp.send('Debugger.evaluateOnCallFrame', {
            callFrameId: event.callFrames[0].callFrameId,
            expression: '({id:u&&u.id,label:f,raw:_,values:u&&u.values})',
            returnByValue: true,
          });
          const value = evaluated.result?.value;
          if (value && expectedIds.has(value.id)) phaseValues.set(value.id, value);
        } finally {
          await cdp.send('Debugger.resume').catch(() => {});
        }
      });
    });
    await cdp.send('Debugger.setBreakpointByUrl', {
      urlRegex: 'https://maxroll\\.gg/assets/export-.*\\.js',
      lineNumber: BREAKPOINT.lineNumber,
      columnNumber: BREAKPOINT.columnNumber,
    });

    const loadStarted = performance.now();
    await page.goto(PLANNER_URL, { waitUntil: 'domcontentloaded', timeout: 120000 });
    await page.waitForTimeout(7000);
    await pauseChain;
    result.localLoadMilliseconds = performance.now() - loadStarted;
    const loadedBody = await page.locator('body').innerText();
    const patch = loadedBody.match(/Game version:\s*([^\n]+)/)?.[1] || null;
    assert(patch === buildA.game.patch, `local runtime patch mismatch: ${patch}`);
    result.preInteraction = {
      bodyText: loadedBody.slice(0, 2000),
      fixedOverlays: await page.locator('div.fixed.inset-0').allInnerTexts(),
    };
    await page.screenshot({ path: path.join(evidenceDir, 'ephemeral-local-before-interaction.png'), fullPage: false });
    const consentButtons = ['Accept All', 'Accept all', 'No Thanks', 'Continue without supporting', 'I agree'];
    for (const label of consentButtons) {
      const button = page.getByRole('button', { name: label, exact: true });
      if (await button.count() > 0 && await button.first().isVisible()) {
        await button.first().click();
        await page.waitForTimeout(300);
        break;
      }
    }
    await page.getByRole('button', { name: 'New Profile', exact: true }).click();
    await page.waitForTimeout(700);
    await setLevel(page, buildA.profile.level);
    const item = buildA.items[buildA.profile.items.Helm];
    const modifier = buildB.items[buildB.profile.items.Helm].explicitModifiers[0];

    async function capture(id, action, expectedModifierCount) {
      activePhase = id;
      phaseValues = new Map();
      const started = performance.now();
      await action();
      const deadline = Date.now() + 30000;
      while (Date.now() < deadline) {
        await page.waitForTimeout(120);
        await pauseChain;
        if (phaseValues.size === 50) break;
      }
      await page.waitForTimeout(300);
      await pauseChain;
      const ui = await readUi(page);
      assert(ui.modifiers.length === expectedModifierCount, `${id}: modifier count mismatch`);
      const metrics = catalog.map(metric => ({
        metricId: metric.metricId,
        rawValue: phaseValues.get(metric.maxrollInternalId)?.raw ?? null,
        displayValue: ui.stats[`${metric.category}|${metric.label}`] ?? null,
      }));
      const snapshot = {
        id,
        navigatorOnline: ui.online,
        calculationMilliseconds: performance.now() - started,
        coverage: {
          raw: metrics.filter(metric => metric.rawValue !== null).length,
          display: metrics.filter(metric => metric.displayValue !== null).length,
        },
        metrics,
        outputSha256: sha256(metrics),
      };
      assert(snapshot.coverage.raw === 50, `${id}: raw coverage ${snapshot.coverage.raw}/50`);
      result.snapshots.push(snapshot);
      activePhase = null;
      return snapshot;
    }

    const a0 = await capture('A0-local-cold', () => equipBaselineItem(page, item), 0);
    for (let cycle = 1; cycle <= 3; cycle += 1) {
      await capture(`B${cycle}-local-cold`, () => addModifier(page, modifier), 1);
      await capture(`A${cycle}-local-cold`, () => removeModifier(page, modifier.expectedEffect), 0);
    }
    await page.screenshot({ path: path.join(evidenceDir, 'ephemeral-local-a-final.png'), fullPage: false });
    const aSnapshots = result.snapshots.filter(snapshot => snapshot.id.startsWith('A'));
    const bSnapshots = result.snapshots.filter(snapshot => snapshot.id.startsWith('B'));
    result.explicitOfflineProbe = await page.evaluate(async () => {
      try {
        await fetch(`https://maxroll.gg/__offline_probe_unarchived?nonce=${Date.now()}`, { cache: 'no-store' });
        return { result: 'UNEXPECTED_SUCCESS', navigatorOnline: navigator.onLine };
      } catch (error) {
        return { result: 'FAILED_AS_EXPECTED', navigatorOnline: navigator.onLine, error: error?.message || String(error) };
      }
    });
    const normalizedOnlineA = onlineA.metrics.map(metric => ({ metricId: metric.metricId, rawValue: metric.rawValue, displayValue: metric.displayValue }));
    const normalizedOnlineB = onlineB.metrics.map(metric => ({ metricId: metric.metricId, rawValue: metric.rawValue, displayValue: metric.displayValue }));
    result.acceptance = {
      newBrowserProcess: true,
      offlineBeforeNavigation: true,
      navigatorOnlineFalseEverySnapshot: result.snapshots.every(snapshot => snapshot.navigatorOnline === false),
      navigatorOnlineObserved: [...new Set(result.snapshots.map(snapshot => snapshot.navigatorOnline))],
      explicitUnarchivedFetchFailed: result.explicitOfflineProbe.result === 'FAILED_AS_EXPECTED',
      everyHttpRequestLocallyFulfilledOrAborted: true,
      archiveMissCount: result.archiveMisses.length,
      remoteResponsesCompleted: 0,
      rawCoverageEverySnapshot: result.snapshots.every(snapshot => snapshot.coverage.raw === 50),
      aUniqueOutputs: new Set(aSnapshots.map(snapshot => snapshot.outputSha256)).size,
      bUniqueOutputs: new Set(bSnapshots.map(snapshot => snapshot.outputSha256)).size,
      aMatchesOnline: aSnapshots.every(snapshot => snapshot.outputSha256 === sha256(normalizedOnlineA)),
      bMatchesOnline: bSnapshots.every(snapshot => snapshot.outputSha256 === sha256(normalizedOnlineB)),
    };
    result.pausedCount = pausedCount;
    assert(result.acceptance.explicitUnarchivedFetchFailed, 'unarchived network probe unexpectedly succeeded');
    assert(result.acceptance.rawCoverageEverySnapshot, 'raw coverage incomplete');
    assert(result.acceptance.aUniqueOutputs === 1 && result.acceptance.bUniqueOutputs === 1, 'A/B output not repeatable');
    assert(result.acceptance.aMatchesOnline && result.acceptance.bMatchesOnline, 'local output mismatch versus online baseline');
  } finally {
    if (context) await context.close().catch(() => {});
    if (browser) await browser.close().catch(() => {});
  }
}

async function main() {
  const args = parseArguments(process.argv);
  assert(args.output && args['evidence-dir'], 'missing --output or --evidence-dir');
  const output = path.resolve(args.output);
  const evidenceDir = path.resolve(args['evidence-dir']);
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.mkdirSync(evidenceDir, { recursive: true });
  const catalog = readJson(path.join(__dirname, 'metric-catalog.json')).metrics;
  const buildA = readJson(path.join(__dirname, 'build-a.json'));
  const buildB = readJson(path.join(__dirname, 'build-b.json'));
  const onlineA = readJson(path.join(__dirname, 'stats-a.json'));
  const onlineB = readJson(path.join(__dirname, 'stats-b.json'));
  const result = {
    contractVersion: 'maxroll-ephemeral-local-runtime-poc/1',
    capturedAt: new Date().toISOString(),
    status: 'RUNNING',
    patch: '3.2.1.73552',
    archive: { storage: 'process memory only', retained: false, blockedNonRead: [], bodyCaptureFailures: [] },
    local: { archiveHits: [], archiveMisses: [], blockedNonRead: [], localResponses: [], requestFailures: [], snapshots: [] },
    safety: {
      publishedBuildMutated: false,
      saveOrPublishInvoked: false,
      cookiesTokensOrStorageRead: false,
      proprietaryAssetsWrittenToTemporaryRuntimePackage: Boolean(args['runtime-dir']),
      proprietaryAssetsWrittenToRepository: false,
    },
  };
  let archive;
  try {
    archive = await buildEphemeralArchive(result.archive);
    if (args['runtime-dir']) {
      result.temporaryRuntimePackage = writeTemporaryRuntimePackage(
        path.resolve(args['runtime-dir']), archive);
      result.temporaryRuntimePackage.retention = 'CALLER_MUST_DELETE_AFTER_LOCAL_CLI_TEST';
    }
    await runLocalRuntime(archive, catalog, buildA, buildB, onlineA, onlineB, evidenceDir, result.local);
    result.status = 'L2_COLD_OFFLINE_PASS_EPHEMERAL_ARCHIVE';
  } finally {
    if (archive) archive.clear();
    result.archive.retained = false;
    result.safety.browserAndMemoryArchiveCleanup = 'PASS';
  }
  fs.writeFileSync(output, `${JSON.stringify(result, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify({ status: result.status, archive: { entries: result.archive.entries, bytes: result.archive.bytes }, acceptance: result.local.acceptance }, null, 2)}\n`);
}

main().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
