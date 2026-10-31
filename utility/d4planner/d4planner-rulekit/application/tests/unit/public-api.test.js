'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { ApplicationError, D4RuleKitApplication, ERROR_CODES } = require('../../src');
const { BASE_BUILD, createOptions, makeStatefulProvider, makeStatelessProvider } = require('../helpers/providers');

function setup(options = {}) {
  const stateful = makeStatefulProvider();
  const stateless = makeStatelessProvider();
  const app = new D4RuleKitApplication({ providers: [stateful.provider, stateless.provider], ...options });
  return { app, stateful, stateless };
}

async function rejectsCode(promise, code) {
  await assert.rejects(promise, error => error instanceof ApplicationError && error.code === code);
}

test('listProviders is deterministic, immutable, sanitized, and rejects duplicate contracts', () => {
  const { app } = setup();
  const providers = app.listProviders();
  assert.deepEqual(providers.map(row => row.id), ['stateful.synthetic', 'stateless.synthetic']);
  assert.equal(Object.isFrozen(providers[0].capabilities), true);
  assert.equal('createSession' in providers[0], false);
  assert.equal('internalSecret' in providers[0].capabilities, false);
  const duplicate = makeStatefulProvider();
  assert.throws(() => new D4RuleKitApplication({ providers: [duplicate.provider, duplicate.provider] }),
    error => error.code === ERROR_CODES.INVALID_INPUT);
  assert.throws(() => new D4RuleKitApplication({ providers: [] }), error => error.code === ERROR_CODES.INVALID_INPUT);
  assert.throws(() => new D4RuleKitApplication({ providers: [{ id: 'invalid' }] }),
    error => error.code === ERROR_CODES.INVALID_INPUT);
});

test('createSession pins identities, isolates input, handles unknown/unavailable/quota', async () => {
  const { app } = setup({ maxSessions: 1 });
  const input = structuredClone(BASE_BUILD);
  const session = await app.createSession(createOptions('stateful.synthetic', '1.0.0', input));
  input.skills.changed = 99;
  assert.equal(session.revision, 0);
  assert.equal(session.providerVersion, '1.0.0');
  assert.equal(session.snapshotManifestSha256, 'a'.repeat(64));
  assert.equal(app.getSession(session.sessionId).buildFingerprint, session.buildFingerprint);
  await rejectsCode(app.createSession(createOptions('missing', '1.0.0')), ERROR_CODES.QUOTA_EXCEEDED);
  await app.closeSession(session.sessionId);
  await rejectsCode(app.createSession(createOptions('missing', '1.0.0')), ERROR_CODES.PROVIDER_NOT_FOUND);
  await rejectsCode(app.createSession({ ...createOptions('stateful.synthetic', 'bad'), providerVersion: 'bad' }), ERROR_CODES.PROVIDER_UNAVAILABLE);
  await rejectsCode(app.createSession({ ...createOptions('stateful.synthetic', '1.0.0'), snapshotManifestSha256: null }), ERROR_CODES.INVALID_INPUT);
  await rejectsCode(app.createSession({ ...createOptions('stateful.synthetic', '1.0.0'), snapshotManifestSha256: 'not-a-digest' }), ERROR_CODES.INVALID_INPUT);
  await rejectsCode(app.createSession({ ...createOptions('stateful.synthetic', '1.0.0'), build: { invalid: Number.NaN } }), ERROR_CODES.INVALID_INPUT);
  const unavailable = makeStatelessProvider({ id: 'unavailable.synthetic', version: '1', available: false });
  const unavailableApp = new D4RuleKitApplication({ providers: [unavailable.provider] });
  await rejectsCode(unavailableApp.createSession(createOptions('unavailable.synthetic', '1')), ERROR_CODES.PROVIDER_UNAVAILABLE);
});

test('evaluate normalizes metrics, caches exact input, rejects unknown and cancelled calls', async () => {
  const { app, stateless } = setup();
  const session = await app.createSession(createOptions('stateless.synthetic', '2.0.0'));
  const first = await app.evaluate(session.sessionId);
  const second = await app.evaluate(session.sessionId);
  assert.equal(first.metrics.length, 5);
  assert.equal(first.metrics.find(metric => metric.status === 'UNKNOWN').rawValue, null);
  assert.equal(first.metrics.some(metric => metric.status === 'VERIFIED'), false);
  assert.equal(second.cache.hit, true);
  assert.equal(stateless.controls.evaluations, 1);
  const controller = new AbortController(); controller.abort();
  await rejectsCode(app.evaluate(session.sessionId, { signal: controller.signal, bypassCache: true }), ERROR_CODES.CANCELLED);
  await rejectsCode(app.evaluate('missing'), ERROR_CODES.SESSION_NOT_FOUND);
});

