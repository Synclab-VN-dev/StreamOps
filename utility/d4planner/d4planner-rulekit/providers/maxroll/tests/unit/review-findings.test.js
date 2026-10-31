'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const {
  NetworkEgressProbe,
  cleanupOwnedRuntime,
  throwAfterCleanup,
} = require('../helpers/adapter-acceptance');
const { classifyExactSlotItemIdentity } = require('../../src/real-runtime-adapter');

class FakeNetworkCdp {
  handlers = new Map();
  commands = [];
  detached = false;

  on(name, handler) { this.handlers.set(name, handler); }
  async send(command) { this.commands.push(command); }
  async detach() { this.detached = true; }
  emit(name, event) { this.handlers.get(name)?.(event); }
}

test('REV-01 probe distinguishes attempts, local replay, failures and completed egress', async () => {
  const cdp = new FakeNetworkCdp();
  const probe = await NetworkEgressProbe.attach({
    page: {}, context: { newCDPSession: async () => cdp },
  });
  cdp.emit('Network.requestWillBeSent', { request: { url: 'https://fixture.invalid/app.js' } });
  cdp.emit('Network.responseReceived', { response: { url: 'https://fixture.invalid/app.js' } });
  cdp.emit('Network.loadingFailed', {});
  cdp.emit('Network.responseReceived', {
    response: { url: 'https://outside.invalid/live', remoteIPAddress: '203.0.113.10' },
  });
  cdp.emit('Network.webSocketCreated', { url: 'wss://outside.invalid/socket' });
  cdp.emit('Network.webSocketHandshakeResponseReceived', {});

  assert.deepEqual(probe.getDiagnostics(), {
    requestAttempts: 1,
    responseEvents: 2,
    loadingFailures: 1,
    webSocketAttempts: 1,
    webSocketHandshakes: 1,
    externalEgressCompleted: 2,
    source: 'CDP.Network',
  });
  await probe.close();
  assert.deepEqual(cdp.commands, ['Network.enable', 'Network.disable']);
  assert.equal(cdp.detached, true);
});

test('REV-02 cleanup failure is propagated after all owned teardown is attempted', async () => {
  let browserStops = 0;
  const browser = {
    getStatus: () => browserStops
      ? { state: 'stopped', pid: null, activeLeases: 0 }
      : { state: 'running', pid: 123, activeLeases: 0 },
    getMetrics: () => ({ currentContexts: 0 }),
    stop: async () => { browserStops += 1; },
  };
  await assert.rejects(() => cleanupOwnedRuntime({
    session: { close: async () => { throw new Error('injected close failure'); } },
    networkProbe: { close: async () => {} },
    mount: { mounted: false },
    lease: { valid: false },
    browser,
    ownedPid: null,
  }), error => error instanceof AggregateError &&
    error.errors.some(failure => failure.message === 'injected close failure'));
  assert.equal(browserStops, 1, 'browser stop must still run after session cleanup fails');

  assert.throws(() => throwAfterCleanup(new Error('test failed'), new Error('cleanup failed')),
    error => error instanceof AggregateError && error.errors.length === 2);
});

test('REV-03 exact slot identity rejects wrong, duplicate, missing and ambiguous DOM', () => {
  assert.deepEqual(classifyExactSlotItemIdentity(1, ['  Runic   Skullcap  '], 'Runic Skullcap'), {
    status: 'EXACT', normalizedName: 'Runic Skullcap',
  });
  assert.equal(classifyExactSlotItemIdentity(1, ['Wrong Runic Skullcap'], 'Runic Skullcap').status,
    'WRONG_ITEM');
  assert.equal(classifyExactSlotItemIdentity(1, ['Runic Skullcap', 'Runic Skullcap'],
    'Runic Skullcap').status, 'AMBIGUOUS_ITEM');
  assert.equal(classifyExactSlotItemIdentity(1, [], 'Runic Skullcap').status, 'MISSING_ITEM');
  assert.equal(classifyExactSlotItemIdentity(0, [], 'Runic Skullcap').status, 'MISSING_SLOT');
  assert.equal(classifyExactSlotItemIdentity(2, ['Runic Skullcap'], 'Runic Skullcap').status,
    'AMBIGUOUS_SLOT');
});
