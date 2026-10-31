'use strict';
// Real Linux Node/Chromium and production composition, synthetic local content.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const readline = require('node:readline');
const { once } = require('node:events');
const { BrowserInfrastructure, FileSystemSnapshotStore, WebSnapshotManager } = require('../../browser-infra/src');
const { BASE_BUILD, createProfile, startRuntimeSite } = require('../../providers/maxroll/tests/helpers/fixtures');

test('private production bootstrap forwards eight APIs against a real offline synthetic runtime', { timeout: 30000 }, async t => {
  const executablePath = process.env.BROWSER_INFRA_CHROMIUM_PATH;
  assert.ok(executablePath, 'explicit isolated Chromium required');
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'f2-bootstrap-'));
  const site = await startRuntimeSite();
  const browser = new BrowserInfrastructure({ executablePath, headless: true, contextOptions: { serviceWorkers: 'block' } });
  let child;
  t.after(async () => {
    if (child && child.exitCode === null) {
      const exit = once(child, 'exit');
      child.stdin.end();
      const timer = setTimeout(() => child.kill('SIGKILL'), 5000);
      await exit;
      clearTimeout(timer);
    }
    await browser.stop(); await site.close(); await fs.rm(root, { recursive: true, force: true });
  });
  await browser.start();
  const snapshots = new WebSnapshotManager({ browser, store: new FileSystemSnapshotStore({ rootDir: root }) });
  await snapshots.save(await snapshots.capture({ url: site.sourceUrl, snapshotId: 'maxroll-synthetic-3-2-1',
    allowedOrigins: [site.origin], site: 'synthetic', version: '3.2.1.73552' }));
  const verified = await snapshots.verify('maxroll-synthetic-3-2-1');
  const profile = createProfile({ sourceUrl: site.sourceUrl, assetUrl: site.assetUrl,
    assetSha256: site.assetSha256, snapshotManifestSha256: verified.manifestSha256 });
  const profileFile = path.join(root, 'profile.json');
  await fs.writeFile(profileFile, JSON.stringify(profile));
  await browser.stop(); site.resetRequests();
  const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith('D4_RULEKIT_')));
  child = spawn(process.execPath, [path.resolve(__dirname, '../src/runtime/bootstrap.js'),
    path.resolve(__dirname, '../../../d4planner/src/d4planner/rulekit/worker.js')], { cwd: root,
    env: { ...env, D4_RULEKIT_WORKER_INSTANCE_ID: 'isolated-bootstrap', D4_RULEKIT_WORKER_GENERATION: '1',
      D4_RULEKIT_PROFILE_JSON: profileFile, D4_RULEKIT_SNAPSHOT_ROOT: root,
      D4_RULEKIT_CHROMIUM_EXECUTABLE: executablePath }, stdio: ['pipe', 'pipe', 'pipe'] });
  child.stderr.resume();
  const lines = readline.createInterface({ input: child.stdout })[Symbol.asyncIterator]();
  async function read() {
    const row = await lines.next(); assert.equal(row.done, false, 'worker exited before response');
    return JSON.parse(row.value);
  }
  const ready = await read(); assert.equal(ready.type, 'READY'); assert.equal(ready.apis.length, 8);
  let correlation = 0;
  async function call(method, params = {}) {
    const id = String(++correlation);
    child.stdin.write(JSON.stringify({ protocolVersion: 'd4-rulekit-ipc/v1', type: 'request', id, method, params }) + '\n');
    const result = await read(); assert.equal(result.correlationId, id); assert.equal(result.type, 'result', JSON.stringify(result.error));
    return result.result;
  }
  assert.equal((await call('listProviders'))[0].id, 'maxroll');
  const session = await call('createSession', { contractVersion: 'd4-rulekit-application/v1', providerId: 'maxroll',
    providerVersion: profile.providerVersion, snapshotId: profile.snapshotId, snapshotManifestSha256: profile.snapshotManifestSha256,
    buildSchemaVersion: profile.supportedBuildSchemaVersion, build: BASE_BUILD });
  const params = { sessionId: session.sessionId };
  const fire = result => result.metrics.find(metric => metric.id === 'maxroll.heroDetails.446').rawValue;
  assert.equal(fire(await call('evaluate', params)), 22);
  const changes = [{ type: 'effect.set', effectId: 'of-dampening', active: true }];
  const preview = await call('previewChanges', { ...params, request: { expectedRevision: 0, changes } });
  assert.equal(preview.after.find(metric => metric.id === 'maxroll.heroDetails.446').rawValue, 2822);
  assert.equal((await call('getSession', params)).revision, 0);
  const committed = await call('commitChanges', { ...params, request: { expectedRevision: 0, changes, previewToken: preview.previewToken } });
  assert.equal(fire(committed.result), 2822);
  assert.equal((await call('resetSession', { ...params, options: { expectedRevision: 1 } })).revision, 2);
  assert.equal(fire(await call('evaluate', params)), 22);
  assert.equal((await call('closeSession', params)).closed, true);
  assert.equal(site.requests.length, 0, 'offline replay must never contact origin');
  const exit = once(child, 'exit'); child.stdin.end();
  assert.deepEqual(await exit, [0, null]);
});
