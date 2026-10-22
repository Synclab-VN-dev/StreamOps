'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { after, before, test } = require('node:test');
const {
  BrowserInfrastructure,
  FileSystemSnapshotStore,
  SNAPSHOT_ERROR_CODES,
  WebSnapshotError,
  WebSnapshotManager,
} = require('../../src');
const { startSnapshotSites } = require('../helpers/snapshot-sites');

const executablePath = process.env.BROWSER_INFRA_CHROMIUM_PATH;
if (!executablePath || !fs.existsSync(executablePath)) {
  throw new Error('BROWSER_INFRA_CHROMIUM_PATH must point to a pinned Chromium executable');
}

let sites;
let rootDir;
let serial = 0;
const active = new Set();

before(async () => {
  sites = await startSnapshotSites();
  rootDir = await fsp.mkdtemp(path.join(os.tmpdir(), 'streamops-snapshot-e2e-'));
});

after(async () => {
  await Promise.allSettled([...active].map(browser => browser.stop()));
  await sites.close();
  await fsp.rm(rootDir, { recursive: true, force: true });
});

function createBrowser() {
  const browser = new BrowserInfrastructure({
    executablePath,
    maxContexts: 2,
    maxQueue: 8,
    acquireTimeoutMs: 3_000,
    leaseTimeoutMs: 30_000,
    cleanupTimeoutMs: 3_000,
    contextOptions: { serviceWorkers: 'block' },
    launchOptions: { args: ['--disable-background-networking'] },
  });
  active.add(browser);
  return browser;
}

function createManager(browser, limits) {
  const store = new FileSystemSnapshotStore({ rootDir, limits });
  return { store, manager: new WebSnapshotManager({ browser, store }) };
}

function nextId(prefix) {
  serial += 1;
  return `${prefix}-${serial}`;
}

async function captureAndSave(browser, options) {
  const { manager } = createManager(browser);
  const draft = await manager.capture(options);
  const manifest = await manager.save(draft);
  return { manager, manifest, draft };
}

async function rejectsCode(promise, code) {
  await assert.rejects(promise, error =>
    error instanceof WebSnapshotError && error.code === code);
}

async function waitFor(predicate, timeoutMs = 5_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 20));
  }
  assert.fail('condition timed out');
}

test('SNAP-01 static HTML/CSS/JS/image/font captures and replays without origin traffic', async () => {
  const browser = createBrowser();
  await browser.start();
  const snapshotId = nextId('static');
  const { manager, manifest } = await captureAndSave(browser, {
    snapshotId,
    site: 'synthetic-static',
    version: 'v1',
    url: `${sites.staticSite.origin}/`,
    allowedOrigins: [sites.staticSite.origin],
  });
  assert.ok(manifest.resourceCount >= 5);
  assert.equal((await manager.verify(snapshotId)).valid, true);
  const before = sites.staticSite.requests.length;
  await browser.withLease({}, async lease => {
    const mount = await manager.mount(lease, snapshotId);
    await lease.page.goto(`${sites.staticSite.origin}/`);
    assert.equal(await lease.page.textContent('#result'), 'static-ready');
    assert.equal(await lease.page.locator('#pixel').evaluate(image => image.complete), true);
    assert.ok(mount.getDiagnostics().fulfilled >= 4);
  });
  assert.equal(sites.staticSite.requests.length, before);
});

test('SNAP-02 SPA dynamic import, navigation and JSON GET API replay deterministically', async () => {
  const browser = createBrowser();
  await browser.start();
  const snapshotId = nextId('spa');
  const { manager, manifest } = await captureAndSave(browser, {
    snapshotId,
    site: 'synthetic-spa',
    version: 'v1',
    url: `${sites.spa.origin}/`,
    allowedOrigins: [sites.spa.origin],
    interact: async ({ page }) => {
      await page.click('#load');
      await page.waitForSelector('#result:text-is("dynamic:42")');
    },
  });
  assert.ok(manifest.resources.some(resource => resource.url.endsWith('/chunk.js')));
  assert.ok(manifest.resources.some(resource => resource.url.endsWith('/api/data?view=full')));
  const before = sites.spa.requests.length;
  await browser.withLease({}, async lease => {
    await manager.mount(lease, snapshotId);
    await lease.page.goto(`${sites.spa.origin}/`);
    await lease.page.click('#load');
    await lease.page.waitForSelector('#result:text-is("dynamic:42")');
    assert.equal(new URL(lease.page.url()).pathname, '/loaded');
  });
  assert.equal(sites.spa.requests.length, before);
});

