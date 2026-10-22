'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { afterEach, test } = require('node:test');
const {
  FileSystemSnapshotStore,
  NetworkInterceptor,
  SNAPSHOT_ERROR_CODES,
  WebSnapshotError,
  WebSnapshotManager,
} = require('../../src');
const {
  containsSensitiveLocation,
  hasSensitiveRequestHeaders,
  redactSensitiveJson,
  sanitizeResponseHeaders,
  validateSafeUrl,
} = require('../../src/snapshot/policy');

const temporaryDirectories = new Set();

afterEach(async () => {
  await Promise.all([...temporaryDirectories].map(directory =>
    fs.rm(directory, { recursive: true, force: true })));
  temporaryDirectories.clear();
});

async function temporaryDirectory() {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'streamops-snapshot-unit-'));
  temporaryDirectories.add(directory);
  return directory;
}

function draft(snapshotId = 'site-v1', overrides = {}) {
  const sourceUrl = overrides.sourceUrl ?? 'https://site.example/app';
  const body = Buffer.from(overrides.body ?? '<h1>fixture</h1>');
  return {
    schemaVersion: 'web-snapshot-draft/v1',
    snapshotId,
    sourceUrl,
    capturedAt: '2026-10-22T00:00:00.000Z',
    allowedOrigins: [new URL(sourceUrl).origin],
    site: overrides.site ?? 'site',
    version: overrides.version ?? 'v1',
    browserVersion: 'fixture-browser',
    playwrightVersion: '1.64.1',
    resources: overrides.resources ?? [{
      key: `GET ${sourceUrl}`,
      method: 'GET',
      url: sourceUrl,
      status: 200,
      headers: { 'content-type': 'text/html; charset=utf-8' },
      redirectedFrom: null,
      body,
    }],
  };
}

async function rejectsCode(promise, code) {
  await assert.rejects(promise, error =>
    error instanceof WebSnapshotError && error.code === code);
}

test('SNAP-03 stores multiple sites and versions immutably', async () => {
  const store = new FileSystemSnapshotStore({ rootDir: await temporaryDirectory() });
  await store.save(draft('site-a-v1', { site: 'a', version: 'v1' }));
  await store.save(draft('site-a-v2', { site: 'a', version: 'v2', body: 'v2' }));
  await store.save(draft('site-b-v1', {
    site: 'b', version: 'v1', sourceUrl: 'https://other.example/app', body: 'b',
  }));
  assert.deepEqual((await store.list()).map(row => row.snapshotId),
    ['site-a-v1', 'site-a-v2', 'site-b-v1']);
  assert.deepEqual((await store.list({ site: 'a' })).map(row => row.version), ['v1', 'v2']);
  await rejectsCode(store.save(draft('site-a-v1')), SNAPSHOT_ERROR_CODES.DUPLICATE_SNAPSHOT);
  assert.equal((await store.load('site-a-v1')).resources[0].size, 16);
});

test('SNAP-06 detects tampered and missing content-addressed resources', async () => {
  const rootDir = await temporaryDirectory();
  const store = new FileSystemSnapshotStore({ rootDir });
  const manifest = await store.save(draft('integrity'));
  const verification = await store.verify('integrity');
  const { manifestSha256, ...summary } = verification;
  assert.deepEqual(summary, {
    snapshotId: 'integrity', valid: true, resourceCount: 1, totalBytes: 16, algorithm: 'sha256',
  });
  assert.match(manifestSha256, /^[a-f0-9]{64}$/);
  const blob = path.join(rootDir, 'integrity', manifest.resources[0].blob);
  await fs.writeFile(blob, 'tampered');
  await rejectsCode(store.verify('integrity'), SNAPSHOT_ERROR_CODES.INTEGRITY_MISMATCH);
  await fs.rm(blob);
  await rejectsCode(store.verify('integrity'), SNAPSHOT_ERROR_CODES.RESOURCE_MISSING);
});

test('W3-R2 SNAP-06 rejects manifest HTTP status tampering', async () => {
  const rootDir = await temporaryDirectory();
  const store = new FileSystemSnapshotStore({ rootDir });
  await store.save(draft('tamper-status'));
  const manifestPath = path.join(rootDir, 'tamper-status', 'manifest.json');
  const manifest = JSON.parse(await fs.readFile(manifestPath, 'utf8'));
  manifest.resources[0].status = 201;
  await fs.writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
  await rejectsCode(store.verify('tamper-status'), SNAPSHOT_ERROR_CODES.INTEGRITY_MISMATCH);
  const manager = new WebSnapshotManager({
    browser: { withLease() {} },
    store,
  });
  await rejectsCode(manager.mount({ valid: true }, 'tamper-status'),
    SNAPSHOT_ERROR_CODES.INTEGRITY_MISMATCH);
});

