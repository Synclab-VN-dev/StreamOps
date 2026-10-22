'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { after, afterEach, before, test } = require('node:test');
const {
  BrowserInfrastructure,
  BrowserInfrastructureError,
  ERROR_CODES,
} = require('../../src');
const { startLocalServer } = require('../helpers/local-server');

const executablePath = process.env.BROWSER_INFRA_CHROMIUM_PATH;
if (!executablePath || !fs.existsSync(executablePath)) {
  throw new Error('BROWSER_INFRA_CHROMIUM_PATH must point to a pinned Chromium executable');
}

let fixture;
const active = new Set();

before(async () => {
  fixture = await startLocalServer();
});

afterEach(async () => {
  await Promise.allSettled([...active].map(instance => instance.stop()));
  active.clear();
});

after(async () => {
  await fixture.close();
});

function create(config = {}) {
  const instance = new BrowserInfrastructure({
    executablePath,
    maxContexts: 2,
    maxQueue: 8,
    acquireTimeoutMs: 2_000,
    leaseTimeoutMs: 20_000,
    launchOptions: { args: ['--disable-background-networking'] },
    ...config,
  });
  active.add(instance);
  return instance;
}

async function rejectsCode(promise, code) {
  await assert.rejects(promise, error =>
    error instanceof BrowserInfrastructureError && error.code === code);
}

async function waitFor(predicate, timeoutMs = 5_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 20));
  }
  assert.fail('condition timed out');
}

test('INF-01 real Chromium lifecycle is idempotent and restartable', async () => {
  const instance = create();
  await Promise.all([instance.start(), instance.start()]);
  assert.equal(instance.getStatus().state, 'running');
  const firstPid = instance.getStatus().pid;
  assert.ok(Number.isInteger(firstPid) && firstPid > 0);
  assert.equal(fs.existsSync(`/proc/${firstPid}`), true);
  assert.equal(instance.getMetrics().launchCount, 1);
  const lease = await instance.acquire();
  await lease.page.goto(`${fixture.origin}/generic`);
  assert.equal(await lease.page.textContent('#value'), 'generic consumer');
  await lease.release();
  await instance.restart();
  assert.equal(instance.getStatus().state, 'running');
  const restartedPid = instance.getStatus().pid;
  assert.ok(Number.isInteger(restartedPid) && restartedPid > 0);
  assert.notEqual(restartedPid, firstPid);
  await waitFor(() => !fs.existsSync(`/proc/${firstPid}`));
  assert.equal(instance.getMetrics().launchCount, 2);
  await instance.stop();
  await instance.stop();
  assert.equal(instance.getStatus().state, 'stopped');
  await waitFor(() => !fs.existsSync(`/proc/${restartedPid}`));
});

test('INF-02/03 repeated real contexts reuse browser and isolate storage', async () => {
  const instance = create({ maxContexts: 2 });
  await instance.start();
  const first = await instance.acquire();
  const second = await instance.acquire();
  assert.notEqual(first.context, second.context);
  await Promise.all([
    first.page.goto(`${fixture.origin}/state`),
    second.page.goto(`${fixture.origin}/state`),
  ]);
  await first.page.evaluate(() => {
    document.cookie = 'isolation=first; path=/';
    localStorage.setItem('isolation', 'first');
  });
  const isolated = await second.page.evaluate(() => ({
    cookie: document.cookie,
    local: localStorage.getItem('isolation'),
  }));
  assert.deepEqual(isolated, { cookie: '', local: null });
  await Promise.all([first.release(), second.release()]);
  assert.equal(instance.getMetrics().launchCount, 1);
  assert.equal(instance.getMetrics().currentContexts, 0);
});

test('INF-04 lazy real CDP evaluates and is invalidated with lease', async () => {
  const instance = create();
  await instance.start();
  const lease = await instance.acquire();
  const cdp = await lease.createCDPSession();
  const evaluated = await cdp.send('Runtime.evaluate', {
    expression: '6 * 7', returnByValue: true,
  });
  assert.equal(evaluated.result.value, 42);
  await lease.release();
  await assert.rejects(cdp.send('Runtime.evaluate', { expression: '1' }));
  await rejectsCode(lease.createCDPSession(), ERROR_CODES.LEASE_EXPIRED);
});

