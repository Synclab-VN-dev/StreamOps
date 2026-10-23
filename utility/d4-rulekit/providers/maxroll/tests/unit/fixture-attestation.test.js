'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { ERROR_CODES, attestMaxrollBuildFixture } = require('../../src');
const { compareCaptures } = require('../../src/fixture-attestation');
const { CalculationEpochAccumulator } = require('../../src/runtime-attestation');

let ordinal = 0;
function capture(overrides = {}) {
  ordinal += 1;
  const rawMetrics = Array.from({ length: 50 }, (_, index) => ({
    metricId: `maxroll.heroDetails.${index}`,
    rawValue: index,
  }));
  return {
    rawMetrics,
    displayMetrics: rawMetrics.map(metric => ({
      labelAnchor: `core|${metric.metricId}`,
      displayValue: String(metric.rawValue),
    })),
    captureId: `capture-${ordinal}`,
    engine: { status: 'EXECUTED', scriptId: '42', pauseScriptId: '42',
      pinnedSha256: 'a'.repeat(64), wireSha256: 'a'.repeat(64),
      scriptSourceSha256: 'a'.repeat(64) },
    profileReadback: { status: 'EXACT', normalizedProfileSha256: 'b'.repeat(64),
      resolvedItemsSha256: 'c'.repeat(64) },
    phase: { captureId: `capture-${ordinal}`, inputProfileSha256: 'b'.repeat(64),
      inputItemsSha256: 'c'.repeat(64), matchedPauseOrdinal: 1,
      firstMetricPauseOrdinal: 1, lastMetricPauseOrdinal: 50,
      epochIdentitySha256: 'e'.repeat(64),
      epochIdentitySource: 'CDP_RUNTIME_OBJECT_IDENTITY:l.context',
      coherentMetricCount: 50 },
    network: { externalEgressCompleted: 0, webSocketHandshakes: 0 },
    ...overrides,
  };
}

test('GB-E1 source and replay vectors require exact output linkage', () => {
  const result = compareCaptures(capture(), capture());
  assert.equal(result.status, 'EXACT');
  assert.equal(result.rawExact, true);
  assert.equal(result.displayExact, true);
});

test('GB-E1 rejects swapped or stale output', () => {
  const replay = capture();
  replay.rawMetrics = replay.rawMetrics.map((metric, index) =>
    index === 10 ? { ...metric, rawValue: 999 } : metric);
  assert.throws(() => compareCaptures(capture(), replay), error =>
    error.code === ERROR_CODES.OUTPUT_NOT_LINKED);
});

test('GB-E1 rejects wrong executing engine script', () => {
  assert.throws(() => compareCaptures(capture(), capture({
    engine: { status: 'EXECUTED', scriptId: '42', pauseScriptId: '99',
      pinnedSha256: 'a'.repeat(64), wireSha256: 'a'.repeat(64),
      scriptSourceSha256: 'a'.repeat(64) },
  })), error => error.code === ERROR_CODES.ENGINE_IDENTITY_UNVERIFIED);
});

test('GB-E1 rejects engine byte hash mismatch', () => {
  const replay = capture();
  replay.engine = { ...replay.engine, wireSha256: 'f'.repeat(64) };
  assert.throws(() => compareCaptures(capture(), replay), error =>
    error.code === ERROR_CODES.ENGINE_IDENTITY_UNVERIFIED);
});

test('GB-E1 rejects wrong profile semantic read-back', () => {
  const replay = capture();
  replay.profileReadback = { ...replay.profileReadback,
    normalizedProfileSha256: 'd'.repeat(64) };
  assert.throws(() => compareCaptures(capture(), replay), error =>
    error.code === ERROR_CODES.INPUT_READBACK_UNVERIFIED);
});

test('GB-E1 rejects partial semantic read-back', () => {
  const replay = capture();
  replay.profileReadback = { status: 'PARTIAL' };
  assert.throws(() => compareCaptures(capture(), replay), error =>
    error.code === ERROR_CODES.INPUT_READBACK_UNVERIFIED);
});

