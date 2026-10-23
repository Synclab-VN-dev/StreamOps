'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const { FIXTURE, assertSafeArchiveEntries } = require('../../src/encrypted-fixture');
const { parse } = require('../../scripts/encrypted-fixture');

test('encrypted fixture trust anchors and public X25519 recipient are immutable', () => {
  assert.equal(FIXTURE.manifestSha256,
    '638a283b8aa0cb822a35176d9d41c8d1751fb6f962ca0a2f7feaa20f1ef39e54');
  assert.match(FIXTURE.recipient, /^age1[0-9a-z]+$/);
  assert.equal(FIXTURE.encryptedSha256,
    'c0163e0627c385dfc8f92d1b6a41b8978d89c94d150c026a5a7b3810efd3a85e');
  assert.equal(FIXTURE.resources, 365);
  assert.equal(FIXTURE.uniqueBlobs, 363);
  assert.equal(FIXTURE.logicalBytes, 56_412_954);
});

test('encrypted fixture CLI requires explicit paths and never accepts a password', () => {
  const options = parse([
    'package', '--snapshot', '/private/snapshot', '--output-dir', '/private/output',
    '--age-bin', '/tools/age', '--identity', '/private/identity',
  ]);
  assert.equal(options.command, 'package');
  assert.equal(Object.hasOwn(options, 'password'), false);
  assert.throws(() => parse(['package', '--password', 'bad']), /unsupported/);
  assert.throws(() => parse(['verify']), /usage/);
});

test('encrypted fixture ZIP validation rejects traversal, absolute and mixed roots', () => {
  assert.doesNotThrow(() => assertSafeArchiveEntries([
    `${FIXTURE.snapshotId}/`, `${FIXTURE.snapshotId}/manifest.json`,
  ]));
  assert.throws(() => assertSafeArchiveEntries([`${FIXTURE.snapshotId}/../escape`]), /unsafe/);
  assert.throws(() => assertSafeArchiveEntries(['/absolute']), /unsafe/);
  assert.throws(() => assertSafeArchiveEntries([
    `${FIXTURE.snapshotId}/manifest.json`, 'another-root/file',
  ]), /exactly the pinned snapshot root/);
});

test('encrypted fixture workflow is trusted-dispatch only and pins ciphertext without live capture', () => {
  const workflow = fs.readFileSync(path.resolve(__dirname,
    '../../../../../../.github/workflows/d4-rulekit-maxroll-real.yml'), 'utf8');
  assert.match(workflow, /workflow_dispatch:/);
  assert.doesNotMatch(workflow, /pull_request(?:_target)?:|\bpush:/);
  assert.match(workflow, /test-fixture\/enc-e2e-20261023-r01/);
  assert.match(workflow, /ci-data-pack-20261023-r01\.zip\.age/);
  assert.match(workflow, /secrets\.MAXROLL_FIXTURE_AGE_IDENTITY/);
  assert.match(workflow, /BLOCKED_KEY_PROVISIONING/);
  assert.doesNotMatch(workflow, /e2e:real:live-capture|snapshot:capture|maxroll\.gg/);
  assert.match(workflow, /RUNTIME_COMPATIBILITY=PATCH_DRIFT/);
  assert.match(workflow, /OFFLINE_E2E=NOT_RUN/);
});
