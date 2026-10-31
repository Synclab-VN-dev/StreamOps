'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const {
  BrowserInfrastructure,
  FileSystemSnapshotStore,
  WebSnapshotManager,
} = require('@streamops/browser-infrastructure');
const {
  ERROR_CODES,
  METRIC_CATALOG,
  MaxrollProvider,
  REAL_MAXROLL_COMPONENT_FACTORY,
  createMaxroll32173552D12aM6KTCandidateProfile,
} = require('../../src');
const {
  NetworkEgressProbe,
  cleanupOwnedRuntime,
  throwAfterCleanup,
} = require('../helpers/adapter-acceptance');
const { BASE_BUILD } = require('../helpers/fixtures');

const MANIFEST_SHA = '638a283b8aa0cb822a35176d9d41c8d1751fb6f962ca0a2f7feaa20f1ef39e54';
const SNAPSHOT_ID = 'maxroll-20261023T034150Z';
const SOURCE_URL = 'https://maxroll.gg/d4/planner/1g1any0x';
const artifactPath = path.resolve(__dirname, '../../artifacts/adapter-real-acceptance.json');

function requiredEnvironment() {
  const executablePath = process.env.BROWSER_INFRA_CHROMIUM_PATH;
  const rootDir = process.env.MAXROLL_AUTHORIZED_SNAPSHOT_ROOT;
  if (!executablePath || !rootDir) {
    throw new Error('BROWSER_INFRA_CHROMIUM_PATH and MAXROLL_AUTHORIZED_SNAPSHOT_ROOT are required');
  }
  return { executablePath, rootDir };
}

function options(profile) {
  return {
    providerVersion: profile.providerVersion,
    expectedGamePatch: profile.gamePatch,
    snapshotId: SNAPSHOT_ID,
    snapshotManifestSha256: MANIFEST_SHA,
    buildSchemaVersion: profile.supportedBuildSchemaVersion,
    build: BASE_BUILD,
  };
}

function createProfile(overrides = {}) {
  return createMaxroll32173552D12aM6KTCandidateProfile({
    snapshotId: SNAPSHOT_ID,
    snapshotManifestSha256: MANIFEST_SHA,
    sourceUrl: SOURCE_URL,
    authorizationRef: 'StreamOps#132-owner-directive-2026-10-23',
    metricCatalog: METRIC_CATALOG,
    ...overrides,
  });
}

async function fixture(profile, { observeNetwork = true } = {}) {
  const { executablePath, rootDir } = requiredEnvironment();
  const browser = new BrowserInfrastructure({
    executablePath, headless: true, maxContexts: 1, maxQueue: 1,
    contextOptions: { serviceWorkers: 'block' },
  });
  await browser.start();
  const resources = {
    lease: null, mount: null, networkProbe: null,
    ownedPid: browser.getStatus().pid,
  };
  const snapshots = new WebSnapshotManager({
    browser, store: new FileSystemSnapshotStore({ rootDir }),
  });
  const providerBrowser = {
    acquire: async options => {
      const lease = await browser.acquire(options);
      resources.lease = lease;
      if (observeNetwork) {
        try {
          resources.networkProbe = await NetworkEgressProbe.attach(lease);
        } catch (error) {
          await lease.release();
          throw error;
        }
      }
      return lease;
    },
  };
  const observedSnapshots = {
    verify: snapshotId => snapshots.verify(snapshotId),
    load: snapshotId => snapshots.load(snapshotId),
    mount: async (...args) => {
      resources.mount = await snapshots.mount(...args);
      return resources.mount;
    },
  };
  return {
    browser,
    resources,
    provider: new MaxrollProvider({
      browser: providerBrowser, snapshots: observedSnapshots, profile,
      componentFactory: REAL_MAXROLL_COMPONENT_FACTORY,
      sessionTimeoutMs: 30_000,
    }),
  };
}

function raw(metrics) { return metrics.map(metric => metric.rawValue); }
function fire(metrics) {
  return metrics.find(metric => metric.id === 'maxroll.heroDetails.446')?.rawValue;
}

