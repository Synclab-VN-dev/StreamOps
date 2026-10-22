'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { ApplicationError, D4RuleKitApplication, ERROR_CODES } = require('../../src');
const { createOptions, makeStatefulProvider, makeStatelessProvider } = require('../helpers/providers');

test('rollback failure quarantines stateful session and never returns stale success', async () => {
  const stateful = makeStatefulProvider();
  const app = new D4RuleKitApplication({ providers: [stateful.provider] });
  const session = await app.createSession(createOptions('stateful.synthetic', '1.0.0'));
  stateful.controls.failRestore = true;
  await assert.rejects(app.previewChanges(session.sessionId, {
    expectedRevision: 0, changes: [{ type: 'skill.setRank', skillId: 's', rank: 1 }],
  }), error => error instanceof ApplicationError && error.code === ERROR_CODES.RECOVERY_FAILED);
  assert.equal(app.getSession(session.sessionId).status, 'QUARANTINED');
  await assert.rejects(app.evaluate(session.sessionId), error => error.code === ERROR_CODES.SESSION_QUARANTINED);
});

test('provider failure rolls back state and leaves revision unchanged when recovery succeeds', async () => {
  const stateful = makeStatefulProvider();
  const app = new D4RuleKitApplication({ providers: [stateful.provider] });
  const session = await app.createSession(createOptions('stateful.synthetic', '1.0.0'));
  stateful.controls.failNext = true;
  await assert.rejects(app.previewChanges(session.sessionId, {
    expectedRevision: 0, changes: [{ type: 'effect.set', effectId: 'e', active: true }],
  }), error => error.code === ERROR_CODES.PROVIDER_FAILURE);
  assert.equal(app.getSession(session.sessionId).revision, 0);
  assert.equal((await app.evaluate(session.sessionId)).metrics.find(metric => metric.id === 'synthetic.effectCount').rawValue, 0);
});

test('failed commit is logically atomic and does not publish a revision', async () => {
  const stateful = makeStatefulProvider();
  const app = new D4RuleKitApplication({ providers: [stateful.provider] });
  const session = await app.createSession(createOptions('stateful.synthetic', '1.0.0'));
  const changes = [{ type: 'skill.setRank', skillId: 's', rank: 2 }];
  const preview = await app.previewChanges(session.sessionId, { expectedRevision: 0, changes });
  stateful.controls.failNext = true;
  await assert.rejects(app.commitChanges(session.sessionId, {
    expectedRevision: 0, changes, previewToken: preview.previewToken,
  }), error => error.code === ERROR_CODES.PROVIDER_FAILURE);
  assert.equal(app.getSession(session.sessionId).revision, 0);
  assert.equal((await app.evaluate(session.sessionId)).metrics.find(metric => metric.id === 'synthetic.percent').rawValue, 0);
});

test('commit output differing from preview is rejected and rolled back', async () => {
  const stateful = makeStatefulProvider();
  const app = new D4RuleKitApplication({ providers: [stateful.provider] });
  const session = await app.createSession(createOptions('stateful.synthetic', '1.0.0'));
  const changes = [{ type: 'skill.setRank', skillId: 's', rank: 2 }];
  const preview = await app.previewChanges(session.sessionId, { expectedRevision: 0, changes });
  stateful.controls.transformMode = 'COMMIT';
  stateful.controls.transformNext = build => ({ ...build, unexpected: true });
  await assert.rejects(app.commitChanges(session.sessionId, {
    expectedRevision: 0, changes, previewToken: preview.previewToken,
  }), error => error.code === ERROR_CODES.STALE_PREVIEW);
  assert.equal(app.getSession(session.sessionId).revision, 0);
  assert.equal(app.getSession(session.sessionId).status, 'ACTIVE');
});

test('stateful reset failure quarantines instead of publishing baseline', async () => {
  const stateful = makeStatefulProvider();
  const app = new D4RuleKitApplication({ providers: [stateful.provider] });
  const session = await app.createSession(createOptions('stateful.synthetic', '1.0.0'));
  stateful.controls.failNext = true;
  stateful.controls.failMode = 'RESET';
  await assert.rejects(app.resetSession(session.sessionId), error => error.code === ERROR_CODES.RECOVERY_FAILED);
  assert.equal(app.getSession(session.sessionId).status, 'QUARANTINED');
});

test('mismatched evaluate output is quarantined and never cached as fresh', async () => {
  const stateful = makeStatefulProvider();
  const app = new D4RuleKitApplication({ providers: [stateful.provider] });
  const session = await app.createSession(createOptions('stateful.synthetic', '1.0.0'));
  stateful.controls.transformMode = 'EVALUATE';
  stateful.controls.transformNext = build => ({ ...build, stale: true });
  await assert.rejects(app.evaluate(session.sessionId), error => error.code === ERROR_CODES.PROVIDER_FAILURE);
  assert.equal(app.getSession(session.sessionId).status, 'QUARANTINED');
});

