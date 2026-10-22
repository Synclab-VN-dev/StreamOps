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
const { CONTRACT_VERSION, D4RuleKitApplication } = require('../../../../application/src');
const { MaxrollProvider } = require('../../src');
const { BASE_BUILD, createProfile, startRuntimeSite } = require('../helpers/fixtures');

const executablePath = process.env.BROWSER_INFRA_CHROMIUM_PATH;
if (!executablePath) throw new Error('BROWSER_INFRA_CHROMIUM_PATH is required for real Chromium E2E');

async function createIntegratedFixture(t) {
  const rootDir = await fs.mkdtemp(path.join(os.tmpdir(), 'maxroll-application-e2e-'));
  const site = await startRuntimeSite();
  const browser = new BrowserInfrastructure({
    executablePath, headless: true, maxContexts: 2, maxQueue: 2,
    contextOptions: { serviceWorkers: 'block' },
  });
  await browser.start();
  const snapshots = new WebSnapshotManager({
    browser, store: new FileSystemSnapshotStore({ rootDir }),
  });
  const draft = await snapshots.capture({
    url: site.sourceUrl,
    snapshotId: 'maxroll-synthetic-3-2-1',
    allowedOrigins: [site.origin],
    site: 'maxroll-shaped-synthetic',
    version: '3.2.1.73552',
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
  const application = new D4RuleKitApplication({
    providers: [provider], operationTimeoutMs: 5_000, cleanupTimeoutMs: 2_000,
  });
  t.after(async () => {
    await browser.stop().catch(() => {});
    await site.close().catch(() => {});
    await fs.rm(rootDir, { recursive: true, force: true });
  });
  return { application, profile, site };
}

function fireResistance(result) {
  return result.metrics.find(metric => metric.id === 'maxroll.heroDetails.446').rawValue;
}

test('Application uses MaxrollProvider through DI for all eight public APIs', async t => {
  const { application, profile, site } = await createIntegratedFixture(t);
  assert.deepEqual(application.listProviders().map(provider => provider.id), ['maxroll']);

  site.resetRequests();
  const created = await application.createSession({
    contractVersion: CONTRACT_VERSION,
    providerId: 'maxroll',
    providerVersion: profile.providerVersion,
    snapshotId: profile.snapshotId,
    snapshotManifestSha256: profile.snapshotManifestSha256,
    buildSchemaVersion: profile.supportedBuildSchemaVersion,
    build: BASE_BUILD,
  });
  const baseline = await application.evaluate(created.sessionId);
  assert.equal(baseline.metrics.length, 50);
  assert.equal(fireResistance(baseline), 22);

  const changes = [{ type: 'effect.set', effectId: 'of-dampening', active: true }];
  const preview = await application.previewChanges(created.sessionId, {
    expectedRevision: 0, changes,
  });
  assert.equal(preview.after.find(metric => metric.id === 'maxroll.heroDetails.446').rawValue, 2822);
  assert.equal(application.getSession(created.sessionId).revision, 0);
  const afterPreview = await application.evaluate(created.sessionId, { bypassCache: true });
  assert.equal(fireResistance(afterPreview), 22);

  const committed = await application.commitChanges(created.sessionId, {
    expectedRevision: 0, changes, previewToken: preview.previewToken,
  });
  assert.equal(committed.session.revision, 1);
  assert.equal(fireResistance(committed.result), 2822);

  const reset = await application.resetSession(created.sessionId, { expectedRevision: 1 });
  assert.equal(reset.revision, 2);
  const restored = await application.evaluate(created.sessionId, { bypassCache: true });
  assert.equal(fireResistance(restored), 22);
  assert.equal(site.requests.length, 0, 'offline-strict replay must not contact the origin');

  const closed = await application.closeSession(created.sessionId);
  assert.equal(closed.closed, true);
  assert.equal(closed.alreadyClosed, false);
  await assert.rejects(application.evaluate(created.sessionId), error => error.code === 'SESSION_NOT_FOUND');
});
