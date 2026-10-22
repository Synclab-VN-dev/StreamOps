'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const {
  ERROR_CODES,
  METRIC_CATALOG,
  MAXROLL_32173552_REFERENCE,
  MaxrollProvider,
  REAL_MAXROLL_COMPONENT_FACTORY,
  RealMaxrollMetricsExtractor,
  RealMaxrollRuntimeAdapter,
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
  constructor({ breakpointLocations = [{}] } = {}) {
    this.breakpointLocations = breakpointLocations;
  }
  handlers = new Map();
  modifierActive = false;

  on(name, handler) { this.handlers.set(name, handler); }

  async send(method, params) {
    if (method === 'Debugger.setBreakpointByUrl') return { locations: this.breakpointLocations };
    if (method === 'Debugger.evaluateOnCallFrame') {
      const internalId = Number(params.callFrameId);
      return { result: { value: {
        id: internalId,
        raw: internalId === 446 ? (this.modifierActive ? 2822 : 22) : internalId,
      } } };
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

function createFakeLease({ breakpointLocations, optionCount = 1, reportedModifierCount } = {}) {
  const cdp = new FakeCdp({ breakpointLocations });
  const state = { level: 1, itemPresent: false, modifierActive: false };
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
        cdp.emitMetrics();
      } });
      if (text === 'Add Modifier') return new FakeLocator();
      if (text === 'Dampening / Of Dampening') return new FakeLocator({ count: optionCount, click: () => {
        state.modifierActive = true;
        cdp.modifierActive = true;
        cdp.emitMetrics();
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
        itemPresent: state.itemPresent, modifierPresent: state.modifierActive,
        modifierCount: reportedModifierCount ?? (state.modifierActive ? 1 : 0), displays,
      };
    },
  };
  return {
    valid: true,
    page,
    createCDPSession: async () => cdp,
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

test('real adapter and extractor enforce read-back, freshness and 50/34 observed coverage', async () => {
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
