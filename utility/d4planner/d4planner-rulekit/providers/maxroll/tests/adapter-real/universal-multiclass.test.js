'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const test = require('node:test');
const { BrowserInfrastructure, FileSystemSnapshotStore,
  WebSnapshotManager } = require('@streamops/browser-infrastructure');
const {
  CANONICAL_SCHEMA_VERSION,
  MAXROLL_32173552_D12AM6KT_REFERENCE,
  MaxrollD12CanonicalCodec,
  MaxrollProvider,
  UniversalMaxrollComponentFactory,
  createMaxroll32173552D12aM6KTUniversalProfile,
  loadMaxrollEntityCatalog,
} = require('../../src');
const { D4RuleKitApplication } = require('../../../../application/src');
const { runCapture, verifiedSnapshot } = require('../../src/fixture-attestation');

const SNAPSHOT_ID = 'maxroll-20261023T034150Z';
const MANIFEST_SHA = '638a283b8aa0cb822a35176d9d41c8d1751fb6f962ca0a2f7feaa20f1ef39e54';
const SNAPSHOT_SOURCE = 'https://maxroll.gg/d4/planner/1g1any0x';
const PLANNER_ID = '1g1any0x';

function exactMap(actual, expected, key, value) {
  const left = new Map(actual.map(entry => [entry[key], entry[value]]));
  const right = new Map(expected.map(entry => [entry[key], entry[value]]));
  assert.equal(left.size, actual.length, `duplicate actual ${key}`);
  assert.equal(right.size, expected.length, `duplicate expected ${key}`);
  assert.deepEqual([...left].sort(), [...right].sort());
}

