'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const {
  ERROR_CODES,
  METRIC_CATALOG,
  MAXROLL_32173552_D12AM6KT_REFERENCE,
  MAXROLL_32173552_REFERENCE,
  MaxrollProvider,
  MaxrollBuildMapper,
  MaxrollSession,
  REAL_MAXROLL_COMPONENT_FACTORY,
  RealMaxrollMetricsExtractor,
  RealMaxrollRuntimeAdapter,
  createMaxroll32173552D12aM6KTCandidateProfile,
  createMaxroll32173552RealProfile,
} = require('../../src');
const { BASE_BUILD, MODIFIED_BUILD } = require('../helpers/fixtures');
const { sha256 } = require('../../src/value');

function createRealProfile(overrides = {}) {
  return createMaxroll32173552RealProfile({
    snapshotId: 'authorized-maxroll-3-2-1',
    snapshotManifestSha256: 'a'.repeat(64),
    sourceUrl: 'https://maxroll.gg/d4/planner/1g1any0x#3',
    authorizationRef: 'owner-approved-test-fixture',
    metricCatalog: METRIC_CATALOG,
    ...overrides,
  });
}

class FakeCdp {
  constructor({
    breakpointLocations = [{}], failEvaluateOnce = false, failResumeOnce = false,
  } = {}) {
    this.breakpointLocations = breakpointLocations;
    this.failEvaluateOnce = failEvaluateOnce;
    this.failResumeOnce = failResumeOnce;
  }
  handlers = new Map();
  modifierActive = false;
  evaluateAttempts = 0;
  resumeAttempts = 0;

  on(name, handler) { this.handlers.set(name, handler); }

  async send(method, params) {
    if (method === 'Debugger.setBreakpointByUrl') return { locations: this.breakpointLocations };
    if (method === 'Debugger.evaluateOnCallFrame') {
      this.evaluateAttempts += 1;
      if (this.failEvaluateOnce) {
        this.failEvaluateOnce = false;
        throw new Error('evaluateOnCallFrame disconnected');
      }
      const internalId = Number(params.callFrameId);
      return { result: { value: {
        id: internalId,
        raw: internalId === 446 ? (this.modifierActive ? 2822 : 22) : internalId,
      } } };
    }
    if (method === 'Debugger.resume') {
      this.resumeAttempts += 1;
      if (this.failResumeOnce) {
        this.failResumeOnce = false;
        throw new Error('resume disconnected');
      }
      return {};
    }
    return {};
  }

  emitMetrics() {
    for (const metric of METRIC_CATALOG) {
      this.handlers.get('Debugger.paused')?.({
        callFrames: [{ callFrameId: String(metric.internalId) }],
      });
    }
  }

  emitDisconnect() {
    this.handlers.get('close')?.();
  }
}

class FakeLocator {
  constructor(actions = {}) { this.actions = actions; }
  first() { return this; }
  async waitFor() {}
  async fill(value) { this.actions.fill?.(value); }
  async press(value) { this.actions.press?.(value); }
  async click() { this.actions.click?.(); }
  async evaluate(callback) {
    callback({ parentElement: { querySelector: () => ({ click: () => this.actions.click?.() }) } });
  }
  async count() { return this.actions.count ?? 1; }
  async isVisible() { return this.actions.visible ?? true; }
}

