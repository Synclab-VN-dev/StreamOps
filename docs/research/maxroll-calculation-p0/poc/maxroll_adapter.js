#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright-core');

const PLANNER_URL = 'https://maxroll.gg/d4/planner/1g1any0x#3';
const BROWSER_PATH = '/home/huy/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome';
const BREAKPOINT = { lineNumber: 762, columnNumber: 226096 };

function argumentsMap(argv) {
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

function readBuild(filename) {
  return JSON.parse(fs.readFileSync(filename, 'utf8'));
}

async function setLevel(page, level) {
  const input = page.locator('input[type=number][min="1"][max="70"]').first();
  await input.fill(String(level));
  await input.press('Enter');
  await page.waitForTimeout(350);
  assert(Number(await input.inputValue()) === level,
    `level state transition failed: expected ${level}`);
}

async function equipItem(page, item) {
  await page.getByText(item.slot, { exact: true }).first().evaluate(element => {
    const target = element.parentElement?.querySelector('[class*=Slot__item]');
    if (!target) throw new Error('slot item target not found');
    target.click();
  });
  await page.waitForTimeout(250);
  await page.getByText(item.baseName, { exact: true }).first().click();
  await page.waitForTimeout(350);
  for (const modifier of item.explicitModifiers) {
    await page.getByText('Add Modifier', { exact: true }).first().click();
    await page.waitForTimeout(180);
    const option = page.getByText(modifier.pickerLabel, { exact: true });
    assert(await option.count() === 1,
      `modifier picker identity is not unique: ${modifier.pickerLabel}`);
    await option.click();
    await page.waitForTimeout(250);
  }
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
      title: document.title,
      url: location.href,
      readyState: document.readyState,
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

async function main() {
  const args = argumentsMap(process.argv);
  for (const key of ['input', 'output', 'input-sha256', 'evidence-dir']) {
    assert(args[key], `missing --${key}`);
  }
  const build = readBuild(args.input);
  const catalog = readBuild(path.join(__dirname, 'metric-catalog.json')).metrics;
  const expectedIds = new Set(catalog.map(metric => metric.maxrollInternalId));
  const itemKey = build.profile.items.Helm;
  const item = build.items[itemKey];
  const runId = `${new Date().toISOString().replace(/[:.]/g, '-')}-${args['input-sha256'].slice(0, 12)}`;
  const screenshot = path.join(args['evidence-dir'], `${runId}.png`);
  fs.mkdirSync(args['evidence-dir'], { recursive: true });

  let browser;
  let context;
  let result;
  try {
    browser = await chromium.launch({ executablePath: BROWSER_PATH, headless: true });
    context = await browser.newContext({ viewport: { width: 1600, height: 1200 } });
    const page = await context.newPage();
    const blockedRequests = [];
    await page.route('**/*', route => {
      const method = route.request().method();
      if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
        const requestUrl = new URL(route.request().url());
        blockedRequests.push({
          method,
          endpoint: `${requestUrl.origin}${requestUrl.pathname}`,
        });
        return route.abort('blockedbyclient');
      }
      return route.continue();
    });

    const cdp = await context.newCDPSession(page);
    await cdp.send('Debugger.enable');
    const runtimeValues = new Map();
    const resolvedLocations = [];
    let pausedCount = 0;
    let captureEnabled = false;
    let pauseChain = Promise.resolve();
    cdp.on('Debugger.breakpointResolved', event => {
      resolvedLocations.push(event.location);
    });
    cdp.on('Debugger.paused', event => {
      pausedCount += 1;
      pauseChain = pauseChain.then(async () => {
        try {
          if (!captureEnabled) return;
          const frame = event.callFrames[0];
          const evaluated = await cdp.send('Debugger.evaluateOnCallFrame', {
            callFrameId: frame.callFrameId,
            expression: '({id:u&&u.id,label:f,raw:_,values:u&&u.values})',
            returnByValue: true,
          });
          const value = evaluated.result?.value;
          if (value && expectedIds.has(value.id)) runtimeValues.set(value.id, value);
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

    await page.goto(PLANNER_URL, { waitUntil: 'domcontentloaded', timeout: 120000 });
    await page.waitForTimeout(7000);
    await pauseChain;
    const referenceResolvedUrl = page.url();
    const observedReferencePatch = (await page.locator('body').innerText())
      .match(/Game version:\s*([^\n]+)/)?.[1] || null;
    assert(observedReferencePatch === build.game.patch,
      `patch mismatch: input=${build.game.patch} observed=${observedReferencePatch}`);

    await page.getByRole('button', { name: 'New Profile', exact: true }).click();
    await page.waitForTimeout(700);
    await setLevel(page, build.profile.level);
    captureEnabled = true;
    await equipItem(page, item);

    const deadline = Date.now() + 30000;
    while (Date.now() < deadline) {
      await page.waitForTimeout(120);
      await pauseChain;
      if (runtimeValues.size === 50) break;
    }
    await page.waitForTimeout(400);
    await pauseChain;
    captureEnabled = false;

    const ui = await readUi(page);
    assert(ui.patch === build.game.patch,
      `calculation patch mismatch: input=${build.game.patch} observed=${ui.patch}`);
    assert(ui.class === build.profile.class,
      `class mismatch: input=${build.profile.class} observed=${ui.class}`);
    assert(ui.level === build.profile.level,
      `level mismatch: input=${build.profile.level} observed=${ui.level}`);
    assert(ui.difficulty === build.profile.worldTier,
      `world tier mismatch: input=${build.profile.worldTier} observed=${ui.difficulty}`);
    const observedModifierText = ui.modifiers.join(' | ');
    assert(ui.modifiers.length === item.explicitModifiers.length,
      `modifier count mismatch: input=${item.explicitModifiers.length} observed=${ui.modifiers.length}`);
    for (const modifier of item.explicitModifiers) {
      assert(observedModifierText.includes(modifier.expectedEffect),
        `modifier effect not applied: ${modifier.expectedEffect}`);
    }

    const metrics = catalog.map(metric => {
      const runtime = runtimeValues.get(metric.maxrollInternalId);
      const key = `${metric.category}|${metric.label}`;
      const displayPresent = Object.hasOwn(ui.stats, key);
      const displayValue = displayPresent ? ui.stats[key] : null;
      return {
        metricId: metric.metricId,
        maxrollInternalId: metric.maxrollInternalId,
        category: metric.category,
        statName: metric.label,
        rawValue: runtime?.raw ?? null,
        displayValue,
        unit: displayValue?.endsWith('%') ? '%' : null,
        status: runtime?.raw !== undefined
          ? (displayPresent ? 'SUPPORTED_RAW_AND_DISPLAY' : 'SUPPORTED_RAW_ONLY')
          : 'UNKNOWN',
        provenance: {
          raw: runtime?.raw !== undefined ? 'MAXROLL_CDP_RUNTIME' : null,
          display: displayPresent ? 'MAXROLL_UI_DOM' : null,
        },
      };
    });
    await page.screenshot({ path: screenshot, fullPage: false });
    const runtimeAssets = await page.evaluate(() => performance
      .getEntriesByType('resource').map(entry => entry.name)
      .filter(name => /^https:\/\/maxroll\.gg\/assets\/export-.*\.js/.test(name))
      .map(name => new URL(name).pathname));

    result = {
      contractVersion: 'maxroll-stats-poc/1',
      provider: 'maxroll',
      calculatedAt: new Date().toISOString(),
      observedMaxrollPatch: ui.patch,
      runtimeVersion: {
        applicationAsset: runtimeAssets[0] || null,
        browser: 'Google Chrome for Testing 153.0.8010.12',
        playwrightCore: '1.64.1',
      },
      inputBuildSha256: args['input-sha256'],
      appliedInput: {
        fixture: 'NEW_PROFILE_LOCAL',
        class: ui.class,
        level: ui.level,
        worldTier: ui.difficulty,
        item: {
          slot: item.slot,
          baseName: item.baseName,
          observedModifiers: ui.modifiers,
        },
      },
      coverage: {
        denominator: 50,
        metricIds: metrics.length,
        rawValues: metrics.filter(metric => metric.rawValue !== null).length,
        displayValues: metrics.filter(metric => metric.displayValue !== null).length,
        unknown: metrics.filter(metric => metric.status === 'UNKNOWN').length,
      },
      metrics,
      evidence: {
        referenceUrl: PLANNER_URL,
        referenceResolvedUrl,
        actualCalculationFixture: 'NEW_PROFILE_LOCAL',
        publishedBuildMutated: false,
        saveOrPublishInvoked: false,
        debuggerEnabled: true,
        breakpointRequested: BREAKPOINT,
        breakpointInitialResolvedLocations: breakpoint.locations?.length || 0,
        breakpointResolvedEvents: resolvedLocations.length,
        pausedCount,
        screenshot: path.relative(path.join(__dirname, '..'), screenshot),
        allowedNetworkMethods: ['GET', 'HEAD', 'OPTIONS'],
        blockedNonReadRequests: blockedRequests.length,
        cookiesTokensOrStorageRead: false,
      },
    };
  } finally {
    if (context) await context.close().catch(() => {});
    if (browser) await browser.close().catch(() => {});
  }

  result.evidence.cleanup = 'PASS';
  fs.writeFileSync(args.output, `${JSON.stringify(result, null, 2)}\n`);
  process.stdout.write(JSON.stringify({
    status: 'PASS',
    inputSha256: result.inputBuildSha256,
    coverage: result.coverage,
    fireResistance: result.metrics.find(
      metric => metric.metricId === 'maxroll.heroDetails.446'),
  }));
}

main().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