test('C03-C05 all eight classes traverse canonical Application and exact pinned engine output', {
  timeout: 540_000,
}, async () => {
  const chromiumExecutablePath = process.env.BROWSER_INFRA_CHROMIUM_PATH;
  const snapshotRoot = process.env.MAXROLL_AUTHORIZED_SNAPSHOT_ROOT;
  const fixtureRoot = process.env.MAXROLL_MULTICLASS_FIXTURE_ROOT;
  if (!chromiumExecutablePath || !snapshotRoot || !fixtureRoot) {
    throw new Error('BROWSER_INFRA_CHROMIUM_PATH, MAXROLL_AUTHORIZED_SNAPSHOT_ROOT and '
      + 'MAXROLL_MULTICLASS_FIXTURE_ROOT are required');
  }
  const matrix = JSON.parse(await fs.readFile(path.join(fixtureRoot, 'fixture-matrix.json')));
  assert.equal(matrix.fixtures.length, 8);
  const selected = process.env.MAXROLL_TEST_CLASS
    ? matrix.fixtures.filter(row => row.class === process.env.MAXROLL_TEST_CLASS)
    : matrix.fixtures;
  assert.ok(selected.length > 0, 'selected class is absent from fixture matrix');
  const catalog = await loadMaxrollEntityCatalog({
    snapshotRoot, snapshotId: SNAPSHOT_ID, expectedManifestSha256: MANIFEST_SHA,
  });
  const codec = new MaxrollD12CanonicalCodec({ catalog });
  const metricCatalog = catalog.metricCatalog();
  assert.ok(metricCatalog.length >= 50, 'pinned catalog metric universe is incomplete');
  const snapshot = await verifiedSnapshot({ snapshotRoot, snapshotId: SNAPSHOT_ID,
    expectedManifestSha256: MANIFEST_SHA, sourceUrl: SNAPSHOT_SOURCE,
    assetUrl: `https://maxroll.gg${MAXROLL_32173552_D12AM6KT_REFERENCE.applicationAssetPath}`,
    assetSha256: MAXROLL_32173552_D12AM6KT_REFERENCE.applicationAssetSha256 });
  const browser = new BrowserInfrastructure({
    executablePath: chromiumExecutablePath, headless: true, maxContexts: 1, maxQueue: 2,
    contextOptions: { serviceWorkers: 'block' },
  });
  const snapshots = new WebSnapshotManager({ browser,
    store: new FileSystemSnapshotStore({ rootDir: snapshotRoot }) });
  const evidence = [];
  let app;
  let sessionId;
  try {
    await browser.start();
    for (const row of selected) {
      process.stderr.write(`# universal-class ${row.class}\n`);
      const [fixture, expected] = await Promise.all([
        fs.readFile(path.join(fixtureRoot, 'inputs', `${row.slug}.json`), 'utf8').then(JSON.parse),
        fs.readFile(path.join(fixtureRoot, 'expected', `${row.slug}.stats.json`), 'utf8')
          .then(JSON.parse),
      ]);
      const canonical = codec.nativeToCanonical(fixture);
      const reconstructed = codec.canonicalToNative(canonical);
      const replayFixture = { ...fixture, nativeState: reconstructed,
        selection: { ...fixture.selection, profileIndex: 0, profileName: 'Canonical Import' } };
      assert.deepEqual(codec.nativeToCanonical(replayFixture), canonical);
      const profile = createMaxroll32173552D12aM6KTUniversalProfile({
        snapshotId: SNAPSHOT_ID, snapshotManifestSha256: MANIFEST_SHA,
        sourceUrl: SNAPSHOT_SOURCE,
        assetUrl: `https://maxroll.gg${MAXROLL_32173552_D12AM6KT_REFERENCE.applicationAssetPath}`,
        catalog, authorizationRef: 'issue-134-r02-encrypted-release',
        realRuntime: { discoverMetricCatalog: true, expectedRawMetrics: metricCatalog.length },
      });
      const directFixture = structuredClone(fixture);
      directFixture.provenance.sourceUrl = SNAPSHOT_SOURCE;
      directFixture.provenance.plannerId = PLANNER_ID;
      const reference = await runCapture({ options: {
        snapshotRoot, snapshotId: SNAPSHOT_ID, expectedManifestSha256: MANIFEST_SHA,
        chromiumExecutablePath, timeoutMs: 60_000,
      }, fixture: directFixture, snapshot, profile, mode: 'replay' });
      const provider = new MaxrollProvider({ browser, snapshots, profile,
        componentFactory: new UniversalMaxrollComponentFactory({
          codec, plannerId: PLANNER_ID,
          profileUrl: `https://planners.maxroll.gg/profiles/load/d4/${PLANNER_ID}`,
        }), sessionTimeoutMs: 60_000 });
      app = new D4RuleKitApplication({ providers: [provider], operationTimeoutMs: 60_000,
        cleanupTimeoutMs: 30_000 });
      assert.equal(app.listProviders().length, 1);
      const created = await app.createSession({
        contractVersion: 'd4-rulekit-application/v1', providerId: provider.id,
        providerVersion: provider.version, build: canonical,
        buildSchemaVersion: CANONICAL_SCHEMA_VERSION, snapshotId: SNAPSHOT_ID,
        snapshotManifestSha256: MANIFEST_SHA, timeoutMs: 60_000,
      });
      sessionId = created.sessionId;
      let actual;
      try {
        actual = await app.evaluate(sessionId, { timeoutMs: 60_000, bypassCache: true });
      } catch (error) {
        process.stderr.write(`# application-error ${JSON.stringify(error.details ?? {})}\n`);
        throw error;
      }
      exactMap(actual.metrics, reference.rawMetrics.map(metric => ({ ...metric,
        id: metric.metricId })), 'id', 'rawValue');
      for (const metric of expected.rawMetrics) {
        assert.equal(actual.metrics.find(candidate => candidate.id === metric.metricId)?.rawValue,
          metric.rawValue, `published reference mismatch: ${metric.metricId}`);
      }
      const attestation = actual.provenance.provider.runtimeAttestation;
      exactMap(attestation.displayMetrics.filter(metric => Number.isInteger(metric.internalId)),
        reference.displayMetrics.filter(metric => Number.isInteger(metric.internalId)),
        'labelAnchor', 'displayValue');
      assert.equal(attestation.profileReadback.status, 'EXACT');
      assert.match(attestation.profileReadback.calculationOptions.status, /^EXACT/);
      assert.equal(attestation.calculationPhase.coherentMetricCount, reference.rawMetrics.length);
      assert.equal(attestation.calculationPhase.expectedMetricCount, reference.rawMetrics.length);
      assert.equal(attestation.network.externalEgressCompleted, 0);
      assert.equal(app.getSession(sessionId).revision, 0);
      await app.closeSession(sessionId);
      sessionId = null;
      app = null;
      assert.equal(browser.getMetrics().currentContexts, 0);
      evidence.push({ class: row.class, slug: row.slug, raw: actual.metrics.length,
        display: attestation.displayMetrics.length, publishedRaw: expected.rawMetrics.length,
        readback: 'EXACT', options: attestation.profileReadback.calculationOptions.status,
        egress: 0 });
    }
  } finally {
    const failures = [];
    try { if (sessionId && app) await app.closeSession(sessionId); } catch (error) { failures.push(error); }
    try { await browser.stop(); } catch (error) { failures.push(error); }
    if (failures.length) throw new AggregateError(failures, 'multi-class cleanup failed');
  }
  assert.equal(browser.getStatus().state, 'stopped');
  assert.equal(browser.getMetrics().currentContexts, 0);
  assert.equal(evidence.length, selected.length);
  if (!process.env.MAXROLL_TEST_CLASS) {
    const artifact = path.resolve(__dirname, '../../artifacts/issue134-multiclass.json');
    await fs.mkdir(path.dirname(artifact), { recursive: true });
    await fs.writeFile(artifact, `${JSON.stringify({
      schemaVersion: 'issue-134-multiclass-evidence/v1', status: 'PASS',
      snapshotId: SNAPSHOT_ID, manifestSha256: MANIFEST_SHA,
      engineSha256: MAXROLL_32173552_D12AM6KT_REFERENCE.applicationAssetSha256,
      metricUniverse: metricCatalog.length, classes: evidence, cleanup: 'PASS',
    }, null, 2)}\n`, { mode: 0o600 });
  }
});