function createFakeLease({
  breakpointLocations, optionCount = 1, reportedModifierCount,
  failEvaluateOnce = false, failResumeOnce = false, emitOnItemClick = true,
} = {}) {
  const cdp = new FakeCdp({ breakpointLocations, failEvaluateOnce, failResumeOnce });
  const state = { level: 1, itemPresent: false, modifierActive: false };
  let emitMetricsOnItemClick = emitOnItemClick;
  const page = {
    async goto() {},
    async waitForFunction() {},
    getByRole(_role, options) {
      if (options.name === 'No Thanks') return new FakeLocator({ count: 0, visible: false });
      return new FakeLocator({ click: () => {
        state.level = 1;
        state.itemPresent = false;
        state.modifierActive = false;
        cdp.modifierActive = false;
      } });
    },
    locator() {
      return new FakeLocator({ fill: value => { state.level = Number(value); } });
    },
    getByText(text) {
      if (text === 'Helm') return new FakeLocator();
      if (text === 'Runic Skullcap') return new FakeLocator({ click: () => {
        state.itemPresent = true;
        if (emitMetricsOnItemClick) cdp.emitMetrics();
      } });
      if (text === 'Add Modifier') return new FakeLocator();
      if (text === 'Dampening / Of Dampening') return new FakeLocator({ count: optionCount, click: () => {
        state.modifierActive = true;
        cdp.modifierActive = true;
        if (emitMetricsOnItemClick) cdp.emitMetrics();
      } });
      return new FakeLocator({ count: 0, visible: false });
    },
    async evaluate(_callback, argument) {
      if (argument.patchPattern) {
        return { gamePatch: '3.2.1.73552', assetMatched: true };
      }
      const displays = {};
      for (const metric of METRIC_CATALOG.slice(0, 34)) {
        const value = metric.internalId === 446 && state.modifierActive ? 2822 :
          metric.internalId === 446 ? 22 : metric.internalId;
        displays[`${metric.category}|${metric.name}`] = String(value);
      }
      return {
        class: 'Rogue', level: state.level, difficulty: 'Torment I',
        legacyItemPresent: state.itemPresent, slotCount: 0, itemNames: [],
        modifierPresent: state.modifierActive,
        modifierCount: reportedModifierCount ?? (state.modifierActive ? 1 : 0), displays,
      };
    },
  };
  return {
    valid: true,
    cdp,
    page,
    setEmitOnItemClick(value) { emitMetricsOnItemClick = value; },
    createCDPSession: async () => cdp,
    release: async () => {},
  };
}

test('real 3.2.1 profile pins historical runtime identity and selects injected components', () => {
  const profile = createRealProfile();
  assert.equal(profile.runtimeKind, 'maxroll-ui-cdp-v1');
  assert.equal(profile.assetSha256, MAXROLL_32173552_REFERENCE.applicationAssetSha256);
  assert.equal(profile.capability().restrictions.runtimeKind, 'maxroll-ui-cdp-v1');
  assert.equal(REAL_MAXROLL_COMPONENT_FACTORY.createRuntimeAdapter({
    lease: createFakeLease(), profile,
  }) instanceof RealMaxrollRuntimeAdapter, true);
  assert.equal(REAL_MAXROLL_COMPONENT_FACTORY.createMetricsExtractor(profile)
    instanceof RealMaxrollMetricsExtractor, true);
});

test('D12aM6KT candidate pins asset identity and version-specific UI semantics', () => {
  const profile = createMaxroll32173552D12aM6KTCandidateProfile({
    snapshotId: 'maxroll-20261023T034150Z',
    snapshotManifestSha256: 'a'.repeat(64),
    sourceUrl: 'https://maxroll.gg/d4/planner/1g1any0x',
    authorizationRef: 'StreamOps#132-owner-directive-2026-10-23',
    metricCatalog: METRIC_CATALOG,
  });
  assert.equal(profile.assetSha256,
    MAXROLL_32173552_D12AM6KT_REFERENCE.applicationAssetSha256);
  assert.match(profile.runtimeVersion, /candidate/);
  assert.equal(profile.realRuntime.requireLevelResetTransition, false);
  assert.equal(profile.realRuntime.slotItemSelector, '[class*="equipment_slot-4"]');
  assert.equal(profile.realRuntime.slotItemNameSelector, '[class*="Slot__title"]');
  assert.equal(profile.realRuntime.itemEditorSelector, '.d4t-ItemEditor');
  assert.equal(profile.realRuntime.discardChangesDialogSelector, '[class*="_Dialog_"]');
  assert.equal(profile.realRuntime.discardChangesConfirmButton, 'Yes');
});

test('real profile rejects incomplete CDP/UI protocol configuration', () => {
  assert.throws(() => createRealProfile({ realRuntime: { captureExpression: '' } }),
    error => error.code === ERROR_CODES.INVALID_CONFIG);
  assert.throws(() => createMaxroll32173552RealProfile({
    snapshotId: 'authorized-maxroll-3-2-1',
    snapshotManifestSha256: 'a'.repeat(64),
    sourceUrl: 'https://maxroll.gg/d4/planner/1g1any0x#3',
    metricCatalog: METRIC_CATALOG,
  }), error => error.code === ERROR_CODES.INVALID_CONFIG);
});

test('provider rejects a real profile paired with the synthetic component factory', () => {
  assert.throws(() => new MaxrollProvider({
    browser: { acquire: async () => {} },
    snapshots: { verify() {}, load() {}, mount() {} },
    profile: createRealProfile(),
  }), error => error.code === ERROR_CODES.INVALID_CONFIG);
});

