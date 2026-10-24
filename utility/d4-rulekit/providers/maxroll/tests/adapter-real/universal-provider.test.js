'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const test = require('node:test');
const {
  BrowserInfrastructure,
  FileSystemSnapshotStore,
  WebSnapshotManager,
} = require('@streamops/browser-infrastructure');
const {
  CANONICAL_SCHEMA_VERSION,
  MAXROLL_32173552_D12AM6KT_REFERENCE,
  METRIC_CATALOG,
  MaxrollD12CanonicalCodec,
  MaxrollProvider,
  UniversalMaxrollComponentFactory,
  createMaxroll32173552D12aM6KTUniversalProfile,
  loadMaxrollEntityCatalog,
} = require('../../src');
const { D4RuleKitApplication } = require('../../../../application/src');

const SNAPSHOT_ID = 'maxroll-20261023T034150Z';
const MANIFEST_SHA = '638a283b8aa0cb822a35176d9d41c8d1751fb6f962ca0a2f7feaa20f1ef39e54';

test('B3-B5 generic native-state provider loads a canonical build with attested metrics', {
  timeout: 180_000,
}, async () => {
  const chromiumExecutablePath = process.env.BROWSER_INFRA_CHROMIUM_PATH;
  const snapshotRoot = process.env.MAXROLL_AUTHORIZED_SNAPSHOT_ROOT;
  const fixtureRoot = process.env.MAXROLL_B0_FIXTURE_ROOT;
  if (!chromiumExecutablePath || !snapshotRoot || !fixtureRoot) {
    throw new Error('real universal provider environment is required');
  }
  const fixture = JSON.parse(await fs.readFile(path.join(fixtureRoot, 'rogue-midgame.json')));
  const catalog = await loadMaxrollEntityCatalog({
    snapshotRoot, snapshotId: SNAPSHOT_ID, expectedManifestSha256: MANIFEST_SHA,
  });
  const codec = new MaxrollD12CanonicalCodec({ catalog });
  const build = codec.nativeToCanonical(fixture);
  const profileUrl = `https://planners.maxroll.gg/profiles/load/d4/${fixture.provenance.plannerId}`;
  const profile = createMaxroll32173552D12aM6KTUniversalProfile({
    snapshotId: SNAPSHOT_ID,
    snapshotManifestSha256: MANIFEST_SHA,
    sourceUrl: fixture.provenance.sourceUrl,
    assetUrl: `https://maxroll.gg${MAXROLL_32173552_D12AM6KT_REFERENCE.applicationAssetPath}`,
    catalog, metricCatalog: METRIC_CATALOG,
    authorizationRef: 'issue-134-universal-approved-offline-snapshot',
  });
  const browser = new BrowserInfrastructure({
    executablePath: chromiumExecutablePath, headless: true, maxContexts: 1, maxQueue: 1,
    contextOptions: { serviceWorkers: 'block' },
  });
  const store = new FileSystemSnapshotStore({ rootDir: snapshotRoot });
  const snapshots = new WebSnapshotManager({ browser, store });
  const factory = new UniversalMaxrollComponentFactory({
    codec, profileUrl, plannerId: fixture.provenance.plannerId,
  });
  const provider = new MaxrollProvider({
    browser, snapshots, profile, componentFactory: factory, sessionTimeoutMs: 60_000,
  });
  let session;
  try {
    await browser.start();
    session = await provider.createSession({
      build, buildSchemaVersion: CANONICAL_SCHEMA_VERSION,
      snapshotId: SNAPSHOT_ID, snapshotManifestSha256: MANIFEST_SHA,
      timeoutMs: 60_000,
    });
    const evaluated = await session.evaluate({
      build, changes: [], buildSchemaVersion: CANONICAL_SCHEMA_VERSION,
      timeoutMs: 60_000,
    });
    assert.equal(evaluated.metrics.length, 50);
    assert.equal(evaluated.metrics.every(metric => metric.status === 'OBSERVED'
      && Number.isFinite(metric.rawValue)), true);
    assert.equal(evaluated.provenance.networkReplay.transportOffline, true);
    assert.equal(evaluated.build.schemaVersion, CANONICAL_SCHEMA_VERSION);
  } finally {
    await cleanupAll([() => session?.close(), () => browser.stop()]);
  }
  assert.equal(browser.getStatus().state, 'stopped');
  assert.equal(browser.getMetrics().currentContexts, 0);
});

