'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const {
  ERROR_CODES, METRIC_CATALOG, MaxrollBuildMapper, MaxrollMetricsExtractor,
  MaxrollPatchProfile, MaxrollProvider, MaxrollProviderError, MaxrollSession,
} = require('../../src');
const { BASE_BUILD, MODIFIED_BUILD, createProfile } = require('../helpers/fixtures');
const { makeSessionDependencies } = require('../helpers/fakes');

async function rejectsCode(promise, code) {
  await assert.rejects(promise, error => error instanceof MaxrollProviderError && error.code === code);
}

test('patch profile exposes a pinned, immutable 50-metric bounded capability', () => {
  const profile = createProfile();
  const capability = profile.capability();
  assert.equal(capability.stateModel, 'stateful');
  assert.equal(capability.metricIds.length, 50);
  assert.deepEqual(capability.changeTypes, ['effect.set']);
  assert.equal(capability.restrictions.class, 'Rogue');
  assert.equal(Object.isFrozen(capability), true);
  assert.throws(() => new MaxrollPatchProfile({}), error => error.code === ERROR_CODES.INVALID_CONFIG);
});

test('build mapper produces exact desired state and rejects every unsupported field/change', () => {
  const mapper = new MaxrollBuildMapper(createProfile());
  const a = mapper.map(BASE_BUILD, [], 'maxroll-build/rogue-l50-v1');
  const b = mapper.map(BASE_BUILD, [{ type: 'effect.set', effectId: 'of-dampening', active: true }], 'maxroll-build/rogue-l50-v1');
  assert.deepEqual(a.desired, BASE_BUILD);
  assert.deepEqual(b.desired, MODIFIED_BUILD);
  assert.notEqual(a.fingerprint, b.fingerprint);
  assert.throws(() => mapper.map({ ...BASE_BUILD, skills: {} }, [], 'maxroll-build/rogue-l50-v1'),
    error => error.code === ERROR_CODES.UNSUPPORTED_INPUT);
  assert.throws(() => mapper.map(BASE_BUILD, [{ type: 'skill.setRank' }], 'maxroll-build/rogue-l50-v1'),
    error => error.code === ERROR_CODES.UNSUPPORTED_INPUT);
  assert.throws(() => mapper.map(BASE_BUILD, [], 'future-schema'),
    error => error.code === ERROR_CODES.UNSUPPORTED_INPUT);
});

test('metric extractor returns complete current-phase observations and independent display nulls', async () => {
  const extractor = new MaxrollMetricsExtractor(createProfile());
  const rows = METRIC_CATALOG.map((metric, index) => ({
    id: metric.id, raw: index, display: index < 34 ? String(index) : null,
    unit: null, phase: 7,
  }));
  const cdp = { send: async () => ({ result: { value: { phase: 7, metrics: rows } } }) };
  const result = await extractor.extract(cdp, 7);
  assert.equal(result.length, 50);
  assert.equal(result.filter(metric => metric.displayValue !== null).length, 34);
  assert.equal(result.every(metric => metric.status === 'OBSERVED'), true);
  assert.equal(result[49].displayValue, null);
});

test('metric extractor fail-closes stale, missing, duplicate and unavailable raw captures', async () => {
  const extractor = new MaxrollMetricsExtractor(createProfile());
  const rows = METRIC_CATALOG.map(metric => ({ id: metric.id, raw: 1, display: '1', unit: null, phase: 2 }));
  await rejectsCode(extractor.extract({ send: async () => ({ result: { value: { phase: 1, metrics: rows } } }) }, 2), ERROR_CODES.STALE_METRICS);
  await rejectsCode(extractor.extract({ send: async () => ({ result: { value: { phase: 2, metrics: rows.slice(1) } } }) }, 2), ERROR_CODES.METRICS_INCOMPLETE);
  await rejectsCode(extractor.extract({ send: async () => ({ result: { value: { phase: 2, metrics: [...rows, rows[0]] } } }) }, 2), ERROR_CODES.METRICS_INCOMPLETE);
  const noRaw = structuredClone(rows); noRaw[0].raw = null;
  await rejectsCode(extractor.extract({ send: async () => ({ result: { value: { phase: 2, metrics: noRaw } } }) }, 2), ERROR_CODES.METRICS_INCOMPLETE);
});

test('stateful provider session evaluates A/B/A, checkpoints, restores and closes idempotently', async () => {
  const profile = createProfile();
  const deps = makeSessionDependencies();
  const session = new MaxrollSession({
    ...deps, profile, mapper: new MaxrollBuildMapper(profile), timeoutMs: 50,
  });
  await session.initialize(BASE_BUILD, 'maxroll-build/rogue-l50-v1');
  const checkpoint = await session.checkpoint();
  const b = await session.evaluate({
    build: BASE_BUILD, buildSchemaVersion: 'maxroll-build/rogue-l50-v1',
    changes: [{ type: 'effect.set', effectId: 'of-dampening', active: true }],
  });
  assert.equal(b.metrics.find(metric => metric.id === 'maxroll.heroDetails.446').rawValue, 2822);
  const a = await session.restore(checkpoint);
  assert.equal(a.metrics.find(metric => metric.id === 'maxroll.heroDetails.446').rawValue, 22);
  await session.close(); await session.close();
  assert.equal(deps.controls.releases, 1);
  assert.equal(deps.controls.unmounts, 1);
});