test('INF-05/06 real queue is FIFO; timeout and cancellation do not leak', async () => {
  const instance = create({ maxContexts: 1, maxQueue: 3 });
  await instance.start();
  const held = await instance.acquire();
  const order = [];
  const next = instance.acquire().then(lease => { order.push('next'); return lease; });
  await rejectsCode(instance.acquire({ timeoutMs: 25 }), ERROR_CODES.QUEUE_TIMEOUT);
  const controller = new AbortController();
  const cancelled = instance.acquire({ signal: controller.signal });
  controller.abort();
  await rejectsCode(cancelled, ERROR_CODES.CANCELLED);
  assert.equal(instance.getStatus().pendingQueue, 1);
  await held.release();
  const acquired = await next;
  assert.deepEqual(order, ['next']);
  await acquired.release();
  assert.equal(instance.getMetrics().currentContexts, 0);
  assert.equal(instance.getStatus().pendingQueue, 0);
});

test('INF-07 deliberate real browser close invalidates and restart recovers', async () => {
  const instance = create({ maxContexts: 1 });
  await instance.start();
  const crashedPid = instance.getStatus().pid;
  const lease = await instance.acquire();
  const cdp = await lease.createCDPSession();
  await cdp.send('Browser.close');
  await waitFor(() => instance.getStatus().state === 'degraded');
  await waitFor(() => !fs.existsSync(`/proc/${crashedPid}`));
  assert.equal(lease.valid, false);
  assert.equal(lease.invalidReason, ERROR_CODES.BROWSER_DISCONNECTED);
  await instance.restart();
  const recovered = await instance.acquire();
  await recovered.page.goto(`${fixture.origin}/generic`);
  assert.equal(await recovered.page.title(), 'fixture');
  await recovered.release();
  assert.equal(instance.getMetrics().crashCount, 1);
});

test('INF-08/10 withLease cleanup and real metrics/status', async () => {
  const logs = [];
  const instance = create({ logger: event => logs.push(event) });
  await instance.start();
  await assert.rejects(instance.withLease({}, async lease => {
    await lease.page.goto(`${fixture.origin}/generic`);
    throw new Error('synthetic consumer failure');
  }), /synthetic consumer failure/);
  assert.equal(instance.getStatus().activeLeases, 0);
  const metrics = instance.getMetrics();
  assert.equal(metrics.acquireSucceeded, 1);
  assert.equal(metrics.releaseCount, 1);
  assert.ok(metrics.lastLaunchDurationMs >= 0);
  assert.equal(Object.hasOwn(metrics, 'rss'), false);
  assert.ok(logs.every(entry => !JSON.stringify(entry).includes(fixture.origin)));
});

test('INF-09 real concurrent lifecycle remains fail-closed', async () => {
  const instance = create();
  await instance.start();
  const lease = await instance.acquire();
  await Promise.all([instance.restart(), instance.restart()]);
  assert.equal(lease.valid, false);
  assert.equal(instance.getStatus().state, 'running');
  assert.equal(instance.getStatus().activeLeases, 0);
  const recovered = await instance.acquire();
  await recovered.release();
});

test('INF-11/12 generic consumer uses local fixture only and has no provider imports', async () => {
  const instance = create();
  await instance.start();
  const attempted = [];
  await instance.withLease({}, async lease => {
    await lease.page.route('**/*', route => {
      const url = new URL(route.request().url());
      attempted.push(url.origin);
      if (url.origin !== fixture.origin) return route.abort('blockedbyclient');
      return route.continue();
    });
    await lease.page.goto(`${fixture.origin}/generic`);
    assert.equal(await lease.page.textContent('#value'), 'generic consumer');
  });
  assert.deepEqual([...new Set(attempted)], [fixture.origin]);
  const sourceRoot = path.resolve(__dirname, '../../src');
  const source = fs.readdirSync(sourceRoot)
    .filter(name => name.endsWith('.js'))
    .map(name => fs.readFileSync(path.join(sourceRoot, name), 'utf8'))
    .join('\n');
  for (const forbidden of ['maxroll', 'heroDetails', 'calculateStats', 'd4planner']) {
    assert.equal(source.toLowerCase().includes(forbidden.toLowerCase()), false);
  }
});

test('INF-13 75 real lifecycle leases retain bounded resource counts', async () => {
  const instance = create({ maxContexts: 1 });
  await instance.start();
  for (let index = 0; index < 75; index += 1) {
    const lease = await instance.acquire();
    await lease.page.setContent(`<p>${index}</p>`);
    assert.equal(await lease.page.textContent('p'), String(index));
    await lease.release();
  }
  const metrics = instance.getMetrics();
  assert.equal(metrics.launchCount, 1);
  assert.equal(metrics.acquireSucceeded, 75);
  assert.equal(metrics.releaseCount, 75);
  assert.equal(metrics.currentContexts, 0);
  assert.equal(metrics.peakContexts, 1);
  assert.equal(instance.getStatus().pendingQueue, 0);
});
