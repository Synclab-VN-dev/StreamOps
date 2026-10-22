'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { D4RuleKitApplication } = require('../../src');
const { createOptions, makeStatefulProvider, makeStatelessProvider } = require('../helpers/providers');

test('stateful end-to-end create/evaluate/preview/commit/reset/close preserves isolation', async () => {
  const stateful = makeStatefulProvider();
  const app = new D4RuleKitApplication({ providers: [stateful.provider] });
  const first = await app.createSession(createOptions('stateful.synthetic', '1.0.0'));
  const second = await app.createSession(createOptions('stateful.synthetic', '1.0.0'));
  const baseline = await app.evaluate(first.sessionId);
  const changes = [
    { type: 'equipment.replace', slot: 'weapon', item: { id: 'fixture-only' } },
    { type: 'skill.setRank', skillId: 'fixture-skill', rank: 4 },
  ];
  const preview = await app.previewChanges(first.sessionId, { expectedRevision: 0, changes });
  assert.equal(preview.after.find(metric => metric.id === 'synthetic.itemCount').rawValue, 1);
  assert.equal((await app.evaluate(first.sessionId)).inputFingerprint, baseline.inputFingerprint);
  const commit = await app.commitChanges(first.sessionId, {
    expectedRevision: 0, changes, previewToken: preview.previewToken,
  });
  assert.equal(commit.session.revision, 1);
  assert.equal((await app.evaluate(first.sessionId)).metrics.find(metric => metric.id === 'synthetic.itemCount').rawValue, 1);
  assert.equal((await app.evaluate(second.sessionId)).metrics.find(metric => metric.id === 'synthetic.itemCount').rawValue, 0);
  const reset = await app.resetSession(first.sessionId, { expectedRevision: 1 });
  assert.equal(reset.revision, 2);
  assert.equal((await app.evaluate(first.sessionId)).metrics.find(metric => metric.id === 'synthetic.itemCount').rawValue, 0);
  await Promise.all([app.closeSession(first.sessionId), app.closeSession(second.sessionId)]);
});

test('stateless end-to-end fully reevaluates candidate and invalidates cache on commit', async () => {
  const stateless = makeStatelessProvider();
  const app = new D4RuleKitApplication({ providers: [stateless.provider] });
  const session = await app.createSession(createOptions('stateless.synthetic', '2.0.0'));
  const baseline = await app.evaluate(session.sessionId);
  assert.equal((await app.evaluate(session.sessionId)).cache.hit, true);
  const changes = [{ type: 'effect.set', effectId: 'fixture-effect', active: true }];
  const preview = await app.previewChanges(session.sessionId, { expectedRevision: 0, changes });
  await app.commitChanges(session.sessionId, { expectedRevision: 0, changes, previewToken: preview.previewToken });
  const after = await app.evaluate(session.sessionId);
  assert.equal(after.cache.hit, false);
  assert.notEqual(after.inputFingerprint, baseline.inputFingerprint);
  assert.equal(after.metrics.find(metric => metric.id === 'synthetic.effectCount').rawValue, 1);
  await app.closeSession(session.sessionId);
});

test('provider version and snapshot digest produce isolated cache identities', async () => {
  const one = makeStatelessProvider({ id: 'one.synthetic', version: '1' });
  const two = makeStatelessProvider({ id: 'two.synthetic', version: '2' });
  const app = new D4RuleKitApplication({ providers: [one.provider, two.provider] });
  const s1 = await app.createSession(createOptions('one.synthetic', '1'));
  const s2 = await app.createSession({ ...createOptions('two.synthetic', '2'), snapshotManifestSha256: 'b'.repeat(64) });
  const [r1, r2] = await Promise.all([app.evaluate(s1.sessionId), app.evaluate(s2.sessionId)]);
  assert.notEqual(r1.cache.key, r2.cache.key);
  assert.equal(r1.providerVersion, '1');
  assert.equal(r2.snapshotManifestSha256, 'b'.repeat(64));
});

test('cache never leaks response ownership across otherwise identical sessions', async () => {
  const fixture = makeStatelessProvider();
  const app = new D4RuleKitApplication({ providers: [fixture.provider] });
  const first = await app.createSession(createOptions('stateless.synthetic', '2.0.0'));
  const second = await app.createSession(createOptions('stateless.synthetic', '2.0.0'));
  const firstResult = await app.evaluate(first.sessionId);
  const secondResult = await app.evaluate(second.sessionId);
  assert.equal(firstResult.sessionId, first.sessionId);
  assert.equal(secondResult.sessionId, second.sessionId);
  assert.notEqual(firstResult.cache.key, secondResult.cache.key);
});
