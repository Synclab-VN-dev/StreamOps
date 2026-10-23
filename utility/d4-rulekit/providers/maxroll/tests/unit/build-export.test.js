'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { FileSystemSnapshotStore } = require('@streamops/browser-infrastructure');
const {
  ERROR_CODES,
  EXPORT_SCHEMA_VERSION,
  exportMaxrollBuildFromSnapshot,
  listMaxrollBuildProfilesFromSnapshot,
} = require('../../src');
const { parseArguments } = require('../../scripts/build-export');

const SNAPSHOT_ID = 'build-export-fixture';
const SOURCE_URL = 'https://maxroll.gg/d4/planner/1g1any0x';
const PROFILE_URL = 'https://planners.maxroll.gg/profiles/load/d4/1g1any0x';

function nativeState(overrides = {}) {
  return {
    embeds: [],
    profiles: [
      { name: 'Hidden', class: 3, level: 70, worldTier: 8, items: {}, hidden: true },
      { name: 'Starter', class: 3, level: 70, worldTier: 8, items: { 4: 10 }, hidden: false,
        skillTree: { steps: [{ data: { 1: 1 } }], position: 0 }, skillBar: [1],
        paragon: { steps: [{ data: [] }], position: 0 }, warPlans: [] },
      { name: 'Midgame', class: 3, level: 70, worldTier: 8, items: { 4: 11 }, hidden: false,
        skillTree: { steps: [{ data: { 2: 2 } }], position: 0 }, skillBar: [2],
        paragon: { steps: [{ data: [{ id: 'board-a' }] }], position: 0 },
        specialization: 'rogue-specialization', warPlans: [], mercenary: { id: 'mercenary' } },
      { name: 'Endgame', class: 3, level: 70, worldTier: 8, items: { 4: 12 }, hidden: false,
        skillTree: { steps: [{ data: { 3: 3 } }], position: 0 }, skillBar: [3],
        paragon: { steps: [{ data: [{ id: 'board-b' }] }], position: 0 },
        specialization: 'rogue-specialization', warPlans: [], mercenary: { id: 'mercenary' } },
    ],
    items: {
      10: { id: 'helm-starter', explicits: [] },
      11: { id: 'helm-midgame', explicits: [{ nid: 101, values: [1] }] },
      12: { id: 'helm-endgame', explicits: [{ nid: 102, values: [2] }] },
    },
    activeEmbed: -1,
    activeProfile: 3,
    options: {},
    pinnedStats: {},
    season: 15,
    ...overrides,
  };
}

function profileBody(state = nativeState()) {
  return JSON.stringify({
    id: '1g1any0x', name: 'Public Rogue fixture', class: 'Rogue', game: 'd4',
    public: true, season: '15', userId: 999, user: { id: 999, username: 'omitted' },
    data: JSON.stringify(state),
  });
}

async function createSnapshot(root, { state = nativeState(), includeProfile = true } = {}) {
  const store = new FileSystemSnapshotStore({ rootDir: root });
  const resources = [{
    key: 'GET https://maxroll.gg/assets/export-test.js', method: 'GET',
    url: 'https://maxroll.gg/assets/export-test.js', status: 200,
    headers: { 'content-type': 'application/javascript' }, body: 'test runtime',
  }];
  if (includeProfile) resources.push({
    key: `GET ${PROFILE_URL}`, method: 'GET', url: PROFILE_URL, status: 200,
    headers: { 'content-type': 'application/json' }, body: profileBody(state),
  });
  await store.save({
    snapshotId: SNAPSHOT_ID, sourceUrl: SOURCE_URL,
    capturedAt: '2026-10-23T03:41:54.689Z',
    allowedOrigins: ['https://maxroll.gg', 'https://planners.maxroll.gg'],
    site: 'maxroll-d4-planner', version: '3.2.1.73552',
    browserVersion: 'test-browser', playwrightVersion: '1.64.1', resources,
  });
  return { store, verification: await store.verify(SNAPSHOT_ID) };
}

function options(root, manifestSha256, overrides = {}) {
  return {
    url: SOURCE_URL, snapshotRoot: root, snapshotId: SNAPSHOT_ID,
    expectedManifestSha256: manifestSha256, ...overrides,
  };
}

async function rejectsCode(operation, code) {
  await assert.rejects(operation, error => error.code === code);
}

test('lists native profiles without exposing profile response bodies', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'maxroll-export-list-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const { verification } = await createSnapshot(root);
  const result = await listMaxrollBuildProfilesFromSnapshot(
    options(root, verification.manifestSha256));
  assert.deepEqual(result.profiles.map(profile => [profile.index, profile.name, profile.hidden]), [
    [0, 'Hidden', true], [1, 'Starter', false], [2, 'Midgame', false], [3, 'Endgame', false],
  ]);
  assert.equal(JSON.stringify(result).includes('username'), false);
  assert.equal(JSON.stringify(result).includes('helm-endgame'), false);
});

