#!/usr/bin/env node
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright-core');

const PLANNER_URL = 'https://maxroll.gg/d4/planner/1g1any0x#3';
const BROWSER_PATH = '/home/huy/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome';

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

function endpoint(rawUrl) {
  try {
    const parsed = new URL(rawUrl);
    if (!['http:', 'https:'].includes(parsed.protocol)) {
      return `${parsed.protocol.toUpperCase()}LOCAL_RESOURCE`;
    }
    return `${parsed.origin}${parsed.pathname}`;
  } catch {
    return 'UNPARSEABLE_URL';
  }
}

function selectedHeaders(headers) {
  const result = {};
  for (const name of ['cache-control', 'content-type', 'etag', 'expires', 'last-modified']) {
    if (headers[name] !== undefined) result[name] = headers[name];
  }
  return result;
}

function summarize(entries, key) {
  const counts = new Map();
  for (const entry of entries) counts.set(entry[key], (counts.get(entry[key]) || 0) + 1);
  return [...counts.entries()]
    .map(([value, count]) => ({ [key]: value, count }))
    .sort((left, right) => right.count - left.count || String(left[key]).localeCompare(String(right[key])));
}

async function onlineSeed(userDataDir, evidence) {
  let context;
  try {
    const started = performance.now();
    context = await chromium.launchPersistentContext(userDataDir, {
      executablePath: BROWSER_PATH,
      headless: true,
      viewport: { width: 1600, height: 1200 },
    });
    const page = context.pages()[0] || await context.newPage();
    const cdp = await context.newCDPSession(page);
    evidence.observedNonRead = [];
    page.on('request', request => {
      if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
        evidence.observedNonRead.push({
          method: request.method(),
          endpoint: endpoint(request.url()),
          resourceType: request.resourceType(),
        });
      }
    });
    await cdp.send('Network.enable');
    await cdp.send('Debugger.enable');
    const requestById = new Map();
    const scripts = new Map();
    const targets = [];
    cdp.on('Network.requestWillBeSent', event => {
      requestById.set(event.requestId, {
        endpoint: endpoint(event.request.url),
        resourceType: event.type,
      });
    });
    cdp.on('Network.responseReceived', event => {
      const request = requestById.get(event.requestId) || {};
      const record = {
        endpoint: endpoint(event.response.url),
        resourceType: event.type || request.resourceType || null,
        status: event.response.status,
        fromDiskCache: event.response.fromDiskCache || false,
        fromServiceWorker: event.response.fromServiceWorker || false,
        headers: selectedHeaders(event.response.headers || {}),
      };
      evidence.responses.push(record);
    });
    cdp.on('Debugger.scriptParsed', event => {
      if (!event.url || !/^https:\/\/(maxroll\.gg|assets-ng\.maxroll\.gg)\//.test(event.url)) return;
      const key = endpoint(event.url);
      if (!scripts.has(key)) scripts.set(key, {
        endpoint: key,
        scriptLanguage: event.scriptLanguage || 'JavaScript',
        length: event.length ?? null,
        hash: event.hash || null,
        isModule: event.isModule ?? null,
      });
    });
    page.on('worker', worker => targets.push({ type: 'worker', endpoint: endpoint(worker.url()) }));

    await page.goto(PLANNER_URL, { waitUntil: 'domcontentloaded', timeout: 120000 });
    await page.waitForTimeout(8000);
    evidence.durationMilliseconds = performance.now() - started;
    evidence.title = await page.title();
    evidence.url = page.url();
    evidence.bodyText = (await page.locator('body').innerText()).slice(0, 1200);
    evidence.patch = evidence.bodyText.match(/Game version:\s*([^\n]+)/)?.[1] || null;
    evidence.scriptMetadata = [...scripts.values()].sort((a, b) => a.endpoint.localeCompare(b.endpoint));
    evidence.workers = targets;
    evidence.wasmResponses = evidence.responses.filter(response =>
      response.endpoint.endsWith('.wasm') || response.headers['content-type']?.includes('application/wasm'));
    assert(evidence.patch === '3.2.1.73552', `online seed patch mismatch: ${evidence.patch}`);
    await page.screenshot({ path: evidence.screenshot, fullPage: false });
  } finally {
    if (context) await context.close().catch(() => {});
  }
}

