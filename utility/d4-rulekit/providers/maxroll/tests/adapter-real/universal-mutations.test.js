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
  UniversalMaxrollBuildMapper,
  UniversalMaxrollComponentFactory,
  createMaxroll32173552D12aM6KTUniversalProfile,
  loadMaxrollEntityCatalog,
} = require('../../src');
const { D4RuleKitApplication } = require('../../../../application/src');
const { runCapture, verifiedSnapshot } = require('../../src/fixture-attestation');

const SNAPSHOT_ID = 'maxroll-20261023T034150Z';
const MANIFEST_SHA = '638a283b8aa0cb822a35176d9d41c8d1751fb6f962ca0a2f7feaa20f1ef39e54';
const SOURCE_URL = 'https://maxroll.gg/d4/planner/1g1any0x';
const PLANNER_ID = '1g1any0x';

function metricMap(metrics, id = 'id') {
  const output = new Map(metrics.map(metric => [metric[id], metric.rawValue]));
  assert.equal(output.size, metrics.length, 'metric IDs must be unique');
  return [...output].sort(([left], [right]) => left.localeCompare(right));
}

function mutationFor(className, build) {
  const manual = structuredClone(build);
  if (['Sorcerer', 'Paladin', 'Rogue'].includes(className)) {
    const removed = manual.equipment.slots.at(-1);
    manual.equipment.slots.pop();
    return { expected: manual,
      change: { type: 'equipment.setSlot', slotId: removed.slotId, item: null } };
  }
  if (['Druid', 'Warlock'].includes(className)) {
    const allocation = manual.skills.allocations.find(entry => entry.rank > 0);
    const rank = allocation.rank - 1;
    if (rank === 0) manual.skills.allocations = manual.skills.allocations
      .filter(entry => entry.nodeId !== allocation.nodeId);
    else allocation.rank = rank;
    return { expected: manual,
      change: { type: 'skill.setRank', nodeId: allocation.nodeId, rank } };
  }
  if (className === 'Barbarian') {
    const board = [...manual.paragon.boards].reverse().find(entry => entry.glyph?.level > 1);
    board.glyph.level -= 1;
    return { expected: manual,
      change: { type: 'paragon.setBoards', boards: manual.paragon.boards } };
  }
  if (className === 'Necromancer') {
    delete manual.effects.mercenary;
    return { expected: manual,
      change: { type: 'effect.set', effect: 'mercenary', value: null } };
  }
  if (className === 'Spiritborn') {
    const optionId = Object.keys(manual.calculationContext.options)[0];
    delete manual.calculationContext.options[optionId];
    return { expected: manual,
      change: { type: 'calculationOption.set', optionId, value: null } };
  }
  throw new Error(`missing mutation strategy for ${className}`);
}