test('exports a deterministic complete native state and preserves all references', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'maxroll-export-positive-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const { verification } = await createSnapshot(root);
  const firstPath = path.join(root, 'private', 'midgame.json');
  const secondPath = path.join(root, 'private', 'midgame-copy.json');
  const first = await exportMaxrollBuildFromSnapshot(options(root,
    verification.manifestSha256, { profile: 2, outputPath: firstPath }));
  const second = await exportMaxrollBuildFromSnapshot(options(root,
    verification.manifestSha256, { profile: 2, outputPath: secondPath }));
  const [firstBytes, secondBytes] = await Promise.all([fs.readFile(firstPath), fs.readFile(secondPath)]);
  assert.deepEqual(firstBytes, secondBytes);
  assert.equal(first.sha256, second.sha256);
  const output = JSON.parse(firstBytes);
  assert.equal(output.schemaVersion, EXPORT_SCHEMA_VERSION);
  assert.equal(output.nativeState.activeProfile, 2);
  assert.deepEqual(output.nativeState.items, nativeState().items);
  assert.equal(output.nativeState.profiles.length, 4);
  assert.equal(output.selection.profileName, 'Midgame');
  assert.equal(output.selection.equipmentReferences, 1);
  assert.deepEqual(output.loaderMetadata.user, { id: 999, username: 'omitted' });
  assert.equal(output.loaderMetadata.userId, 999);
  assert.equal((await fs.stat(firstPath)).mode & 0o777, 0o600);
});

test('URL fragment selects a one-based visible profile without guessing native indexes', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'maxroll-export-fragment-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const { verification } = await createSnapshot(root);
  const outputPath = path.join(root, 'fragment.json');
  await exportMaxrollBuildFromSnapshot(options(root, verification.manifestSha256, {
    url: `${SOURCE_URL}#2`, outputPath,
  }));
  const output = JSON.parse(await fs.readFile(outputPath));
  assert.equal(output.selection.profileIndex, 2);
  assert.equal(output.selection.profileName, 'Midgame');
  assert.equal(output.selection.selectedBy, 'url-fragment');
});

test('fails closed for wrong URL, profile, manifest, existing output and invalid references', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'maxroll-export-negative-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const { verification } = await createSnapshot(root);
  const outputPath = path.join(root, 'fixture.json');
  const base = options(root, verification.manifestSha256, { outputPath });
  await rejectsCode(() => exportMaxrollBuildFromSnapshot({ ...base,
    url: 'https://maxroll.gg/d4/planner/notthere' }), ERROR_CODES.PROFILE_NOT_IN_SNAPSHOT);
  await rejectsCode(() => exportMaxrollBuildFromSnapshot({ ...base, profile: 99 }),
    ERROR_CODES.PROFILE_VARIANT_NOT_FOUND);
  await rejectsCode(() => exportMaxrollBuildFromSnapshot({ ...base,
    expectedManifestSha256: '0'.repeat(64) }), ERROR_CODES.SNAPSHOT_MISMATCH);
  await exportMaxrollBuildFromSnapshot({ ...base, profile: 3 });
  await rejectsCode(() => exportMaxrollBuildFromSnapshot({ ...base, profile: 3 }),
    ERROR_CODES.OUTPUT_EXISTS);

  const invalidRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'maxroll-export-invalid-'));
  t.after(() => fs.rm(invalidRoot, { recursive: true, force: true }));
  const invalid = nativeState();
  invalid.profiles[3].items[4] = 999;
  const invalidSnapshot = await createSnapshot(invalidRoot, { state: invalid });
  await rejectsCode(() => exportMaxrollBuildFromSnapshot(options(invalidRoot,
    invalidSnapshot.verification.manifestSha256, {
      profile: 3, outputPath: path.join(invalidRoot, 'invalid.json'),
    })), ERROR_CODES.NATIVE_BUILD_INVALID);
});

test('fails with PROFILE_NOT_IN_SNAPSHOT when the verified package lacks the profile response', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'maxroll-export-missing-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const { verification } = await createSnapshot(root, { includeProfile: false });
  await rejectsCode(() => exportMaxrollBuildFromSnapshot(options(root,
    verification.manifestSha256, { outputPath: path.join(root, 'missing.json') })),
  ERROR_CODES.PROFILE_NOT_IN_SNAPSHOT);
});

test('CLI argument parser keeps list and export modes explicit', () => {
  assert.deepEqual(parseArguments([
    '--url', SOURCE_URL, '--snapshot-root', '/snapshots', '--snapshot-id', SNAPSHOT_ID,
    '--manifest-sha256', 'a'.repeat(64), '--profile', '3', '--output', '/private/a.json',
  ]), {
    url: SOURCE_URL, snapshotRoot: '/snapshots', snapshotId: SNAPSHOT_ID,
    expectedManifestSha256: 'a'.repeat(64), profile: 3, outputPath: '/private/a.json',
  });
  assert.equal(parseArguments(['--list-profiles']).listProfiles, true);
  assert.throws(() => parseArguments(['--unknown']), /unsupported/);
});
