'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const {execFileSync} = require('node:child_process');
const {createHash} = require('node:crypto');
const {PlannerServerManager} = require('../../tooling/planner/manager');
const {canonical} = require('../../tooling/planner/selection');
const {loadSnapshot, startServer} = require('../../tooling/web/server');

async function fixture(t) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'planner-manager-'));
  t.after(() => fs.rm(root, {recursive: true, force: true}));
  const config = JSON.parse(execFileSync(process.execPath, [path.resolve(__dirname, '../../tooling/web/activation-fixture.js'), path.join(root, 'ui')]))[0];
  const p = {kind: 'ui', snapshotId: config.snapshotId, validationStatus: 'VALIDATED', runId: 'test',
    manifestSha256: config.manifestSha256, coverageSha256: config.uiTrust.coverageSha256,
    validationSha256: config.uiTrust.validationSha256, config};
  const payload = {schemaVersion: 'maxroll-capture-state/v1', revision: 1, activeUi: config.snapshotId,
    packages: {[config.snapshotId]: p}, runs: {test: {status: 'COMPLETE'}}};
  const stateRoot = path.join(root, 'state'); await fs.mkdir(stateRoot);
  const file = path.join(stateRoot, 'capture-state.json');
  const write = async () => fs.writeFile(file, JSON.stringify({payload, sha256: createHash('sha256').update(canonical(payload)).digest('hex')}));
  await write();
  const probe = http.createServer(); await new Promise(r => probe.listen(0, '127.0.0.1', r));
  const port = probe.address().port; await new Promise(r => probe.close(r));
  return {root, config, payload, file, write, stateRoot, port};
}
function owned(t, config) { const manager = new PlannerServerManager(config); t.after(() => manager.close()); return manager; }

test('real HTTP start single-flight, authenticated health, reuse, crash recovery and port cleanup', async t => {
  const f = await fixture(t); let starts = 0;
  const m = owned(t, {...f, start: async (...args) => { starts++; return startServer(...args); }});
  const responses = await Promise.all(Array.from({length: 12}, () => m.ensureReady()));
  assert.equal(starts, 1); assert(responses.every(r => r.status === 'READY' && !r.reused));
  const server = m.running.server;
  const r = await m.ensureReady(); assert(r.reused); assert.equal(m.running.server, server);
  assert.equal((await fetch(r.url + '__local/health')).status, 403);
  assert.equal((await fetch(r.url)).status, 200);
  assert.equal(m.identity.pid, process.pid);
  await m.running.close(); assert.equal(m.state, 'STOPPED');
  assert.equal((await m.ensureReady()).reused, false); assert.equal(starts, 2);
  await m.close(); assert.equal(m.state, 'STOPPED');
  const port = http.createServer(); await new Promise(r => port.listen(f.port, '127.0.0.1', r)); await new Promise(r => port.close(r));
});

test('foreign HTTP 200/PID does not count as READY and is never stopped', async t => {
  const f = await fixture(t), foreign = http.createServer((req, res) => res.end('{"status":"READY"}'));
  await new Promise(r => foreign.listen(f.port, '127.0.0.1', r)); t.after(() => new Promise(r => foreign.close(r)));
  const m = owned(t, f);
  await assert.rejects(m.ensureReady(), {code: 'PLANNER_PORT_CONFLICT'});
  assert(foreign.listening); assert.equal((await fetch(`http://127.0.0.1:${f.port}/`)).status, 200);
});

test('missing/unvalidated/corrupt state and tampered blobs fail closed without bind', async t => {
  const f = await fixture(t), m = owned(t, f);
  await fs.unlink(f.file); await assert.rejects(m.ensureReady(), {code: 'PLANNER_SNAPSHOT_UNAVAILABLE'});
  await f.write(); f.payload.packages[f.config.snapshotId].validationStatus = 'CAPTURED_UNVALIDATED'; await f.write();
  await assert.rejects(m.ensureReady(), {code: 'PLANNER_SNAPSHOT_UNTRUSTED'});
  f.payload.packages[f.config.snapshotId].validationStatus = 'VALIDATED'; await f.write();
  const state = JSON.parse(await fs.readFile(f.file)); state.sha256 = '0'.repeat(64); await fs.writeFile(f.file, JSON.stringify(state));
  await assert.rejects(m.ensureReady(), {code: 'PLANNER_SNAPSHOT_UNTRUSTED'});
  await f.write(); await fs.appendFile(path.join(f.config.snapshotRoot, f.config.snapshotId, 'manifest.json'), ' ');
  await assert.rejects(m.ensureReady(), {code: 'PLANNER_SNAPSHOT_UNTRUSTED'}); assert.equal(m.running, null);
});

