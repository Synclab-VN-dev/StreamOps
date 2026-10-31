'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const {
  attestMaxrollBuildFixture,
  exportMaxrollBuildFromSnapshot,
} = require('../../src');

const SNAPSHOT_ID = 'maxroll-20261023T034150Z';
const MANIFEST_SHA = '638a283b8aa0cb822a35176d9d41c8d1751fb6f962ca0a2f7feaa20f1ef39e54';
const SOURCE_URL = 'https://maxroll.gg/d4/planner/1g1any0x';

function environment() {
  const chromiumExecutablePath = process.env.BROWSER_INFRA_CHROMIUM_PATH;
  const snapshotRoot = process.env.MAXROLL_AUTHORIZED_SNAPSHOT_ROOT;
  if (!chromiumExecutablePath || !snapshotRoot) {
    throw new Error('BROWSER_INFRA_CHROMIUM_PATH and MAXROLL_AUTHORIZED_SNAPSHOT_ROOT are required');
  }
  return { chromiumExecutablePath, snapshotRoot };
}

test('GB-E1 attests Midgame and Endgame source/replay through the executing engine', {
  timeout: 180_000,
}, async t => {
  const env = environment();
  const root = await fsp.mkdtemp(path.join(os.tmpdir(), 'maxroll-gb-e1-'));
  t.after(() => fsp.rm(root, { recursive: true, force: true }));
  const report = { schemaVersion: 'maxroll-build-attestation-acceptance/1',
    status: 'FAIL', fixtures: [] };
  for (const fixture of [{ profile: 3, name: 'rogue-midgame' },
    { profile: 4, name: 'rogue-endgame' }]) {
    const inputPath = path.join(root, `${fixture.name}.json`);
    const outputPath = path.join(root, `${fixture.name}.stats.json`);
    const exported = await exportMaxrollBuildFromSnapshot({
      url: SOURCE_URL,
      snapshotRoot: env.snapshotRoot,
      snapshotId: SNAPSHOT_ID,
      expectedManifestSha256: MANIFEST_SHA,
      profile: fixture.profile,
      outputPath: inputPath,
    });
    const result = await attestMaxrollBuildFixture({
      inputPath,
      outputPath,
      snapshotRoot: env.snapshotRoot,
      snapshotId: SNAPSHOT_ID,
      expectedManifestSha256: MANIFEST_SHA,
      chromiumExecutablePath: env.chromiumExecutablePath,
    });
    const observed = JSON.parse(await fsp.readFile(outputPath, 'utf8'));
    assert.deepEqual(Object.values(observed.gates).map(gate => gate.status),
      ['PASS', 'PASS', 'PASS', 'PASS']);
    assert.equal(result.rawCount, 50);
    assert.equal(new Set(observed.rawMetrics.map(metric => metric.metricId)).size, 50);
    assert.equal(observed.rawMetrics.every(metric => Number.isFinite(metric.rawValue)), true);
    assert.equal(observed.displayMetrics.every(metric => metric.metricId), true);
    assert.equal(result.sourceReplay, 'EXACT');
    for (const phase of [observed.gates.G4.source, observed.gates.G4.replay]) {
      assert.equal(phase.coherentMetricCount, 50);
      assert.equal(phase.epochIdentitySource, 'CDP_RUNTIME_OBJECT_IDENTITY:l.context');
      assert.match(phase.epochIdentitySha256, /^[a-f0-9]{64}$/);
      assert.equal(phase.epochComparisons > 0, true);
      assert.equal(phase.consistentDuplicateMetrics, 50);
    }
    assert.equal(observed.network.source.externalEgressCompleted, 0);
    assert.equal(observed.network.replay.externalEgressCompleted, 0);
    assert.equal(observed.cleanup.source.status, 'PASS');
    assert.equal(observed.cleanup.replay.status, 'PASS');
    report.fixtures.push({ name: fixture.name, inputSha256: exported.sha256,
      outputSha256: result.outputSha256, rawCount: result.rawCount,
      displayCount: result.displayCount, gates: 'G1-G4_PASS',
      coherentEpoch: 'CDP_RUNTIME_OBJECT_IDENTITY:l.context',
      sourceReplay: result.sourceReplay, externalEgressCompleted: 0,
      cleanup: 'PASS' });
  }
  report.status = 'PASS';
  fs.writeFileSync(path.resolve(__dirname, '../../artifacts/build-attestation-real.json'),
    `${JSON.stringify(report, null, 2)}\n`);
});
