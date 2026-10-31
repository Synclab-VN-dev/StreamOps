'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { D4RuleKitApplication, ERROR_CODES } = require('../../src');
const { BASE_BUILD, createOptions } = require('../helpers/providers');

function copy(value) { return structuredClone(value); }

function applyChanges(build, changes) {
  const next = copy(build);
  next.effects ??= {};
  for (const change of changes) {
    if (change.type === 'effect.set') next.effects[change.effectId] = change.active;
  }
  return next;
}

function createStatefulFixture(id) {
  const controls = {
    state: null,
    failBaseline: false,
    failRestore: false,
    baselineGate: null,
    baselineStarted: null,
    restores: 0,
    closes: 0,
  };
  const provider = {
    id,
    version: '1',
    getCapabilities: () => ({
      version: 'app-r7/v1', stateModel: 'stateful',
      metricIds: ['synthetic.value'], changeTypes: ['effect.set'],
    }),
    createSession: async ({ build }) => {
      controls.state = copy(build);
      return {
        checkpoint: async () => copy(controls.state),
        restore: async checkpoint => {
          controls.restores += 1;
          if (controls.failRestore) throw new Error('restore failed');
          controls.state = copy(checkpoint);
        },
        evaluate: async input => {
          if (input.mode === 'EVALUATE' && (controls.failBaseline || controls.baselineGate)) {
            controls.state = { corrupted: true };
            controls.baselineStarted?.();
            if (controls.baselineGate) await controls.baselineGate;
            if (controls.failBaseline) {
              controls.failBaseline = false;
              throw new Error('baseline evaluation failed after mutation');
            }
          }
          const candidate = applyChanges(input.build, input.changes ?? []);
          controls.state = copy(candidate);
          const value = Object.values(candidate.effects ?? {}).filter(Boolean).length;
          return {
            build: candidate,
            metrics: [{
              id: 'synthetic.value', rawValue: value, displayValue: String(value),
              unit: 'count', status: 'OBSERVED', provenance: { fixture: 'APP-R7' },
            }],
          };
        },
        close: async () => { controls.closes += 1; },
      };
    },
  };
  return { controls, provider };
}

function changeRequest(expectedRevision = 0) {
  return {
    expectedRevision,
    changes: [{ type: 'effect.set', effectId: 'candidate', active: true }],
  };
}

test('APP-R7-01 preview baseline failure restores the verified checkpoint before reuse', async () => {
  const fixture = createStatefulFixture('app-r7-restore.synthetic');
  const app = new D4RuleKitApplication({ providers: [fixture.provider] });
  const session = await app.createSession(createOptions(fixture.provider.id, fixture.provider.version));
  fixture.controls.failBaseline = true;
  await assert.rejects(app.previewChanges(session.sessionId, changeRequest()),
    error => error.code === ERROR_CODES.PROVIDER_FAILURE);
  assert.equal(app.getSession(session.sessionId).revision, 0);
  assert.equal(app.getSession(session.sessionId).status, 'ACTIVE');
  assert.deepEqual(fixture.controls.state, BASE_BUILD);
  assert.equal(fixture.controls.restores, 1);
  const evaluated = await app.evaluate(session.sessionId, { bypassCache: true });
  assert.equal(evaluated.metrics[0].rawValue, 0);
  await app.closeSession(session.sessionId);
});

test('APP-R7-02 failed baseline restore quarantines session and invalidates cached reuse', async () => {
  const fixture = createStatefulFixture('app-r7-quarantine.synthetic');
  const app = new D4RuleKitApplication({ providers: [fixture.provider] });
  const session = await app.createSession(createOptions(fixture.provider.id, fixture.provider.version));
  await app.evaluate(session.sessionId);
  fixture.controls.failBaseline = true;
  fixture.controls.failRestore = true;
  await assert.rejects(app.previewChanges(session.sessionId, changeRequest()),
    error => error.code === ERROR_CODES.RECOVERY_FAILED);
  assert.equal(app.getSession(session.sessionId).status, 'QUARANTINED');
  await assert.rejects(app.evaluate(session.sessionId), error => error.code === ERROR_CODES.SESSION_QUARANTINED);
  await assert.rejects(app.previewChanges(session.sessionId, changeRequest()),
    error => error.code === ERROR_CODES.SESSION_QUARANTINED);
  await assert.rejects(app.commitChanges(session.sessionId, {
    ...changeRequest(), previewToken: 'untrusted-preview',
  }), error => error.code === ERROR_CODES.SESSION_QUARANTINED);
});

