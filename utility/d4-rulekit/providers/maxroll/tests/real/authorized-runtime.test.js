'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const {
  BrowserInfrastructure,
  FileSystemSnapshotStore,
  WebSnapshotManager,
} = require('@streamops/browser-infrastructure');
const { CONTRACT_VERSION, D4RuleKitApplication } = require('../../../../application/src');
const {
  METRIC_CATALOG,
  MaxrollProvider,
  REAL_MAXROLL_COMPONENT_FACTORY,
  createMaxroll32173552RealProfile,
} = require('../../src');
const { BASE_BUILD } = require('../helpers/fixtures');

const REQUIRED_ENV = [
  'BROWSER_INFRA_CHROMIUM_PATH',
  'MAXROLL_AUTHORIZED_SNAPSHOT_ROOT',
  'MAXROLL_AUTHORIZED_SNAPSHOT_ID',
  'MAXROLL_AUTHORIZED_MANIFEST_SHA256',
  'MAXROLL_SNAPSHOT_AUTHORIZATION_REF',
];

function requireAuthorizedEnvironment() {
  const missing = REQUIRED_ENV.filter(name => !process.env[name]);
  if (missing.length) {
    throw new Error(`BLOCKED_AUTHORIZED_SNAPSHOT: missing ${missing.join(', ')}`);
  }
  if (!/^[a-f0-9]{64}$/i.test(process.env.MAXROLL_AUTHORIZED_MANIFEST_SHA256)) {
    throw new Error('BLOCKED_AUTHORIZED_SNAPSHOT: manifest trust anchor must be SHA-256');
  }
}

function sessionOptions(profile) {
  return {
    contractVersion: CONTRACT_VERSION,
    providerVersion: profile.providerVersion,
    expectedGamePatch: profile.gamePatch,
    snapshotId: profile.snapshotId,
    snapshotManifestSha256: profile.snapshotManifestSha256,
    buildSchemaVersion: profile.supportedBuildSchemaVersion,
    build: BASE_BUILD,
  };
}

function raw(metrics) { return metrics.map(metric => metric.rawValue); }
function fire(metrics) {
  return metrics.find(metric => metric.id === 'maxroll.heroDetails.446')?.rawValue;
}

async function fixture(t) {
  requireAuthorizedEnvironment();
  const browser = new BrowserInfrastructure({
    executablePath: process.env.BROWSER_INFRA_CHROMIUM_PATH,
    headless: true,
    maxContexts: 2,
    maxQueue: 2,
    contextOptions: { serviceWorkers: 'block' },
  });
  await browser.start();
  const snapshots = new WebSnapshotManager({
    browser,
    store: new FileSystemSnapshotStore({ rootDir: process.env.MAXROLL_AUTHORIZED_SNAPSHOT_ROOT }),
  });
  const profile = createMaxroll32173552RealProfile({
    snapshotId: process.env.MAXROLL_AUTHORIZED_SNAPSHOT_ID,
    snapshotManifestSha256: process.env.MAXROLL_AUTHORIZED_MANIFEST_SHA256,
    sourceUrl: process.env.MAXROLL_SOURCE_URL ?? 'https://maxroll.gg/d4/planner/1g1any0x#3',
    authorizationRef: process.env.MAXROLL_SNAPSHOT_AUTHORIZATION_REF,
    metricCatalog: METRIC_CATALOG,
  });
  const provider = new MaxrollProvider({
    browser,
    snapshots,
    profile,
    componentFactory: REAL_MAXROLL_COMPONENT_FACTORY,
    sessionTimeoutMs: 90_000,
  });
  t.after(async () => { await browser.stop().catch(() => {}); });
  return { profile, provider };
}

test('MXP-09 authorized offline runtime preserves three exact A→B→A cycles', {
  timeout: 150_000,
}, async t => {
  const { provider, profile } = await fixture(t);
  const session = await provider.createSession(sessionOptions(profile));
  const checkpoint = await session.checkpoint();
  let canonicalA = null;
  let canonicalB = null;
  for (let cycle = 0; cycle < 3; cycle += 1) {
    const a = await session.evaluate({
      build: BASE_BUILD,
      buildSchemaVersion: profile.supportedBuildSchemaVersion,
    });
    const b = await session.evaluate({
      build: BASE_BUILD,
      changes: [{ type: 'effect.set', effectId: 'of-dampening', active: true }],
      buildSchemaVersion: profile.supportedBuildSchemaVersion,
    });
    const a2 = await session.restore(checkpoint);
    assert.equal(a.metrics.length, 50);
    assert.equal(a.metrics.filter(metric => metric.displayValue !== null).length, 34);
    assert.equal(b.metrics.length, 50);
    assert.equal(b.metrics.filter(metric => metric.displayValue !== null).length, 34);
    assert.equal(fire(a.metrics), 22);
    assert.equal(fire(b.metrics), 2822);
    assert.equal(a.provenance.networkReplay.transportOffline, true);
    assert.deepEqual(raw(a2.metrics), raw(a.metrics));
    canonicalA ??= raw(a.metrics);
    canonicalB ??= raw(b.metrics);
    assert.deepEqual(raw(a.metrics), canonicalA);
    assert.deepEqual(raw(b.metrics), canonicalB);
  }
  await session.close();
});

test('MXP-10 and APP-07 exercise all eight APIs through the authorized real provider', {
  timeout: 150_000,
}, async t => {
  const { provider, profile } = await fixture(t);
  const application = new D4RuleKitApplication({
    providers: [provider], operationTimeoutMs: 90_000, cleanupTimeoutMs: 15_000,
  });
  assert.deepEqual(application.listProviders().map(value => value.id), ['maxroll']);
  const created = await application.createSession({
    ...sessionOptions(profile), providerId: 'maxroll',
  });
  const a = await application.evaluate(created.sessionId, { bypassCache: true });
  const change = [{ type: 'effect.set', effectId: 'of-dampening', active: true }];
  const preview = await application.previewChanges(created.sessionId, {
    expectedRevision: 0, changes: change,
  });
  assert.equal(fire(preview.before), 22);
  assert.equal(fire(preview.after), 2822);
  assert.equal(application.getSession(created.sessionId).revision, 0);
  assert.equal(fire((await application.evaluate(created.sessionId, { bypassCache: true })).metrics), 22);
  const committed = await application.commitChanges(created.sessionId, {
    expectedRevision: 0, changes: change, previewToken: preview.previewToken,
  });
  assert.equal(committed.session.revision, 1);
  assert.equal(fire(committed.result.metrics), 2822);
  const reset = await application.resetSession(created.sessionId, { expectedRevision: 1 });
  assert.equal(reset.revision, 2);
  assert.deepEqual(raw((await application.evaluate(created.sessionId, { bypassCache: true })).metrics),
    raw(a.metrics));
  const closed = await application.closeSession(created.sessionId);
  assert.equal(closed.closed, true);
});
