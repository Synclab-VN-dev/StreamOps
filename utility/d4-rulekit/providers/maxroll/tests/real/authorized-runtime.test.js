'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const { after } = test;
const {
  BrowserInfrastructure,
  FileSystemSnapshotStore,
  WebSnapshotManager,
} = require('@streamops/browser-infrastructure');
const {
  CONTRACT_VERSION,
  D4RuleKitApplication,
  ERROR_CODES: APPLICATION_ERROR_CODES,
} = require('../../../../application/src');
const {
  METRIC_CATALOG,
  MaxrollProvider,
  REAL_MAXROLL_COMPONENT_FACTORY,
  createMaxroll32173552D12aM6KTCandidateProfile,
  createMaxroll32173552RealProfile,
} = require('../../src');
const {
  NetworkEgressProbe,
  cleanupOwnedRuntime,
  throwAfterCleanup,
} = require('../helpers/adapter-acceptance');
const { BASE_BUILD } = require('../helpers/fixtures');

const acceptancePath = path.resolve(__dirname, '../../artifacts/real-acceptance.json');
const acceptance = {
  schemaVersion: 'maxroll-real-acceptance/2',
  status: 'FAIL',
  profileId: null,
  rawCoverage: 0,
  displayCoverage: 0,
  cycles: 0,
  rollbackExact: false,
  crossCycleConsistency: false,
  phaseFreshness: false,
  phaseOutputSha256: [],
  fireResistance: [],
  transportOfflineEveryEvaluation: false,
  networkEvidence: {},
  blockedOfflineRequests: {},
  applicationApis: [],
  applicationRevisionFlow: [],
  negativeApplicationChecks: 0,
  cleanup: {},
};

after(() => {
  const networkPass = Object.values(acceptance.networkEvidence).length === 2 &&
    Object.values(acceptance.networkEvidence).every(value =>
      value.source === 'CDP.Network' && value.requestAttempts > 0 &&
      value.externalEgressCompleted === 0 && value.webSocketHandshakes === 0);
  const cleanupPass = Object.values(acceptance.cleanup).length === 2 &&
    Object.values(acceptance.cleanup).every(value => value.status === 'PASS');
  acceptance.status = acceptance.profileId === 'd12am6kt-candidate' &&
    acceptance.cycles === 3 && acceptance.rollbackExact &&
    acceptance.crossCycleConsistency && acceptance.phaseFreshness &&
    acceptance.rawCoverage === 50 && acceptance.displayCoverage === 34 &&
    acceptance.transportOfflineEveryEvaluation && networkPass &&
    acceptance.applicationApis.length === 8 && acceptance.negativeApplicationChecks >= 3 &&
    cleanupPass ? 'PASS' : 'FAIL';
  fs.mkdirSync(path.dirname(acceptancePath), { recursive: true });
  fs.writeFileSync(acceptancePath, `${JSON.stringify(acceptance, null, 2)}\n`);
});

const REQUIRED_ENV = [
  'BROWSER_INFRA_CHROMIUM_PATH',
  'MAXROLL_AUTHORIZED_SNAPSHOT_ROOT',
  'MAXROLL_AUTHORIZED_SNAPSHOT_ID',
  'MAXROLL_AUTHORIZED_MANIFEST_SHA256',
  'MAXROLL_SNAPSHOT_AUTHORIZATION_REF',
  'MAXROLL_SOURCE_URL',
  'MAXROLL_REAL_PROFILE_ID',
];

const PROFILE_FACTORIES = Object.freeze({
  'dojdl1l3-historical': createMaxroll32173552RealProfile,
  'd12am6kt-candidate': createMaxroll32173552D12aM6KTCandidateProfile,
});

function requireAuthorizedEnvironment() {
  const missing = REQUIRED_ENV.filter(name => !process.env[name]);
  if (missing.length) {
    throw new Error(`BLOCKED_AUTHORIZED_SNAPSHOT: missing ${missing.join(', ')}`);
  }
  if (!/^[a-f0-9]{64}$/i.test(process.env.MAXROLL_AUTHORIZED_MANIFEST_SHA256)) {
    throw new Error('BLOCKED_AUTHORIZED_SNAPSHOT: manifest trust anchor must be SHA-256');
  }
  if (!PROFILE_FACTORIES[process.env.MAXROLL_REAL_PROFILE_ID]) {
    throw new Error('RUNTIME_MISMATCH: MAXROLL_REAL_PROFILE_ID is not a known exact asset profile');
  }
}