test('W3-R2 SNAP-06 rejects manifest content-type tampering', async () => {
  const rootDir = await temporaryDirectory();
  const store = new FileSystemSnapshotStore({ rootDir });
  await store.save(draft('tamper-content-type'));
  const manifestPath = path.join(rootDir, 'tamper-content-type', 'manifest.json');
  const manifest = JSON.parse(await fs.readFile(manifestPath, 'utf8'));
  manifest.resources[0].headers['content-type'] = 'application/javascript';
  await fs.writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
  await rejectsCode(store.verify('tamper-content-type'), SNAPSHOT_ERROR_CODES.INTEGRITY_MISMATCH);
});

test('SNAP-09 rejects corrupt/partial packages and cleans failed atomic saves', async () => {
  const rootDir = await temporaryDirectory();
  const store = new FileSystemSnapshotStore({ rootDir });
  await fs.mkdir(path.join(rootDir, 'corrupt'));
  await fs.writeFile(path.join(rootDir, 'corrupt', 'manifest.json'), '{not-json');
  await rejectsCode(store.load('corrupt'), SNAPSHOT_ERROR_CODES.INVALID_SNAPSHOT);
  await fs.mkdir(path.join(rootDir, 'partial'));
  await rejectsCode(store.load('partial'), SNAPSHOT_ERROR_CODES.INVALID_SNAPSHOT);

  const failingFs = Object.create(fs);
  failingFs.writeFile = async (...args) => {
    if (String(args[0]).endsWith('manifest.json')) throw Object.assign(new Error('disk full'), { code: 'ENOSPC' });
    return fs.writeFile(...args);
  };
  const failing = new FileSystemSnapshotStore({ rootDir, fsImpl: failingFs });
  await rejectsCode(failing.save(draft('disk-failure')), SNAPSHOT_ERROR_CODES.STORAGE_IO);
  const entries = await fs.readdir(rootDir);
  assert.equal(entries.some(name => name.includes('disk-failure')), false);
});

test('SNAP-10 enforces resource, byte and snapshot limits', async () => {
  const rootDir = await temporaryDirectory();
  const store = new FileSystemSnapshotStore({
    rootDir,
    limits: { maxSnapshots: 1, maxResources: 1, maxResourceBytes: 4, maxTotalBytes: 4 },
  });
  await rejectsCode(store.save(draft('too-big')), SNAPSHOT_ERROR_CODES.RESOURCE_LIMIT);
  await store.save(draft('small', { body: '1234' }));
  await rejectsCode(store.save(draft('second', { body: '1' })), SNAPSHOT_ERROR_CODES.STORAGE_LIMIT);
  const twoResources = draft('many', { body: '1' });
  twoResources.resources.push({ ...twoResources.resources[0], key: 'GET https://site.example/other', url: 'https://site.example/other' });
  const another = new FileSystemSnapshotStore({
    rootDir: await temporaryDirectory(), limits: { maxResources: 1 },
  });
  await rejectsCode(another.save(twoResources), SNAPSHOT_ERROR_CODES.RESOURCE_LIMIT);
});

test('SNAP-03/09 concurrent duplicate save has one winner and no partial package', async () => {
  const rootDir = await temporaryDirectory();
  const store = new FileSystemSnapshotStore({ rootDir });
  const results = await Promise.allSettled([
    store.save(draft('race')),
    store.save(draft('race')),
  ]);
  assert.equal(results.filter(result => result.status === 'fulfilled').length, 1);
  assert.equal(results.filter(result => result.status === 'rejected'
    && result.reason.code === SNAPSHOT_ERROR_CODES.DUPLICATE_SNAPSHOT).length, 1);
  assert.equal((await store.verify('race')).valid, true);
  assert.equal((await fs.readdir(rootDir)).some(name => name.startsWith('.tmp-')), false);
});

test('SNAP-10 concurrent unique saves cannot race past store capacity', async () => {
  const rootDir = await temporaryDirectory();
  const store = new FileSystemSnapshotStore({ rootDir, limits: { maxSnapshots: 1 } });
  const results = await Promise.allSettled([
    store.save(draft('capacity-a')),
    store.save(draft('capacity-b')),
  ]);
  assert.equal(results.filter(result => result.status === 'fulfilled').length, 1);
  assert.equal(results.filter(result => result.status === 'rejected'
    && result.reason.code === SNAPSHOT_ERROR_CODES.STORAGE_LIMIT).length, 1);
  assert.equal((await store.list()).length, 1);
});

