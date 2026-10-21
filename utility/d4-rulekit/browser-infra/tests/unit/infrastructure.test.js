'use strict';

const assert = require('node:assert/strict');
const { test } = require('node:test');
const {
  BrowserInfrastructure,
  BrowserInfrastructureError,
  ERROR_CODES,
} = require('../../src');
const { FakeLauncher } = require('../helpers/fakes');

function infra(config = {}, launcher = new FakeLauncher()) {
  return { instance: new BrowserInfrastructure(config, { launcher }), launcher };
}

async function rejectsCode(promise, code) {
  await assert.rejects(promise, error =>
    error instanceof BrowserInfrastructureError && error.code === code);
}

test('INF-09 rejects invalid configuration fail-closed', () => {
  for (const config of [
    { maxContexts: 0 }, { maxQueue: -1 }, { acquireTimeoutMs: 0 },
    { leaseTimeoutMs: 0 }, { headless: 'yes' }, { logger: true },
  ]) {
    assert.throws(() => new BrowserInfrastructure(config), error =>
      error.code === ERROR_CODES.INVALID_CONFIG);
  }
});

test('INF-01 start and stop are idempotent; restart replaces one browser', async () => {
  const { instance, launcher } = infra();
  await Promise.all([instance.start(), instance.start(), instance.start()]);
  assert.equal(launcher.launchCount, 1);
  assert.equal(instance.getStatus().state, 'running');
  await instance.restart();
  assert.equal(launcher.launchCount, 2);
  assert.equal(launcher.peakConnected, 1);
  assert.equal(instance.getStatus().restartCount, 1);
  await Promise.all([instance.stop(), instance.stop()]);
  assert.equal(instance.getStatus().state, 'stopped');
  assert.equal(launcher.connected, 0);
});

test('INF-09 concurrent restart/stop lifecycle never keeps two fake browsers', async () => {
  const { instance, launcher } = infra({}, new FakeLauncher({ launchDelayMs: 2 }));
  await instance.start();
  await Promise.all([instance.restart(), instance.restart()]);
  assert.equal(launcher.peakConnected, 1);
  await Promise.all([instance.stop(), instance.stop()]);
  assert.equal(launcher.connected, 0);
});

test('INF-02 repeated leases reuse browser and dispose contexts', async () => {
  const { instance, launcher } = infra({ maxContexts: 1 });
  await instance.start();
  const contexts = [];
  for (let index = 0; index < 5; index += 1) {
    const lease = await instance.acquire();
    contexts.push(lease.context);
    await lease.release();
    await lease.release();
  }
  assert.equal(launcher.launchCount, 1);
  assert.equal(new Set(contexts).size, 5);
  assert.ok(contexts.every(context => context.closed));
  assert.equal(instance.getStatus().activeLeases, 0);
  await instance.stop();
});

test('INF-04 CDP session is lazy, cached, and detached on release', async () => {
  const { instance } = infra();
  await instance.start();
  const lease = await instance.acquire();
  assert.equal(lease.context.sessions.length, 0);
  const first = await lease.createCDPSession();
  const second = await lease.createCDPSession();
  assert.equal(first, second);
  assert.equal(lease.context.sessions.length, 1);
  await lease.release();
  assert.equal(first.detached, true);
  await rejectsCode(lease.createCDPSession(), ERROR_CODES.LEASE_EXPIRED);
  await instance.stop();
});

test('INF-05 bounded queue is FIFO and capacity is honored', async () => {
  const { instance } = infra({ maxContexts: 1, maxQueue: 2 });
  await instance.start();
  const first = await instance.acquire();
  const order = [];
  const secondPromise = instance.acquire().then(lease => { order.push('second'); return lease; });
  const thirdPromise = instance.acquire().then(lease => { order.push('third'); return lease; });
  assert.equal(instance.getStatus().pendingQueue, 2);
  await first.release();
  const second = await secondPromise;
  assert.deepEqual(order, ['second']);
  await second.release();
  const third = await thirdPromise;
  assert.deepEqual(order, ['second', 'third']);
  await third.release();
  await instance.stop();
});

test('INF-05 capacity exceeded is typed when queue is full', async () => {
  const { instance } = infra({ maxContexts: 1, maxQueue: 0 });
  await instance.start();
  const lease = await instance.acquire();
  await rejectsCode(instance.acquire(), ERROR_CODES.CAPACITY_EXCEEDED);
  await lease.release();
  await instance.stop();
});

test('INF-06 queue timeout removes waiter without leak', async () => {
  const { instance } = infra({ maxContexts: 1, maxQueue: 1 });
  await instance.start();
  const lease = await instance.acquire();
  await rejectsCode(instance.acquire({ timeoutMs: 10 }), ERROR_CODES.QUEUE_TIMEOUT);
  assert.equal(instance.getStatus().pendingQueue, 0);
  assert.equal(instance.getMetrics().queueTimeoutCount, 1);
  await lease.release();
  await instance.stop();
});

