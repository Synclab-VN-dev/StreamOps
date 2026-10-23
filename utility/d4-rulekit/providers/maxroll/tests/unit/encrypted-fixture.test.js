'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const { FIXTURE, assertSafeArchiveEntries } = require('../../src/encrypted-fixture');
const { parse } = require('../../scripts/encrypted-fixture');
const { parse: parseOffline } = require('../../scripts/offline-real-e2e');

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
  const orchestrator = fs.readFileSync(path.resolve(__dirname,
    '../../src/offline-real-e2e.js'), 'utf8');
  assert.match(workflow, /workflow_dispatch:/);
  assert.doesNotMatch(workflow, /pull_request(?:_target)?:|\bpush:/);
  assert.match(orchestrator, /test-fixture\/enc-e2e-20261023-r01/);
  assert.equal(FIXTURE.assetName, 'ci-data-pack-20261023-r01.zip.age');
  assert.match(orchestrator, /d12am6kt-candidate/);
  assert.match(workflow, /secrets\.MAXROLL_FIXTURE_AGE_IDENTITY/);
  assert.match(workflow, /BLOCKED_KEY_PROVISIONING/);
  assert.doesNotMatch(workflow, /e2e:real:live-capture|snapshot:capture|maxroll\.gg/);
  assert.match(workflow, /github\.ref == 'refs\/heads\/master'/);
  assert.match(workflow, /refs\/heads\/feat\/127-128-real-maxroll-provider/);
  assert.match(workflow, /environment: maxroll-fixture-trusted/);
  assert.match(workflow, /e2e:real:offline/);
  assert.doesNotMatch(workflow, /RUNTIME_COMPATIBILITY=PATCH_DRIFT|OFFLINE_E2E=NOT_RUN/);
});

test('offline real CLI accepts only explicit identity, age and Chromium paths', () => {
  const options = parseOffline([
    '--identity', '/private/identity', '--age-bin', '/tools/age',
    '--chromium', '/tools/chromium',
  ], {});
  assert.deepEqual(options, {
    identity: '/private/identity', ageBin: '/tools/age', chromium: '/tools/chromium',
  });
  assert.throws(() => parseOffline(['--password', 'bad'], {}), /unsupported/);
});

test('REV-04 full real acceptance selects the candidate by explicit asset identity', () => {
  const realTest = fs.readFileSync(path.resolve(__dirname,
    '../real/authorized-runtime.test.js'), 'utf8');
  assert.match(realTest, /MAXROLL_REAL_PROFILE_ID/);
  assert.match(realTest, /createMaxroll32173552D12aM6KTCandidateProfile/);
  assert.doesNotMatch(realTest, /const profile = createMaxroll32173552RealProfile/);
});