test('previewChanges is immutable, rejects unsupported/stale changes, and computes percentage points', async () => {
  const { app } = setup();
  const session = await app.createSession(createOptions('stateful.synthetic', '1.0.0'));
  const request = { expectedRevision: 0, changes: [{ type: 'skill.setRank', skillId: 's1', rank: 3 }] };
  const preview = await app.previewChanges(session.sessionId, request);
  assert.equal(app.getSession(session.sessionId).revision, 0);
  assert.equal(app.getSession(session.sessionId).buildFingerprint, session.buildFingerprint);
  const delta = preview.delta.find(row => row.id === 'synthetic.percent');
  assert.equal(delta.delta, 3);
  assert.equal(delta.deltaKind, 'PERCENTAGE_POINT');
  await rejectsCode(app.previewChanges(session.sessionId, { expectedRevision: 0, changes: [{ type: 'unknown' }] }), ERROR_CODES.UNSUPPORTED_CHANGE);
  await rejectsCode(app.previewChanges(session.sessionId, { expectedRevision: 0, changes: [{}] }), ERROR_CODES.INVALID_INPUT);
  await rejectsCode(app.previewChanges(session.sessionId, { expectedRevision: 1, changes: request.changes }), ERROR_CODES.REVISION_CONFLICT);
  await rejectsCode(app.previewChanges(session.sessionId, { expectedRevision: 0, changes: [] }), ERROR_CODES.INVALID_INPUT);
});

test('commitChanges requires matching preview and expected revision, then publishes atomically', async () => {
  const { app } = setup();
  const session = await app.createSession(createOptions('stateful.synthetic', '1.0.0'));
  const changes = [{ type: 'equipment.replace', slot: 'head', item: { id: 'synthetic-head' } }];
  const preview = await app.previewChanges(session.sessionId, { expectedRevision: 0, changes });
  await rejectsCode(app.commitChanges(session.sessionId, { expectedRevision: 0, changes }), ERROR_CODES.INVALID_INPUT);
  await rejectsCode(app.commitChanges(session.sessionId, { expectedRevision: 0, changes: [{ ...changes[0], slot: 'hand' }], previewToken: preview.previewToken }), ERROR_CODES.STALE_PREVIEW);
  const committed = await app.commitChanges(session.sessionId, { expectedRevision: 0, changes, previewToken: preview.previewToken });
  assert.equal(committed.session.revision, 1);
  assert.notEqual(committed.session.buildFingerprint, session.buildFingerprint);
  await rejectsCode(app.commitChanges(session.sessionId, { expectedRevision: 0, changes, previewToken: preview.previewToken }), ERROR_CODES.REVISION_CONFLICT);
});

test('resetSession restores baseline, checks revision, and clears previews', async () => {
  const { app } = setup();
  const session = await app.createSession(createOptions('stateless.synthetic', '2.0.0'));
  const changes = [{ type: 'effect.set', effectId: 'e1', active: true }];
  const preview = await app.previewChanges(session.sessionId, { expectedRevision: 0, changes });
  await app.commitChanges(session.sessionId, { expectedRevision: 0, changes, previewToken: preview.previewToken });
  await rejectsCode(app.resetSession(session.sessionId, { expectedRevision: 0 }), ERROR_CODES.REVISION_CONFLICT);
  const reset = await app.resetSession(session.sessionId, { expectedRevision: 1 });
  assert.equal(reset.revision, 2);
  assert.equal(reset.buildFingerprint, session.buildFingerprint);
  await rejectsCode(app.commitChanges(session.sessionId, { expectedRevision: 2, changes, previewToken: preview.previewToken }), ERROR_CODES.STALE_PREVIEW);
});

test('getSession returns sanitized metadata and deterministic expiry errors', async () => {
  let now = 1_000;
  const { app } = setup({ clock: () => now, sessionTtlMs: 10 });
  const session = await app.createSession(createOptions('stateless.synthetic', '2.0.0'));
  const view = app.getSession(session.sessionId);
  assert.equal('committedBuild' in view, false);
  assert.equal('providerRuntime' in view, false);
  now += 11;
  assert.throws(() => app.getSession(session.sessionId), error => error.code === ERROR_CODES.SESSION_EXPIRED);
  assert.throws(() => app.getSession('missing'), error => error.code === ERROR_CODES.SESSION_NOT_FOUND);
});

test('expired capacity is reclaimed only after bounded provider cleanup succeeds', async () => {
  let now = 100;
  const stateful = makeStatefulProvider();
  const app = new D4RuleKitApplication({
    providers: [stateful.provider], clock: () => now, sessionTtlMs: 10,
    maxSessions: 1, cleanupTimeoutMs: 15,
  });
  await app.createSession(createOptions('stateful.synthetic', '1.0.0'));
  now += 11;
  const replacement = await app.createSession(createOptions('stateful.synthetic', '1.0.0'));
  assert.equal(replacement.status, 'ACTIVE');
  assert.equal(stateful.controls.closes, 1);
  stateful.controls.hangClose = true;
  now += 11;
  await rejectsCode(app.createSession(createOptions('stateful.synthetic', '1.0.0')), ERROR_CODES.QUOTA_EXCEEDED);
});

test('closeSession is bounded/idempotent and reports cleanup failures', async () => {
  const { app, stateful } = setup({ cleanupTimeoutMs: 15 });
  const session = await app.createSession(createOptions('stateful.synthetic', '1.0.0'));
  const closed = await app.closeSession(session.sessionId);
  assert.equal(closed.alreadyClosed, false);
  assert.equal((await app.closeSession(session.sessionId)).alreadyClosed, true);
  assert.equal(stateful.controls.closes, 1);
  const second = await app.createSession(createOptions('stateful.synthetic', '1.0.0'));
  stateful.controls.hangClose = true;
  await rejectsCode(app.closeSession(second.sessionId), ERROR_CODES.RECOVERY_FAILED);
  assert.equal(app.getSession(second.sessionId).status, 'QUARANTINED');
});