test('SNAP-03 multi-site/multi-version list remains isolated and immutable in real browser', async () => {
  const browser = createBrowser();
  await browser.start();
  const first = await captureAndSave(browser, {
    snapshotId: nextId('multi-a-v1'), site: 'multi-a', version: 'v1',
    url: `${sites.staticSite.origin}/`, allowedOrigins: [sites.staticSite.origin],
  });
  await captureAndSave(browser, {
    snapshotId: nextId('multi-a-v2'), site: 'multi-a', version: 'v2',
    url: `${sites.staticSite.origin}/`, allowedOrigins: [sites.staticSite.origin],
  });
  await captureAndSave(browser, {
    snapshotId: nextId('multi-b-v1'), site: 'multi-b', version: 'v1',
    url: `${sites.spa.origin}/`, allowedOrigins: [sites.spa.origin],
  });
  const rows = await first.manager.list({ version: 'v1' });
  assert.ok(rows.some(row => row.site === 'multi-a'));
  assert.ok(rows.some(row => row.site === 'multi-b'));
  await rejectsCode(first.manager.save(first.draft), SNAPSHOT_ERROR_CODES.DUPLICATE_SNAPSHOT);
});

test('SNAP-04 fresh Chromium process cold-replays SPA with zero source requests', async () => {
  const captureBrowser = createBrowser();
  await captureBrowser.start();
  const snapshotId = nextId('cold');
  const { manager } = await captureAndSave(captureBrowser, {
    snapshotId, site: 'cold-spa', version: 'v1',
    url: `${sites.spa.origin}/`, allowedOrigins: [sites.spa.origin],
    interact: async ({ page }) => {
      await page.click('#load');
      await page.waitForSelector('#result:text-is("dynamic:42")');
    },
  });
  const firstPid = captureBrowser.getStatus().pid;
  await captureBrowser.stop();
  active.delete(captureBrowser);
  const replayBrowser = createBrowser();
  await replayBrowser.start();
  assert.notEqual(replayBrowser.getStatus().pid, firstPid);
  const before = sites.spa.requests.length;
  await replayBrowser.withLease({}, async lease => {
    await manager.mount(lease, snapshotId);
    await lease.page.goto(`${sites.spa.origin}/`);
    await lease.page.click('#load');
    await lease.page.waitForSelector('#result:text-is("dynamic:42")');
  });
  assert.equal(sites.spa.requests.length, before);
});

test('SNAP-05/08 replay misses and wrong-site mounts fail closed; unmount restores network', async () => {
  const browser = createBrowser();
  await browser.start();
  const snapshotId = nextId('isolation');
  const { manager } = await captureAndSave(browser, {
    snapshotId, site: 'isolation', version: 'v1',
    url: `${sites.staticSite.origin}/`, allowedOrigins: [sites.staticSite.origin],
  });
  const lease = await browser.acquire();
  const mount = await manager.mount(lease, snapshotId);
  await assert.rejects(lease.page.goto(`${sites.spa.origin}/`));
  assert.ok(mount.getDiagnostics().misses.some(row => row.url === `${sites.spa.origin}/`));
  await mount.unmount();
  const before = sites.spa.requests.length;
  await lease.page.goto(`${sites.spa.origin}/`);
  assert.ok(sites.spa.requests.length > before);
  await lease.release();
});

test('SNAP-08 browser restart invalidates a mount and a new lease can remount', async () => {
  const browser = createBrowser();
  await browser.start();
  const snapshotId = nextId('restart-mount');
  const { manager } = await captureAndSave(browser, {
    snapshotId, site: 'restart-mount', version: 'v1',
    url: `${sites.staticSite.origin}/`, allowedOrigins: [sites.staticSite.origin],
  });
  const lease = await browser.acquire();
  const mount = await manager.mount(lease, snapshotId);
  await browser.restart();
  assert.equal(mount.mounted, false);
  await browser.withLease({}, async replacement => {
    const remounted = await manager.mount(replacement, snapshotId);
    await replacement.page.goto(`${sites.staticSite.origin}/`);
    assert.equal(await replacement.page.textContent('#result'), 'static-ready');
    await remounted.unmount();
  });
});

test('SNAP-03/10 concurrent capture, save and load remain isolated', async () => {
  const browser = createBrowser();
  await browser.start();
  const { manager } = createManager(browser);
  const ids = [nextId('concurrent-a'), nextId('concurrent-b')];
  const [first, second] = await Promise.all([
    manager.capture({ snapshotId: ids[0], site: 'concurrent', version: 'a',
      url: `${sites.staticSite.origin}/`, allowedOrigins: [sites.staticSite.origin] }),
    manager.capture({ snapshotId: ids[1], site: 'concurrent', version: 'b',
      url: `${sites.spa.origin}/`, allowedOrigins: [sites.spa.origin] }),
  ]);
  await Promise.all([manager.save(first), manager.save(second)]);
  const loaded = await Promise.all(ids.map(id => manager.load(id)));
  assert.deepEqual(loaded.map(row => row.snapshotId), ids);
  assert.notEqual(loaded[0].sourceUrl, loaded[1].sourceUrl);
});