test('MXP-R3-04 successful capture preserves 50 raw, 34 display and single-use freshness', async () => {
  const profile = createRealProfile();
  const adapter = new RealMaxrollRuntimeAdapter({ lease: createFakeLease(), profile });
  const extractor = new RealMaxrollMetricsExtractor(profile);
  const identity = await adapter.initialize();
  assert.equal(identity.gamePatch, '3.2.1.73552');
  assert.equal(identity.breakpointLocations, 1);

  const appliedA = await adapter.apply(BASE_BUILD, sha256(BASE_BUILD));
  const metricsA = await extractor.extract(adapter, appliedA);
  assert.equal(metricsA.length, 50);
  assert.equal(metricsA.filter(metric => metric.displayValue !== null).length, 34);
  assert.equal(metricsA.find(metric => metric.id === 'maxroll.heroDetails.446').rawValue, 22);
  await assert.rejects(() => extractor.extract(adapter, appliedA),
    error => error.code === ERROR_CODES.STALE_METRICS);

  const appliedB = await adapter.apply(MODIFIED_BUILD, sha256(MODIFIED_BUILD));
  const metricsB = await extractor.extract(adapter, appliedB);
  assert.equal(metricsB.find(metric => metric.id === 'maxroll.heroDetails.446').rawValue, 2822);
});

test('real extractor rejects invalid runtime raw values instead of fabricating zero', async () => {
  const profile = createRealProfile();
  const extractor = new RealMaxrollMetricsExtractor(profile);
  const raw = METRIC_CATALOG.map(metric => ({
    internalId: metric.internalId,
    rawValue: metric.internalId === 446 ? Number.NaN : metric.internalId,
  }));
  const adapter = { takeCapture: () => ({ phase: 1, raw, displays: {} }) };
  await assert.rejects(() => extractor.extract(adapter, { phase: 1, inputFingerprint: 'x' }),
    error => error.code === ERROR_CODES.METRICS_INCOMPLETE);
});

test('real adapter fails closed on unresolved breakpoint and ambiguous modifier identity', async () => {
  const profile = createRealProfile();
  await assert.rejects(() => new RealMaxrollRuntimeAdapter({
    lease: createFakeLease({ breakpointLocations: [] }), profile,
  }).initialize(), error => error.code === ERROR_CODES.RUNTIME_MISMATCH);

  const adapter = new RealMaxrollRuntimeAdapter({
    lease: createFakeLease({ optionCount: 2 }), profile,
  });
  await adapter.initialize();
  await assert.rejects(() => adapter.apply(MODIFIED_BUILD, sha256(MODIFIED_BUILD)),
    error => error.code === ERROR_CODES.APPLY_FAILED);
});

test('MXP-R3-01 evaluateOnCallFrame failure resumes and rejects active capture promptly', async () => {
  const profile = createRealProfile({ realRuntime: { captureTimeoutMs: 500 } });
  const lease = createFakeLease({ failEvaluateOnce: true });
  const adapter = new RealMaxrollRuntimeAdapter({ lease, profile });
  await adapter.initialize();
  const started = performance.now();
  await assert.rejects(() => adapter.apply(BASE_BUILD, sha256(BASE_BUILD)),
    error => error.code === ERROR_CODES.RUNTIME_NOT_READY);
  assert.equal(performance.now() - started < 100, true, 'known CDP failure must not wait for capture timeout');
  assert.equal(lease.cdp.resumeAttempts >= 1, true);
});

test('MXP-R3-02 a failed pause cannot poison later event handling or return partial success', async () => {
  const profile = createRealProfile({ realRuntime: { captureTimeoutMs: 500 } });
  const lease = createFakeLease({ failEvaluateOnce: true });
  const adapter = new RealMaxrollRuntimeAdapter({ lease, profile });
  await adapter.initialize();
  await assert.rejects(() => adapter.apply(BASE_BUILD, sha256(BASE_BUILD)),
    error => error.code === ERROR_CODES.RUNTIME_NOT_READY);
  const resumesBefore = lease.cdp.resumeAttempts;
  lease.cdp.emitMetrics();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(lease.cdp.resumeAttempts > resumesBefore, true, 'later paused targets must be resumed');
  await assert.rejects(() => adapter.apply(BASE_BUILD, sha256(BASE_BUILD)),
    error => error.code === ERROR_CODES.RUNTIME_NOT_READY);
});

