'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { parse } = require('../../scripts/issue134-acceptance');

test('Issue 134 runner requires explicit private identity, age and Chromium inputs', () => {
  assert.throws(() => parse([], {}), /identity is required/);
  const parsed = parse(['--resume', 'multiclass,mutations'], {
    MAXROLL_FIXTURE_AGE_IDENTITY_FILE: '/private/fixture.agekey',
    AGE_BIN: '/tools/age', BROWSER_INFRA_CHROMIUM_PATH: '/tools/chromium',
  });
  assert.deepEqual(parsed.selected, ['multiclass', 'mutations']);
  assert.equal(parsed.identity, '/private/fixture.agekey');
  assert.throws(() => parse(['--resume', 'unknown'], {
    MAXROLL_FIXTURE_AGE_IDENTITY_FILE: '/private/key', AGE_BIN: '/age',
    BROWSER_INFRA_CHROMIUM_PATH: '/chrome',
  }), /resume must be/);
});
