'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const crypto = require('node:crypto');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { ERROR_CODES } = require('../../src');
const {
  MATRIX_SCHEMA_VERSION,
  installReadOnlyPolicy,
  validateMatrix,
  verifiedReuseFixtures,
} = require('../../src/class-fixture-capture');
const { serialize } = require('../../src/build-export');
const { parseArguments } = require('../../scripts/class-fixture-capture');

const defaultMatrix = JSON.parse(fs.readFileSync(
  path.join(__dirname, '..', '..', 'fixture-sources.json'), 'utf8'));

test('multi-class fixture matrix pins one unique source for every missing class', () => {
  const result = validateMatrix(defaultMatrix);
  assert.equal(result.schemaVersion, MATRIX_SCHEMA_VERSION);
  assert.deepEqual(result.fixtures.map(entry => entry.class).sort(), [
    'Barbarian', 'Druid', 'Necromancer', 'Paladin', 'Sorcerer', 'Spiritborn', 'Warlock',
  ]);
  assert.equal(result.reuse[0].class, 'Rogue');
  assert.equal(result.fixtures.every(entry => entry.url.startsWith(
    'https://maxroll.gg/d4/planner/')), true);
});

test('multi-class fixture matrix fails closed on duplicate class, unsafe URL and unknown action', () => {
  const duplicate = structuredClone(defaultMatrix);
  duplicate.fixtures[1].class = duplicate.fixtures[0].class;
  assert.throws(() => validateMatrix(duplicate), error => error.code === ERROR_CODES.INVALID_INPUT);
  const unsafe = structuredClone(defaultMatrix);
  unsafe.fixtures[0].url = 'https://example.com/d4/planner/j849ij0q';
  assert.throws(() => validateMatrix(unsafe), error => error.code === ERROR_CODES.INVALID_INPUT);
  const action = structuredClone(defaultMatrix);
  action.fixtures[0].action = 'REUSE';
  assert.throws(() => validateMatrix(action), error => error.code === ERROR_CODES.INVALID_INPUT);
});

test('multi-class fixture CLI parses only explicit bounded options', () => {
  assert.deepEqual(parseArguments([
    '--output', '/private/run', '--snapshot-root', '/snapshots',
    '--snapshot-id', 'snapshot', '--manifest-sha256', 'a'.repeat(64),
    '--chromium', '/usr/bin/chromium', '--class', 'Sorcerer', '--timeout-ms', '90000',
    '--reuse-root', '/private/reuse',
  ]), {
    outputRoot: '/private/run', snapshotRoot: '/snapshots', snapshotId: 'snapshot',
    expectedManifestSha256: 'a'.repeat(64), chromiumExecutablePath: '/usr/bin/chromium',
    className: 'Sorcerer', timeoutMs: 90000, reuseRoot: '/private/reuse',
  });
  assert.throws(() => parseArguments(['--unknown', 'value']), /unsupported/);
});

test('online capture policy allows only anonymous read methods on pinned Maxroll origins', async () => {
  let handler;
  await installReadOnlyPolicy({ route: async (pattern, callback) => {
    assert.equal(pattern, '**/*');
    handler = callback;
  } });
  const action = async (url, method) => {
    let result;
    await handler({
      request: () => ({ url: () => url, method: () => method }),
      continue: () => { result = 'continue'; },
      abort: () => { result = 'abort'; },
    });
    return result;
  };
  assert.equal(await action('https://maxroll.gg/d4/planner/id', 'GET'), 'continue');
  assert.equal(await action('https://planners.maxroll.gg/profiles/load/d4/id', 'HEAD'), 'continue');
  assert.equal(await action('https://maxroll.gg/api/save', 'POST'), 'abort');
  assert.equal(await action('https://example.com/tracker', 'GET'), 'abort');
});