test('MXP-R3-03 resume failure and CDP disconnect reject pending capture fail-closed', async () => {
  const profile = createRealProfile({ realRuntime: { captureTimeoutMs: 500 } });
  const resumeLease = createFakeLease({ failResumeOnce: true });
  const resumeAdapter = new RealMaxrollRuntimeAdapter({ lease: resumeLease, profile });
  await resumeAdapter.initialize();
  await assert.rejects(() => resumeAdapter.apply(BASE_BUILD, sha256(BASE_BUILD)),
    error => error.code === ERROR_CODES.RUNTIME_NOT_READY);

  const disconnectLease = createFakeLease({ emitOnItemClick: false });
  const disconnectAdapter = new RealMaxrollRuntimeAdapter({ lease: disconnectLease, profile });
  await disconnectAdapter.initialize();
  const pending = disconnectAdapter.apply(BASE_BUILD, sha256(BASE_BUILD));
  await new Promise(resolve => setImmediate(resolve));
  disconnectLease.cdp.emitDisconnect();
  await assert.rejects(pending, error => error.code === ERROR_CODES.RUNTIME_NOT_READY);
});

test('MXP-R3 timeout, close and late callbacks settle once without stale capture reuse', async () => {
  const profile = createRealProfile({ realRuntime: { captureTimeoutMs: 15 } });
  const lease = createFakeLease({ emitOnItemClick: false });
  const adapter = new RealMaxrollRuntimeAdapter({ lease, profile });
  const extractor = new RealMaxrollMetricsExtractor(profile);
  await adapter.initialize();

  await assert.rejects(() => adapter.apply(BASE_BUILD, sha256(BASE_BUILD)),
    error => error.code === ERROR_CODES.METRICS_INCOMPLETE);
  lease.cdp.emitMetrics();
  await new Promise(resolve => setImmediate(resolve));

  lease.setEmitOnItemClick(true);
  const applied = await adapter.apply(BASE_BUILD, sha256(BASE_BUILD));
  const metrics = await extractor.extract(adapter, applied);
  assert.equal(metrics.length, 50);
  await assert.rejects(() => extractor.extract(adapter, applied),
    error => error.code === ERROR_CODES.STALE_METRICS);

  const pendingLease = createFakeLease({ emitOnItemClick: false });
  const pendingAdapter = new RealMaxrollRuntimeAdapter({ lease: pendingLease, profile });
  await pendingAdapter.initialize();
  const pending = pendingAdapter.apply(BASE_BUILD, sha256(BASE_BUILD));
  await new Promise(resolve => setImmediate(resolve));
  await pendingAdapter.close();
  await assert.rejects(pending, error => error.code === ERROR_CODES.SESSION_INVALIDATED);
  pendingLease.cdp.emitMetrics();
  await new Promise(resolve => setImmediate(resolve));
  await assert.rejects(() => pendingAdapter.apply(BASE_BUILD, sha256(BASE_BUILD)),
    error => error.code === ERROR_CODES.SESSION_INVALIDATED);
});

test('MXP-R3 cancellation closes the real adapter and rejects late paused callbacks', async () => {
  const profile = createRealProfile({ realRuntime: { captureTimeoutMs: 500 } });
  const lease = createFakeLease();
  const adapter = new RealMaxrollRuntimeAdapter({ lease, profile });
  await adapter.initialize();
  const session = new MaxrollSession({
    adapter,
    mapper: new MaxrollBuildMapper(profile),
    extractor: new RealMaxrollMetricsExtractor(profile),
    profile,
    lease,
    mount: { unmount: async () => {} },
    timeoutMs: 500,
  });
  await session.initialize(BASE_BUILD, profile.supportedBuildSchemaVersion);
  lease.setEmitOnItemClick(false);
  const abort = new AbortController();
  const pending = session.evaluate({
    build: MODIFIED_BUILD,
    buildSchemaVersion: profile.supportedBuildSchemaVersion,
    signal: abort.signal,
  });
  await new Promise(resolve => setImmediate(resolve));
  abort.abort();
  await assert.rejects(pending, error => error.code === ERROR_CODES.CANCELLED);
  await new Promise(resolve => setImmediate(resolve));
  lease.cdp.emitMetrics();
  await new Promise(resolve => setImmediate(resolve));
  await assert.rejects(() => session.evaluate({
    build: BASE_BUILD,
    buildSchemaVersion: profile.supportedBuildSchemaVersion,
  }), error => error.code === ERROR_CODES.SESSION_INVALIDATED);
});