function sessionOptions(profile) {
  return {
    contractVersion: CONTRACT_VERSION,
    providerVersion: profile.providerVersion,
    expectedGamePatch: profile.gamePatch,
    snapshotId: profile.snapshotId,
    snapshotManifestSha256: profile.snapshotManifestSha256,
    buildSchemaVersion: profile.supportedBuildSchemaVersion,
    build: BASE_BUILD,
  };
}

function raw(metrics) { return metrics.map(metric => metric.rawValue); }
function digest(values) {
  return crypto.createHash('sha256').update(JSON.stringify(values)).digest('hex');
}
function fire(metrics) {
  return metrics.find(metric => metric.id === 'maxroll.heroDetails.446')?.rawValue;
}
function assertMetrics(result) {
  assert.equal(result.metrics.length, 50);
  assert.equal(new Set(result.metrics.map(metric => metric.id)).size, 50);
  assert.equal(result.metrics.every(metric => Number.isFinite(metric.rawValue)), true);
  assert.equal(result.metrics.filter(metric => metric.displayValue !== null).length, 34);
  const providerProvenance = typeof result.provenance.provider === 'object'
    ? result.provenance.provider : result.provenance;
  assert.equal(providerProvenance.networkReplay.transportOffline, true);
}

async function fixture() {
  requireAuthorizedEnvironment();
  const browser = new BrowserInfrastructure({
    executablePath: process.env.BROWSER_INFRA_CHROMIUM_PATH,
    headless: true,
    maxContexts: 1,
    maxQueue: 1,
    contextOptions: { serviceWorkers: 'block' },
  });
  await browser.start();
  const resources = {
    lease: null, mount: null, networkProbe: null,
    ownedPid: browser.getStatus().pid,
  };
  const snapshots = new WebSnapshotManager({
    browser,
    store: new FileSystemSnapshotStore({ rootDir: process.env.MAXROLL_AUTHORIZED_SNAPSHOT_ROOT }),
  });
  const providerBrowser = {
    acquire: async options => {
      const lease = await browser.acquire(options);
      resources.lease = lease;
      try {
        resources.networkProbe = await NetworkEgressProbe.attach(lease);
      } catch (error) {
        await lease.release();
        throw error;
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
  const profileFactory = PROFILE_FACTORIES[process.env.MAXROLL_REAL_PROFILE_ID];
  const profile = profileFactory({
    snapshotId: process.env.MAXROLL_AUTHORIZED_SNAPSHOT_ID,
    snapshotManifestSha256: process.env.MAXROLL_AUTHORIZED_MANIFEST_SHA256,
    sourceUrl: process.env.MAXROLL_SOURCE_URL,
    authorizationRef: process.env.MAXROLL_SNAPSHOT_AUTHORIZATION_REF,
    metricCatalog: METRIC_CATALOG,
  });
  acceptance.profileId = process.env.MAXROLL_REAL_PROFILE_ID;
  return {
    browser,
    resources,
    profile,
    provider: new MaxrollProvider({
      browser: providerBrowser,
      snapshots: observedSnapshots,
      profile,
      componentFactory: REAL_MAXROLL_COMPONENT_FACTORY,
      sessionTimeoutMs: 90_000,
    }),
  };
}

async function cleanupFixture(label, runtime, session) {
  const cleanup = await cleanupOwnedRuntime({ session, browser: runtime.browser, ...runtime.resources });
  acceptance.cleanup[label] = { status: 'PASS', ...cleanup };
}

test('MXP-09 authorized candidate runtime preserves three exact A→B→A cycles', {
  timeout: 150_000,
}, async () => {
  const runtime = await fixture();
  let session;
  let primaryError = null;
  let cleanupError = null;
  try {
    session = await runtime.provider.createSession(sessionOptions(runtime.profile));
    const checkpoint = await session.checkpoint();
    let canonicalA = null;
    let canonicalB = null;
    const phases = [];
    let finalReplay;
    for (let cycle = 0; cycle < 3; cycle += 1) {
      const a = await session.evaluate({
        build: BASE_BUILD,
        buildSchemaVersion: runtime.profile.supportedBuildSchemaVersion,
      });
      const b = await session.evaluate({
        build: BASE_BUILD,
        changes: [{ type: 'effect.set', effectId: 'of-dampening', active: true }],
        buildSchemaVersion: runtime.profile.supportedBuildSchemaVersion,
      });
      const a2 = await session.restore(checkpoint);
      for (const result of [a, b, a2]) assertMetrics(result);
      assert.equal(fire(a.metrics), 22);
      assert.equal(fire(b.metrics), 2822);
      assert.equal(fire(a2.metrics), 22);
      assert.deepEqual(raw(a2.metrics), raw(a.metrics));
      assert.notEqual(a.provenance.inputFingerprint, b.provenance.inputFingerprint);
      assert.equal(a2.provenance.inputFingerprint, a.provenance.inputFingerprint);
      canonicalA ??= raw(a.metrics);
      canonicalB ??= raw(b.metrics);
      assert.deepEqual(raw(a.metrics), canonicalA);
      assert.deepEqual(raw(a2.metrics), canonicalA);
      assert.deepEqual(raw(b.metrics), canonicalB);
      phases.push(a.provenance.phase, b.provenance.phase, a2.provenance.phase);
      finalReplay = a2.provenance.networkReplay;
      acceptance.cycles = cycle + 1;
      acceptance.fireResistance.push({ cycle: cycle + 1, a: 22, b: 2822, a2: 22 });
      acceptance.phaseOutputSha256.push({
        cycle: cycle + 1,
        a: digest(raw(a.metrics)), b: digest(raw(b.metrics)), a2: digest(raw(a2.metrics)),
      });
    }
    assert.equal(new Set(phases).size, 9);
    assert.deepEqual(phases, [...phases].sort((left, right) => left - right));
    acceptance.rawCoverage = 50;
    acceptance.displayCoverage = 34;
    acceptance.rollbackExact = true;
    acceptance.crossCycleConsistency = true;
    acceptance.phaseFreshness = true;
    acceptance.transportOfflineEveryEvaluation = true;
    acceptance.blockedOfflineRequests.mxp09 = finalReplay.aborted;
    acceptance.networkEvidence.mxp09 = runtime.resources.networkProbe.getDiagnostics();
    assert.equal(acceptance.networkEvidence.mxp09.requestAttempts > 0, true);
    assert.equal(acceptance.networkEvidence.mxp09.externalEgressCompleted, 0);
    assert.equal(acceptance.networkEvidence.mxp09.webSocketHandshakes, 0);
  } catch (error) {
    primaryError = error;
  } finally {
    try {
      await cleanupFixture('mxp09', runtime, session);
    } catch (error) {
      cleanupError = error;
      acceptance.cleanup.mxp09 = { status: 'FAIL', error: error.name };
    }
  }
  throwAfterCleanup(primaryError, cleanupError);
});

test('MXP-10 and APP-07 exercise all eight APIs through the authorized real provider', {
  timeout: 150_000,
}, async () => {
  const runtime = await fixture();
  const application = new D4RuleKitApplication({
    providers: [runtime.provider], operationTimeoutMs: 90_000, cleanupTimeoutMs: 15_000,
  });
  let sessionId = null;
  let primaryError = null;
  let cleanupError = null;
  try {
    const listed = application.listProviders();
    assert.deepEqual(listed.map(value => value.id), ['maxroll']);
    assert.equal(listed[0].version, runtime.profile.providerVersion);
    acceptance.applicationApis.push('listProviders');

    const created = await application.createSession({
      ...sessionOptions(runtime.profile), providerId: 'maxroll',
    });
    sessionId = created.sessionId;
    assert.equal(created.revision, 0);
    assert.equal(created.snapshotManifestSha256, runtime.profile.snapshotManifestSha256);
    acceptance.applicationApis.push('createSession');

    const a = await application.evaluate(sessionId, { bypassCache: true });
    assertMetrics(a);
    assert.equal(fire(a.metrics), 22);
    acceptance.applicationApis.push('evaluate');

    const change = [{ type: 'effect.set', effectId: 'of-dampening', active: true }];
    const preview = await application.previewChanges(sessionId, {
      expectedRevision: 0, changes: change,
    });
    assert.equal(fire(preview.before), 22);
    assert.equal(fire(preview.after), 2822);
    assert.notEqual(preview.baseBuildFingerprint, preview.candidateBuildFingerprint);
    assert.equal(application.getSession(sessionId).revision, 0);
    assert.equal(fire((await application.evaluate(sessionId, { bypassCache: true })).metrics), 22);
    acceptance.applicationApis.push('previewChanges');

    await assert.rejects(() => application.commitChanges(sessionId, {
      expectedRevision: 1, changes: change, previewToken: preview.previewToken,
    }), error => error.code === APPLICATION_ERROR_CODES.REVISION_CONFLICT);
    await assert.rejects(() => application.commitChanges(sessionId, {
      expectedRevision: 0, changes: change, previewToken: `${preview.previewToken}-stale`,
    }), error => error.code === APPLICATION_ERROR_CODES.STALE_PREVIEW);
    await assert.rejects(() => application.previewChanges(sessionId, {
      expectedRevision: 0, changes: [{ type: 'unsupported.real.input' }],
    }), error => error.code === APPLICATION_ERROR_CODES.UNSUPPORTED_CHANGE);
    acceptance.negativeApplicationChecks = 3;

    const committed = await application.commitChanges(sessionId, {
      expectedRevision: 0, changes: change, previewToken: preview.previewToken,
    });
    assert.equal(committed.session.revision, 1);
    assert.equal(fire(committed.result.metrics), 2822);
    assert.equal(fire((await application.evaluate(sessionId, { bypassCache: true })).metrics), 2822);
    acceptance.applicationApis.push('commitChanges');
    acceptance.applicationRevisionFlow.push(0, 1);

    const reset = await application.resetSession(sessionId, { expectedRevision: 1 });
    assert.equal(reset.revision, 2);
    const restored = await application.evaluate(sessionId, { bypassCache: true });
    assert.deepEqual(raw(restored.metrics), raw(a.metrics));
    acceptance.applicationApis.push('resetSession');
    acceptance.applicationRevisionFlow.push(2);

    const metadata = application.getSession(sessionId);
    assert.equal(metadata.revision, 2);
    assert.equal(metadata.providerVersion, runtime.profile.providerVersion);
    assert.equal(metadata.snapshotManifestSha256, runtime.profile.snapshotManifestSha256);
    acceptance.applicationApis.push('getSession');

    acceptance.blockedOfflineRequests.app07 =
      restored.provenance.provider.networkReplay.aborted;
    acceptance.networkEvidence.app07 = runtime.resources.networkProbe.getDiagnostics();
    assert.equal(acceptance.networkEvidence.app07.requestAttempts > 0, true);
    assert.equal(acceptance.networkEvidence.app07.externalEgressCompleted, 0);
    assert.equal(acceptance.networkEvidence.app07.webSocketHandshakes, 0);
    await runtime.resources.networkProbe.close();

    const closed = await application.closeSession(sessionId);
    const closedAgain = await application.closeSession(sessionId);
    assert.equal(closed.closed, true);
    assert.equal(closed.alreadyClosed, false);
    assert.equal(closedAgain.closed, true);
    assert.equal(closedAgain.alreadyClosed, true);
    acceptance.applicationApis.push('closeSession');
  } catch (error) {
    primaryError = error;
  } finally {
    const applicationSession = sessionId
      ? { close: () => application.closeSession(sessionId) } : null;
    try {
      await cleanupFixture('app07', runtime, applicationSession);
    } catch (error) {
      cleanupError = error;
      acceptance.cleanup.app07 = { status: 'FAIL', error: error.name };
    }
  }
  throwAfterCleanup(primaryError, cleanupError);
});
