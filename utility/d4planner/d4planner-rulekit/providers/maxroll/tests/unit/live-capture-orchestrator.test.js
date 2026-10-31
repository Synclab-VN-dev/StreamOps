'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { ERROR_CODES, MaxrollProviderError } = require('../../src');
const {
  LIVE_CAPTURE_ERROR_CODES,
  MaxrollLiveCaptureOrchestrator,
} = require('../../src/live-capture-orchestrator');
const { MAXROLL_32173552_REFERENCE } = require('../../src/real-profile');

const manifestSha256 = 'b'.repeat(64);

function observation(overrides = {}) {
  return {
    gamePatch: MAXROLL_32173552_REFERENCE.gamePatch,
    breakpointLocations: 1,
    phases: [
      { rawCount: 50, displayCount: 34, outputSha256: '1'.repeat(64) },
      { rawCount: 50, displayCount: 34, outputSha256: '2'.repeat(64) },
      { rawCount: 50, displayCount: 34, outputSha256: '1'.repeat(64) },
    ],
    ...overrides,
  };
}

function acceptance(overrides = {}) {
  return {
    status: 'PASS', rawCoverage: 50, displayCoverage: 34, cycles: 3,
    rollbackExact: true, applicationApis: 8,
    transportOfflineEveryEvaluation: true, externalEgressCompleted: 0,
    cleanup: 'PASS',
    ...overrides,
  };
}

function harness(overrides = {}) {
  let captureInteraction = overrides.captureInteraction ?? (async () => observation());
  const resource = {
    url: `https://maxroll.gg${MAXROLL_32173552_REFERENCE.applicationAssetPath}`,
    sha256: overrides.assetSha256 ?? MAXROLL_32173552_REFERENCE.applicationAssetSha256,
    size: 100,
  };
  const manifest = { resources: overrides.resources ?? [resource] };
  const manager = {
    async capture(options) {
      if (overrides.captureError) throw overrides.captureError;
      const observed = await captureInteraction();
      overrides.observationSink?.(observed);
      await options.interact({ page: {} });
      return {
        resources: [],
        capture: { durationMs: 5, blockedRequestCount: 0 },
      };
    },
    async save() { if (overrides.saveError) throw overrides.saveError; },
    async verify() {
      if (overrides.verifyError) throw overrides.verifyError;
      return { manifestSha256, resourceCount: manifest.resources.length, totalBytes: 100 };
    },
    async load() { return manifest; },
  };
  const browser = {
    starts: 0, stops: 0,
    async start() { this.starts += 1; },
    async stop() { this.stops += 1; },
    async withLease(_options, callback) {
      return callback({ context: { browser: () => ({ version: () => 'Fake Chromium' }) } });
    },
  };
  return {
    browser,
    dependencies: {
      browserFactory: () => browser,
      managerFactory: () => manager,
      captureInteraction: overrides.interactionError
        ? async () => { throw overrides.interactionError; }
        : async () => overrides.observed ?? observation(),
      realTestRunner: async () => overrides.runner ?? {
        exitCode: 0, signal: null, acceptance: acceptance(),
      },
      cleanup: overrides.cleanup ?? (root => fs.rm(root, { recursive: true, force: true })),
    },
  };
}

async function execute(t, overrides = {}) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'mxp-live-test-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const fixture = harness(overrides);
  const orchestrator = new MaxrollLiveCaptureOrchestrator(fixture.dependencies);
  const promise = orchestrator.run({
    packageRoot: root,
    artifactsDir: path.join(root, 'artifacts'),
    temporaryBase: root,
    executablePath: process.execPath,
  });
  return { promise, root, ...fixture };
}

async function rejectsCode(t, overrides, code) {
  const { promise } = await execute(t, overrides);
  await assert.rejects(promise, error => error.code === code && error.report?.cleanup !== 'PENDING');
}

test('CI-REAL-01 orchestrates capture, independent pin validation, offline test and cleanup', async t => {
  const { promise, root, browser } = await execute(t);
  const report = await promise;
  assert.equal(report.status, 'PASS');
  assert.equal(report.capture.resourceCount, 1);
  assert.equal(report.runtime.observedAssetSha256,
    MAXROLL_32173552_REFERENCE.applicationAssetSha256);
  assert.equal(report.offline.rawCoverage, 50);
  assert.equal(report.offline.applicationApis, 8);
  assert.equal(report.cleanup, 'PASS');
  assert.equal(browser.starts, 1);
  assert.equal(browser.stops, 1);
  assert.equal(JSON.parse(await fs.readFile(path.join(root, 'artifacts',
    'live-capture-real.json'))).status, 'PASS');
});

test('CI-REAL-08 classifies unreachable, timeout and cancellation without a real fallback', async t => {
  await rejectsCode(t, { captureError: Object.assign(new Error('net::ERR_NAME_NOT_RESOLVED'), {
    code: 'ERR_NAME_NOT_RESOLVED',
  }) }, LIVE_CAPTURE_ERROR_CODES.SITE_UNREACHABLE);
  await rejectsCode(t, { captureError: Object.assign(new Error('bounded timeout'), {
    code: 'CAPTURE_TIMEOUT',
  }) }, LIVE_CAPTURE_ERROR_CODES.TIMEOUT);
  await rejectsCode(t, { captureError: Object.assign(new Error('cancelled'), {
    code: 'CAPTURE_CANCELLED',
  }) }, LIVE_CAPTURE_ERROR_CODES.CANCELLED);
});

test('CI-REAL-08 rejects missing dynamic runtime, asset hash mismatch and invalid manifest', async t => {
  await rejectsCode(t, { resources: [] }, LIVE_CAPTURE_ERROR_CODES.CAPTURE_INCOMPLETE);
  await rejectsCode(t, { assetSha256: 'c'.repeat(64) },
    LIVE_CAPTURE_ERROR_CODES.ASSET_HASH_MISMATCH);
  await rejectsCode(t, { verifyError: new Error('tampered manifest') },
    LIVE_CAPTURE_ERROR_CODES.MANIFEST_INVALID);
});

test('CI-REAL-08 rejects patch, CDP breakpoint and read-back drift', async t => {
  await rejectsCode(t, { observed: observation({ gamePatch: 'future-patch' }) },
    LIVE_CAPTURE_ERROR_CODES.PATCH_DRIFT);
  await rejectsCode(t, { interactionError: new MaxrollProviderError(
    ERROR_CODES.RUNTIME_MISMATCH, 'breakpoint drift') }, LIVE_CAPTURE_ERROR_CODES.PATCH_DRIFT);
  await rejectsCode(t, { interactionError: new MaxrollProviderError(
    ERROR_CODES.READBACK_MISMATCH, 'read-back drift') },
  LIVE_CAPTURE_ERROR_CODES.CAPTURE_INCOMPLETE);
});

test('CI-REAL-08 rejects incomplete real tests and offline egress evidence', async t => {
  await rejectsCode(t, { runner: {
    exitCode: 1, signal: null, acceptance: acceptance({ status: 'FAIL' }),
  } }, LIVE_CAPTURE_ERROR_CODES.REAL_E2E_FAILED);
  await rejectsCode(t, { runner: {
    exitCode: 0, signal: null,
    acceptance: acceptance({ externalEgressCompleted: 1 }),
  } }, LIVE_CAPTURE_ERROR_CODES.OFFLINE_EGRESS);
});

test('CI-REAL-08 reports cleanup failure instead of leaving a false PASS', async t => {
  await rejectsCode(t, { cleanup: async () => { throw new Error('cleanup failed'); } },
    LIVE_CAPTURE_ERROR_CODES.CLEANUP_FAILED);
});
