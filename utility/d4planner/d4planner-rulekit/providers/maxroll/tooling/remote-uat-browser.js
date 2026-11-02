#!/usr/bin/env node
'use strict';
// UI-only UAT: no export adapter or new calculation API.
const fs = require('node:fs');
const path = require('node:path');
const { BrowserInfrastructure, FileSystemSnapshotStore, WebSnapshotManager } = require('../../../browser-infra/src');
const { loadCatalog } = require('../../../snapshot-management/compatibility/loader');

async function main() {
  const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const runtime = process.argv[3];
  const binding = loadCatalog().definitions.find(d => d.identity.snapshotId === config.snapshotId
    && d.identity.snapshotManifestSha256 === config.manifestSha256);
  if (!binding) throw new Error('Unsupported configured snapshot binding');
  const store = new FileSystemSnapshotStore({ rootDir: config.snapshotRoot });
  const verified = await store.verify(config.snapshotId);
  if (verified.manifestSha256 !== config.manifestSha256) throw new Error('Snapshot integrity mismatch');
  const manifest = await store.load(config.snapshotId);
  const browser = new BrowserInfrastructure({ executablePath: config.chromium, headless: false,
    maxContexts: 1, leaseTimeoutMs: 8 * 60 * 60 * 1000,
    contextOptions: { serviceWorkers: 'block', viewport: { width: 1280, height: 800 }, acceptDownloads: false },
    launchOptions: { args: ['--window-position=0,0', '--window-size=1280,900'] } });
  let lease, timer, finish;
  const stopped = new Promise(resolve => { finish = resolve; });
  const stop = () => finish();
  process.once('SIGTERM', stop); process.once('SIGINT', stop);
  const network = { externalEgressCompleted: 0, webSocketHandshakes: 0 };
  function save(name, data) {
    const target = path.join(runtime, name);
    fs.writeFileSync(target + '.tmp', JSON.stringify(data, null, 2), { mode: 0o600 });
    fs.renameSync(target + '.tmp', target);
  }
  try {
    await browser.start();
    lease = await browser.acquire();
    const cdp = await lease.createCDPSession();
    await cdp.send('Network.enable');
    cdp.on('Network.responseReceived', event => { if (event.response.remoteIPAddress) network.externalEgressCompleted++; });
    cdp.on('Network.webSocketHandshakeResponseReceived', () => { network.webSocketHandshakes++; });
    const snapshots = new WebSnapshotManager({ browser, store });
    const mount = await snapshots.mount(lease, config.snapshotId);
    const page = lease.page;
    page.once('close', stop);
    await page.goto(manifest.sourceUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.getByRole('button', { name: 'New Profile', exact: true }).waitFor({ timeout: 30000 });
    const dismiss = page.getByRole('button', { name: 'No Thanks', exact: true });
    if (await dismiss.isVisible()) await dismiss.click();
    await page.getByRole('button', { name: 'New Profile', exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(runtime, 'planner.png') });
    const evidence = () => save('browser.json', { ready: true, version: browser.getStatus(),
      snapshotId: config.snapshotId, manifestSha256: verified.manifestSha256,
      replay: mount.getDiagnostics(), network, observedAt: new Date().toISOString() });
    evidence(); timer = setInterval(evidence, 2000);
    if (!page.isClosed()) await stopped;
  } finally {
    clearInterval(timer);
    try { await lease?.release(); } finally { await browser.stop(); }
    save('browser-cleanup.json', { status: browser.getStatus(), metrics: browser.getMetrics(), network });
    process.removeListener('SIGTERM', stop); process.removeListener('SIGINT', stop);
  }
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