test('B6 all eight Application APIs operate through the real universal provider', {
  timeout: 300_000,
}, async () => {
  const chromiumExecutablePath = process.env.BROWSER_INFRA_CHROMIUM_PATH;
  const snapshotRoot = process.env.MAXROLL_AUTHORIZED_SNAPSHOT_ROOT;
  const fixtureRoot = process.env.MAXROLL_B0_FIXTURE_ROOT;
  if (!chromiumExecutablePath || !snapshotRoot || !fixtureRoot) {
    throw new Error('real universal provider environment is required');
  }
  const [midgame, endgame, midgameStats, endgameStats] = await Promise.all([
    'rogue-midgame.json', 'rogue-endgame.json', 'rogue-midgame.stats.json',
    'rogue-endgame.stats.json',
  ].map(name => fs.readFile(path.join(fixtureRoot, name), 'utf8').then(JSON.parse)));
  const catalog = await loadMaxrollEntityCatalog({
    snapshotRoot, snapshotId: SNAPSHOT_ID, expectedManifestSha256: MANIFEST_SHA,
  });
  const codec = new MaxrollD12CanonicalCodec({ catalog });
  const buildA = codec.nativeToCanonical(midgame);
  const buildB = codec.nativeToCanonical(endgame);
  const profileUrl = `https://planners.maxroll.gg/profiles/load/d4/${midgame.provenance.plannerId}`;
  const profile = createMaxroll32173552D12aM6KTUniversalProfile({
    snapshotId: SNAPSHOT_ID,
    snapshotManifestSha256: MANIFEST_SHA,
    sourceUrl: midgame.provenance.sourceUrl,
    assetUrl: `https://maxroll.gg${MAXROLL_32173552_D12AM6KT_REFERENCE.applicationAssetPath}`,
    catalog, metricCatalog: METRIC_CATALOG,
    authorizationRef: 'issue-134-universal-approved-offline-snapshot',
  });
  const browser = new BrowserInfrastructure({
    executablePath: chromiumExecutablePath, headless: true, maxContexts: 1, maxQueue: 1,
    contextOptions: { serviceWorkers: 'block' },
  });
  const store = new FileSystemSnapshotStore({ rootDir: snapshotRoot });
  const snapshots = new WebSnapshotManager({ browser, store });
  const provider = new MaxrollProvider({
    browser, snapshots, profile,
    componentFactory: new UniversalMaxrollComponentFactory({
      codec, profileUrl, plannerId: midgame.provenance.plannerId,
    }),
    sessionTimeoutMs: 60_000,
  });
  const app = new D4RuleKitApplication({
    providers: [provider], operationTimeoutMs: 60_000, cleanupTimeoutMs: 30_000,
  });
  let sessionId;
  try {
    await browser.start();
    assert.equal(app.listProviders().length, 1);
    const created = await app.createSession({
      contractVersion: 'd4-rulekit-application/v1',
      providerId: provider.id, providerVersion: provider.version,
      build: buildA, buildSchemaVersion: CANONICAL_SCHEMA_VERSION,
      snapshotId: SNAPSHOT_ID, snapshotManifestSha256: MANIFEST_SHA,
      timeoutMs: 60_000,
    });
    sessionId = created.sessionId;
    const baseline = await app.evaluate(sessionId, { timeoutMs: 60_000 });
    assertMetricVector(baseline.metrics, midgameStats.rawMetrics);
    assert.equal(app.getSession(sessionId).revision, 0);
    const changes = [{ type: 'build.replace', build: buildB }];
    const preview = await app.previewChanges(sessionId, {
      expectedRevision: 0, changes, timeoutMs: 60_000,
    });
    assert.notEqual(preview.baseBuildFingerprint, preview.candidateBuildFingerprint);
    assertMetricVector(preview.before, midgameStats.rawMetrics);
    assertMetricVector(preview.after, endgameStats.rawMetrics);
    const beforeById = new Map(preview.before.map(metric => [metric.id, metric.rawValue]));
    const afterById = new Map(preview.after.map(metric => [metric.id, metric.rawValue]));
    for (const delta of preview.delta) {
      assert.equal(delta.before, beforeById.get(delta.id));
      assert.equal(delta.after, afterById.get(delta.id));
      assert.equal(delta.delta, delta.after - delta.before);
    }
    assert.equal(app.getSession(sessionId).revision, 0);
    const afterPreview = await app.evaluate(sessionId, { timeoutMs: 60_000, bypassCache: true });
    assertMetricVector(afterPreview.metrics, midgameStats.rawMetrics);
    const committed = await app.commitChanges(sessionId, {
      expectedRevision: 0, changes, previewToken: preview.previewToken, timeoutMs: 60_000,
    });
    assert.equal(committed.session.revision, 1);
    assertMetricVector(committed.result.metrics, endgameStats.rawMetrics);
    const reset = await app.resetSession(sessionId, { expectedRevision: 1, timeoutMs: 60_000 });
    assert.equal(reset.revision, 2);
    const restored = await app.evaluate(sessionId, { timeoutMs: 60_000, bypassCache: true });
    assert.equal(restored.inputFingerprint, baseline.inputFingerprint);
    assertMetricVector(restored.metrics, midgameStats.rawMetrics);
    await app.closeSession(sessionId);
    sessionId = null;
  } finally {
    await cleanupAll([() => sessionId ? app.closeSession(sessionId) : undefined,
      () => browser.stop()]);
  }
  assert.equal(browser.getStatus().state, 'stopped');
  assert.equal(browser.getMetrics().currentContexts, 0);
});

async function cleanupAll(steps) {
  const failures = [];
  for (const step of steps) {
    try { await step(); } catch (error) { failures.push(error); }
  }
  if (failures.length === 1) throw failures[0];
  if (failures.length > 1) throw new AggregateError(failures,
    'universal provider test cleanup failed');
}

function assertMetricVector(actual, expected) {
  const left = new Map(actual.map(metric => [metric.id, metric.rawValue]));
  const right = new Map(expected.map(metric => [metric.metricId, metric.rawValue]));
  assert.equal(left.size, actual.length);
  assert.equal(right.size, expected.length);
  assert.deepEqual([...left].sort(), [...right].sort());
}
