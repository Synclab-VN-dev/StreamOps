#!/usr/bin/env node
'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright-core');

const PLANNER_URL = 'https://maxroll.gg/d4/planner/1g1any0x#3';
const BROWSER_PATH = '/home/huy/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome';
const BREAKPOINT = { lineNumber: 762, columnNumber: 226096 };
const BUILD_A_SHA = '32fdcb90bbc054981d9cfc54fa369cdbc2452aef84e22037703f2fc77e742536';
const BUILD_B_SHA = 'fa398c8b089eb7b6adcc336b6a77f35db9df76a5bfeeae54a55a90545ae5189c';

function parseArguments(argv) {
  const result = {};
  for (let index = 2; index < argv.length; index += 2) {
    if (!argv[index].startsWith('--') || argv[index + 1] === undefined) {
      throw new Error(`invalid argument at ${argv[index]}`);
    }
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
  const bytes = Buffer.isBuffer(value)
    ? value
    : Buffer.from(typeof value === 'string' ? value : JSON.stringify(value));
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

function sanitizedUrl(rawUrl) {
  try {
    const parsed = new URL(rawUrl);
    return `${parsed.origin}${parsed.pathname}`;
  } catch {
    return 'UNPARSEABLE_URL';
  }
}

function metricValue(metrics, id) {
  return metrics.find(metric => metric.metricId === id);
}

async function setLevel(page, level) {
  const input = page.locator('input[type=number][min="1"][max="70"]').first();
  await input.fill(String(level));
  await input.press('Enter');
  await page.waitForTimeout(350);
  assert(Number(await input.inputValue()) === level,
    `level transition failed: expected ${level}`);
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
  assert(await option.count() === 1,
    `modifier picker identity is not unique: ${modifier.pickerLabel}`);
  await option.click();
  await page.waitForTimeout(250);
}

async function removeModifier(page, expectedEffect) {
  const row = page.locator('ul.d4t-item-mods > li:not(.d4t-empty)')
    .filter({ hasText: expectedEffect }).first();
  assert(await row.count() === 1, `modifier row not found: ${expectedEffect}`);
  await row.hover();
  await page.waitForTimeout(120);
  await row.locator('[title="Remove Modifier"]').click();
  await page.waitForTimeout(250);
}

async function readUi(page) {
  return page.evaluate(() => {
    const categories = {
      'CORE STATS': 'core',
      RESISTANCES: 'resistances',
      OFFENSIVE: 'offensive',
      DEFENSIVE: 'defensive',
      UTILITY: 'utility',
      PVP: 'pvp',
    };
    const stats = {};
    for (const section of document.querySelectorAll('div[class*="stats_StatSection"]')) {
      const title = (section.querySelector('h3')?.textContent || '').trim().toUpperCase();
      const category = categories[title] || (title === '' ? 'summary' : null);
      if (!category) continue;
      for (const row of section.querySelectorAll('li')) {
        const spans = row.querySelectorAll(':scope > span');
        if (spans.length >= 2) {
          stats[`${category}|${spans[0].textContent.trim()}`] =
            spans[1].textContent.trim();
        }
      }
    }
    const body = document.body.innerText;
    return {
      online: navigator.onLine,
      patch: (body.match(/Game version:\s*([^\n]+)/) || [])[1] || null,
      class: (body.match(/Class\s*\n([^\n]+)/) || [])[1] || null,
      level: Number(document.querySelector(
        'input[type=number][min="1"][max="70"]')?.value),
      difficulty: (body.match(/Stats\s*\n([^\n]+)/) || [])[1] || null,
      modifiers: [...document.querySelectorAll(
        'ul.d4t-item-mods > li:not(.d4t-empty)')]
        .map(row => (row.innerText || '').trim()).filter(Boolean),
      stats,
    };
  });
}

function performanceMap(result) {
  return Object.fromEntries((result.metrics || []).map(metric => [metric.name, metric.value]));
}

async function main() {
  const args = parseArguments(process.argv);
  assert(args.output, 'missing --output');
  assert(args['evidence-dir'], 'missing --evidence-dir');
  const outputPath = path.resolve(args.output);
  const evidenceDir = path.resolve(args['evidence-dir']);
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.mkdirSync(evidenceDir, { recursive: true });

  const catalog = readJson(path.join(__dirname, 'metric-catalog.json')).metrics;
  const buildA = readJson(path.join(__dirname, 'build-a.json'));
  const buildB = readJson(path.join(__dirname, 'build-b.json'));
  const onlineA = readJson(path.join(__dirname, 'stats-a.json'));
  const onlineB = readJson(path.join(__dirname, 'stats-b.json'));
  const expectedIds = new Set(catalog.map(metric => metric.maxrollInternalId));
  const item = buildA.items[buildA.profile.items.Helm];
  const modifier = buildB.items[buildB.profile.items.Helm].explicitModifiers[0];

  const network = {
    offlineActivatedAt: null,
    attemptedAfterOffline: [],
    failedAfterOffline: [],
    responsesAfterOffline: [],
    blockedNonRead: [],
    explicitProbe: null,
  };
  const runtimeResources = [];
  let runtimeFingerprint = null;
  let browser;
  let context;
  let result;
  let activePhase = null;

  try {
    const launchStarted = performance.now();
    browser = await chromium.launch({ executablePath: BROWSER_PATH, headless: true });
    context = await browser.newContext({ viewport: { width: 1600, height: 1200 } });
    const page = await context.newPage();
    const launchMilliseconds = performance.now() - launchStarted;

    await page.route('**/*', route => {
      const method = route.request().method();
      if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
        network.blockedNonRead.push({
          afterOffline: network.offlineActivatedAt !== null,
          method,
          endpoint: sanitizedUrl(route.request().url()),
        });
        return route.abort('blockedbyclient');
      }
      return route.continue();
    });
    page.on('request', request => {
      if (network.offlineActivatedAt !== null) {
        network.attemptedAfterOffline.push({
          phase: activePhase,
          method: request.method(),
          endpoint: sanitizedUrl(request.url()),
          resourceType: request.resourceType(),
        });
      }
    });
    page.on('requestfailed', request => {
      if (network.offlineActivatedAt !== null) {
        network.failedAfterOffline.push({
          phase: activePhase,
          method: request.method(),
          endpoint: sanitizedUrl(request.url()),
          resourceType: request.resourceType(),
          errorText: request.failure()?.errorText || null,
        });
      }
    });
    page.on('response', async response => {
      const resource = {
        phase: activePhase,
        observedAt: new Date().toISOString(),
        endpoint: sanitizedUrl(response.url()),
        status: response.status(),
        resourceType: response.request().resourceType(),
      };
      if (network.offlineActivatedAt !== null) {
        network.responsesAfterOffline.push(resource);
      } else {
        runtimeResources.push(resource);
      }
      if (!runtimeFingerprint && /^https:\/\/maxroll\.gg\/assets\/export-.*\.js/.test(response.url())) {
        try {
          const body = await response.body();
          runtimeFingerprint = {
            assetPath: new URL(response.url()).pathname,
            byteLength: body.length,
            sha256: sha256(body),
            retained: false,
          };
        } catch {}
      }
    });

    const cdp = await context.newCDPSession(page);
    await cdp.send('Debugger.enable');
    await cdp.send('Network.enable');
    await cdp.send('Performance.enable');
    const resolvedLocations = [];
    let pausedCount = 0;
    let phaseValues = new Map();
    let pauseChain = Promise.resolve();
    cdp.on('Debugger.breakpointResolved', event => {
      resolvedLocations.push(event.location);
    });
    cdp.on('Debugger.paused', event => {
      pausedCount += 1;
      pauseChain = pauseChain.then(async () => {
        try {
          if (!activePhase) return;
          const frame = event.callFrames[0];
          const evaluated = await cdp.send('Debugger.evaluateOnCallFrame', {
            callFrameId: frame.callFrameId,
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
    const breakpoint = await cdp.send('Debugger.setBreakpointByUrl', {
      urlRegex: 'https://maxroll\\.gg/assets/export-.*\\.js',
      lineNumber: BREAKPOINT.lineNumber,
      columnNumber: BREAKPOINT.columnNumber,
    });

    const navigationStarted = performance.now();
    await page.goto(PLANNER_URL, { waitUntil: 'domcontentloaded', timeout: 120000 });
    await page.waitForTimeout(7000);
    await pauseChain;
    const warmLoadMilliseconds = performance.now() - navigationStarted;
    const observedPatch = (await page.locator('body').innerText())
      .match(/Game version:\s*([^\n]+)/)?.[1] || null;
    assert(observedPatch === buildA.game.patch,
      `patch mismatch: expected=${buildA.game.patch} observed=${observedPatch}`);
    await page.getByRole('button', { name: 'New Profile', exact: true }).click();
    await page.waitForTimeout(700);
    await setLevel(page, buildA.profile.level);

    const snapshots = [];
    async function capture(id, expectedBuildSha, expectedModifierCount, action) {
      activePhase = id;
      phaseValues = new Map();
      const perfBefore = performanceMap(await cdp.send('Performance.getMetrics'));
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
      const calculationMilliseconds = performance.now() - started;
      const perfAfter = performanceMap(await cdp.send('Performance.getMetrics'));
      const ui = await readUi(page);
      assert(ui.modifiers.length === expectedModifierCount,
        `${id}: expected ${expectedModifierCount} modifiers, observed ${ui.modifiers.length}`);
      if (expectedModifierCount === 1) {
        assert(ui.modifiers.join(' | ').includes(modifier.expectedEffect),
          `${id}: modifier effect not visible`);
      }
      const metrics = catalog.map(metric => {
        const runtime = phaseValues.get(metric.maxrollInternalId);
        const displayKey = `${metric.category}|${metric.label}`;
        return {
          metricId: metric.metricId,
          rawValue: runtime?.raw ?? null,
          displayValue: Object.hasOwn(ui.stats, displayKey) ? ui.stats[displayKey] : null,
        };
      });
      assert(metrics.filter(metric => metric.rawValue !== null).length === 50,
        `${id}: raw coverage did not reach 50/50`);
      const snapshot = {
        id,
        mode: network.offlineActivatedAt === null ? 'ONLINE_WARMUP' : 'WARM_OFFLINE',
        inputBuildSha256: expectedBuildSha,
        capturedAt: new Date().toISOString(),
        calculationMilliseconds,
        navigatorOnline: ui.online,
        observedModifiers: ui.modifiers,
        coverage: {
          metricIds: metrics.length,
          rawValues: metrics.filter(metric => metric.rawValue !== null).length,
          displayValues: metrics.filter(metric => metric.displayValue !== null).length,
        },
        performance: {
          jsHeapUsedBytes: perfAfter.JSHeapUsedSize ?? null,
          jsHeapDeltaBytes: perfAfter.JSHeapUsedSize !== undefined && perfBefore.JSHeapUsedSize !== undefined
            ? perfAfter.JSHeapUsedSize - perfBefore.JSHeapUsedSize : null,
          taskDurationDeltaSeconds: perfAfter.TaskDuration !== undefined && perfBefore.TaskDuration !== undefined
            ? perfAfter.TaskDuration - perfBefore.TaskDuration : null,
        },
        metrics,
        outputSha256: sha256(metrics),
      };
      snapshots.push(snapshot);
      activePhase = null;
      return snapshot;
    }

    const baselineA = await capture('A-online-warmup', BUILD_A_SHA, 0,
      () => equipBaselineItem(page, item));

    await context.setOffline(true);
    network.offlineActivatedAt = new Date().toISOString();
    await page.waitForTimeout(100);
    network.explicitProbe = await page.evaluate(async () => {
      try {
        await fetch(`https://maxroll.gg/favicon.ico?offline_probe=${Date.now()}`, {
          cache: 'no-store',
        });
        return { navigatorOnline: navigator.onLine, fetchResult: 'UNEXPECTED_SUCCESS' };
      } catch (error) {
        return {
          navigatorOnline: navigator.onLine,
          fetchResult: 'FAILED_AS_EXPECTED',
          errorName: error?.name || null,
          errorMessage: error?.message || null,
        };
      }
    });

    for (let cycle = 1; cycle <= 3; cycle += 1) {
      await capture(`B${cycle}-offline`, BUILD_B_SHA, 1,
        () => addModifier(page, modifier));
      await capture(`A${cycle}-offline`, BUILD_A_SHA, 0,
        () => removeModifier(page, modifier.expectedEffect));
    }

    const screenshotB = path.join(evidenceDir, 'warm-offline-b3.png');
    await addModifier(page, modifier);
    await page.screenshot({ path: screenshotB, fullPage: false });
    await removeModifier(page, modifier.expectedEffect);
    const screenshotA = path.join(evidenceDir, 'warm-offline-a-final.png');
    await page.screenshot({ path: screenshotA, fullPage: false });

    const offlineA = snapshots.filter(snapshot => snapshot.id.startsWith('A') && snapshot.mode === 'WARM_OFFLINE');
    const offlineB = snapshots.filter(snapshot => snapshot.id.startsWith('B'));
    const normalizedAHashes = [...new Set(offlineA.map(snapshot => snapshot.outputSha256))];
    const normalizedBHashes = [...new Set(offlineB.map(snapshot => snapshot.outputSha256))];
    const onlineAMetrics = onlineA.metrics.map(metric => ({
      metricId: metric.metricId,
      rawValue: metric.rawValue,
      displayValue: metric.displayValue,
    }));
    const onlineBMetrics = onlineB.metrics.map(metric => ({
      metricId: metric.metricId,
      rawValue: metric.rawValue,
      displayValue: metric.displayValue,
    }));
    const remoteResponses = network.responsesAfterOffline.filter(response =>
      !response.endpoint.startsWith('http://127.0.0.1') &&
      !response.endpoint.startsWith('http://localhost'));
    const remoteCalculationResponses = remoteResponses.filter(response => response.phase !== null);
    const fireA = metricValue(baselineA.metrics, 'maxroll.heroDetails.446');
    const fireB = metricValue(offlineB[0].metrics, 'maxroll.heroDetails.446');

    result = {
      contractVersion: 'maxroll-warm-offline-poc/1',
      capturedAt: new Date().toISOString(),
      status: 'L1_WARM_OFFLINE_PASS',
      environment: {
        browser: 'Google Chrome for Testing 153.0.8010.12',
        playwrightCore: '1.64.1',
        maxrollPatch: observedPatch,
        runtimeFingerprint,
      },
      performance: {
        browserLaunchMilliseconds: launchMilliseconds,
        onlineWarmLoadMilliseconds: warmLoadMilliseconds,
        calculationMilliseconds: snapshots.map(snapshot => ({
          id: snapshot.id,
          value: snapshot.calculationMilliseconds,
        })),
        cpuProxy: 'CDP Performance.TaskDuration delta; not host-wide CPU utilization',
        memoryProxy: 'CDP Performance.JSHeapUsedSize; not total browser RSS',
      },
      snapshots,
      acceptance: {
        cycles: 3,
        offlineAUniqueOutputHashes: normalizedAHashes.length,
        offlineBUniqueOutputHashes: normalizedBHashes.length,
        allOfflineNavigatorFalse: [...offlineA, ...offlineB]
          .every(snapshot => snapshot.navigatorOnline === false),
        explicitOfflineFetchFailed: network.explicitProbe?.fetchResult === 'FAILED_AS_EXPECTED',
        remoteResponsesCompletedAfterOffline: remoteResponses.length,
        remoteCalculationResponsesCompletedAfterOffline: remoteCalculationResponses.length,
        rawCoverageEverySnapshot: snapshots.every(snapshot => snapshot.coverage.rawValues === 50),
        aRollbackExact: normalizedAHashes.length === 1 && normalizedAHashes[0] === baselineA.outputSha256,
        aMatchesOnlineBaseline: sha256(onlineAMetrics) === baselineA.outputSha256,
        bMatchesOnlineBaseline: sha256(onlineBMetrics) === offlineB[0].outputSha256,
        fireResistanceDelta: fireB.rawValue - fireA.rawValue,
      },
      network,
      runtimeResourcesLoadedOnline: runtimeResources,
      evidence: {
        screenshots: [
          path.relative(path.join(__dirname, '..'), screenshotB),
          path.relative(path.join(__dirname, '..'), screenshotA),
        ],
        breakpointRequested: BREAKPOINT,
        breakpointInitialResolvedLocations: breakpoint.locations?.length || 0,
        breakpointResolvedEvents: resolvedLocations.length,
        pausedCount,
        publishedBuildMutated: false,
        saveOrPublishInvoked: false,
        cookiesTokensOrStorageRead: false,
        proprietaryBundleRetained: false,
      },
    };
    assert(result.acceptance.offlineAUniqueOutputHashes === 1,
      'offline A outputs were not repeatable');
    assert(result.acceptance.offlineBUniqueOutputHashes === 1,
      'offline B outputs were not repeatable');
    assert(result.acceptance.allOfflineNavigatorFalse,
      'navigator.onLine was true during an offline snapshot');
    assert(result.acceptance.explicitOfflineFetchFailed,
      'explicit offline fetch unexpectedly succeeded');
    assert(result.acceptance.remoteCalculationResponsesCompletedAfterOffline === 0,
      'a remote response completed during an offline calculation phase');
    assert(result.acceptance.rawCoverageEverySnapshot,
      'one or more snapshots had less than 50 raw values');
    assert(result.acceptance.aRollbackExact,
      'offline A rollback did not match the warm baseline');
    assert(result.acceptance.aMatchesOnlineBaseline,
      'warm baseline A did not match committed online baseline');
    assert(result.acceptance.bMatchesOnlineBaseline,
      'warm offline B did not match committed online baseline');
    assert(result.acceptance.fireResistanceDelta === 2800,
      `unexpected Fire Resistance delta: ${result.acceptance.fireResistanceDelta}`);
  } finally {
    if (context) await context.close().catch(() => {});
    if (browser) await browser.close().catch(() => {});
  }

  result.evidence.cleanup = 'PASS';
  fs.writeFileSync(outputPath, `${JSON.stringify(result, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify({
    status: result.status,
    acceptance: result.acceptance,
    runtimeFingerprint: result.environment.runtimeFingerprint,
    calculationMilliseconds: result.performance.calculationMilliseconds,
  }, null, 2)}\n`);
}

main().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
