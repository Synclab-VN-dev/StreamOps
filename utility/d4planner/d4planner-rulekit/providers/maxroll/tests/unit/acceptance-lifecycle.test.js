'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const {
  initializeOwnedRuntime,
  runOwnedAcceptance,
} = require('../helpers/acceptance-lifecycle');

function runtimeHarness() {
  const trace = [];
  const runtime = {
    browser: {
      async start() { trace.push('browser:start'); },
    },
    resources: { lease: null, mount: null, networkProbe: null, ownedPid: null },
  };
  const cleanup = async owned => {
    trace.push('cleanup');
    owned.resources.networkProbe = null;
    owned.resources.mount = null;
    owned.resources.lease = null;
  };
  return { cleanup, runtime, trace };
}

test('E2E-01 browser-start failure still enters owned cleanup', async () => {
  const { cleanup, runtime, trace } = runtimeHarness();
  runtime.browser.start = async () => { trace.push('browser:start'); throw new Error('start failed'); };
  await assert.rejects(() => initializeOwnedRuntime({
    createBrowser: () => runtime.browser,
    createSnapshots: () => { throw new Error('unreachable'); },
    createProfile: () => ({}), createProvider: () => ({}), cleanup,
  }), /start failed/);
  assert.deepEqual(trace, ['browser:start', 'cleanup']);
});

test('E2E-01 snapshot-manager initialization failure cleans started browser', async () => {
  const { cleanup, runtime, trace } = runtimeHarness();
  await assert.rejects(() => initializeOwnedRuntime({
    createBrowser: () => runtime.browser,
    createSnapshots: () => { trace.push('snapshots:init'); throw new Error('snapshot failed'); },
    createProfile: () => ({}), createProvider: () => ({}), cleanup,
  }), /snapshot failed/);
  assert.deepEqual(trace, ['browser:start', 'snapshots:init', 'cleanup']);
});

for (const [name, resource] of [
  ['network-probe attach', 'networkProbe'],
  ['snapshot mount', 'mount'],
  ['provider-session initialization', 'lease'],
]) {
  test(`E2E-01 ${name} failure cleans every previously owned resource`, async () => {
    const { cleanup, runtime, trace } = runtimeHarness();
    await assert.rejects(() => runOwnedAcceptance({
      initialize: async () => runtime,
      execute: async owned => {
        owned.resources[resource] = { owned: true };
        trace.push(`${resource}:created`);
        throw new Error(`${name} failed`);
      },
      cleanup,
    }), new RegExp(`${name} failed`));
    assert.deepEqual(trace, [`${resource}:created`, 'cleanup']);
    assert.equal(runtime.resources[resource], null);
  });
}

test('E2E-01 preserves primary and cleanup failures in AggregateError', async () => {
  const { runtime } = runtimeHarness();
  await assert.rejects(() => runOwnedAcceptance({
    initialize: async () => runtime,
    execute: async () => { throw new Error('primary failure'); },
    cleanup: async () => { throw new Error('cleanup failure'); },
  }), error => {
    assert.equal(error instanceof AggregateError, true);
    assert.deepEqual(error.errors.map(value => value.message), ['primary failure', 'cleanup failure']);
    return true;
  });
});