test('GB-E1 rejects stale phase ordering', () => {
  const replay = capture();
  replay.phase = { ...replay.phase, matchedPauseOrdinal: 20, firstMetricPauseOrdinal: 10 };
  assert.throws(() => compareCaptures(capture(), replay), error =>
    error.code === ERROR_CODES.STALE_METRICS);
});

test('GB-E1 rejects missing and duplicate metrics', () => {
  const missing = capture();
  missing.rawMetrics = missing.rawMetrics.slice(1);
  assert.throws(() => compareCaptures(capture(), missing), error =>
    error.code === ERROR_CODES.METRICS_INCOMPLETE);
  const duplicate = capture();
  duplicate.rawMetrics[49] = { ...duplicate.rawMetrics[0] };
  assert.throws(() => compareCaptures(capture(), duplicate), error =>
    error.code === ERROR_CODES.METRICS_INCOMPLETE);
});

test('GB-E1 rejects any completed egress', () => {
  assert.throws(() => compareCaptures(capture(), capture({
    network: { externalEgressCompleted: 1, webSocketHandshakes: 0 },
  })), error => error.code === ERROR_CODES.OUTPUT_NOT_LINKED);
});

test('GB-E1 refuses an existing output before browser or snapshot work', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'gb-e1-output-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const outputPath = path.join(root, 'existing.json');
  await fs.writeFile(outputPath, '{}');
  await assert.rejects(attestMaxrollBuildFixture({
    inputPath: path.join(root, 'missing-input.json'),
    outputPath,
    snapshotRoot: path.join(root, 'missing-snapshot'),
    snapshotId: 'snapshot',
    expectedManifestSha256: 'a'.repeat(64),
    chromiumExecutablePath: '/missing/chromium',
  }), error => error.code === ERROR_CODES.OUTPUT_EXISTS);
});

test('GB-REV-ATT-01 accepts 50 metrics from one runtime epoch', () => {
  const accumulator = new CalculationEpochAccumulator(Array.from({ length: 50 }, (_, id) => id));
  for (let id = 0; id < 50; id += 1) {
    accumulator.observe({ epochKey: 'epoch-A', internalId: id, rawValue: id, label: `m${id}` });
  }
  accumulator.assertComplete();
  assert.equal(accumulator.size, 50);
});

test('GB-REV-ATT-01 rejects 30 metrics from epoch A plus 20 from epoch B', () => {
  const accumulator = new CalculationEpochAccumulator(Array.from({ length: 50 }, (_, id) => id));
  for (let id = 0; id < 30; id += 1) {
    accumulator.observe({ epochKey: 'epoch-A', internalId: id, rawValue: id, label: `m${id}` });
  }
  assert.throws(() => accumulator.observe({ epochKey: 'epoch-B', internalId: 30,
    rawValue: 30, label: 'm30' }), error => error.code === ERROR_CODES.STALE_METRICS);
  assert.equal(accumulator.size, 30);
});

test('GB-REV-ATT-01 rejects an incomplete epoch', () => {
  const accumulator = new CalculationEpochAccumulator([1, 2]);
  accumulator.observe({ epochKey: 'epoch-A', internalId: 1, rawValue: 1, label: 'one' });
  assert.throws(() => accumulator.assertComplete(), error =>
    error.code === ERROR_CODES.METRICS_INCOMPLETE);
});

test('GB-REV-ATT-01 allows proven consistent duplicates but rejects inconsistent duplicates', () => {
  const accumulator = new CalculationEpochAccumulator([1, 2]);
  accumulator.observe({ epochKey: 'epoch-A', internalId: 1, rawValue: 1, label: 'one' });
  accumulator.observe({ epochKey: 'epoch-A', internalId: 1, rawValue: 1, label: 'one' });
  assert.equal(accumulator.consistentDuplicates, 1);
  assert.throws(() => accumulator.observe({ epochKey: 'epoch-A', internalId: 1,
    rawValue: 2, label: 'one' }), error => error.code === ERROR_CODES.OUTPUT_NOT_LINKED);
});
