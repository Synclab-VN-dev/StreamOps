'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const test = require('node:test');
const {
  MAXROLL_32173552_D12AM6KT_REFERENCE,
  METRIC_CATALOG,
  MaxrollD12CanonicalCodec,
  createMaxroll32173552D12aM6KTCandidateProfile,
  loadMaxrollEntityCatalog,
} = require('../../src');
const {
  runCapture,
  verifiedSnapshot,
  validateCaptureEvidence,
} = require('../../src/fixture-attestation');
const { semanticHash } = require('../../src/runtime-attestation');

const SNAPSHOT_ID = 'maxroll-20261023T034150Z';
const MANIFEST_SHA = '638a283b8aa0cb822a35176d9d41c8d1751fb6f962ca0a2f7feaa20f1ef39e54';
const SOURCE_URL = 'https://maxroll.gg/d4/planner/1g1any0x';

function environment() {
  const chromiumExecutablePath = process.env.BROWSER_INFRA_CHROMIUM_PATH;
  const snapshotRoot = process.env.MAXROLL_AUTHORIZED_SNAPSHOT_ROOT;
  const fixtureRoot = process.env.MAXROLL_B0_FIXTURE_ROOT;
  if (!chromiumExecutablePath || !snapshotRoot || !fixtureRoot) {
    throw new Error('BROWSER_INFRA_CHROMIUM_PATH, MAXROLL_AUTHORIZED_SNAPSHOT_ROOT and '
      + 'MAXROLL_B0_FIXTURE_ROOT are required');
  }
  return { chromiumExecutablePath, snapshotRoot, fixtureRoot };
}

function exactMetrics(actual, expected, identity, value) {
  const left = new Map(actual.map(metric => [metric[identity], metric[value]]));
  const right = new Map(expected.map(metric => [metric[identity], metric[value]]));
  assert.equal(left.size, actual.length);
  assert.equal(right.size, expected.length);
  assert.deepEqual([...left].sort(), [...right].sort());
  return semanticHash([...left].sort());
}

test('B0 imports Midgame and Endgame through one canonical codec and pinned engine', {
  timeout: 180_000,
}, async () => {
  const env = environment();
  const catalog = await loadMaxrollEntityCatalog({
    snapshotRoot: env.snapshotRoot,
    snapshotId: SNAPSHOT_ID,
    expectedManifestSha256: MANIFEST_SHA,
  });
  const codec = new MaxrollD12CanonicalCodec({ catalog });
  const assetUrl = `https://maxroll.gg${MAXROLL_32173552_D12AM6KT_REFERENCE.applicationAssetPath}`;
  const assetSha256 = MAXROLL_32173552_D12AM6KT_REFERENCE.applicationAssetSha256;
  const snapshot = await verifiedSnapshot({
    snapshotRoot: env.snapshotRoot,
    snapshotId: SNAPSHOT_ID,
    expectedManifestSha256: MANIFEST_SHA,
    sourceUrl: SOURCE_URL,
    assetUrl,
    assetSha256,
  });
  const profile = createMaxroll32173552D12aM6KTCandidateProfile({
    snapshotId: SNAPSHOT_ID,
    snapshotManifestSha256: MANIFEST_SHA,
    sourceUrl: SOURCE_URL,
    assetUrl,
    metricCatalog: METRIC_CATALOG,
    authorizationRef: 'issue-134-b0-approved-offline-snapshot',
  });
  const report = {
    schemaVersion: 'universal-import-b0-evidence/v1', status: 'FAIL', fixtures: [],
    snapshotId: SNAPSHOT_ID, snapshotManifestSha256: MANIFEST_SHA,
    engineAssetSha256: assetSha256,
  };

  for (const name of ['rogue-midgame', 'rogue-endgame']) {
    const [fixture, expected] = await Promise.all([
      fsp.readFile(path.join(env.fixtureRoot, `${name}.json`), 'utf8').then(JSON.parse),
      fsp.readFile(path.join(env.fixtureRoot, `${name}.stats.json`), 'utf8').then(JSON.parse),
    ]);
    const canonical = codec.nativeToCanonical(fixture);
    const nativeState = codec.canonicalToNative(canonical);
    assert.equal(Object.hasOwn(canonical, 'nativeState'), false);
    assert.equal(nativeState.profiles.length, 1);
    assert.equal(Object.keys(nativeState.items).length, canonical.equipment.slots.length);
    const replayFixture = {
      ...fixture,
      nativeState,
      selection: {
        ...fixture.selection,
        profileIndex: 0,
        profileName: 'Canonical Import',
      },
    };
    const semanticRoundTrip = codec.nativeToCanonical(replayFixture);
    assert.deepEqual(semanticRoundTrip, canonical);
    const capture = await runCapture({
      options: {
        snapshotRoot: env.snapshotRoot,
        snapshotId: SNAPSHOT_ID,
        expectedManifestSha256: MANIFEST_SHA,
        chromiumExecutablePath: env.chromiumExecutablePath,
        timeoutMs: 30_000,
      },
      fixture: replayFixture,
      snapshot,
      profile,
      mode: 'replay',
    });
    validateCaptureEvidence(capture);
    const rawSha256 = exactMetrics(capture.rawMetrics, expected.rawMetrics,
      'metricId', 'rawValue');
    const displaySha256 = exactMetrics(capture.displayMetrics, expected.displayMetrics,
      'labelAnchor', 'displayValue');
    assert.equal(capture.rawMetrics.length, 50);
    assert.equal(capture.rawMetrics.every(metric => Number.isFinite(metric.rawValue)), true);
    assert.equal(capture.displayMetrics.length, expected.displayMetrics.length);
    assert.equal(capture.network.externalEgressCompleted, 0);
    assert.equal(capture.network.webSocketHandshakes, 0);
    assert.equal(capture.cleanup.status, 'PASS');
    assert.equal(capture.phase.coherentMetricCount, 50);
    assert.equal(capture.phase.epochIdentitySource, 'CDP_RUNTIME_OBJECT_IDENTITY:l.context');
    report.fixtures.push({
      id: name,
      canonicalSha256: semanticHash(canonical),
      reconstructedNativeSha256: semanticHash(nativeState),
      semanticReadback: capture.profileReadback.status,
      G1: 'PASS', G2: capture.engine.status === 'EXECUTED' ? 'PASS' : 'FAIL',
      G3: capture.profileReadback.status === 'EXACT' ? 'PASS' : 'FAIL', G4: 'PASS',
      rawCount: capture.rawMetrics.length,
      displayCount: capture.displayMetrics.length,
      rawSha256, displaySha256,
      referenceParity: 'EXACT', externalEgressCompleted: capture.network.externalEgressCompleted,
      cleanup: capture.cleanup.status,
    });
  }
  assert.notEqual(report.fixtures[0].canonicalSha256, report.fixtures[1].canonicalSha256);
  report.status = 'B0_VERTICAL_SLICE_PASS';
  const artifacts = path.resolve(__dirname, '../../artifacts');
  fs.mkdirSync(artifacts, { recursive: true });
  fs.writeFileSync(path.join(artifacts, 'universal-import-b0-real.json'),
    `${JSON.stringify(report, null, 2)}\n`);
});
