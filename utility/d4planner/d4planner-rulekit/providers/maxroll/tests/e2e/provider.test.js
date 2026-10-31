'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const {
  BrowserInfrastructure,
  FileSystemSnapshotStore,
  WebSnapshotManager,
} = require('@streamops/browser-infrastructure');
const {
  ERROR_CODES, METRIC_CATALOG, MaxrollPatchProfile, MaxrollProvider,
} = require('../../src');
const { BASE_BUILD, createProfile, startRuntimeSite } = require('../helpers/fixtures');

const executablePath = process.env.BROWSER_INFRA_CHROMIUM_PATH;
if (!executablePath) throw new Error('BROWSER_INFRA_CHROMIUM_PATH is required for real Chromium E2E');

async function fixture(t) {
  const rootDir = await fs.mkdtemp(path.join(os.tmpdir(), 'maxroll-provider-e2e-'));
  const site = await startRuntimeSite();
  const browser = new BrowserInfrastructure({
    executablePath, headless: true, maxContexts: 3, maxQueue: 3,
    contextOptions: { serviceWorkers: 'block' },
  });
  await browser.start();
  const store = new FileSystemSnapshotStore({ rootDir });
  const snapshots = new WebSnapshotManager({ browser, store });
  const draft = await snapshots.capture({
    url: site.sourceUrl,
    snapshotId: 'maxroll-synthetic-3-2-1',
    allowedOrigins: [site.origin],
    site: 'maxroll-shaped-synthetic', version: '3.2.1.73552',
  });
  await snapshots.save(draft);
  const verification = await snapshots.verify('maxroll-synthetic-3-2-1');
  const profile = createProfile({
    sourceUrl: site.sourceUrl,
    assetUrl: site.assetUrl,
    assetSha256: site.assetSha256,
    snapshotManifestSha256: verification.manifestSha256,
  });
  const provider = new MaxrollProvider({ browser, snapshots, profile, sessionTimeoutMs: 5_000 });
  t.after(async () => {
    await browser.stop().catch(() => {});
    await site.close().catch(() => {});
    await fs.rm(rootDir, { recursive: true, force: true });
  });
  return { browser, provider, profile, site, snapshots, rootDir };
}

function sessionOptions(profile) {
  return {
    providerVersion: profile.providerVersion,
    snapshotId: profile.snapshotId,
    snapshotManifestSha256: profile.snapshotManifestSha256,
    buildSchemaVersion: profile.supportedBuildSchemaVersion,
    build: BASE_BUILD,
  };
}

async function chromiumRssBytes(pid) {
  if (!pid) return null;
  try {
    const status = await fs.readFile(`/proc/${pid}/status`, 'utf8');
    const match = status.match(/^VmRSS:\s+(\d+)\s+kB$/m);
    return match ? Number(match[1]) * 1024 : null;
  } catch {
    return null;
  }
}

test('MXP-08 records bounded cold load, warm calculation, queue and RSS measurements', async t => {
  const { browser, provider, profile } = await fixture(t);
  const loadStarted = process.hrtime.bigint();
  const session = await provider.createSession(sessionOptions(profile));
  const sessionLoadMs = Number(process.hrtime.bigint() - loadStarted) / 1e6;
  const durations = [];
  for (let index = 0; index < 3; index += 1) {
    const started = process.hrtime.bigint();
    await session.evaluate({
      build: BASE_BUILD, changes: [], buildSchemaVersion: profile.supportedBuildSchemaVersion,
    });
    durations.push(Number(process.hrtime.bigint() - started) / 1e6);
  }
  const browserMetrics = browser.getMetrics();
  const status = browser.getStatus();
  const report = {
    schemaVersion: 'maxroll-provider-performance/1',
    fixture: 'SYNTHETIC_MAXROLL_RUNTIME',
    browserLaunchMs: browserMetrics.lastLaunchDurationMs,
    sessionLoadMs,
    warmCalculationMs: durations,
    averageAcquireWaitMs: browserMetrics.averageAcquireWaitMs,
    nodeRssBytes: process.memoryUsage().rss,
    chromiumRssBytes: await chromiumRssBytes(status.pid),
  };
  for (const value of [report.browserLaunchMs, report.sessionLoadMs,
    ...report.warmCalculationMs, report.averageAcquireWaitMs, report.nodeRssBytes]) {
    assert.equal(Number.isFinite(value) && value >= 0, true);
  }
  await fs.mkdir(path.resolve(__dirname, '../../artifacts'), { recursive: true });
  await fs.writeFile(path.resolve(__dirname, '../../artifacts/performance.json'),
    `${JSON.stringify(report, null, 2)}\n`);
  await session.close();
});