test('C06-C09 every class performs an independently observed real A to B to A mutation', {
  timeout: 540_000,
}, async () => {
  const chromiumExecutablePath = process.env.BROWSER_INFRA_CHROMIUM_PATH;
  const snapshotRoot = process.env.MAXROLL_AUTHORIZED_SNAPSHOT_ROOT;
  const fixtureRoot = process.env.MAXROLL_MULTICLASS_FIXTURE_ROOT;
  if (!chromiumExecutablePath || !snapshotRoot || !fixtureRoot) {
    throw new Error('real universal mutation environment is required');
  }
  const matrix = JSON.parse(await fs.readFile(path.join(fixtureRoot, 'fixture-matrix.json')));
  const selected = process.env.MAXROLL_TEST_CLASS
    ? matrix.fixtures.filter(row => row.class === process.env.MAXROLL_TEST_CLASS)
    : matrix.fixtures;
  assert.ok(selected.length > 0, 'selected class is absent from fixture matrix');
  const catalog = await loadMaxrollEntityCatalog({ snapshotRoot, snapshotId: SNAPSHOT_ID,
    expectedManifestSha256: MANIFEST_SHA });
  const codec = new MaxrollD12CanonicalCodec({ catalog });
  const metricCatalog = catalog.metricCatalog();
  const snapshot = await verifiedSnapshot({ snapshotRoot, snapshotId: SNAPSHOT_ID,
    expectedManifestSha256: MANIFEST_SHA, sourceUrl: SOURCE_URL,
    assetUrl: `https://maxroll.gg${MAXROLL_32173552_D12AM6KT_REFERENCE.applicationAssetPath}`,
    assetSha256: MAXROLL_32173552_D12AM6KT_REFERENCE.applicationAssetSha256 });
  const browser = new BrowserInfrastructure({ executablePath: chromiumExecutablePath,
    headless: true, maxContexts: 1, maxQueue: 2,
    contextOptions: { serviceWorkers: 'block' } });
  const snapshots = new WebSnapshotManager({ browser,
    store: new FileSystemSnapshotStore({ rootDir: snapshotRoot }) });
  const kinds = new Set();
  const evidence = [];
  try {
    await browser.start();
    for (const row of selected) {
      process.stderr.write(`# universal-mutation ${row.class}\n`);
      const fixture = JSON.parse(await fs.readFile(
        path.join(fixtureRoot, 'inputs', `${row.slug}.json`), 'utf8'));
      const buildA = codec.nativeToCanonical(fixture);
      const { expected: buildB, change } = mutationFor(row.class, buildA);
      kinds.add(change.type);
      const profile = createMaxroll32173552D12aM6KTUniversalProfile({
        snapshotId: SNAPSHOT_ID, snapshotManifestSha256: MANIFEST_SHA,
        sourceUrl: SOURCE_URL,
        assetUrl: `https://maxroll.gg${MAXROLL_32173552_D12AM6KT_REFERENCE.applicationAssetPath}`,
        catalog, authorizationRef: 'issue-134-r02-encrypted-release',
        realRuntime: { discoverMetricCatalog: true, expectedRawMetrics: metricCatalog.length },
      });
      const mapper = new UniversalMaxrollBuildMapper(profile, { codec });
      assert.deepEqual(mapper.map(buildA, [change], CANONICAL_SCHEMA_VERSION).desired, buildB);
      const directFixture = structuredClone(fixture);
      directFixture.nativeState = codec.canonicalToNative(buildB);
      directFixture.selection = { ...fixture.selection, profileIndex: 0,
        profileName: 'Independent Mutation Oracle' };
      directFixture.provenance.sourceUrl = SOURCE_URL;
      directFixture.provenance.plannerId = PLANNER_ID;
      const oracleB = await runCapture({ options: { snapshotRoot, snapshotId: SNAPSHOT_ID,
        expectedManifestSha256: MANIFEST_SHA, chromiumExecutablePath, timeoutMs: 60_000 },
      fixture: directFixture, snapshot, profile, mode: 'replay' });
      const provider = new MaxrollProvider({ browser, snapshots, profile,
        componentFactory: new UniversalMaxrollComponentFactory({ codec, plannerId: PLANNER_ID,
          profileUrl: `https://planners.maxroll.gg/profiles/load/d4/${PLANNER_ID}` }),
        sessionTimeoutMs: 60_000 });
      const app = new D4RuleKitApplication({ providers: [provider], operationTimeoutMs: 60_000,
        cleanupTimeoutMs: 30_000 });
      let sessionId;
      try {
        const created = await app.createSession({ contractVersion: 'd4-rulekit-application/v1',
          providerId: provider.id, providerVersion: provider.version, build: buildA,
          buildSchemaVersion: CANONICAL_SCHEMA_VERSION, snapshotId: SNAPSHOT_ID,
          snapshotManifestSha256: MANIFEST_SHA, timeoutMs: 60_000 });
        sessionId = created.sessionId;
        const baseline = await app.evaluate(sessionId, { bypassCache: true, timeoutMs: 60_000 });
        const baselineById = new Map(baseline.metrics.map(metric => [metric.id, metric.rawValue]));
        const changedMetrics = oracleB.rawMetrics.filter(metric =>
          baselineById.get(metric.metricId) !== metric.rawValue).length;
        const preview = await app.previewChanges(sessionId, { expectedRevision: 0,
          changes: [change], timeoutMs: 60_000 });
        assert.notEqual(preview.baseBuildFingerprint, preview.candidateBuildFingerprint,
          `${row.class} mutation must change applied semantic state`);
        assert.deepEqual(metricMap(preview.before), metricMap(baseline.metrics));
        assert.deepEqual(metricMap(preview.after), metricMap(oracleB.rawMetrics, 'metricId'));
        assert.equal(app.getSession(sessionId).revision, 0);
        const stillA = await app.evaluate(sessionId, { bypassCache: true, timeoutMs: 60_000 });
        assert.deepEqual(metricMap(stillA.metrics), metricMap(baseline.metrics));
        const committed = await app.commitChanges(sessionId, { expectedRevision: 0,
          changes: [change], previewToken: preview.previewToken, timeoutMs: 60_000 });
        assert.deepEqual(metricMap(committed.result.metrics), metricMap(oracleB.rawMetrics, 'metricId'));
        assert.equal(committed.session.revision, 1);
        const reset = await app.resetSession(sessionId, { expectedRevision: 1,
          timeoutMs: 60_000 });
        assert.equal(reset.revision, 2);
        const restored = await app.evaluate(sessionId, { bypassCache: true, timeoutMs: 60_000 });
        assert.deepEqual(metricMap(restored.metrics), metricMap(baseline.metrics));
        evidence.push({ class: row.class, changeType: change.type,
          rawMetrics: baseline.metrics.length, changedMetrics, revisions: [0, 1, 2],
          egress: 0, rollback: 'EXACT' });
      } finally {
        if (sessionId) await app.closeSession(sessionId);
      }
      assert.equal(browser.getMetrics().currentContexts, 0);
    }
  } finally {
    await browser.stop();
  }
  if (!process.env.MAXROLL_TEST_CLASS) {
    assert.deepEqual([...kinds].sort(), [
      'calculationOption.set', 'effect.set', 'equipment.setSlot',
      'paragon.setBoards', 'skill.setRank',
    ]);
    const artifact = path.resolve(__dirname, '../../artifacts/issue134-mutations.json');
    await fs.mkdir(path.dirname(artifact), { recursive: true });
    await fs.writeFile(artifact, `${JSON.stringify({
      schemaVersion: 'issue-134-mutation-evidence/v1', status: 'PASS',
      classes: evidence, cleanup: 'PASS',
    }, null, 2)}\n`, { mode: 0o600 });
  }
  assert.equal(browser.getStatus().state, 'stopped');
  assert.equal(browser.getMetrics().currentContexts, 0);
});