test('timeout and cancellation cannot bind after a late snapshot verification', async t => {
  const f = await fixture(t); let release; let starts = 0;
  const m = owned(t, {...f, timeoutMs: 25, load: async c => { await new Promise(r => { release = r; }); return loadSnapshot(c); },
    start: (...args) => { starts++; return startServer(...args); }});
  await assert.rejects(m.ensureReady(), {code: 'PLANNER_HEALTH_FAILED'});
  release(); await m.flight.promise.catch(() => {}); assert.equal(starts, 0); assert.equal(m.running, null);
  m.timeoutMs = 2000;
  const abort = new AbortController(); const pending = m.ensureReady({signal: abort.signal});
  await new Promise(r => setTimeout(r, 15)); abort.abort(); await assert.rejects(pending, {code: 'PLANNER_UNAVAILABLE'});
  release(); await m.flight.promise.catch(() => {}); assert.equal(starts, 0);
});

test('one cancelled waiter does not cancel another, and selection never changes on Create Build', async t => {
  const f = await fixture(t); let release;
  const m = owned(t, {...f, load: async c => { await new Promise(r => {release = r;}); return loadSnapshot(c); }});
  const abort = new AbortController(); const a = m.ensureReady({signal: abort.signal}); const b = m.ensureReady();
  await new Promise(r => setTimeout(r, 15)); abort.abort(); await assert.rejects(a, {code: 'PLANNER_UNAVAILABLE'});
  release(); const ready = await b; assert.equal(ready.status, 'READY');
  const before = await fs.readFile(f.file); f.payload.activeUi = 'another-unvalidated-candidate'; await f.write();
  assert.equal((await m.ensureReady()).snapshotId, f.config.snapshotId);
  assert.notDeepEqual(await fs.readFile(f.file), before); // manager did not overwrite externally changed metadata
});

test('wrong server identity fails health and closes only the owned listener', async t => {
  const f = await fixture(t);
  const m = owned(t, {...f, start: (c, options) => startServer(c, {...options, health: {...options.health, identity: {pid: -1}}})});
  await assert.rejects(m.ensureReady(), {code: 'PLANNER_HEALTH_FAILED'}); assert.equal(m.running, null);
});

test('cancelling a reuse request preserves the READY server used by existing tabs', async t => {
  const f = await fixture(t), m = owned(t, f);
  const ready = await m.ensureReady(), server = m.running.server;
  const health = m.health.bind(m);
  let checking;
  const checked = new Promise(resolve => { checking = resolve; });
  m.health = signal => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(signal.reason), {once: true}); checking();
  });
  const caller = new AbortController();
  const pending = m.ensureReady({signal: caller.signal});
  await checked; caller.abort();
  await assert.rejects(pending, {code: 'PLANNER_UNAVAILABLE'});
  await m.flight?.promise.catch(() => {});
  assert.equal(m.state, 'READY'); assert.equal(m.running.server, server);
  assert.equal((await fetch(ready.url)).status, 200);
  m.health = health;
  assert.equal((await m.ensureReady()).reused, true);
});

test('issue 187: missing selection provisions once, validates and opens; local reuse stays offline', async t => {
  const f = await fixture(t); await fs.unlink(f.file); let provisions = 0;
  const m = owned(t, {...f, provision: async signal => {signal.throwIfAborted(); provisions++; await f.write();}});
  const ready = await Promise.all([m.ensureReady(), m.ensureReady()]);
  assert(ready.every(r => r.status === 'READY')); assert.equal(provisions, 1);
  assert.equal((await fetch(ready[0].url)).status, 200);
  await m.stopListener(); await m.ensureReady(); assert.equal(provisions, 1);
});

test('issue 187: corrupt local state never downloads a replacement', async t => {
  const f = await fixture(t); await fs.writeFile(f.file, '{}'); let provisions = 0;
  const m = owned(t, {...f, provision: async () => {provisions++;}});
  await assert.rejects(m.ensureReady(), {code: 'PLANNER_SNAPSHOT_UNTRUSTED'});
  assert.equal(provisions, 0);
});

test('issue 187: release lookup errors propagate without starting a server', async t => {
  const f = await fixture(t); await fs.unlink(f.file);
  const m = owned(t, {...f, provision: async () => {throw Object.assign(Error(), {code:'PLANNER_RELEASE_NOT_FOUND'});}});
  await assert.rejects(m.ensureReady(), {code:'PLANNER_RELEASE_NOT_FOUND'}); assert.equal(m.running, null);
});
