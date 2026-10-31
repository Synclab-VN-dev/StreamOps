'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { ERROR_CODES, attestMaxrollBuildFixture } = require('../../src');
const { compareCaptures } = require('../../src/fixture-attestation');
const { D12_OPTION_READBACK_RULES } = require('../../src/d12-option-readback');
const { D12_SHARED_OPTION_DEFINITIONS } = require('../../src/d12-shared-options');
const { CalculationEpochAccumulator, exactOptionReadback,
  normalizedExpectedOptions, resolveApplicableMetricInventory, resolveSharedOptionControls,
  semanticHash } = require('../../src/runtime-attestation');

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

test('semantic section hashing distinguishes an absent field from null', () => {
  assert.match(semanticHash(undefined), /^[a-f0-9]{64}$/);
  assert.notEqual(semanticHash(undefined), semanticHash(null));
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

test('multi-class source/replay comparison permits measured online source traffic only', () => {
  const source = capture({
    network: { externalEgressCompleted: 4, webSocketHandshakes: 0 },
  });
  const replay = capture();
  assert.equal(compareCaptures(source, replay, { sourceOnline: true }).status, 'EXACT');
  const replayWithEgress = capture({
    network: { externalEgressCompleted: 1, webSocketHandshakes: 0 },
  });
  assert.throws(() => compareCaptures(source, replayWithEgress, { sourceOnline: true }),
    error => error.code === ERROR_CODES.OUTPUT_NOT_LINKED);
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

test('MC-REV-02 metric discovery waits for the independently enumerated set, not a low count', () => {
  const accumulator = new CalculationEpochAccumulator({ discover: true });
  accumulator.observe({ epochKey: 'epoch-A', internalId: 1001, rawValue: 1, label: 'one' });
  assert.equal(accumulator.complete, false);
  accumulator.observe({ epochKey: 'epoch-A', internalId: 1002, rawValue: 2, label: 'two' });
  accumulator.observe({ epochKey: 'epoch-A', internalId: 1003, rawValue: 3, label: 'three' });
  assert.equal(accumulator.complete, false);
  accumulator.finalize(new Set([1001, 1002, 1003]));
  accumulator.assertComplete();
  assert.deepEqual(accumulator.observedIds, [1001, 1002, 1003]);
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

test('FULL-REV-02 calculation option read-back rejects ignored or altered applicable state', () => {
  const expected = { Skill_A: { flags: [true], params: [2] },
    shared: { enemy_burning: true } };
  const exact = exactOptionReadback(expected, [{ power: 'Skill_A',
    options: { flags: [true], params: [2] } }], { enemy_burning: true });
  assert.equal(exact.status, 'EXACT');
  assert.deepEqual(exact.notApplicable, []);
  assert.throws(() => exactOptionReadback(expected, [{ power: 'Skill_A',
    options: { flags: [false], params: [2] } }], { enemy_burning: true }),
  error => error.code === ERROR_CODES.READBACK_MISMATCH);
  assert.throws(() => exactOptionReadback(expected, [{ power: 'Skill_A',
    options: { flags: [true], params: [2] } }], {}),
  error => error.code === ERROR_CODES.INPUT_READBACK_UNVERIFIED);
});

test('FULL-REV-02 shared options are read from exact scoped UI controls, never input echo', () => {
  const definitions = {
    enemy_burning: { group: 'Enemy', labels: ['Burning'] },
    enemy_type: { group: 'Enemy', labels: ['Type'], options: ['Normal', 'Boss'] },
    primary_resource: { group: 'Player', labels: ['Mana'], normalize: 'percent-of-max' },
  };
  const observed = resolveSharedOptionControls({ enemy_burning: true, enemy_type: 1,
    primary_resource: 50 }, [
    { group: 'Enemy', label: 'Burning', kind: 'checkbox', checked: true },
    { group: 'Enemy', label: 'Type', kind: 'select', value: 'Boss' },
    { group: 'Player', label: 'Mana', kind: 'number', value: 75, max: 150 },
  ], definitions);
  assert.deepEqual(observed.values,
    { enemy_burning: true, enemy_type: 1, primary_resource: 50 });
  assert.deepEqual(observed.notApplicable, []);
  assert.throws(() => resolveSharedOptionControls({ enemy_burning: true }, [], definitions),
    error => error.code === ERROR_CODES.INPUT_READBACK_UNVERIFIED);
  assert.throws(() => resolveSharedOptionControls({ enemy_burning: true }, [
    { group: 'Enemy', label: 'Burning', kind: 'checkbox', checked: true },
    { group: 'Enemy', label: 'Burning', kind: 'checkbox', checked: true },
  ], definitions), error => error.code === ERROR_CODES.INPUT_READBACK_UNVERIFIED);
});

test('FINAL-01 option read-back never normalizes toward expected without pinned authority', () => {
  assert.throws(() => exactOptionReadback({ Skill_A: { params: [5] } }, [{ power: 'Skill_A',
    options: { params: [4] } }], {}), error => error.code === ERROR_CODES.READBACK_MISMATCH);
  assert.throws(() => exactOptionReadback({ Skill_Max: { params: ['max'] } }, [{ power: 'Skill_Max',
    options: { params: [0] } }], {}), error => error.code === ERROR_CODES.READBACK_MISMATCH);
  assert.throws(() => exactOptionReadback({ Skill_Flag: { flags: [true] } }, [{ power: 'Skill_Flag',
    options: { flags: [] } }], {}), error => error.code === ERROR_CODES.READBACK_MISMATCH);
  assert.throws(() => exactOptionReadback({ Legacy_Option: { params: [6] } }, [], {}),
    error => error.code === ERROR_CODES.INPUT_READBACK_UNVERIFIED);
});

test('FINAL-01 production definitions cannot turn missing observations into EXACT', () => {
  assert.throws(() => resolveSharedOptionControls({ enemy_burning: true }, [],
    D12_SHARED_OPTION_DEFINITIONS),
  error => error.code === ERROR_CODES.INPUT_READBACK_UNVERIFIED);
  const productionDruidDefinition = {
    applicability: { kind: 'pinned-engine-enumeration', registered: true,
      authority: 'sha256:891c1f82717c50e598450575068394c6d2fe1c8d26de26f2eeed028d028997db' },
    ...D12_OPTION_READBACK_RULES.Druid_WolfPack,
  };
  assert.throws(() => exactOptionReadback({ Druid_WolfPack: { active: true } }, [], {}, {
    Druid_WolfPack: productionDruidDefinition,
  }), error => error.code === ERROR_CODES.INPUT_READBACK_UNVERIFIED);

  const storedShared = resolveSharedOptionControls({ enemy_burning: true }, [],
    D12_SHARED_OPTION_DEFINITIONS, { enemy_burning: true });
  assert.deepEqual(storedShared.values, { enemy_burning: true });
  assert.deepEqual(storedShared.rawValues.enemy_burning, { status: 'OBSERVED',
    source: 'MAXROLL_CALCULATION_INPUT_STORE', value: true });
  const storedInactive = exactOptionReadback({ Druid_WolfPack: { active: true } }, [], {}, {
    Druid_WolfPack: productionDruidDefinition,
  }, [], { Druid_WolfPack: { active: true } });
  assert.equal(storedInactive.status, 'EXACT');
  assert.deepEqual(storedInactive.rawObserved.Druid_WolfPack, { active: true });
  assert.deepEqual(storedInactive.observationEvidence, [{
    optionId: 'Druid_WolfPack', source: 'MAXROLL_CALCULATION_INPUT_STORE',
    applicability: 'INACTIVE', authority: 'CURRENT_CALCULATION_FRAME:options',
  }]);
});

test('FINAL-01 missing or stale production observations fail closed', () => {
  const definitions = { Skill_A: { applicability: {
    kind: 'pinned-engine-enumeration', registered: true, authority: 'pinned-engine-test',
  } } };
  assert.throws(() => exactOptionReadback({ Skill_A: { params: [2] } }, [], {}, definitions),
    error => error.code === ERROR_CODES.INPUT_READBACK_UNVERIFIED);
  assert.throws(() => exactOptionReadback({ Skill_A: { params: [2] } }, [{ power: 'Skill_A',
    options: { params: [1] } }], {}, definitions),
  error => error.code === ERROR_CODES.READBACK_MISMATCH);
});

test('FINAL-01 applies only versioned per-option normalization rules and records raw evidence', () => {
  const result = exactOptionReadback({ Skill_Max: { params: ['max'] },
    Skill_Enum: { params: [2] }, Skill_Flags: { flags: [true] } }, [
    { power: 'Skill_Max', options: { params: [10] } },
    { power: 'Skill_Enum', options: { params: [1] } },
    { power: 'Skill_Flags', options: { flags: [true, false] } },
  ], {}, {
    Skill_Max: { params: { 0: { kind: 'max', boundControl: {
      group: 'Skill Max', label: 'Stacks' } } } },
    Skill_Enum: { params: { 0: { kind: 'enum-index', runtimeBase: 0, canonicalBase: 1,
      values: ['a', 'b', 'c'] } } },
    Skill_Flags: { flags: { trailingDefault: false } },
  }, [{ group: 'Skill Max', label: 'Stacks', kind: 'number', value: 10, max: 10 }]);
  assert.equal(result.status, 'EXACT');
  assert.deepEqual(result.rawObserved.Skill_Max.params, [10]);
  assert.deepEqual(result.observed.Skill_Max.params, ['max']);
  assert.equal(result.normalizationEvidence.length, 3);
  assert.throws(() => exactOptionReadback({ Skill_Max: { params: ['max'] } }, [
    { power: 'Skill_Max', options: { params: [10] } },
  ], {}, { Skill_Max: { params: { 0: { kind: 'max', boundControl: {
    group: 'Skill Max', label: 'Stacks' } } } } }, []),
  error => error.code === ERROR_CODES.READBACK_MISMATCH);
});

test('FINAL-01 native loader metadata normalization is versioned and never inferred from expected', () => {
  const normalized = normalizedExpectedOptions({
    ignored: { active: true, flags: [true] }, clamped: { params: [6] }, untouched: { params: [4] },
  }, {
    ignored: { ignoredNativeFields: ['flags'] },
    clamped: { nativeParamCanonicalization: { 0: { kind: 'clamp-max', max: 5 } } },
  });
  assert.deepEqual(normalized, {
    ignored: { active: true }, clamped: { params: [5] }, untouched: { params: [4] },
  });
});

test('FINAL-02 required display inventory cannot silently shrink around unresolved raw IDs', () => {
  const definitions = new Map([['Strength', new Set([1])]]);
  assert.throws(() => resolveApplicableMetricInventory({
    rows: [{ section: 'core', label: 'Strength' },
      { section: 'core', label: 'Intelligence' }],
    observedMetricDefinitions: definitions,
    metricCatalog: [{ internalId: 1, category: 'core', name: 'Strength' }],
  }), error => error.code === ERROR_CODES.METRICS_INCOMPLETE
    && error.details.unresolved.some(row => row.label === 'Intelligence'));
});

test('FINAL-02 rejects ambiguous mappings but permits pinned display-only classification', () => {
  assert.throws(() => resolveApplicableMetricInventory({
    rows: [{ section: 'core', label: 'Power' }],
    observedMetricDefinitions: new Map([['Power', new Set([1, 2])]]),
    metricCatalog: [],
  }), error => error.code === ERROR_CODES.METRICS_INCOMPLETE);
  const result = resolveApplicableMetricInventory({
    rows: [{ section: 'summary', label: 'Build Name' },
      { section: 'core', label: 'Strength' }],
    observedMetricDefinitions: new Map([['Strength', new Set([1])]]),
    metricCatalog: [{ internalId: 1, category: 'core', name: 'Strength' }],
    displayOnly: [{ section: 'summary', label: 'Build Name', reason: 'pinned-ui-summary' }],
  });
  assert.deepEqual([...result.expectedIds], [1]);
  assert.deepEqual(result.displayOnly, [{ section: 'summary', label: 'Build Name',
    reason: 'pinned-ui-summary' }]);
});

test('FINAL-02 retains coherent raw-only runtime definitions instead of shrinking coverage', () => {
  const result = resolveApplicableMetricInventory({
    rows: [{ section: 'core', label: 'Strength' }],
    observedMetricDefinitions: new Map([
      ['Strength', new Set([1])], ['Late Runtime Stat', new Set([99])],
    ]),
    metricCatalog: [{ internalId: 1, category: 'core', name: 'Strength' }],
  });
  assert.deepEqual([...result.expectedIds], [1, 99]);
  assert.deepEqual(result.rawOnly, [{ internalId: 99, label: 'Late Runtime Stat',
    reason: 'coherent-runtime-definition-without-display-row' }]);
});