test('ADP-01..12 candidate adapter performs one exact offline A→B→A cycle', {
  timeout: 90_000,
}, async () => {
  const report = {
    schemaVersion: 'maxroll-adapter-real-acceptance/1', status: 'FAIL',
    manifestSha256: MANIFEST_SHA, rawCoverage: 0, displayCoverage: 0,
    phases: 0, rollbackExact: false, externalEgressCompleted: null,
    blockedOfflineRequests: null, networkEvidence: null,
    cleanup: { status: 'UNVERIFIED' },
  };
  const profile = createProfile();
  const { browser, provider, resources } = await fixture(profile);
  let session;
  let primaryError = null;
  let cleanupError = null;
  try {
    session = await provider.createSession(options(profile));
    const checkpoint = await session.checkpoint();
    const a = await session.evaluate({
      build: BASE_BUILD, buildSchemaVersion: profile.supportedBuildSchemaVersion,
    });
    const b = await session.evaluate({
      build: BASE_BUILD,
      changes: [{ type: 'effect.set', effectId: 'of-dampening', active: true }],
      buildSchemaVersion: profile.supportedBuildSchemaVersion,
    });
    const a2 = await session.restore(checkpoint);
    for (const result of [a, b, a2]) {
      assert.equal(result.metrics.length, 50);
      assert.equal(new Set(result.metrics.map(metric => metric.id)).size, 50);
      assert.equal(result.metrics.every(metric => Number.isFinite(metric.rawValue)), true);
      assert.equal(result.metrics.filter(metric => metric.displayValue !== null).length, 34);
      assert.equal(result.provenance.networkReplay.transportOffline, true);
    }
    assert.equal(fire(a.metrics), 22);
    assert.equal(fire(b.metrics), 2822);
    assert.deepEqual(raw(a2.metrics), raw(a.metrics));
    assert.notEqual(a.provenance.inputFingerprint, b.provenance.inputFingerprint);
    assert.equal(a2.provenance.inputFingerprint, a.provenance.inputFingerprint);
    assert.deepEqual([a.provenance.phase, b.provenance.phase, a2.provenance.phase], [2, 3, 4]);
    report.rawCoverage = 50;
    report.displayCoverage = 34;
    report.phases = 3;
    report.rollbackExact = true;
    report.blockedOfflineRequests = a2.provenance.networkReplay.aborted;
    report.networkEvidence = resources.networkProbe.getDiagnostics();
    report.externalEgressCompleted = report.networkEvidence.externalEgressCompleted;
    assert.equal(report.networkEvidence.source, 'CDP.Network');
    assert.equal(report.networkEvidence.requestAttempts > 0, true);
    assert.equal(report.networkEvidence.responseEvents > 0, true);
    assert.equal(report.networkEvidence.externalEgressCompleted, 0);
    assert.equal(report.networkEvidence.webSocketHandshakes, 0);
    report.status = 'PASS';
  } catch (error) {
    primaryError = error;
  } finally {
    try {
      report.cleanup = {
        status: 'PASS',
        ...await cleanupOwnedRuntime({ session, browser, ...resources }),
      };
    } catch (error) {
      cleanupError = error;
      report.cleanup = { status: 'FAIL', error: error.name };
      report.status = 'FAIL';
    }
    fs.mkdirSync(path.dirname(artifactPath), { recursive: true });
    fs.writeFileSync(artifactPath, `${JSON.stringify(report, null, 2)}\n`);
  }
  throwAfterCleanup(primaryError, cleanupError);
  assert.equal(report.status, 'PASS');
});

test('candidate adapter fails closed on breakpoint and DOM strategy drift', {
  timeout: 30_000,
}, async () => {
  const badBreakpoint = createProfile({
    realRuntime: { breakpoint: { lineNumber: 999_999, columnNumber: 0 } },
  });
  let runtime = await fixture(badBreakpoint, { observeNetwork: false });
  try {
    await assert.rejects(() => runtime.provider.createSession(options(badBreakpoint)),
      error => error.code === ERROR_CODES.RUNTIME_MISMATCH);
  } finally {
    await runtime.browser.stop();
    assert.equal(runtime.browser.getStatus().state, 'stopped');
    assert.equal(runtime.browser.getMetrics().currentContexts, 0);
  }

  const badDom = createProfile({
    realRuntime: { slotItemSelector: '[data-missing-slot]', interactionTimeoutMs: 300 },
  });
  runtime = await fixture(badDom, { observeNetwork: false });
  try {
    await assert.rejects(() => runtime.provider.createSession(options(badDom)),
      error => error.code === ERROR_CODES.RUNTIME_NOT_READY);
  } finally {
    await runtime.browser.stop();
    assert.equal(runtime.browser.getStatus().state, 'stopped');
    assert.equal(runtime.browser.getMetrics().currentContexts, 0);
  }

  const wrongItemIdentity = createProfile({
    realRuntime: { slotItemNameSelector: '[class*="Slot__info"]' },
  });
  runtime = await fixture(wrongItemIdentity, { observeNetwork: false });
  try {
    await assert.rejects(() => runtime.provider.createSession(options(wrongItemIdentity)),
      error => error.code === ERROR_CODES.READBACK_MISMATCH);
  } finally {
    await runtime.browser.stop();
    assert.equal(runtime.browser.getStatus().state, 'stopped');
    assert.equal(runtime.browser.getMetrics().currentContexts, 0);
  }
});