test('SNAP-07 sensitive response data is excluded and sensitive request URLs are blocked', async () => {
  const browser = createBrowser();
  await browser.start();
  const snapshotId = nextId('sensitive');
  const requestOffset = sites.staticSite.requests.length;
  const { manifest, draft } = await captureAndSave(browser, {
    snapshotId, site: 'sensitive', version: 'v1',
    url: `${sites.staticSite.origin}/sensitive`, allowedOrigins: [sites.staticSite.origin],
  });
  const root = manifest.resources.find(resource => resource.url.endsWith('/sensitive'));
  assert.equal(root.headers.etag, 'fixture-etag');
  assert.equal(Object.hasOwn(root.headers, 'set-cookie'), false);
  assert.equal(JSON.stringify(manifest).includes('session=secret'), false);
  assert.equal(manifest.resources.some(resource => resource.url.endsWith('/private')), false);
  assert.equal(manifest.resources.some(resource => resource.url.endsWith('/write')), false);
  assert.ok(draft.capture.blockedRequestCount >= 2);
  assert.equal(sites.staticSite.requests.slice(requestOffset)
    .some(request => ['/private', '/write'].includes(request.url)), false);
  const { manager } = createManager(browser);
  await rejectsCode(manager.capture({
    snapshotId: nextId('blocked-query'),
    url: `${sites.staticSite.origin}/?token=secret`,
    allowedOrigins: [sites.staticSite.origin],
  }), SNAPSHOT_ERROR_CODES.POLICY_BLOCKED);
});

test('SNAP-10 cancellation and resource limits terminate capture without a package', async () => {
  const browser = createBrowser();
  await browser.start();
  const { manager } = createManager(browser);
  const timeoutId = nextId('timeout');
  await rejectsCode(manager.capture({
    snapshotId: timeoutId,
    url: `${sites.staticSite.origin}/slow`,
    allowedOrigins: [sites.staticSite.origin],
    timeoutMs: 30,
  }), SNAPSHOT_ERROR_CODES.CAPTURE_TIMEOUT);
  await rejectsCode(manager.load(timeoutId), SNAPSHOT_ERROR_CODES.SNAPSHOT_NOT_FOUND);
  await waitFor(() => browser.getStatus().state === 'running');
  await rejectsCode(manager.capture({
    snapshotId: nextId('resource-limit'),
    url: `${sites.staticSite.origin}/`,
    allowedOrigins: [sites.staticSite.origin],
    capturePolicy: { maxResources: 1 },
  }), SNAPSHOT_ERROR_CODES.RESOURCE_LIMIT);

  const controller = new AbortController();
  const cancelledId = nextId('cancelled');
  const cancelled = manager.capture({
    snapshotId: cancelledId,
    url: `${sites.staticSite.origin}/slow`,
    allowedOrigins: [sites.staticSite.origin],
    signal: controller.signal,
  });
  setTimeout(() => controller.abort(), 200);
  await rejectsCode(cancelled, SNAPSHOT_ERROR_CODES.CAPTURE_CANCELLED);
  await rejectsCode(manager.load(cancelledId), SNAPSHOT_ERROR_CODES.SNAPSHOT_NOT_FOUND);
});

test('SNAP-11/12/13 redirect/query/MIME/lazy cross-origin fidelity and SW block', async () => {
  const browser = createBrowser();
  await browser.start();
  const snapshotId = nextId('dynamic');
  const { manager, manifest, draft } = await captureAndSave(browser, {
    snapshotId, site: 'synthetic-dynamic', version: 'v1',
    url: `${sites.dynamic.origin}/`,
    allowedOrigins: [sites.dynamic.origin, sites.asset.origin],
    interact: async ({ page }) => {
      await page.click('#lazy');
      await page.waitForSelector('#result:text-is("lazy-ready")');
    },
  });
  assert.ok(manifest.resources.some(resource => resource.status === 302
    && resource.headers.location === '/landing?version=1'));
  const lazy = manifest.resources.find(resource => resource.url.endsWith('/lazy.png'));
  assert.equal(lazy.headers['content-type'], 'image/png');
  const missing = manifest.resources.find(resource => resource.url.endsWith('/missing?case=404'));
  assert.equal(missing.status, 404);
  assert.equal(missing.headers['content-type'], 'text/plain');
  assert.equal(manifest.resources.some(resource => resource.url.endsWith('/sw.js')), false);
  assert.equal(draft.capture.serviceWorkerPolicy, 'block');
  const dynamicBefore = sites.dynamic.requests.length;
  const assetBefore = sites.asset.requests.length;
  await browser.withLease({}, async lease => {
    const mount = await manager.mount(lease, snapshotId);
    await lease.page.goto(`${sites.dynamic.origin}/`);
    assert.equal(new URL(lease.page.url()).pathname, '/landing');
    await lease.page.click('#lazy');
    await lease.page.waitForSelector('#result:text-is("lazy-ready")');
    assert.deepEqual(await lease.page.evaluate(() => ({
      status: window.missingStatus, body: window.missingBody,
    })), { status: 404, body: 'missing' });
    assert.equal(await lease.page.evaluate(() => navigator.serviceWorker.controller), null);
    assert.equal(await lease.page.evaluate(() => window.webSocketBlocked), true);
    assert.equal(mount.getDiagnostics().aborted, 0);
  });
  assert.equal(sites.dynamic.requests.length, dynamicBefore);
  assert.equal(sites.asset.requests.length, assetBefore);
});