test('MXP cold offline provider runs three exact A→B→A cycles with zero origin egress', async t => {
  const { provider, profile, site } = await fixture(t);
  site.resetRequests();
  const session = await provider.createSession(sessionOptions(profile));
  const checkpoint = await session.checkpoint();
  const rawA = [];
  const rawB = [];
  for (let cycle = 0; cycle < 3; cycle += 1) {
    const a = await session.evaluate({
      build: BASE_BUILD, changes: [], buildSchemaVersion: profile.supportedBuildSchemaVersion,
    });
    const b = await session.evaluate({
      build: BASE_BUILD,
      changes: [{ type: 'effect.set', effectId: 'of-dampening', active: true }],
      buildSchemaVersion: profile.supportedBuildSchemaVersion,
    });
    const restored = await session.restore(checkpoint);
    rawA.push(JSON.stringify(a.metrics.map(metric => metric.rawValue)));
    rawB.push(JSON.stringify(b.metrics.map(metric => metric.rawValue)));
    assert.deepEqual(restored.metrics.map(metric => metric.rawValue), a.metrics.map(metric => metric.rawValue));
    assert.equal(a.metrics.length, 50);
    assert.equal(a.metrics.filter(metric => metric.displayValue !== null).length, 34);
    assert.equal(b.metrics.find(metric => metric.id === 'maxroll.heroDetails.446').rawValue, 2822);
    assert.equal(a.metrics.find(metric => metric.id === 'maxroll.heroDetails.446').rawValue, 22);
  }
  assert.equal(new Set(rawA).size, 1);
  assert.equal(new Set(rawB).size, 1);
  assert.equal(site.requests.length, 0);
  await session.close();
});

test('MXP warm sessions are isolated and a browser restart invalidates old provider state', async t => {
  const { browser, provider, profile, site } = await fixture(t);
  site.resetRequests();
  const [first, second] = await Promise.all([
    provider.createSession(sessionOptions(profile)), provider.createSession(sessionOptions(profile)),
  ]);
  await first.evaluate({
    build: BASE_BUILD,
    changes: [{ type: 'effect.set', effectId: 'of-dampening', active: true }],
    buildSchemaVersion: profile.supportedBuildSchemaVersion,
  });
  const untouched = await second.evaluate({
    build: BASE_BUILD, changes: [], buildSchemaVersion: profile.supportedBuildSchemaVersion,
  });
  assert.equal(untouched.metrics.find(metric => metric.id === 'maxroll.heroDetails.446').rawValue, 22);
  await browser.restart();
  await assert.rejects(first.evaluate({
    build: BASE_BUILD, changes: [], buildSchemaVersion: profile.supportedBuildSchemaVersion,
  }), error => error.code === ERROR_CODES.SESSION_INVALIDATED);
  assert.equal(site.requests.length, 0);
  await Promise.allSettled([first.close(), second.close()]);
});

test('MXP profile rejects runtime identity drift fail-closed', async t => {
  const { browser, profile, site, snapshots } = await fixture(t);
  site.resetRequests();
  const drifted = new MaxrollPatchProfile({
    ...profile,
    runtimeVersion: 'unexpected-runtime',
    metricCatalog: METRIC_CATALOG,
    selectors: profile.selectors,
  });
  const provider = new MaxrollProvider({ browser, snapshots, profile: drifted });
  await assert.rejects(provider.createSession(sessionOptions(drifted)),
    error => error.code === ERROR_CODES.RUNTIME_MISMATCH || error.code === ERROR_CODES.RUNTIME_NOT_READY);
  assert.equal(site.requests.length, 0);
});

test('MXP provider rejects an incomplete current-phase metric set', async t => {
  const { browser, profile, site, snapshots } = await fixture(t);
  site.resetRequests();
  const incomplete = new MaxrollPatchProfile({
    ...profile,
    metricCatalog: [...METRIC_CATALOG, {
      id: 'maxroll.heroDetails.synthetic-missing', internalId: -1,
      category: 'synthetic', name: 'Missing fixture metric',
    }],
    selectors: profile.selectors,
  });
  const provider = new MaxrollProvider({ browser, snapshots, profile: incomplete });
  await assert.rejects(provider.createSession(sessionOptions(incomplete)),
    error => error.code === ERROR_CODES.METRICS_INCOMPLETE);
  assert.equal(site.requests.length, 0);
});