test('invalid provider runtime is cleaned up during createSession', async () => {
  let closes = 0;
  const provider = {
    id: 'invalid.synthetic', version: '1',
    getCapabilities: () => ({ version: '1', stateModel: 'stateless', metricIds: [], changeTypes: [] }),
    createSession: async () => ({ close: async () => { closes += 1; } }),
  };
  const app = new D4RuleKitApplication({ providers: [provider] });
  await assert.rejects(app.createSession(createOptions('invalid.synthetic', '1')), error => error.code === ERROR_CODES.PROVIDER_FAILURE);
  assert.equal(closes, 1);
});

test('provider hang times out quickly and fail-closes stateful session', async () => {
  const stateful = makeStatefulProvider();
  const app = new D4RuleKitApplication({ providers: [stateful.provider], operationTimeoutMs: 15, cleanupTimeoutMs: 15 });
  const session = await app.createSession(createOptions('stateful.synthetic', '1.0.0'));
  stateful.controls.hangNext = true;
  stateful.controls.hangMode = 'PREVIEW';
  await assert.rejects(app.previewChanges(session.sessionId, {
    expectedRevision: 0, timeoutMs: 15, changes: [{ type: 'effect.set', effectId: 'e', active: true }],
  }), error => error.code === ERROR_CODES.TIMEOUT || error.code === ERROR_CODES.RECOVERY_FAILED);
  assert.equal(app.getSession(session.sessionId).status, 'QUARANTINED');
});

test('cancellation during stateful mutation quarantines uncertain runtime', async () => {
  const stateful = makeStatefulProvider();
  const app = new D4RuleKitApplication({ providers: [stateful.provider], cleanupTimeoutMs: 15 });
  const session = await app.createSession(createOptions('stateful.synthetic', '1.0.0'));
  stateful.controls.hangNext = true;
  stateful.controls.hangMode = 'PREVIEW';
  const controller = new AbortController();
  const pending = app.previewChanges(session.sessionId, {
    expectedRevision: 0, signal: controller.signal,
    changes: [{ type: 'effect.set', effectId: 'e', active: true }],
  });
  await new Promise(resolve => setImmediate(resolve));
  controller.abort();
  await assert.rejects(pending, error => error.code === ERROR_CODES.CANCELLED);
  assert.equal(app.getSession(session.sessionId).status, 'QUARANTINED');
});

test('normalizer rejects fabricated UNKNOWN values from a provider', async () => {
  const provider = {
    id: 'bad-metrics.synthetic', version: '1',
    getCapabilities: () => ({ version: '1', stateModel: 'stateless', metricIds: ['bad'], changeTypes: [] }),
    createSession: async () => ({
      evaluate: async ({ build }) => ({ build, metrics: [{ id: 'bad', rawValue: 0, status: 'UNKNOWN' }] }),
      close: async () => {},
    }),
  };
  const app = new D4RuleKitApplication({ providers: [provider] });
  const session = await app.createSession(createOptions('bad-metrics.synthetic', '1'));
  await assert.rejects(app.evaluate(session.sessionId), error => error.code === ERROR_CODES.PROVIDER_FAILURE);
});

test('invalid evaluation envelope is a typed provider failure', async () => {
  const provider = {
    id: 'bad-output.synthetic', version: '1',
    getCapabilities: () => ({ version: '1', stateModel: 'stateless', metricIds: [], changeTypes: [] }),
    createSession: async () => ({ evaluate: async () => null, close: async () => {} }),
  };
  const app = new D4RuleKitApplication({ providers: [provider] });
  const session = await app.createSession(createOptions('bad-output.synthetic', '1'));
  await assert.rejects(app.evaluate(session.sessionId), error => error.code === ERROR_CODES.PROVIDER_FAILURE);
});

test('same-session work serializes while independent sessions can overlap', async () => {
  const stateless = makeStatelessProvider();
  const app = new D4RuleKitApplication({ providers: [stateless.provider] });
  const one = await app.createSession(createOptions('stateless.synthetic', '2.0.0'));
  const two = await app.createSession(createOptions('stateless.synthetic', '2.0.0'));
  let release;
  stateless.controls.gate = new Promise(resolve => { release = resolve; });
  const a = app.evaluate(one.sessionId, { bypassCache: true });
  const b = app.evaluate(one.sessionId, { bypassCache: true });
  const c = app.evaluate(two.sessionId, { bypassCache: true });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(stateless.controls.active, 2);
  assert.equal(stateless.controls.maxActive, 2);
  release();
  await Promise.all([a, b, c]);
  assert.equal(stateless.controls.evaluations, 3);
});
