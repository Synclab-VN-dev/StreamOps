'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { MUTATION_CLASSES, MUTATION_SHARD_TIMEOUT_MS, assertCompleteMutationShards,
  mutationShardPlan, parse } = require('../../scripts/issue134-acceptance');

test('Issue 134 runner requires explicit private identity, age and Chromium inputs', () => {
  assert.throws(() => parse([], {}), /identity is required/);
  const parsed = parse(['--resume', 'multiclass,mutations', '--mutation-classes', 'Rogue'], {
    MAXROLL_FIXTURE_AGE_IDENTITY_FILE: '/private/fixture.agekey',
    AGE_BIN: '/tools/age', BROWSER_INFRA_CHROMIUM_PATH: '/tools/chromium',
  });
  assert.deepEqual(parsed.selected, ['multiclass', 'mutations']);
  assert.deepEqual(parsed.mutationClasses, ['Rogue']);
  assert.equal(parsed.fullMode, false);
  assert.equal(parsed.identity, '/private/fixture.agekey');
  assert.throws(() => parse(['--resume', 'unknown'], {
    MAXROLL_FIXTURE_AGE_IDENTITY_FILE: '/private/key', AGE_BIN: '/age',
    BROWSER_INFRA_CHROMIUM_PATH: '/chrome',
  }), /resume must be/);
});

test('FINAL-04 full mode always plans all eight bounded shards and ignores inherited filters', () => {
  const parsed = parse([], { MAXROLL_FIXTURE_AGE_IDENTITY_FILE: '/private/key',
    AGE_BIN: '/age', BROWSER_INFRA_CHROMIUM_PATH: '/chrome',
    MAXROLL_TEST_CLASS: 'Rogue' });
  assert.equal(parsed.fullMode, true);
  assert.deepEqual(parsed.mutationClasses, MUTATION_CLASSES);
  const plan = mutationShardPlan(parsed.mutationClasses);
  assert.equal(plan.length, 8);
  assert.ok(plan.every(shard => shard.timeoutMs === MUTATION_SHARD_TIMEOUT_MS
    && shard.timeoutMs < 600_000));
  assert.throws(() => parse(['--resume', 'all', '--mutation-classes', 'Rogue'], {
    MAXROLL_FIXTURE_AGE_IDENTITY_FILE: '/private/key', AGE_BIN: '/age',
    BROWSER_INFRA_CHROMIUM_PATH: '/chrome' }), /always runs the complete/);
});

test('FINAL-04 missing, failed or timed-out shards can never aggregate to PASS', () => {
  const pass = MUTATION_CLASSES.map(className => ({ className, status: 'PASS' }));
  assert.equal(assertCompleteMutationShards(MUTATION_CLASSES, pass).passed, 8);
  assert.throws(() => assertCompleteMutationShards(MUTATION_CLASSES, pass.slice(1)), /incomplete/);
  assert.throws(() => assertCompleteMutationShards(MUTATION_CLASSES,
    pass.map((entry, index) => index === 2 ? { ...entry, status: 'FAIL' } : entry)), /failed=Druid/);
  assert.throws(() => assertCompleteMutationShards(MUTATION_CLASSES,
    pass.map((entry, index) => index === 3 ? { ...entry, status: 'TIMEOUT' } : entry)),
  /failed=Barbarian/);
});

test('FINAL-04 targeted mutation mode is explicit subset evidence', () => {
  const parsed = parse(['--resume', 'mutations', '--mutation-classes', 'Rogue,Sorcerer'], {
    MAXROLL_FIXTURE_AGE_IDENTITY_FILE: '/private/key', AGE_BIN: '/age',
    BROWSER_INFRA_CHROMIUM_PATH: '/chrome' });
  assert.equal(parsed.fullMode, false);
  assert.deepEqual(parsed.mutationClasses, ['Rogue', 'Sorcerer']);
  assert.throws(() => parse(['--resume', 'mutations'], {
    MAXROLL_FIXTURE_AGE_IDENTITY_FILE: '/private/key', AGE_BIN: '/age',
    BROWSER_INFRA_CHROMIUM_PATH: '/chrome' }), /require --mutation-classes/);
});
