'use strict';

// TEST_ONLY synthetic composition. Production never imports this module.
const { D4RuleKitApplication } = require('../../../d4planner-rulekit/application/src');

function clone(value) { return structuredClone(value); }

function assertComplete(build) {
  if (!build || typeof build !== 'object' || typeof build.class !== 'string' ||
      !build.equipment || !build.skills || !build.paragon || !build.effects) {
    throw Object.assign(new Error('complete canonical build sections are required'), { code: 'INVALID_INPUT' });
  }
}

function apply(build, changes) {
  const next = clone(build);
  for (const change of changes) {
    if (change.type !== 'equipment.replace') {
      throw Object.assign(new Error('unsupported synthetic change'), { code: 'UNSUPPORTED_INPUT' });
    }
    if (change.item === null) delete next.equipment[change.slot];
    else next.equipment[change.slot] = clone(change.item);
  }
  return next;
}

function metrics(build) {
  return [{ id: 'synthetic.itemCount', rawValue: Object.keys(build.equipment).length,
    displayValue: String(Object.keys(build.equipment).length), unit: 'count', status: 'OBSERVED' }];
}

async function createComposition(env) {
  const provider = {
    id: 'test.synthetic', version: '1.0.0',
    getCapabilities: () => ({ version: 'test/v1', policyVersion: 'TEST_ONLY', stateModel: 'stateless',
      metricIds: ['synthetic.itemCount'], changeTypes: ['equipment.replace'] }),
    async createSession({ build }) {
      assertComplete(build);
      return {
        async evaluate(input) {
          if (input.build.testDelayMs) {
            await new Promise((resolve, reject) => {
              const timer = setTimeout(resolve, input.build.testDelayMs);
              input.signal?.addEventListener('abort', () => {
                clearTimeout(timer);
                reject(Object.assign(new Error('synthetic operation cancelled'), { code: 'CANCELLED' }));
              }, { once: true });
            });
          }
          const candidate = apply(input.build, input.changes);
          return { build: candidate, metrics: metrics(candidate), provenance: { source: 'TEST_ONLY' } };
        },
        async close() {},
      };
    },
  };
  return { application: new D4RuleKitApplication({
    providers: [provider], maxSessions: Number(env.D4_RULEKIT_MAX_SESSIONS || 4),
    sessionTtlMs: Number(env.D4_RULEKIT_SESSION_TTL_MS || 30_000), operationTimeoutMs: 2_000,
  }) };
}

module.exports = { createComposition };