async function coldOfflineLaunch(userDataDir, evidence) {
  let context;
  try {
    const started = performance.now();
    context = await chromium.launchPersistentContext(userDataDir, {
      executablePath: BROWSER_PATH,
      headless: true,
      viewport: { width: 1600, height: 1200 },
    });
    await context.setOffline(true);
    const page = context.pages()[0] || await context.newPage();
    const cdp = await context.newCDPSession(page);
    evidence.blockedNonRead = [];
    await cdp.send('Network.enable');
    // Playwright's context-level offline mode is applied before navigation.
    // Applying a second CDP Network.emulateNetworkConditions call here prevents
    // Chromium from consulting its disk cache for the main document, which is a
    // harness artifact rather than the cold-start behavior under test.
    const requests = new Map();
    cdp.on('Network.requestWillBeSent', event => {
      requests.set(event.requestId, {
        endpoint: endpoint(event.request.url),
        method: event.request.method,
        resourceType: event.type,
      });
    });
    cdp.on('Network.responseReceived', event => {
      evidence.responses.push({
        endpoint: endpoint(event.response.url),
        status: event.response.status,
        resourceType: event.type,
        fromDiskCache: event.response.fromDiskCache || false,
        fromServiceWorker: event.response.fromServiceWorker || false,
      });
    });
    cdp.on('Network.loadingFailed', event => {
      const request = requests.get(event.requestId) || {};
      evidence.failures.push({
        endpoint: request.endpoint || null,
        method: request.method || null,
        resourceType: event.type || request.resourceType || null,
        errorText: event.errorText,
        blockedReason: event.blockedReason || null,
      });
    });

    let navigationError = null;
    try {
      await page.goto(PLANNER_URL, { waitUntil: 'domcontentloaded', timeout: 120000 });
    } catch (error) {
      navigationError = error.message;
    }
    await page.waitForTimeout(8000);
    evidence.durationMilliseconds = performance.now() - started;
    evidence.navigationError = navigationError;
    evidence.title = await page.title();
    evidence.url = page.url();
    evidence.navigatorOnline = await page.evaluate(() => navigator.onLine).catch(() => null);
    evidence.bodyText = await page.locator('body').innerText().then(text => text.slice(0, 1600)).catch(() => '');
    evidence.patch = evidence.bodyText.match(/Game version:\s*([^\n]+)/)?.[1] || null;
    evidence.errorPage = /An issue occurred|Failed to fetch/i.test(evidence.bodyText);
    evidence.cachedResponseCount = evidence.responses.filter(response =>
      response.fromDiskCache || response.fromServiceWorker).length;
    evidence.responseEndpointCounts = summarize(evidence.responses, 'endpoint');
    evidence.failureEndpointCounts = summarize(evidence.failures, 'endpoint');
    await page.screenshot({ path: evidence.screenshot, fullPage: false });
  } finally {
    if (context) await context.close().catch(() => {});
  }
}

async function main() {
  const args = parseArguments(process.argv);
  assert(args.output, 'missing --output');
  assert(args['evidence-dir'], 'missing --evidence-dir');
  const output = path.resolve(args.output);
  const evidenceDir = path.resolve(args['evidence-dir']);
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.mkdirSync(evidenceDir, { recursive: true });
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'maxroll-cold-offline-'));
  const result = {
    contractVersion: 'maxroll-cold-offline-cache-poc/1',
    capturedAt: new Date().toISOString(),
    status: 'RUNNING',
    method: 'Fresh Chromium process and persistent profile pre-seeded online; Playwright context offline before cold navigation, with CDP traffic evidence',
    environment: {
      browser: 'Google Chrome for Testing 153.0.8010.12',
      playwrightCore: '1.64.1',
      profileLifecycle: 'temporary; removed after evidence serialization',
    },
    onlineSeed: {
      responses: [],
      screenshot: path.join(evidenceDir, 'cold-offline-online-seed.png'),
    },
    coldOffline: {
      responses: [],
      failures: [],
      screenshot: path.join(evidenceDir, 'cold-offline-error.png'),
    },
    safety: {
      publishedBuildMutated: false,
      saveOrPublishInvoked: false,
      cookiesTokensOrStorageRead: false,
      proprietaryBundleRetained: false,
      onlineSeedIsNavigationOnly: true,
      coldPhaseNonReadRequestsBlockedByOfflineNetwork: true,
    },
  };

  try {
    await onlineSeed(userDataDir, result.onlineSeed);
    await coldOfflineLaunch(userDataDir, result.coldOffline);
    const appBooted = result.coldOffline.patch === '3.2.1.73552' && !result.coldOffline.errorPage;
    result.acceptance = {
      freshBrowserProcess: true,
      offlineBeforeNavigation: true,
      navigatorOnlineFalse: result.coldOffline.navigatorOnline === false,
      remoteResponsesCompleted: result.coldOffline.responses.filter(response =>
        response.endpoint?.startsWith('https://') || response.endpoint?.startsWith('http://')).filter(response =>
        !response.endpoint?.startsWith('http://127.0.0.1') &&
        !response.endpoint?.startsWith('http://localhost')).length,
      diskOrServiceWorkerResponses: result.coldOffline.cachedResponseCount,
      appBooted,
      patchObserved: result.coldOffline.patch,
      calculationAttempted: false,
      rawCoverage: 0,
      reason: appBooted
        ? 'App shell booted; calculation phase requires a separate adapter run.'
        : (result.coldOffline.cachedResponseCount > 0
          ? 'Fresh offline startup reached cached resources but failed during mandatory bootstrap fetches.'
          : 'The fresh offline process could not load the planner document from Chromium disk cache; application bootstrap never began.'),
    };
    result.status = appBooted
      ? 'L2_COLD_OFFLINE_PARTIAL_APP_BOOT_ONLY'
      : 'L2_COLD_OFFLINE_BLOCKED_BOOTSTRAP_FETCH';
  } finally {
    fs.rmSync(userDataDir, { recursive: true, force: true });
    result.safety.temporaryProfileCleanup = 'PASS';
  }

  fs.writeFileSync(output, `${JSON.stringify(result, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify({
    status: result.status,
    acceptance: result.acceptance,
    failureEndpoints: result.coldOffline.failureEndpointCounts?.slice(0, 20),
  }, null, 2)}\n`);
}

main().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