test('SNAP-07 excludes sensitive URLs/headers and strips unsafe response headers', () => {
  assert.throws(() => validateSafeUrl('https://site.example/?token=secret',
    ['https://site.example']), error => error.code === SNAPSHOT_ERROR_CODES.POLICY_BLOCKED);
  assert.throws(() => validateSafeUrl('https://outside.example/',
    ['https://site.example']), error => error.code === SNAPSHOT_ERROR_CODES.POLICY_BLOCKED);
  assert.equal(hasSensitiveRequestHeaders({ Cookie: 'session=secret' }), true);
  assert.equal(hasSensitiveRequestHeaders({ accept: 'text/html' }), false);
  assert.deepEqual(sanitizeResponseHeaders({
    'Content-Type': 'text/plain', 'Set-Cookie': 'secret=1', authorization: 'secret', etag: 'abc',
  }), { 'content-type': 'text/plain', etag: 'abc' });
});

test('W3-R3 SNAP-07 redacts generic sensitive JSON keys and detects sensitive redirects', () => {
  const original = Buffer.from(JSON.stringify({
    safe: 42,
    access_token: 'secret',
    profile: { email: 'private@example.test' },
  }));
  const result = redactSensitiveJson(original, 'application/json; charset=utf-8');
  assert.deepEqual(JSON.parse(result.body.toString()), {
    safe: 42,
    access_token: '[REDACTED]',
    profile: { email: '[REDACTED]' },
  });
  assert.deepEqual(result.redactedFields, ['access_token', 'email']);
  assert.equal(containsSensitiveLocation('/next?token=secret', 'https://site.example/start'), true);
  assert.equal(containsSensitiveLocation('/next#access_token=secret',
    'https://site.example/start'), true);
  assert.equal(containsSensitiveLocation('/next?view=public', 'https://site.example/start'), false);
});

class FakeReplayContext extends EventEmitter {
  constructor() {
    super();
    this.handler = null;
    this.unrouteCount = 0;
    this.initScriptCount = 0;
    this.offline = false;
  }

  async addInitScript() { this.initScriptCount += 1; }
  async setOffline(value) { this.offline = value; }
  serviceWorkers() { return []; }
  async route(_pattern, handler) { this.handler = handler; }
  async unroute(_pattern, handler) {
    assert.equal(handler, this.handler);
    this.handler = null;
    this.unrouteCount += 1;
  }
}

function fakeRoute(method, url) {
  const calls = [];
  return {
    calls,
    request: () => ({ method: () => method, url: () => url, resourceType: () => 'document' }),
    fulfill: async options => calls.push(['fulfill', options]),
    abort: async reason => calls.push(['abort', reason]),
    continue: async () => calls.push(['continue']),
  };
}

test('SNAP-05/08 strict mount fulfills exact resources, aborts misses, and unmounts', async () => {
  const context = new FakeReplayContext();
  const lease = { valid: true, context };
  const interceptor = new NetworkInterceptor();
  const resources = new Map([['GET https://site.example/app', {
    status: 200, headers: { 'content-type': 'text/plain' }, body: Buffer.from('ok'),
  }]]);
  const mount = await interceptor.mount(lease, { resources });
  await rejectsCode(interceptor.mount(lease, { resources }), SNAPSHOT_ERROR_CODES.MOUNT_INVALID);
  const hit = fakeRoute('GET', 'https://site.example/app');
  await context.handler(hit);
  assert.equal(hit.calls[0][0], 'fulfill');
  assert.equal(hit.calls.some(call => call[0] === 'continue'), false);
  const miss = fakeRoute('GET', 'https://site.example/missing?token=secret');
  await context.handler(miss);
  assert.deepEqual(miss.calls, [['abort', 'blockedbyclient']]);
  assert.deepEqual(mount.getDiagnostics(), {
    fulfilled: 1, aborted: 1, redirected: 0, transportOffline: true,
    misses: [{ method: 'GET', url: 'https://site.example/missing', code: 'REPLAY_MISS' }],
  });
  await Promise.all([mount.unmount(), mount.unmount()]);
  assert.equal(mount.mounted, false);
  assert.equal(context.unrouteCount, 1);
  assert.equal(context.offline, false);
});