test('evaluation recovery failure invalidates provider session and never returns stale metrics', async () => {
  const profile = createProfile();
  const deps = makeSessionDependencies();
  const session = new MaxrollSession({
    ...deps, profile, mapper: new MaxrollBuildMapper(profile), timeoutMs: 50,
  });
  await session.initialize(BASE_BUILD, 'maxroll-build/rogue-l50-v1');
  deps.controls.failExtract = true;
  deps.controls.failRestore = true;
  await rejectsCode(session.evaluate({
    build: MODIFIED_BUILD, changes: [], buildSchemaVersion: 'maxroll-build/rogue-l50-v1',
  }), ERROR_CODES.SESSION_INVALIDATED);
  await rejectsCode(session.evaluate({
    build: BASE_BUILD, changes: [], buildSchemaVersion: 'maxroll-build/rogue-l50-v1',
  }), ERROR_CODES.SESSION_INVALIDATED);
});

test('hung evaluation times out, invalidates and cleans provider resources', async () => {
  const profile = createProfile();
  const deps = makeSessionDependencies();
  const session = new MaxrollSession({
    ...deps, profile, mapper: new MaxrollBuildMapper(profile), timeoutMs: 10,
  });
  await session.initialize(BASE_BUILD, 'maxroll-build/rogue-l50-v1');
  deps.controls.hangApply = true;
  await rejectsCode(session.evaluate({
    build: MODIFIED_BUILD, changes: [], buildSchemaVersion: 'maxroll-build/rogue-l50-v1',
  }), ERROR_CODES.TIMEOUT);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(deps.controls.releases, 1);
  await rejectsCode(session.evaluate({
    build: BASE_BUILD, changes: [], buildSchemaVersion: 'maxroll-build/rogue-l50-v1',
  }), ERROR_CODES.SESSION_INVALIDATED);
});

test('provider rejects snapshot digest/resource mismatch before acquiring Chromium', async () => {
  let acquires = 0;
  const profile = createProfile();
  const browser = { acquire: async () => { acquires += 1; } };
  const snapshots = {
    verify: async () => ({ manifestSha256: 'c'.repeat(64) }),
    load: async () => ({ snapshotId: profile.snapshotId, sourceUrl: profile.sourceUrl, resources: [] }),
    mount: async () => {},
  };
  const provider = new MaxrollProvider({ browser, snapshots, profile });
  await rejectsCode(provider.createSession({
    snapshotId: profile.snapshotId,
    snapshotManifestSha256: profile.snapshotManifestSha256,
    buildSchemaVersion: profile.supportedBuildSchemaVersion,
    build: BASE_BUILD,
  }), ERROR_CODES.SNAPSHOT_MISMATCH);
  assert.equal(acquires, 0);
});

test('late browser acquisition after create timeout is released and never mounted', async () => {
  const profile = createProfile();
  let resolveAcquire;
  let releases = 0;
  let mounts = 0;
  const lease = { valid: true, release: async () => { releases += 1; } };
  const browser = { acquire: () => new Promise(resolve => { resolveAcquire = resolve; }) };
  const snapshots = {
    verify: async () => ({ manifestSha256: profile.snapshotManifestSha256 }),
    load: async () => ({
      snapshotId: profile.snapshotId, sourceUrl: profile.sourceUrl,
      resources: [{ url: profile.assetUrl, sha256: profile.assetSha256 }],
    }),
    mount: async () => { mounts += 1; },
  };
  const provider = new MaxrollProvider({ browser, snapshots, profile, sessionTimeoutMs: 10 });
  const pending = provider.createSession({
    snapshotId: profile.snapshotId, snapshotManifestSha256: profile.snapshotManifestSha256,
    buildSchemaVersion: profile.supportedBuildSchemaVersion, build: BASE_BUILD, timeoutMs: 10,
  });
  await rejectsCode(pending, ERROR_CODES.TIMEOUT);
  resolveAcquire(lease);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(releases, 1);
  assert.equal(mounts, 0);
});

test('snapshot store failures and expected patch drift are typed before browser use', async () => {
  const profile = createProfile();
  let acquires = 0;
  const browser = { acquire: async () => { acquires += 1; } };
  const snapshots = {
    verify: async () => { throw new Error('corrupt'); }, load: async () => {}, mount: async () => {},
  };
  const provider = new MaxrollProvider({ browser, snapshots, profile });
  const base = {
    snapshotId: profile.snapshotId, snapshotManifestSha256: profile.snapshotManifestSha256,
    buildSchemaVersion: profile.supportedBuildSchemaVersion, build: BASE_BUILD,
  };
  await rejectsCode(provider.createSession(base), ERROR_CODES.SNAPSHOT_MISMATCH);
  await rejectsCode(provider.createSession({ ...base, expectedGamePatch: 'future-patch' }), ERROR_CODES.RUNTIME_MISMATCH);
  assert.equal(acquires, 0);
});

test('close attempts lease release even when unmount cleanup fails', async () => {
  const profile = createProfile();
  const deps = makeSessionDependencies();
  deps.mount.unmount = async () => { deps.controls.unmounts += 1; throw new Error('unmount'); };
  const session = new MaxrollSession({
    ...deps, profile, mapper: new MaxrollBuildMapper(profile), timeoutMs: 50,
  });
  await session.initialize(BASE_BUILD, 'maxroll-build/rogue-l50-v1');
  await rejectsCode(session.close(), ERROR_CODES.CLEANUP_FAILED);
  assert.equal(deps.controls.releases, 1);
});
