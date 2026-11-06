'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { catalogFrom, extractStats, parseDisplay } = require('../../src/dom-calculation/stats');
const { nativeInput, digest } = require('../../src/dom-calculation/input');
const entry = (id, overrides = {}) => ({ id: `maxroll.heroDetails.${id}`, internalId: id,
  name: `Stat ${id}`, section: 'Core Stats', applicable: true, collapse: false, format: {}, ...overrides });
const row = (id, displayValue = '10') => ({ section: 'Core Stats', name: `Stat ${id}`, displayValue, selector: `li:${id}` });

test('DOM numbers are quantized display observations, never fabricated raw values', () => {
  const output = extractStats([row(1, '52,051')], [entry(1)], ['maxroll.heroDetails.1']);
  assert.equal(output.metrics[0].rawValue, null);
  assert.equal(output.metrics[0].displayNumber, 52051);
  assert.deepEqual(output.metrics[0].precision, { kind: 'DISPLAY_QUANTIZED', quantum: 1, lower: 52050.5, upper: 52051.5 });
  assert.equal(output.coverage.exactRaw, 0);
  assert.equal(parseDisplay('92.0%', { percent: true }).displayNumber, 0.92);
  assert.throws(() => parseDisplay('92.0%', {}), { code: 'DOM_VALUE_UNSUPPORTED' });
});
test('collapsed zero is unknown from DOM, and inapplicable IDs remain distinct', () => {
  const output = extractStats([row(1)], [entry(1), entry(2, { collapse: true }), entry(3, { applicable: false })],
    [1, 2, 3].map(x => `maxroll.heroDetails.${x}`));
  assert.equal(output.metrics[1].status, 'NOT_RENDERED');
  assert.equal(output.metrics[1].inferredZero, false);
  assert.equal(output.metrics[1].displayNumber, null);
  assert.equal(output.metrics[2].status, 'NOT_APPLICABLE');
});
test('missing mandatory rows, ambiguous labels and unknown IDs fail closed', () => {
  assert.throws(() => extractStats([], [entry(1)], ['maxroll.heroDetails.1']), { code: 'DOM_INCOMPLETE' });
  assert.throws(() => extractStats([row(1)], [entry(1), entry(2, { name: 'Stat 1' })], ['maxroll.heroDetails.1']), { code: 'DOM_SCHEMA_MISMATCH' });
  assert.throws(() => extractStats([row(1), row(1)], [entry(1)], ['maxroll.heroDetails.1']), { code: 'DOM_SCHEMA_MISMATCH' });
  assert.throws(() => extractStats([row(1)], [entry(1)], ['maxroll.heroDetails.99']), { code: 'DOM_CATALOG_UNSUPPORTED' });
});
test('section participates in label identity; percent precision is preserved', () => {
  const catalog = [entry(1, { name: 'Armor' }), entry(2, { name: 'Armor', section: 'Defensive', format: { percent: true } })];
  const rows = [{ ...row(1), name: 'Armor' }, { ...row(2, '1.25%'), name: 'Armor', section: 'Defensive' }];
  const r = extractStats(rows, catalog, ['maxroll.heroDetails.1']);
  assert.equal(r.additionalMetrics[0].displayNumber, 0.0125);
  assert.equal(r.additionalMetrics[0].precision.quantum, 0.0001);
});
test('class-specific labels are resolved from verified snapshot data, not local variable names', () => {
  const data = { classes: { 0: { primaryResource: { type: 0 } } }, heroDetails: [[], [], [], [{ id: 81, classFilter: [true], values: [{}] }]] };
  const locale = { uiStrings: { resourceType: { 0: 'Mana' } }, heroDetails: [[], [], [], [{ name: 'Maximum {PRIMARY_RESOURCE}' }]] };
  assert.equal(catalogFrom(data, locale, 0)[0].name, 'Maximum Mana');
});
test('malformed/native tampering and canonical format never silently fall back', () => {
  const state = { activeProfile: 0, profiles: [{ name: 'A', class: 3, level: 70, items: {} }], items: {} };
  const envelope = { schemaVersion: 'maxroll-native-build-export/v1', format: 'MAXROLL_NATIVE_STATE', nativeState: state,
    integrity: { algorithm: 'sha256', nativeStateSha256: digest(state) } };
  assert.deepEqual(nativeInput(envelope), state);
  envelope.nativeState.profiles[0].level = 69;
  assert.throws(() => nativeInput(envelope), { code: 'DOM_INPUT_INTEGRITY' });
  assert.throws(() => nativeInput({ schemaVersion: 'd4-build/v1' }), { code: 'DOM_BUILD_FORMAT_UNSUPPORTED' });
  assert.throws(() => nativeInput(state), { code: 'DOM_BUILD_FORMAT_UNSUPPORTED' });
  const invalid = { ...state, activeProfile: 99 };
  assert.throws(() => nativeInput({ ...envelope, nativeState: invalid, integrity: { algorithm: 'sha256', nativeStateSha256: digest(invalid) } }), { code: 'DOM_INVALID_INPUT' });
});
test('benchmark accuracy compares separate visible rows, not self-generated expected numbers', () => {
  const { distribution, compare } = require('../../scripts/dom-benchmark');
  assert.deepEqual(distribution([5, 1, 3, 2, 4]), { count: 5, min: 1, p50: 3, p95: 5, max: 5 });
  const output = extractStats([row(1)], [entry(1)], ['maxroll.heroDetails.1']);
  assert.equal(compare(output, [{ section: 'Core Stats', rows: [{ name: 'Stat 1', value: '10' }] }]).status, 'PASS');
  assert.equal(compare(output, [{ section: 'Core Stats', rows: [{ name: 'Stat 1', value: '11' }] }]).status, 'FAIL');
  assert.equal(compare(output, []).status, 'FAIL');
});