test('SNAP-08 context close cleans mount state for subsequent mount', async () => {
  const context = new FakeReplayContext();
  const interceptor = new NetworkInterceptor();
  const lease = { valid: true, context };
  const resources = new Map();
  const first = await interceptor.mount(lease, { resources });
  context.emit('close');
  assert.equal(first.mounted, false);
  const second = await interceptor.mount(lease, { resources });
  assert.equal(second.mounted, true);
  await second.unmount();
});

test('W3-R1 SNAP-12 rejects a context with pre-existing service workers', async () => {
  const context = new FakeReplayContext();
  context.serviceWorkers = () => [{ url: () => 'https://site.example/sw.js' }];
  const interceptor = new NetworkInterceptor();
  await rejectsCode(interceptor.mount({ valid: true, context }, { resources: new Map() }),
    SNAPSHOT_ERROR_CODES.MOUNT_INVALID);
  assert.equal(context.handler, null);
  assert.equal(context.offline, false);
});

test('SNAP-08 cleanup failure is explicit and context close enables recovery', async () => {
  const context = new FakeReplayContext();
  context.unroute = async () => { throw new Error('synthetic cleanup failure'); };
  const interceptor = new NetworkInterceptor();
  const lease = { valid: true, context };
  const resources = new Map();
  const mount = await interceptor.mount(lease, { resources });
  await rejectsCode(mount.unmount(), SNAPSHOT_ERROR_CODES.MOUNT_CLEANUP_FAILED);
  assert.equal(mount.mounted, true);
  await rejectsCode(interceptor.mount(lease, { resources }), SNAPSHOT_ERROR_CODES.MOUNT_INVALID);
  context.emit('close');
  const replacement = new FakeReplayContext();
  const recovered = await interceptor.mount({ valid: true, context: replacement }, { resources });
  await recovered.unmount();
});

test('SNAP-11 redirect replay never continues network and requires captured target', async () => {
  const context = new FakeReplayContext();
  const interceptor = new NetworkInterceptor();
  const source = {
    status: 302,
    url: 'https://site.example/start',
    headers: { location: '/target' },
    body: Buffer.alloc(0),
  };
  const target = {
    status: 200,
    url: 'https://site.example/target',
    headers: { 'content-type': 'text/html' },
    body: Buffer.from('target'),
  };
  const resources = new Map([
    ['GET https://site.example/start', source],
    ['GET https://site.example/target', target],
  ]);
  const mount = await interceptor.mount({ valid: true, context }, { resources });
  const route = fakeRoute('GET', source.url);
  await context.handler(route);
  assert.equal(route.calls[0][0], 'fulfill');
  assert.equal(route.calls[0][1].status, 200);
  assert.match(route.calls[0][1].body, /location\.replace/);
  assert.equal(mount.getDiagnostics().redirected, 1);
  await mount.unmount();

  const missingContext = new FakeReplayContext();
  const missingMount = await interceptor.mount({ valid: true, context: missingContext }, {
    resources: new Map([['GET https://site.example/start', source]]),
  });
  const missing = fakeRoute('GET', source.url);
  await missingContext.handler(missing);
  assert.deepEqual(missing.calls, [['abort', 'blockedbyclient']]);
  await missingMount.unmount();
});

test('SNAP-10 capture timeout/cancellation are typed and never save output', async () => {
  const browser = {
    withLease: ({ signal }) => new Promise((resolve, reject) => {
      signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true });
    }),
  };
  const store = {
    save() {}, load() {}, list() {}, verify() {}, loadPackage() {},
  };
  const manager = new WebSnapshotManager({ browser, store });
  await rejectsCode(manager.capture({
    url: 'https://site.example/', allowedOrigins: ['https://site.example'], timeoutMs: 5,
  }), SNAPSHOT_ERROR_CODES.CAPTURE_TIMEOUT);
  const controller = new AbortController();
  const capture = manager.capture({
    url: 'https://site.example/', allowedOrigins: ['https://site.example'],
    signal: controller.signal,
  });
  controller.abort();
  await rejectsCode(capture, SNAPSHOT_ERROR_CODES.CAPTURE_CANCELLED);
});

test('SNAP-09 rejects unsafe identifiers and invalid drafts fail-closed', async () => {
  const store = new FileSystemSnapshotStore({ rootDir: await temporaryDirectory() });
  await rejectsCode(store.load('../escape'), SNAPSHOT_ERROR_CODES.INVALID_OPTIONS);
  const invalid = draft('invalid');
  invalid.resources.push({ ...invalid.resources[0] });
  await rejectsCode(store.save(invalid), SNAPSHOT_ERROR_CODES.INVALID_SNAPSHOT);
});
