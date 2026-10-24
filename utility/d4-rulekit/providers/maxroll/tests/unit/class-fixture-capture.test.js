'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const { ERROR_CODES } = require('../../src');
const {
  MATRIX_SCHEMA_VERSION,
  installReadOnlyPolicy,
  validateMatrix,
} = require('../../src/class-fixture-capture');
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
