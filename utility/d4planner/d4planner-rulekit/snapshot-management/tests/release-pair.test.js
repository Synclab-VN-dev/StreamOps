'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {matchCapture} = require('../release/pair');
function capture() {
  const identity = {version:'1', fingerprints:Object.fromEntries([
    'https://maxroll.gg/assets/export-1.js', 'https://maxroll.gg/game/data.min.json',
    'https://maxroll.gg/game/data.enus.json'].map(url => [url, 'a'.repeat(64)]))};
  return {status:'COMPLETE', mode:'all', consistency:'PASS', runId:'run-1',
    packages:['calculation', 'ui'].map(kind => ({kind, runId:'run-1', snapshotId:kind,
      manifestSha256:'b'.repeat(64), identity:structuredClone(identity),
      compatibility:'PIN_MATCH_UNVALIDATED', validationStatus:kind === 'ui' ? 'VALIDATED' : 'CAPTURED_UNVALIDATED'}))};
}
test('matching provenance is not Calculation approval', () => {
  const result = matchCapture(capture());
  assert.equal(result.calculationSnapshotId, 'calculation');
  assert.equal(result.captureRunId, 'run-1');
  assert.equal(result.status, undefined);
});
for (const [name, mutate, code] of [
  ['drift', r => {r.packages[0].compatibility='PATCH_DRIFT';}, 'BLOCKED_COMPATIBILITY'],
  ['mixed run', r => {r.packages[1].runId='other';}, 'BLOCKED_PROVENANCE'],
  ['missing UI', r => {r.packages.pop();}, 'BLOCKED_PROVENANCE'],
  ['invalid UI', r => {r.packages[1].validationStatus='FAILED';}, 'BLOCKED_UI_VALIDATION'],
  ['different bytes', r => {r.packages[1].identity.fingerprints['https://maxroll.gg/game/data.min.json']='c'.repeat(64);}, 'BLOCKED_PAIR_MISMATCH'],
  ['missing localization', r => {delete r.packages[0].identity.fingerprints['https://maxroll.gg/game/data.enus.json'];}, 'BLOCKED_RUNTIME_IDENTITY'],
  ['incomplete capture', r => {r.status='FAILED';}, 'BLOCKED_CAPTURE'],
]) test(name, () => {
  const report = capture(); mutate(report);
  assert.throws(() => matchCapture(report), error => error.code === code);
});
