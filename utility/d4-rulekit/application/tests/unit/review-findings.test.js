'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { ApplicationError, D4RuleKitApplication, ERROR_CODES } = require('../../src');
const { BASE_BUILD, createOptions, makeStatelessProvider } = require('../helpers/providers');

function capabilities(stateModel = 'stateless', metricIds = ['synthetic.one']) {
  return { version: 'review/v1', stateModel, metricIds, changeTypes: ['effect.set'] };
}

function metric(id = 'synthetic.one') {
  return { id, rawValue: 1, displayValue: '1', unit: null, status: 'OBSERVED' };
}

test('APP-R1 concurrent createSession reservations cannot exceed maxSessions', async () => {
  const fixture = makeStatelessProvider({ id: 'quota.synthetic', version: '1' });
  const create = fixture.provider.createSession.bind(fixture.provider);
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  fixture.provider.createSession = async options => { await gate; return create(options); };
  const app = new D4RuleKitApplication({ providers: [fixture.provider], maxSessions: 1 });
  const first = app.createSession(createOptions('quota.synthetic', '1'));
  const second = app.createSession(createOptions('quota.synthetic', '1'));
  const settled = Promise.allSettled([first, second]);
  await new Promise(resolve => setImmediate(resolve));
  release();
  const results = await settled;
  assert.equal(results.filter(result => result.status === 'fulfilled').length, 1);
  assert.equal(results.filter(result => result.status === 'rejected' &&
    result.reason?.code === ERROR_CODES.QUOTA_EXCEEDED).length, 1);
  if (results[0].status === 'fulfilled') await app.closeSession(results[0].value.sessionId);
  if (results[1].status === 'fulfilled') await app.closeSession(results[1].value.sessionId);
});

test('APP-R2 late provider runtime after create timeout is automatically closed', async () => {
  let resolveCreate;
  let closes = 0;
  const provider = {
    id: 'late.synthetic', version: '1', getCapabilities: () => capabilities(),
    createSession: () => new Promise(resolve => { resolveCreate = resolve; }),
  };
  const app = new D4RuleKitApplication({ providers: [provider], operationTimeoutMs: 10, cleanupTimeoutMs: 20 });
  await assert.rejects(app.createSession({ ...createOptions('late.synthetic', '1'), timeoutMs: 10 }),
    error => error.code === ERROR_CODES.TIMEOUT);
  resolveCreate({ evaluate: async () => ({ build: BASE_BUILD, metrics: [metric()] }), close: async () => { closes += 1; } });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(closes, 1);
});

test('APP-R3 incomplete provider metric coverage fails and is never cached', async () => {
  let evaluations = 0;
  const provider = {
    id: 'partial.synthetic', version: '1',
    getCapabilities: () => capabilities('stateless', ['synthetic.one', 'synthetic.two']),
    createSession: async () => ({
      evaluate: async ({ build }) => { evaluations += 1; return { build, metrics: [metric('synthetic.one')] }; },
      close: async () => {},
    }),
  };
  const app = new D4RuleKitApplication({ providers: [provider] });
  const session = await app.createSession(createOptions('partial.synthetic', '1'));
  await assert.rejects(app.evaluate(session.sessionId), error => error.code === ERROR_CODES.PROVIDER_FAILURE);
  await assert.rejects(app.evaluate(session.sessionId), error => error.code === ERROR_CODES.PROVIDER_FAILURE);
  assert.equal(evaluations, 2);
});

test('APP-R4 stateful evaluate failure restores checkpoint before reuse', async () => {
  let state = structuredClone(BASE_BUILD);
  let fail = false;
  let restores = 0;
  const provider = {
    id: 'recover.synthetic', version: '1', getCapabilities: () => capabilities('stateful'),
    createSession: async () => ({
      checkpoint: async () => structuredClone(state),
      restore: async checkpoint => { restores += 1; state = structuredClone(checkpoint); },
      evaluate: async ({ build }) => {
        if (fail) { state = { corrupted: true }; throw new Error('partial provider mutation'); }
        state = structuredClone(build);
        return { build, metrics: [metric()] };
      },
      close: async () => {},
    }),
  };
  const app = new D4RuleKitApplication({ providers: [provider] });
  const session = await app.createSession(createOptions('recover.synthetic', '1'));
  fail = true;
  await assert.rejects(app.evaluate(session.sessionId, { bypassCache: true }),
    error => error.code === ERROR_CODES.PROVIDER_FAILURE);
  assert.equal(restores, 1);
  assert.equal(app.getSession(session.sessionId).status, 'ACTIVE');
  assert.deepEqual(state, BASE_BUILD);
});

test('APP-R5 TTL cleanup runs without a later public API request', async () => {
  let now = 100;
  let closes = 0;
  const tasks = new Map();
  let nextId = 0;
  const scheduler = {
    setTimeout(callback) { const id = ++nextId; tasks.set(id, callback); return id; },
    clearTimeout(id) { tasks.delete(id); },
    async runAll() {
      const callbacks = [...tasks.values()]; tasks.clear();
      for (const callback of callbacks) callback();
      await new Promise(resolve => setImmediate(resolve));
    },
  };
  const provider = {
    id: 'ttl.synthetic', version: '1', getCapabilities: () => capabilities(),
    createSession: async () => ({
      evaluate: async ({ build }) => ({ build, metrics: [metric()] }),
      close: async () => { closes += 1; },
    }),
  };
  const app = new D4RuleKitApplication({
    providers: [provider], clock: () => now, scheduler, sessionTtlMs: 10,
  });
  const session = await app.createSession(createOptions('ttl.synthetic', '1'));
  now += 11;
  await scheduler.runAll();
  assert.equal(closes, 1);
  assert.throws(() => app.getSession(session.sessionId),
    error => error instanceof ApplicationError && error.code === ERROR_CODES.SESSION_NOT_FOUND);
});