test('MC-REV-01 reused evidence is linked to independent package, input, output and runtime pins', async t => {
  const root = await fsp.mkdtemp(path.join(os.tmpdir(), 'maxroll-reuse-'));
  t.after(() => fsp.rm(root, { recursive: true, force: true }));
  const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
  const nativeState = { profiles: [{ class: 3 }], items: {}, season: 15 };
  const nativeStateSha256 = hash(Buffer.from(serialize(nativeState)));
  const input = {
    schemaVersion: 'maxroll-native-build-export/v1', format: 'MAXROLL_NATIVE_STATE',
    selection: { class: 'Rogue', profileIndex: 0 }, nativeState,
    provenance: { snapshotManifestSha256: 'a'.repeat(64), runtimeAssetSha256: 'b'.repeat(64) },
    integrity: { nativeStateSha256 },
  };
  const inputBytes = Buffer.from(JSON.stringify(input));
  const inputSha256 = hash(inputBytes);
  const cleanup = { status: 'PASS', activeLeases: 0, currentContexts: 0,
    browserState: 'stopped', ownedProcessExited: true };
  const stats = {
    schemaVersion: 'maxroll-character-stats-attestation/v1',
    input: { class: 'Rogue', buildSha256: inputSha256, nativeStateSha256 },
    engine: { snapshotManifestSha256: 'a'.repeat(64), assetSha256: 'b'.repeat(64) },
    gates: Object.fromEntries(['G1', 'G2', 'G3', 'G4'].map(gate => [gate, { status: 'PASS' }])),
    coverage: { rawCount: 1, displayCount: 1 },
    rawMetrics: [{ metricId: 'metric-1', rawValue: 1, status: 'OBSERVED' }],
    displayMetrics: [{ metricId: 'metric-1', labelAnchor: 'summary|Metric',
      displayValue: '1', status: 'OBSERVED' }],
    sourceReplay: { status: 'EXACT' },
    network: { source: { externalEgressCompleted: 0 }, replay: { externalEgressCompleted: 0 } },
    cleanup: { source: cleanup, replay: cleanup },
  };
  const statsBytes = Buffer.from(JSON.stringify(stats));
  const statsSha256 = hash(statsBytes);
  const manifest = { files: {
    'rogue.json': { sha256: inputSha256 }, 'rogue.stats.json': { sha256: statsSha256 },
  }, pairs: [{ name: 'rogue', inputSha256, outputSha256: statsSha256, nativeStateSha256 }] };
  const manifestBytes = Buffer.from(JSON.stringify(manifest));
  await Promise.all([
    fsp.writeFile(path.join(root, 'rogue.json'), inputBytes),
    fsp.writeFile(path.join(root, 'rogue.stats.json'), statsBytes),
    fsp.writeFile(path.join(root, 'manifest.json'), manifestBytes),
  ]);
  const entry = { class: 'Rogue', fixture: 'rogue', profileIndex: 0,
    inputSha256, statsSha256, nativeStateSha256,
    trustedPackageManifestSha256: hash(manifestBytes), runtimeAssetSha256: 'b'.repeat(64),
    schemaVersion: stats.schemaVersion, rawCount: 1, displayCount: 1 };
  const matrix = { reuse: [entry] };
  assert.equal((await verifiedReuseFixtures(matrix, root, 'a'.repeat(64))).length, 1);

  for (const mutation of [
    value => { value.statsSha256 = 'c'.repeat(64); },
    value => { value.nativeStateSha256 = 'd'.repeat(64); },
    value => { value.runtimeAssetSha256 = 'e'.repeat(64); },
    value => { value.rawCount = 2; },
  ]) {
    const altered = structuredClone(entry);
    mutation(altered);
    await assert.rejects(verifiedReuseFixtures({ reuse: [altered] }, root, 'a'.repeat(64)),
      error => [ERROR_CODES.OUTPUT_NOT_LINKED, ERROR_CODES.INVALID_INPUT].includes(error.code));
  }
});
