'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const test = require('node:test');
const { BrowserInfrastructure, FileSystemSnapshotStore,
  WebSnapshotManager } = require('@streamops/browser-infrastructure');
const {
  CANONICAL_SCHEMA_VERSION, MAXROLL_32173552_D12AM6KT_REFERENCE,
  MaxrollD12CanonicalCodec, MaxrollProvider, UniversalMaxrollComponentFactory,
  createMaxroll32173552D12aM6KTUniversalProfile, loadMaxrollEntityCatalog,
} = require('../../src');
const { D4RuleKitApplication } = require('../../../../application/src');

const SNAPSHOT_ID = 'maxroll-20261023T034150Z';
const MANIFEST_SHA = '638a283b8aa0cb822a35176d9d41c8d1751fb6f962ca0a2f7feaa20f1ef39e54';
const SOURCE_URL = 'https://maxroll.gg/d4/planner/1g1any0x';

function scratchBuild(classId) {
  return {
    schemaVersion: CANONICAL_SCHEMA_VERSION,
    game: { id: 'diablo-iv', patch: '3.2.1.73552' },
    character: { classId: String(classId), level: 1, worldTier: 0 },
    equipment: { slots: [] }, skills: { allocations: [], bar: [] },
    paragon: { boards: [] }, effects: { elixirs: [], warPlans: [] },
    world: {}, calculationContext: { season: 15, options: {} },
  };
}

test('C03 authored canonical builds for all eight classes load without native fixture state', {
  timeout: 540_000,
}, async () => {
  const chromiumExecutablePath = process.env.BROWSER_INFRA_CHROMIUM_PATH;
  const snapshotRoot = process.env.MAXROLL_AUTHORIZED_SNAPSHOT_ROOT;
  if (!chromiumExecutablePath || !snapshotRoot) throw new Error('real authored-build environment is required');
  const catalog = await loadMaxrollEntityCatalog({ snapshotRoot, snapshotId: SNAPSHOT_ID,
    expectedManifestSha256: MANIFEST_SHA });
  const codec = new MaxrollD12CanonicalCodec({ catalog });
  const profile = createMaxroll32173552D12aM6KTUniversalProfile({ snapshotId: SNAPSHOT_ID,
    snapshotManifestSha256: MANIFEST_SHA, sourceUrl: SOURCE_URL,
    assetUrl: `https://maxroll.gg${MAXROLL_32173552_D12AM6KT_REFERENCE.applicationAssetPath}`,
    catalog, authorizationRef: 'issue-134-approved-offline-snapshot',
    realRuntime: { discoverMetricCatalog: true,
      expectedRawMetrics: catalog.metricCatalog().length } });
  const browser = new BrowserInfrastructure({ executablePath: chromiumExecutablePath,
    headless: true, maxContexts: 1, maxQueue: 2,
    contextOptions: { serviceWorkers: 'block' } });
  const snapshots = new WebSnapshotManager({ browser,
    store: new FileSystemSnapshotStore({ rootDir: snapshotRoot }) });
  const selected = process.env.MAXROLL_TEST_CLASS_ID == null
    ? [...Array(8).keys()] : [Number(process.env.MAXROLL_TEST_CLASS_ID)];
  const evidence = [];
  try {
    await browser.start();
    for (const classId of selected) {
      const build = scratchBuild(classId);
      const item = catalog.firstEquippable(classId);
      build.character.level = 70;
      build.character.worldTier = 4;
      build.equipment.slots.push({ slotId: item.slotId, item: {
        baseItemId: item.itemId, itemPower: 800, affixes: [], implicits: [], aspects: [],
        tempers: [], sockets: [],
      } });
      build.world = { renownSkills: 0, renownParagon: 0 };
      build.effects.warPlans = Array.from({ length: catalog.counts.warPlans }, () => ({}));
      build.paragon.boards = [{ boardId: catalog.starterParagonBoard(classId), rotation: 0,
        allocations: [], position: { x: 0, y: 0 } }];
      const native = codec.canonicalToNative(build);
      const resolvedItems = Object.fromEntries(Object.entries(native.profiles[0].items)
        .map(([slotId, reference]) => [slotId, native.items[reference]]));
      assert.deepEqual(codec.runtimeStateToCanonical({ profile: native.profiles[0],
        items: resolvedItems, options: native.options, season: native.season }), build);
      const provider = new MaxrollProvider({ browser, snapshots, profile,
        componentFactory: new UniversalMaxrollComponentFactory({ codec, plannerId: '1g1any0x',
          profileUrl: 'https://planners.maxroll.gg/profiles/load/d4/1g1any0x' }),
        sessionTimeoutMs: 60_000 });
      const app = new D4RuleKitApplication({ providers: [provider], operationTimeoutMs: 60_000,
        cleanupTimeoutMs: 30_000 });
      let sessionId;
      try {
        sessionId = (await app.createSession({ contractVersion: 'd4-rulekit-application/v1',
          providerId: provider.id, providerVersion: provider.version, build,
          buildSchemaVersion: CANONICAL_SCHEMA_VERSION, snapshotId: SNAPSHOT_ID,
          snapshotManifestSha256: MANIFEST_SHA, timeoutMs: 60_000 })).sessionId;
        const result = await app.evaluate(sessionId, { bypassCache: true, timeoutMs: 60_000 });
        assert.ok(result.metrics.length > 0);
        assert.equal(result.metrics.every(metric => metric.status === 'OBSERVED'
          && Number.isFinite(metric.rawValue)), true);
        assert.equal(result.provenance.provider.runtimeAttestation.profileReadback.status, 'EXACT');
        assert.equal(result.provenance.provider.runtimeAttestation.network.externalEgressCompleted, 0);
        evidence.push({ classId, itemId: item.itemId, slotId: item.slotId,
          rawMetrics: result.metrics.length, readback: 'EXACT', egress: 0 });
      } finally {
        if (sessionId) await app.closeSession(sessionId);
      }
    }
  } finally {
    await browser.stop();
  }
  assert.equal(browser.getStatus().state, 'stopped');
  assert.equal(browser.getMetrics().currentContexts, 0);
  assert.equal(evidence.length, selected.length);
  if (process.env.MAXROLL_TEST_CLASS_ID == null) {
    const artifact = path.resolve(__dirname, '../../artifacts/issue134-authored.json');
    await fs.mkdir(path.dirname(artifact), { recursive: true });
    await fs.writeFile(artifact, `${JSON.stringify({
      schemaVersion: 'issue-134-authored-evidence/v1', status: 'PASS',
      classes: evidence, cleanup: 'PASS',
    }, null, 2)}\n`, { mode: 0o600 });
  }
});