test('APP-R7-03 timeout during preview baseline quarantines uncertain late mutation', async () => {
  const fixture = createStatefulFixture('app-r7-timeout.synthetic');
  fixture.controls.baselineGate = new Promise(() => {});
  const app = new D4RuleKitApplication({
    providers: [fixture.provider], operationTimeoutMs: 10, cleanupTimeoutMs: 10,
  });
  const session = await app.createSession(createOptions(fixture.provider.id, fixture.provider.version));
  await assert.rejects(app.previewChanges(session.sessionId, { ...changeRequest(), timeoutMs: 10 }),
    error => error.code === ERROR_CODES.TIMEOUT);
  assert.equal(app.getSession(session.sessionId).status, 'QUARANTINED');
  await assert.rejects(app.evaluate(session.sessionId), error => error.code === ERROR_CODES.SESSION_QUARANTINED);
});

test('APP-R7-03 cancellation during preview baseline quarantines uncertain late mutation', async () => {
  let release;
  let started;
  const startedPromise = new Promise(resolve => { started = resolve; });
  const fixture = createStatefulFixture('app-r7-cancel.synthetic');
  fixture.controls.baselineStarted = started;
  fixture.controls.baselineGate = new Promise(resolve => { release = resolve; });
  const app = new D4RuleKitApplication({ providers: [fixture.provider] });
  const session = await app.createSession(createOptions(fixture.provider.id, fixture.provider.version));
  const controller = new AbortController();
  const preview = app.previewChanges(session.sessionId, {
    ...changeRequest(), signal: controller.signal,
  });
  await startedPromise;
  controller.abort();
  await assert.rejects(preview, error => error.code === ERROR_CODES.CANCELLED);
  release();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(app.getSession(session.sessionId).status, 'QUARANTINED');
  await assert.rejects(app.evaluate(session.sessionId), error => error.code === ERROR_CODES.SESSION_QUARANTINED);
});

test('APP-R7-04 successful A→preview B→commit B→reset A preserves all API semantics', async () => {
  const fixture = createStatefulFixture('app-r7-success.synthetic');
  const app = new D4RuleKitApplication({ providers: [fixture.provider] });
  assert.deepEqual(app.listProviders().map(provider => provider.id), [fixture.provider.id]);
  const created = await app.createSession(createOptions(fixture.provider.id, fixture.provider.version));
  const initial = await app.evaluate(created.sessionId);
  assert.equal(initial.metrics[0].rawValue, 0);
  const request = changeRequest();
  const preview = await app.previewChanges(created.sessionId, request);
  assert.equal(preview.before[0].rawValue, 0);
  assert.equal(preview.after[0].rawValue, 1);
  assert.equal(app.getSession(created.sessionId).revision, 0);
  assert.deepEqual(fixture.controls.state, BASE_BUILD);
  const committed = await app.commitChanges(created.sessionId, {
    ...request, previewToken: preview.previewToken,
  });
  assert.equal(committed.session.revision, 1);
  assert.equal((await app.evaluate(created.sessionId)).metrics[0].rawValue, 1);
  const reset = await app.resetSession(created.sessionId, { expectedRevision: 1 });
  assert.equal(reset.revision, 2);
  assert.equal((await app.evaluate(created.sessionId)).metrics[0].rawValue, 0);
  assert.equal((await app.closeSession(created.sessionId)).closed, true);
});