test('INF-06 queued and pre-aborted acquisitions cancel without leak', async () => {
  const { instance } = infra({ maxContexts: 1, maxQueue: 2 });
  await instance.start();
  const lease = await instance.acquire();
  const queuedAbort = new AbortController();
  const queued = instance.acquire({ signal: queuedAbort.signal });
  queuedAbort.abort();
  await rejectsCode(queued, ERROR_CODES.CANCELLED);
  const preAbort = new AbortController();
  preAbort.abort();
  await rejectsCode(instance.acquire({ signal: preAbort.signal }), ERROR_CODES.CANCELLED);
  assert.equal(instance.getStatus().pendingQueue, 0);
  await lease.release();
  await instance.stop();
});

test('INF-01/06 stop rejects queued acquisition and closes active lease', async () => {
  const { instance } = infra({ maxContexts: 1, maxQueue: 1 });
  await instance.start();
  const lease = await instance.acquire();
  const queued = instance.acquire();
  await instance.stop();
  await rejectsCode(queued, ERROR_CODES.CANCELLED);
  assert.equal(lease.valid, false);
  assert.equal(instance.getStatus().activeLeases, 0);
  assert.equal(instance.getStatus().pendingQueue, 0);
});

test('INF-06 cancellation during context creation closes reservation', async () => {
  const launcher = new FakeLauncher({ contextDelayMs: 15 });
  const { instance } = infra({ maxContexts: 1 }, launcher);
  await instance.start();
  const controller = new AbortController();
  const pending = instance.acquire({ signal: controller.signal });
  setTimeout(() => controller.abort(), 2);
  await rejectsCode(pending, ERROR_CODES.CANCELLED);
  assert.equal(instance.getMetrics().currentContexts, 0);
  assert.ok(launcher.latest().contexts.every(context => context.closed));
  await instance.stop();
});

test('INF-08 withLease releases after callback throws', async () => {
  const { instance } = infra();
  await instance.start();
  await assert.rejects(instance.withLease({}, async () => {
    throw new Error('consumer failure');
  }), /consumer failure/);
  assert.equal(instance.getStatus().activeLeases, 0);
  assert.equal(instance.getMetrics().releaseCount, 1);
  await instance.stop();
});

test('INF-07 disconnect invalidates lease and queued waiter; restart recovers', async () => {
  const { instance, launcher } = infra({ maxContexts: 1, maxQueue: 1 });
  await instance.start();
  const lease = await instance.acquire();
  const queued = instance.acquire();
  await launcher.latest().crash();
  await rejectsCode(queued, ERROR_CODES.BROWSER_DISCONNECTED);
  assert.equal(instance.getStatus().state, 'degraded');
  assert.equal(lease.valid, false);
  assert.equal(lease.invalidReason, ERROR_CODES.BROWSER_DISCONNECTED);
  await instance.restart();
  const recovered = await instance.acquire();
  await recovered.release();
  await instance.stop();
});

test('INF-06 lease expiry invalidates handles and frees capacity', async () => {
  const { instance } = infra({ maxContexts: 1, leaseTimeoutMs: 10 });
  await instance.start();
  const expired = await instance.acquire();
  await new Promise(resolve => setTimeout(resolve, 25));
  assert.equal(expired.valid, false);
  assert.equal(expired.invalidReason, ERROR_CODES.LEASE_EXPIRED);
  const next = await instance.acquire();
  await next.release();
  assert.equal(instance.getMetrics().leaseExpirationCount, 1);
  await instance.stop();
});

test('INF-10 status and metrics contain real lifecycle counters only', async () => {
  const logs = [];
  const { instance } = infra({ logger: event => logs.push(event) });
  assert.deepEqual(instance.getStatus(), {
    state: 'stopped', pid: null, activeLeases: 0, pendingQueue: 0,
    restartCount: 0, uptimeMs: 0,
  });
  await instance.start();
  const lease = await instance.acquire();
  await lease.release();
  const metrics = instance.getMetrics();
  assert.equal(metrics.launchCount, 1);
  assert.equal(metrics.acquireRequested, 1);
  assert.equal(metrics.acquireSucceeded, 1);
  assert.equal(metrics.releaseCount, 1);
  assert.equal(metrics.peakContexts, 1);
  assert.equal(metrics.currentContexts, 0);
  assert.equal(Object.hasOwn(metrics, 'rss'), false);
  assert.ok(logs.every(event => !Object.hasOwn(event, 'url')));
  await instance.stop();
});

test('INF-01 acquire before start and after stop returns NOT_RUNNING', async () => {
  const { instance } = infra();
  await rejectsCode(instance.acquire(), ERROR_CODES.NOT_RUNNING);
  await instance.start();
  await instance.stop();
  await rejectsCode(instance.acquire(), ERROR_CODES.NOT_RUNNING);
});
