'use strict';

const crypto = require('node:crypto');
const { ERROR_CODES, MaxrollProviderError } = require('./errors');

function sha256(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(Object.keys(value).sort()
    .map(key => [key, canonicalize(value[key])]));
}

function semanticHash(value) {
  const normalized = value === undefined
    ? { $streamopsSemanticValue: 'ABSENT' }
    : canonicalize(value);
  return sha256(Buffer.from(JSON.stringify(normalized)));
}

function normalizedProfile(profile) {
  const normalized = structuredClone(profile);
  delete normalized.id;
  return normalized;
}

function semanticDifferencePaths(expected, observed, prefix = '', output = []) {
  if (output.length >= 20 || Object.is(expected, observed)) return output;
  if (Array.isArray(expected) && Array.isArray(observed)) {
    if (expected.length !== observed.length) output.push(`${prefix}.length`);
    for (let index = 0; index < Math.min(expected.length, observed.length); index += 1) {
      semanticDifferencePaths(expected[index], observed[index], `${prefix}.${index}`, output);
    }
    return output;
  }
  if (expected && observed && typeof expected === 'object' && typeof observed === 'object'
      && !Array.isArray(expected) && !Array.isArray(observed)) {
    for (const key of new Set([...Object.keys(expected), ...Object.keys(observed)])) {
      if (!Object.hasOwn(expected, key) || !Object.hasOwn(observed, key)) output.push(`${prefix}.${key}`);
      else semanticDifferencePaths(expected[key], observed[key], `${prefix}.${key}`, output);
      if (output.length >= 20) break;
    }
    return output;
  }
  output.push(prefix || '$');
  return output;
}

function resolvedItems(nativeState, profile) {
  return Object.fromEntries(Object.entries(profile.items)
    .filter(([, reference]) => Boolean(reference))
    .map(([slot, reference]) => [slot, nativeState.items[String(reference)]]));
}

function inputSemantics(nativeState, profileIndex) {
  const profile = nativeState?.profiles?.[profileIndex];
  if (!profile) {
    throw new MaxrollProviderError(ERROR_CODES.PROFILE_VARIANT_NOT_FOUND,
      `native profile index ${profileIndex} does not exist`);
  }
  const items = resolvedItems(nativeState, profile);
  return Object.freeze({
    profile,
    items,
    identity: Object.freeze({
      name: profile.name,
      class: profile.class,
      level: profile.level,
      worldTier: profile.worldTier,
    }),
    profileSha256: semanticHash(normalizedProfile(profile)),
    itemsSha256: semanticHash(items),
    options: structuredClone(nativeState.options ?? {}),
    optionsSha256: semanticHash(nativeState.options ?? {}),
    season: nativeState.season,
    sections: Object.freeze(Object.fromEntries([
      'items', 'skillTree', 'skillBar', 'paragon', 'warPlans', 'world',
      'specialization', 'mercenary',
    ].map(name => [name, semanticHash(profile[name])]))),
  });
}

function resolveSharedOptionControls(expectedShared, controls, definitions, storedShared) {
  const expected = expectedShared ?? {};
  if (!expected || typeof expected !== 'object' || Array.isArray(expected)
      || !Array.isArray(controls) || !definitions || typeof definitions !== 'object') {
    throw new MaxrollProviderError(ERROR_CODES.INPUT_READBACK_UNVERIFIED,
      'shared option UI read-back contract is unavailable');
  }
  const observed = {};
  const notApplicable = [];
  const rawValues = {};
  const applicabilityEvidence = [];
  for (const [key, expectedValue] of Object.entries(expected)) {
    const definition = definitions[key];
    if (!definition || !Array.isArray(definition.labels) || !definition.labels.length) {
      throw new MaxrollProviderError(ERROR_CODES.INPUT_READBACK_UNVERIFIED,
        `shared option has no pinned UI identity: ${key}`);
    }
    const matches = controls.filter(control => control.group === definition.group
      && definition.labels.includes(control.label));
    if (matches.length === 0) {
      if (storedShared && typeof storedShared === 'object' && !Array.isArray(storedShared)
          && Object.hasOwn(storedShared, key)) {
        const storedValue = structuredClone(storedShared[key]);
        observed[key] = storedValue;
        rawValues[key] = Object.freeze({ status: 'OBSERVED',
          source: 'MAXROLL_CALCULATION_INPUT_STORE', value: storedValue });
        applicabilityEvidence.push({ key, rule: 'calculation-input-store',
          authority: 'CURRENT_CALCULATION_FRAME:options.shared' });
        continue;
      }
      throw new MaxrollProviderError(ERROR_CODES.INPUT_READBACK_UNVERIFIED,
        `shared option has no runtime UI observation: ${key}`);
    }
    if (matches.length !== 1) {
      throw new MaxrollProviderError(ERROR_CODES.INPUT_READBACK_UNVERIFIED,
        `shared option UI identity is ambiguous: ${key}`);
    }
    const control = matches[0];
    let value;
    if (typeof expectedValue === 'boolean' && control.kind === 'checkbox') {
      value = control.checked;
    } else if (typeof expectedValue === 'number' && control.kind === 'number') {
      value = control.value;
      if (definition.normalize === 'percent-of-max') value = (value / control.max) * 100;
    } else if (typeof expectedValue === 'number' && control.kind === 'select'
        && Array.isArray(definition.options)) {
      value = definition.options.indexOf(control.value);
    } else {
      throw new MaxrollProviderError(ERROR_CODES.INPUT_READBACK_UNVERIFIED,
        `shared option UI type is incompatible: ${key}`);
    }
    if ((typeof value === 'number' && !Number.isFinite(value)) || value === -1) {
      throw new MaxrollProviderError(ERROR_CODES.INPUT_READBACK_UNVERIFIED,
        `shared option UI value is invalid: ${key}`);
    }
    observed[key] = value;
    rawValues[key] = value;
    applicabilityEvidence.push({ key, rule: 'ui-control-observation',
      authority: 'CURRENT_MAXROLL_UI_DOM' });
  }
  return Object.freeze({ values: Object.freeze(observed),
    rawValues: Object.freeze(rawValues),
    applicabilityEvidence: Object.freeze(applicabilityEvidence.map(Object.freeze)),
    notApplicable: Object.freeze(notApplicable) });
}

function exactOptionReadback(expectedOptions, optionEntries, sharedReadback = {},
  optionDefinitions = {}, runtimeControls = [], storedOptions = null) {
  const expected = expectedOptions ?? {};
  if (!Array.isArray(optionEntries) || !sharedReadback
      || typeof sharedReadback !== 'object' || Array.isArray(sharedReadback)) {
    throw new MaxrollProviderError(ERROR_CODES.INPUT_READBACK_UNVERIFIED,
      'runtime calculation options are unavailable for semantic read-back');
  }
  const observed = {};
  const notApplicable = [];
  const normalized = [];
  const normalizationEvidence = [];
  const observationEvidence = [];
  const rawObserved = {};
  const sharedValues = sharedReadback.values ?? sharedReadback;
  const sharedNotApplicable = new Set(sharedReadback.notApplicable ?? []);
  for (const [optionId, value] of Object.entries(expected)) {
    if (optionId === 'shared') {
      const shared = {};
      for (const key of Object.keys(value)) {
        if (!Object.hasOwn(sharedValues, key)) {
          throw new MaxrollProviderError(ERROR_CODES.INPUT_READBACK_UNVERIFIED,
            `shared calculation option was not read from runtime UI: ${key}`);
        }
        shared[key] = structuredClone(sharedValues[key]);
        if (sharedNotApplicable.has(key)) notApplicable.push(`shared.${key}`);
      }
      observed.shared = shared;
      rawObserved.shared = structuredClone(sharedReadback.rawValues ?? shared);
      observationEvidence.push(...(sharedReadback.applicabilityEvidence ?? []).map(entry => ({
        optionId: `shared.${entry.key}`,
        source: entry.rule === 'calculation-input-store'
          ? 'MAXROLL_CALCULATION_INPUT_STORE' : 'MAXROLL_UI_DOM',
        applicability: entry.rule === 'calculation-input-store' ? 'UNOBSERVED_ACTIVITY' : 'ACTIVE',
        authority: entry.authority,
      })));
      continue;
    }
    const matches = optionEntries.filter(entry =>
      String(entry?.power ?? entry?.id ?? entry?.key) === optionId);
    const stored = storedOptions && typeof storedOptions === 'object'
      && !Array.isArray(storedOptions) && Object.hasOwn(storedOptions, optionId)
      ? storedOptions[optionId] : undefined;
    if (matches.length === 0 && stored === undefined) {
      throw new MaxrollProviderError(ERROR_CODES.INPUT_READBACK_UNVERIFIED,
        `calculation option has no runtime observation: ${optionId}`);
    }
    if (matches.length > 1) throw new MaxrollProviderError(ERROR_CODES.READBACK_MISMATCH,
      `runtime calculation option is ambiguous: ${optionId}`);
    const entry = matches[0];
    const runtimeValue = entry ? (entry.options ?? entry) : stored;
    const definition = optionDefinitions[optionId] ?? {};
    rawObserved[optionId] = structuredClone(runtimeValue);
    observationEvidence.push(Object.freeze({ optionId,
      source: entry ? 'MAXROLL_RESOLVED_OPTION_ENTRY' : 'MAXROLL_CALCULATION_INPUT_STORE',
      applicability: entry ? 'ACTIVE' : 'INACTIVE',
      authority: entry ? 'CURRENT_CALCULATION_FRAME:ProfileStats.optionEntries'
        : 'CURRENT_CALCULATION_FRAME:options',
    }));
    observed[optionId] = Object.fromEntries(Object.keys(value).map(key => {
      const actual = structuredClone(runtimeValue[key]);
      if (key === 'params' && Array.isArray(value.params) && Array.isArray(actual)) {
        return [key, actual.map((entryValue, index) => {
          const rule = definition.params?.[index];
          if (rule?.kind === 'max' && value.params[index] === 'max') {
            const boundMatches = runtimeControls.filter(control => control.kind === 'number'
              && control.group === rule.boundControl?.group
              && control.label === rule.boundControl?.label);
            if (boundMatches.length !== 1 || !Number.isFinite(entryValue)
                || !Object.is(boundMatches[0].value, entryValue)
                || !Object.is(boundMatches[0].max, entryValue)) return entryValue;
            const bound = boundMatches[0].max;
            const evidence = `${optionId}.params.${index}:max=${bound}`;
            normalized.push(evidence);
            normalizationEvidence.push({ optionId, field: `params.${index}`,
              rule: 'pinned-ui-bound-max',
              rawValue: entryValue, boundValue: bound, semanticValue: 'max',
              authority: rule.authority });
            return 'max';
          }
          if (rule?.kind === 'loader-offset' && Number.isInteger(entryValue)
              && entryValue >= rule.min && entryValue <= rule.max) {
            const semantic = entryValue + rule.offset;
            normalizationEvidence.push({ optionId, field: `params.${index}`,
              rule: 'pinned-loader-offset', rawValue: entryValue, semanticValue: semantic,
              authority: rule.authority });
            normalized.push(`${optionId}.params.${index}:loader-offset=${rule.offset}`);
            return semantic;
          }
          if (rule?.kind === 'enum-index' && Number.isInteger(entryValue)) {
            const semantic = entryValue - rule.runtimeBase + rule.canonicalBase;
            if (!Array.isArray(rule.values) || entryValue < rule.runtimeBase
                || entryValue - rule.runtimeBase >= rule.values.length) return entryValue;
            normalizationEvidence.push({ optionId, field: `params.${index}`,
              rule: 'pinned-enum-index', rawValue: entryValue, semanticValue: semantic,
              authority: rule.authority });
            normalized.push(`${optionId}.params.${index}:enum-index=${entryValue}`);
            return semantic;
          }
          return entryValue;
        })];
      }
      if (key === 'flags' && Array.isArray(value.flags) && Array.isArray(actual)
          && Object.hasOwn(definition, 'flags')
          && Object.hasOwn(definition.flags, 'trailingDefault')
          && actual.length >= value.flags.length
          && value.flags.every((flag, index) => flag === actual[index])
          && actual.slice(value.flags.length)
            .every(flag => flag === definition.flags.trailingDefault)) {
        if (actual.length !== value.flags.length) {
          normalized.push(`${optionId}.flags:trailing-defaults=${actual.length - value.flags.length}`);
          normalizationEvidence.push({ optionId, field: 'flags',
            rule: 'pinned-trailing-default', rawValue: actual,
            semanticValue: structuredClone(value.flags), authority: definition.flags.authority });
        }
        return [key, structuredClone(value.flags)];
      }
      return [key, actual];
    }));
  }
  if (semanticHash(observed) !== semanticHash(expected)) {
    const differences = semanticDifferencePaths(expected, observed, 'options');
    throw new MaxrollProviderError(ERROR_CODES.READBACK_MISMATCH,
      `runtime calculation options do not match the requested state: ${differences.join(', ')}`, {
        details: { expectedSha256: semanticHash(expected), observedSha256: semanticHash(observed),
          expected, observed, rawObserved, differences },
      });
  }
  const count = Object.entries(expected).reduce((total, [optionId, value]) =>
    total + (optionId === 'shared' ? Object.keys(value).length : 1), 0);
  return Object.freeze({ status: 'EXACT', expectedSha256: semanticHash(expected),
    observedSha256: semanticHash(observed), count,
    applicableCount: count - notApplicable.length,
    notApplicable: Object.freeze(notApplicable),
    normalized: Object.freeze(normalized),
    normalizationEvidence: Object.freeze(normalizationEvidence.map(Object.freeze)),
    observationEvidence: Object.freeze(observationEvidence),
    rawObserved: Object.freeze(structuredClone(rawObserved)),
    observed: structuredClone(observed) });
}

function normalizedExpectedOptions(options, definitions = {}) {
  const output = structuredClone(options ?? {});
  for (const [optionId, option] of Object.entries(output)) {
    const definition = definitions[optionId];
    for (const field of definition?.ignoredNativeFields ?? []) delete option[field];
    for (const [index, rule] of Object.entries(
      definition?.nativeParamCanonicalization ?? {})) {
      if (rule.kind === 'clamp-max' && Number.isFinite(option.params?.[index])) {
        option.params[index] = Math.min(option.params[index], rule.max);
      }
    }
    if (Object.keys(option).length === 0) delete output[optionId];
  }
  return output;
}

function resolveApplicableMetricInventory({ rows, observedMetricDefinitions, metricCatalog,
  displayOnly = [] }) {
  if (!Array.isArray(rows) || !(observedMetricDefinitions instanceof Map)
      || !Array.isArray(metricCatalog) || !Array.isArray(displayOnly)) {
    throw new MaxrollProviderError(ERROR_CODES.INVALID_CONFIG,
      'applicable metric inventory contract is invalid');
  }
  const displayOnlyByAnchor = new Map(displayOnly.map(entry =>
    [`${entry.section}|${entry.label}`, entry]));
  const catalogByAnchor = new Map(metricCatalog
    .filter(metric => metric.category !== 'runtime')
    .map(metric => [`${metric.category}|${metric.name}`, metric.internalId]));
  const expectedIds = new Set();
  const classifiedDisplayOnly = [];
  const unresolved = [];
  for (const row of rows) {
    const anchor = `${row.section}|${row.label}`;
    const displayClassification = displayOnlyByAnchor.get(anchor);
    if (displayClassification) {
      classifiedDisplayOnly.push(displayClassification);
      continue;
    }
    const catalogId = catalogByAnchor.get(anchor);
    const observedIds = observedMetricDefinitions.get(row.label) ?? new Set();
    if (observedIds.size === 1) {
      expectedIds.add([...observedIds][0]);
      continue;
    }
    if (observedIds.size > 1 && Number.isInteger(catalogId) && observedIds.has(catalogId)) {
      expectedIds.add(catalogId);
    }
    else unresolved.push({ ...row, reason: observedIds.size === 0
      ? 'raw-id-unresolved' : 'raw-id-ambiguous', observedInternalIds: [...observedIds] });
  }
  if (unresolved.length) throw new MaxrollProviderError(ERROR_CODES.METRICS_INCOMPLETE,
    `applicable display inventory could not be linked to stable raw metric IDs: ${unresolved
      .slice(0, 5).map(row => `${row.section}|${row.label}:${row.reason}`
        + `[${row.observedInternalIds.join(',')}]`).join(', ')}`, {
      details: { unresolved },
    });
  const rawOnly = [];
  for (const [label, ids] of observedMetricDefinitions) {
    for (const internalId of ids) {
      if (!expectedIds.has(internalId)) rawOnly.push({ internalId, label,
        reason: 'coherent-runtime-definition-without-display-row' });
      expectedIds.add(internalId);
    }
  }
  if (!expectedIds.size) throw new MaxrollProviderError(ERROR_CODES.METRICS_INCOMPLETE,
    'applicable metric inventory contains no raw metrics');
  return Object.freeze({ expectedIds,
    rawOnly: Object.freeze(rawOnly.map(Object.freeze)),
    displayOnly: Object.freeze(classifiedDisplayOnly.map(entry => Object.freeze({ ...entry }))) });
}

class CalculationEpochAccumulator {
  #expected;
  #expectedCount;
  #epochKey = null;
  #values = new Map();
  #labels = new Map();
  #consistentDuplicates = 0;
  #dynamic = false;

  constructor(expectedInternalIds) {
    if (expectedInternalIds?.discover === true) {
      this.#expected = null;
      this.#expectedCount = null;
      this.#dynamic = true;
    } else if (Number.isInteger(expectedInternalIds?.count) && expectedInternalIds.count > 0) {
      this.#expected = null;
      this.#expectedCount = expectedInternalIds.count;
    } else {
      this.#expected = new Set(expectedInternalIds);
      this.#expectedCount = this.#expected.size;
    }
    if (this.#expectedCount === 0) {
      throw new MaxrollProviderError(ERROR_CODES.INVALID_CONFIG,
        'calculation epoch requires at least one expected metric');
    }
  }

  bindEpoch(epochKey) {
    if (typeof epochKey !== 'string' || !epochKey) {
      throw new MaxrollProviderError(ERROR_CODES.INPUT_READBACK_UNVERIFIED,
        'calculation epoch identity is unavailable');
    }
    this.#epochKey ??= epochKey;
    if (this.#epochKey !== epochKey) {
      throw new MaxrollProviderError(ERROR_CODES.STALE_METRICS,
        'calculation epoch changed before the metric vector was complete');
    }
  }

  observe({ epochKey, internalId, rawValue, label }) {
    this.bindEpoch(epochKey);
    if (this.#expected && !this.#expected.has(internalId)) return this.complete;
    if (typeof rawValue !== 'number' || !Number.isFinite(rawValue)) {
      throw new MaxrollProviderError(ERROR_CODES.METRICS_INCOMPLETE,
        `attested raw metric is invalid: ${internalId}`);
    }
    if (this.#values.has(internalId)) {
      if (!Object.is(this.#values.get(internalId), rawValue)
          || this.#labels.get(internalId) !== label) {
        throw new MaxrollProviderError(ERROR_CODES.OUTPUT_NOT_LINKED,
          `metric ${internalId} changed within one calculation epoch`);
      }
      this.#consistentDuplicates += 1;
      return this.complete;
    }
    this.#values.set(internalId, rawValue);
    this.#labels.set(internalId, label);
    return this.complete;
  }

  finalize(expectedInternalIds) {
    if (!this.#dynamic || this.#expected !== null || !expectedInternalIds?.size) {
      throw new MaxrollProviderError(ERROR_CODES.INVALID_CONFIG,
        'dynamic calculation metric contract cannot be finalized');
    }
    this.#expected = new Set(expectedInternalIds);
    this.#expectedCount = this.#expected.size;
    this.#dynamic = false;
    for (const internalId of this.#values.keys()) {
      if (!this.#expected.has(internalId)) this.#values.delete(internalId);
    }
  }

  get complete() { return Number.isInteger(this.#expectedCount)
    && this.#values.size === this.#expectedCount; }
  get expectedCount() { return this.#expectedCount; }
  get size() { return this.#values.size; }
  get epochKey() { return this.#epochKey; }
  get consistentDuplicates() { return this.#consistentDuplicates; }
  get missingIds() {
    return this.#expected ? [...this.#expected].filter(id => !this.#values.has(id)) : [];
  }
  get observedIds() { return [...this.#values.keys()]; }
  value(internalId) { return this.#values.get(internalId); }
  label(internalId) { return this.#labels.get(internalId); }

  assertComplete() {
    if (!this.complete) {
      throw new MaxrollProviderError(ERROR_CODES.METRICS_INCOMPLETE,
        `calculation epoch ended with ${this.#values.size}/${this.#expectedCount} metrics`);
    }
  }
}

class MaxrollRuntimeAttestationObserver {
  #lease;
  #profile;
  #semantics;
  #cdp = null;
  #pauseChain = Promise.resolve();
  #capture = null;
  #runtimeFailure = null;
  #closed = false;
  #script = null;
  #inputStateBreakpointId = null;
  #wire = null;
  #wireWaiters = [];
  #requestIds = new Map();
  #network = {
    requestAttempts: 0,
    responseEvents: 0,
    loadingFailures: 0,
    webSocketAttempts: 0,
    webSocketHandshakes: 0,
    externalEgressCompleted: 0,
  };

  constructor({ lease, profile, nativeState, profileIndex }) {
    this.#lease = lease;
    this.#profile = profile;
    this.#semantics = inputSemantics(nativeState, profileIndex);
  }

  async initialize() {
    if (!this.#lease?.valid) throw new MaxrollProviderError(ERROR_CODES.SESSION_INVALIDATED,
      'attestation requires a valid browser lease');
    const runtime = this.#profile.realRuntime;
    if (!runtime?.attestationReadbackExpression || !runtime?.calculationEpochExpression) {
      throw new MaxrollProviderError(ERROR_CODES.INVALID_CONFIG,
        'runtime profile has no attestation read-back or calculation epoch expression');
    }
    this.#cdp = await this.#lease.createCDPSession();
    await Promise.all([
      this.#cdp.send('Debugger.enable'),
      this.#cdp.send('Network.enable'),
    ]);
    this.#cdp.on('Debugger.scriptParsed', event => {
      if (new RegExp(runtime.assetUrlRegex).test(event.url)) {
        this.#script = { scriptId: event.scriptId, url: event.url };
      }
    });
    this.#cdp.on('Debugger.paused', event => { this.#queuePause(event); });
    this.#cdp.on('Network.requestWillBeSent', event => {
      if (!isNetworkUrl(event.request?.url)) return;
      this.#network.requestAttempts += 1;
    });
    this.#cdp.on('Network.responseReceived', event => {
      const url = event.response?.url;
      if (!isNetworkUrl(url)) return;
      this.#network.responseEvents += 1;
      if (event.response?.remoteIPAddress) this.#network.externalEgressCompleted += 1;
      if (new RegExp(runtime.assetUrlRegex).test(url)) {
        this.#requestIds.set(event.requestId, url);
      }
    });
    this.#cdp.on('Network.loadingFailed', () => { this.#network.loadingFailures += 1; });
    this.#cdp.on('Network.loadingFinished', event => { this.#captureWireBytes(event.requestId); });
    this.#cdp.on('Network.webSocketCreated', event => {
      if (isNetworkUrl(event.url)) this.#network.webSocketAttempts += 1;
    });
    this.#cdp.on('Network.webSocketHandshakeResponseReceived', () => {
      this.#network.webSocketHandshakes += 1;
      this.#network.externalEgressCompleted += 1;
    });
    const breakpoint = await this.#cdp.send('Debugger.setBreakpointByUrl', {
      urlRegex: runtime.assetUrlRegex,
      lineNumber: runtime.breakpoint.lineNumber,
      columnNumber: runtime.breakpoint.columnNumber,
    });
    let inputStateBreakpointLocations = 0;
    if (runtime.inputStateBreakpoint) {
      if (!runtime.inputStateReadbackExpression || !runtime.inputStateEpochExpression) {
        throw new MaxrollProviderError(ERROR_CODES.INVALID_CONFIG,
          'runtime input-state breakpoint has no read-back contract');
      }
      const inputBreakpoint = await this.#cdp.send('Debugger.setBreakpointByUrl', {
        urlRegex: runtime.assetUrlRegex,
        lineNumber: runtime.inputStateBreakpoint.lineNumber,
        columnNumber: runtime.inputStateBreakpoint.columnNumber,
      });
      this.#inputStateBreakpointId = inputBreakpoint.breakpointId;
      inputStateBreakpointLocations = inputBreakpoint.locations?.length ?? 0;
    }
    return Object.freeze({ initialBreakpointLocations: breakpoint.locations?.length ?? 0,
      inputStateBreakpointLocations });
  }

  setInput(nativeState, profileIndex) {
    this.#assertHealthy();
    if (this.#capture) throw new MaxrollProviderError(ERROR_CODES.RUNTIME_NOT_READY,
      'cannot replace attestation input while capture is active');
    this.#semantics = inputSemantics(nativeState, profileIndex);
  }

  async capture({ navigateUrl, replayResponse = null }) {
    this.#assertHealthy();
    if (this.#capture) throw new MaxrollProviderError(ERROR_CODES.RUNTIME_NOT_READY,
      'attestation capture is already active');
    if (replayResponse) {
      await this.#lease.page.route(replayResponse.url, route => route.fulfill({
        status: 200,
        headers: {
          'content-type': 'application/json',
          'access-control-allow-origin': 'https://maxroll.gg',
        },
        body: replayResponse.body,
      }));
    }
    const capture = this.#newCapture();
    this.#capture = capture;
    let primaryError;
    let result;
    try {
      await this.#lease.page.goto(navigateUrl, {
        waitUntil: 'domcontentloaded',
        timeout: this.#profile.realRuntime.navigationTimeoutMs ?? 30_000,
      });
      if (this.#profile.realRuntime.discoverMetricCatalog === true) {
        await this.#finalizeDiscoveredMetrics(capture);
      }
      await capture.completion;
      await this.#pauseChain;
      const engine = await this.#engineEvidence();
      const displayMetrics = await this.#readDisplayMetrics(capture.observedMetricDefinitions);
      if (!capture.storedOptions || typeof capture.storedOptions !== 'object'
          || Array.isArray(capture.storedOptions)) {
        throw new MaxrollProviderError(ERROR_CODES.INPUT_READBACK_UNVERIFIED,
          'calculation input option store was not observed in the current runtime frame');
      }
      const globalReadback = await this.#readGlobalContext(capture.storedOptions);
      const optionDefinitions = this.#profile.realRuntime.optionReadbackDefinitions ?? {};
      const optionReadback = exactOptionReadback(
        normalizedExpectedOptions(this.#semantics.options, optionDefinitions),
        capture.optionEntries, globalReadback.shared,
        optionDefinitions, globalReadback.controls, capture.storedOptions);
      if (globalReadback.season !== this.#semantics.season) {
        throw new MaxrollProviderError(ERROR_CODES.READBACK_MISMATCH,
          'runtime season does not match the requested state', {
            details: { expected: this.#semantics.season, observed: globalReadback.season },
          });
      }
      capture.profileReadback = Object.freeze({ ...capture.profileReadback,
        calculationOptions: optionReadback,
        season: Object.freeze({ expected: this.#semantics.season,
          observed: globalReadback.season, exact: true, evidence: 'MAXROLL_UI_DOM' }),
      });
      capture.runtimeState = Object.freeze({ ...capture.runtimeState,
        options: structuredClone(optionReadback.observed), season: globalReadback.season });
      const rawMetrics = this.#rawMetrics(capture, displayMetrics);
      result = Object.freeze({
        captureId: capture.id,
        profileReadback: Object.freeze({ ...capture.profileReadback }),
        runtimeState: Object.freeze(structuredClone(capture.runtimeState)),
        engine,
        rawMetrics: Object.freeze(rawMetrics.map(definition => Object.freeze({
          metricId: definition.id,
          internalId: definition.internalId,
          label: capture.accumulator.label(definition.internalId) ?? definition.name,
          category: definition.category,
          rawValue: capture.accumulator.value(definition.internalId),
          unit: null,
          status: 'OBSERVED',
          provenance: 'MAXROLL_CDP_RUNTIME',
        }))),
        displayMetrics: Object.freeze(displayMetrics),
        phase: Object.freeze({
          captureId: capture.id,
          matchedPauseOrdinal: capture.matchedPauseOrdinal,
          firstMetricPauseOrdinal: capture.firstMetricPauseOrdinal,
          lastMetricPauseOrdinal: capture.lastMetricPauseOrdinal,
          totalPauseEvents: capture.pauseOrdinal,
          epochIdentitySha256: capture.epochIdentitySha256,
          epochIdentitySource: 'CDP_RUNTIME_OBJECT_IDENTITY:l.context',
          epochComparisons: capture.epochComparisons,
          consistentDuplicateMetrics: capture.accumulator.consistentDuplicates,
          coherentMetricCount: capture.accumulator.size,
          expectedMetricCount: capture.accumulator.expectedCount,
          inputProfileSha256: this.#semantics.profileSha256,
          inputItemsSha256: this.#semantics.itemsSha256,
        }),
        network: Object.freeze({ ...this.#network, source: 'CDP.Network' }),
      });
    } catch (error) {
      primaryError = error;
      capture.reject(error);
    } finally {
      clearTimeout(capture.timer);
      this.#capture = null;
    }
    const cleanupErrors = [];
    try { await this.#releaseEpochObject(capture); } catch (error) { cleanupErrors.push(error); }
    if (replayResponse) {
      try { await this.#lease.page.unroute(replayResponse.url); } catch (error) { cleanupErrors.push(error); }
    }
    if (primaryError && cleanupErrors.length) {
      throw new AggregateError([primaryError, ...cleanupErrors],
        'attestation capture and route cleanup both failed');
    }
    if (cleanupErrors.length === 1) throw cleanupErrors[0];
    if (cleanupErrors.length > 1) throw new AggregateError(cleanupErrors,
      'attestation capture cleanup failed');
    if (primaryError) throw primaryError;
    return result;
  }

  async close() {
    if (this.#closed) return;
    this.#closed = true;
    const failures = [];
    if (this.#capture) this.#capture.reject(new MaxrollProviderError(
      ERROR_CODES.SESSION_INVALIDATED, 'attestation observer closed during capture'));
    await this.#pauseChain.catch(error => failures.push(error));
    for (const command of ['Network.disable', 'Debugger.disable']) {
      try { await this.#cdp?.send(command); } catch (error) { failures.push(error); }
    }
    try { await this.#cdp?.detach(); } catch (error) { failures.push(error); }
    if (failures.length) throw new AggregateError(failures, 'attestation observer cleanup failed');
  }

  #newCapture() {
    const expected = new Set(this.#profile.metricCatalog.map(metric => metric.internalId));
    const discover = this.#profile.realRuntime.discoverMetricCatalog === true;
    let resolveCompletion;
    let rejectCompletion;
    const completion = new Promise((resolve, reject) => {
      resolveCompletion = resolve;
      rejectCompletion = reject;
    });
    const capture = {
      id: crypto.randomUUID(),
      expected,
      accumulator: new CalculationEpochAccumulator(discover
        ? { discover: true }
        : expected),
      observedMetricDefinitions: new Map(),
      epochObjectId: null,
      epochIdentitySha256: null,
      epochComparisons: 0,
      pauseOrdinal: 0,
      matchedPauseOrdinal: null,
      firstMetricPauseOrdinal: null,
      lastMetricPauseOrdinal: null,
      profileReadback: null,
      runtimeState: null,
      optionEntries: null,
      storedOptions: null,
      pendingInputState: null,
      lastObservedIdentity: null,
      settled: false,
      completion,
      resolve: () => {
        if (capture.settled) return;
        capture.settled = true;
        clearTimeout(capture.timer);
        resolveCompletion();
      },
      reject: error => {
        if (capture.settled) return;
        capture.settled = true;
        clearTimeout(capture.timer);
        rejectCompletion(error);
      },
    };
    capture.timer = setTimeout(() => capture.reject(new MaxrollProviderError(
      capture.profileReadback ? ERROR_CODES.METRICS_INCOMPLETE : ERROR_CODES.INPUT_READBACK_UNVERIFIED,
      capture.profileReadback
        ? 'timed out waiting for a complete fresh metric phase'
        : 'timed out waiting for exact runtime semantic read-back', {
        details: {
          lastObservedIdentity: capture.lastObservedIdentity,
          observedMetricIds: capture.accumulator.observedIds,
          missingMetricIds: capture.accumulator.missingIds,
        },
      })),
    this.#profile.realRuntime.captureTimeoutMs ?? 30_000);
    return capture;
  }

  #queuePause(event) {
    this.#pauseChain = this.#pauseChain
      .then(() => this.#handlePause(event))
      .catch(error => {
        const failure = error instanceof MaxrollProviderError ? error :
          new MaxrollProviderError(ERROR_CODES.RUNTIME_NOT_READY,
            'attestation CDP pause processing failed', { cause: error });
        this.#runtimeFailure ??= failure;
        this.#capture?.reject(failure);
      });
  }

  async #handlePause(event) {
    let failure = null;
    try {
      const capture = this.#capture;
      const frame = event.callFrames?.[0];
      if (!capture || !frame
          || (capture.settled && this.#profile.realRuntime.discoverMetricCatalog === true)) return;
      capture.pauseOrdinal += 1;
      capture.pauseScriptId ??= frame.location?.scriptId ?? null;
      if (this.#inputStateBreakpointId
          && event.hitBreakpoints?.includes(this.#inputStateBreakpointId)) {
        await this.#captureInputState(capture, frame);
        return;
      }
      const readback = await this.#evaluate(frame.callFrameId,
        this.#profile.realRuntime.attestationReadbackExpression);
      const observedProfile = readback?.profile;
      const observedItems = readback?.items;
      capture.lastObservedIdentity = observedProfile ? {
        name: observedProfile.name, class: observedProfile.class,
        level: observedProfile.level, worldTier: observedProfile.worldTier,
      } : null;
      const sameIdentity = observedProfile?.name === this.#semantics.identity.name
        && observedProfile?.class === this.#semantics.identity.class
        && observedProfile?.level === this.#semantics.identity.level
        && observedProfile?.worldTier === this.#semantics.identity.worldTier;
      if (!sameIdentity) return;
      const profileSha256 = semanticHash(normalizedProfile(observedProfile));
      const itemsSha256 = semanticHash(observedItems);
      if (profileSha256 !== this.#semantics.profileSha256
          || itemsSha256 !== this.#semantics.itemsSha256) {
        const differences = [
          ...semanticDifferencePaths(normalizedProfile(this.#semantics.profile),
            normalizedProfile(observedProfile), 'profile'),
          ...semanticDifferencePaths(this.#semantics.items, observedItems, 'items'),
        ].slice(0, 20);
        throw new MaxrollProviderError(ERROR_CODES.READBACK_MISMATCH,
          `runtime semantic state does not match the exported build: ${differences.join(', ')}`, {
            details: { profileSha256, itemsSha256, differences },
          });
      }
      if (!capture.profileReadback) {
        const sections = Object.fromEntries(Object.entries(this.#semantics.sections)
          .map(([name, expected]) => [name, Object.freeze({
            expected,
            observed: semanticHash(observedProfile[name]),
            exact: expected === semanticHash(observedProfile[name]),
          })]));
        if (Object.values(sections).some(section => !section.exact)) {
          throw new MaxrollProviderError(ERROR_CODES.READBACK_MISMATCH,
            'runtime semantic profile section mismatch');
        }
        capture.profileReadback = Object.freeze({
          status: 'EXACT',
          normalizedProfileSha256: profileSha256,
          resolvedItemsSha256: itemsSha256,
          resolvedItemCount: Object.keys(observedItems).length,
          sections: Object.freeze(sections),
        });
        capture.runtimeState = Object.freeze({
          profile: structuredClone(observedProfile),
          items: structuredClone(observedItems),
        });
        capture.optionEntries = structuredClone(readback?.optionEntries ?? []);
        capture.matchedPauseOrdinal = capture.pauseOrdinal;
      }
      const epochObject = await this.#evaluateObject(frame.callFrameId,
        this.#profile.realRuntime.calculationEpochExpression);
      const epochKey = await this.#bindCalculationEpoch(capture, epochObject.objectId,
        frame.location?.scriptId);
      const metric = await this.#evaluate(frame.callFrameId,
        this.#profile.realRuntime.captureExpression);
      const internalId = Number(metric?.id);
      if (Number.isInteger(internalId) && typeof metric?.label === 'string' && metric.label) {
        const ids = capture.observedMetricDefinitions.get(metric.label) ?? new Set();
        ids.add(internalId);
        capture.observedMetricDefinitions.set(metric.label, ids);
      }
      if (this.#profile.realRuntime.discoverMetricCatalog !== true
          && !capture.expected.has(internalId)) return;
      const labelAllowlist = this.#profile.realRuntime.metricLabelAllowlist;
      if (this.#profile.realRuntime.discoverMetricCatalog === true
          && Array.isArray(labelAllowlist) && !labelAllowlist.includes(metric?.label)) return;
      capture.firstMetricPauseOrdinal ??= capture.pauseOrdinal;
      capture.lastMetricPauseOrdinal = capture.pauseOrdinal;
      const complete = capture.accumulator.observe({ epochKey, internalId, rawValue: metric.raw,
        label: metric.label });
      if (this.#profile.realRuntime.discoverMetricCatalog !== true && complete) capture.resolve();
    } catch (error) {
      failure = error;
    } finally {
      try {
        await this.#cdp.send('Debugger.resume');
      } catch (error) {
        failure = new MaxrollProviderError(ERROR_CODES.RUNTIME_NOT_READY,
          'attestation could not resume the paused runtime', { cause: error });
      }
    }
    if (failure) throw failure;
  }

  async #evaluate(callFrameId, expression) {
    const evaluated = await this.#cdp.send('Debugger.evaluateOnCallFrame', {
      callFrameId,
      expression,
      returnByValue: true,
    });
    if (evaluated.exceptionDetails) {
      throw new MaxrollProviderError(ERROR_CODES.RUNTIME_NOT_READY,
        'attestation call-frame expression failed');
    }
    return evaluated.result?.value;
  }

  async #captureInputState(capture, frame) {
    const runtime = this.#profile.realRuntime;
    const readback = await this.#evaluate(frame.callFrameId,
      runtime.inputStateReadbackExpression);
    const observedProfile = readback?.profile;
    const sameIdentity = observedProfile?.name === this.#semantics.identity.name
      && observedProfile?.class === this.#semantics.identity.class
      && observedProfile?.level === this.#semantics.identity.level
      && observedProfile?.worldTier === this.#semantics.identity.worldTier;
    if (!sameIdentity
        || semanticHash(normalizedProfile(observedProfile)) !== this.#semantics.profileSha256) return;
    if (!readback.options || typeof readback.options !== 'object'
        || Array.isArray(readback.options)) {
      throw new MaxrollProviderError(ERROR_CODES.INPUT_READBACK_UNVERIFIED,
        'calculation input option store is unavailable at the invocation boundary');
    }
    const epoch = await this.#evaluateObject(frame.callFrameId,
      runtime.inputStateEpochExpression);
    if (capture.pendingInputState?.epochObjectId) {
      await this.#cdp.send('Runtime.releaseObject', {
        objectId: capture.pendingInputState.epochObjectId,
      });
    }
    capture.pendingInputState = Object.freeze({
      epochObjectId: epoch.objectId,
      options: structuredClone(readback.options),
      profileSha256: this.#semantics.profileSha256,
      pauseOrdinal: capture.pauseOrdinal,
    });
  }

  async #evaluateObject(callFrameId, expression) {
    const evaluated = await this.#cdp.send('Debugger.evaluateOnCallFrame', {
      callFrameId,
      expression,
      returnByValue: false,
    });
    if (evaluated.exceptionDetails || !evaluated.result?.objectId) {
      throw new MaxrollProviderError(ERROR_CODES.INPUT_READBACK_UNVERIFIED,
        'calculation epoch object is unavailable');
    }
    return evaluated.result;
  }

  async #bindCalculationEpoch(capture, currentObjectId, scriptId) {
    if (!capture.epochObjectId) {
      const pending = capture.pendingInputState;
      if (!pending?.epochObjectId) {
        throw new MaxrollProviderError(ERROR_CODES.INPUT_READBACK_UNVERIFIED,
          'metric epoch has no matching calculation input-state observation');
      }
      const comparison = await this.#cdp.send('Runtime.callFunctionOn', {
        objectId: pending.epochObjectId,
        functionDeclaration: 'function(other){return this===other}',
        arguments: [{ objectId: currentObjectId }],
        returnByValue: true,
      });
      await this.#cdp.send('Runtime.releaseObject', { objectId: currentObjectId });
      if (comparison?.result?.value !== true) {
        throw new MaxrollProviderError(ERROR_CODES.STALE_METRICS,
          'calculation input state and metric epoch belong to different invocations');
      }
      capture.epochObjectId = pending.epochObjectId;
      capture.storedOptions = structuredClone(pending.options);
      capture.pendingInputState = null;
      capture.epochIdentitySha256 = sha256(Buffer.from(`${scriptId}:${currentObjectId}`));
      capture.accumulator.bindEpoch(capture.epochIdentitySha256);
      return capture.epochIdentitySha256;
    }
    if (currentObjectId === capture.epochObjectId) return capture.epochIdentitySha256;
    let comparison;
    let releaseError;
    try {
      comparison = await this.#cdp.send('Runtime.callFunctionOn', {
        objectId: capture.epochObjectId,
        functionDeclaration: 'function(other){return this===other}',
        arguments: [{ objectId: currentObjectId }],
        returnByValue: true,
      });
    } finally {
      try { await this.#cdp.send('Runtime.releaseObject', { objectId: currentObjectId }); }
      catch (error) { releaseError = error; }
    }
    if (releaseError) throw new MaxrollProviderError(ERROR_CODES.RUNTIME_NOT_READY,
      'calculation epoch comparison object could not be released', { cause: releaseError });
    capture.epochComparisons += 1;
    if (comparison?.result?.value !== true) {
      capture.accumulator.bindEpoch(sha256(Buffer.from(`${scriptId}:${currentObjectId}`)));
    }
    return capture.epochIdentitySha256;
  }

  async #releaseEpochObject(capture) {
    const objectIds = [capture.epochObjectId, capture.pendingInputState?.epochObjectId]
      .filter(Boolean);
    capture.epochObjectId = null;
    capture.pendingInputState = null;
    for (const objectId of new Set(objectIds)) {
      await this.#cdp.send('Runtime.releaseObject', { objectId });
    }
  }

  async #captureWireBytes(requestId) {
    const url = this.#requestIds.get(requestId);
    if (!url) return;
    try {
      const result = await this.#cdp.send('Network.getResponseBody', { requestId });
      const bytes = Buffer.from(result.body, result.base64Encoded ? 'base64' : 'utf8');
      this.#wire = Object.freeze({ url, bytes: bytes.length, sha256: sha256(bytes) });
      for (const resolve of this.#wireWaiters.splice(0)) resolve(this.#wire);
    } catch (error) {
      this.#runtimeFailure ??= new MaxrollProviderError(
        ERROR_CODES.ENGINE_IDENTITY_UNVERIFIED,
        'could not read calculation asset bytes supplied to Chromium', { cause: error });
      this.#capture?.reject(this.#runtimeFailure);
    }
  }

  async #engineEvidence() {
    const wire = this.#wire ?? await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new MaxrollProviderError(
        ERROR_CODES.ENGINE_IDENTITY_UNVERIFIED,
        'calculation asset response bytes were not observed')),
      this.#profile.realRuntime.captureTimeoutMs ?? 30_000);
      this.#wireWaiters.push(value => { clearTimeout(timer); resolve(value); });
    });
    if (!this.#script?.scriptId) {
      throw new MaxrollProviderError(ERROR_CODES.ENGINE_IDENTITY_UNVERIFIED,
        'CDP did not report the calculation script');
    }
    const source = await this.#cdp.send('Debugger.getScriptSource', {
      scriptId: this.#script.scriptId,
    });
    const sourceBytes = Buffer.from(source.scriptSource, 'utf8');
    const sourceSha256 = sha256(sourceBytes);
    if (wire.sha256 !== this.#profile.assetSha256
        || sourceSha256 !== this.#profile.assetSha256) {
      throw new MaxrollProviderError(ERROR_CODES.RUNTIME_MISMATCH,
        'executing calculation engine does not match the pinned asset', {
          details: { wireSha256: wire.sha256, sourceSha256 },
        });
    }
    const pauseScriptId = this.#capture?.pauseScriptId;
    if (!pauseScriptId || pauseScriptId !== this.#script.scriptId) {
      throw new MaxrollProviderError(ERROR_CODES.ENGINE_IDENTITY_UNVERIFIED,
        'captured calculation did not execute in the pinned script context', {
          details: { parsedScriptId: this.#script.scriptId, pauseScriptId },
        });
    }
    return Object.freeze({
      status: 'EXECUTED',
      assetUrl: this.#script.url,
      pinnedSha256: this.#profile.assetSha256,
      wireSha256: wire.sha256,
      wireBytes: wire.bytes,
      scriptSourceSha256: sourceSha256,
      scriptSourceBytes: sourceBytes.length,
      scriptId: this.#script.scriptId,
      pauseScriptId,
    });
  }

  async #readGlobalContext(storedOptions) {
    const runtime = this.#profile.realRuntime;
    const season = await this.#lease.page.evaluate(() => {
      const matches = [...document.body.innerText.matchAll(/Season\s+(\d+)\s*:/g)]
        .map(match => Number(match[1]));
      const unique = [...new Set(matches)];
      return unique.length === 1 ? unique[0] : null;
    });
    if (!Number.isInteger(season)) {
      throw new MaxrollProviderError(ERROR_CODES.INPUT_READBACK_UNVERIFIED,
        'runtime season could not be read unambiguously from the planner UI');
    }
    const expectedShared = this.#semantics.options?.shared ?? {};
    const optionDefinitions = runtime.optionReadbackDefinitions ?? {};
    const needsBoundControls = Object.entries(this.#semantics.options ?? {})
      .some(([optionId]) => Object.values(optionDefinitions[optionId]?.params ?? {})
        .some(rule => rule?.kind === 'max' && rule.boundControl));
    if (Object.keys(expectedShared).length === 0 && !needsBoundControls) {
      return Object.freeze({ season, shared: {}, controls: Object.freeze([]) });
    }
    if (!runtime.sharedOptionReadback || !runtime.statsWidgetSelector
        || !runtime.settingsGroupSelector || !runtime.settingsGroupTitleSelector) {
      throw new MaxrollProviderError(ERROR_CODES.INPUT_READBACK_UNVERIFIED,
        'runtime profile has no shared option UI read-back strategy');
    }
    const dismiss = this.#lease.page.getByRole('button', {
      name: runtime.dismissButton, exact: true,
    });
    if (await dismiss.count() && await dismiss.first().isVisible()) await dismiss.first().click();
    await this.#lease.page.locator(`${runtime.statsWidgetSelector} button`).first().click();
    const effectsTab = this.#lease.page.getByText(runtime.effectsTabLabel, { exact: true }).last();
    await effectsTab.waitFor({ state: 'visible',
      timeout: runtime.interactionTimeoutMs ?? 10_000 });
    await effectsTab.click();
    const controls = await this.#lease.page.evaluate(config => {
      const result = [];
      for (const group of document.querySelectorAll(config.groupSelector)) {
        const groupName = group.querySelector(config.groupTitleSelector)?.textContent?.trim();
        if (!groupName) continue;
        for (const labelNode of group.querySelectorAll('label')) {
          const label = labelNode.querySelector('[class*="Params__name"]')?.textContent?.trim()
            ?? labelNode.textContent?.trim();
          const checkbox = labelNode.querySelector('input[type="checkbox"]');
          const number = labelNode.querySelector('input[type="number"]');
          const selected = labelNode.querySelector('[class*="Select__value"] span');
          if (checkbox) result.push({ group: groupName, label, kind: 'checkbox',
            checked: checkbox.checked });
          else if (number) result.push({ group: groupName, label, kind: 'number',
            value: Number(number.value), max: Number(number.max) });
          else if (selected) result.push({ group: groupName, label, kind: 'select',
            value: selected.textContent?.trim() });
        }
      }
      return result;
    }, { groupSelector: runtime.settingsGroupSelector,
      groupTitleSelector: runtime.settingsGroupTitleSelector });
    await this.#lease.page.keyboard.press('Escape');
    return Object.freeze({ season,
      controls: Object.freeze(controls.map(Object.freeze)),
      shared: Object.keys(expectedShared).length === 0 ? {}
        : resolveSharedOptionControls(expectedShared, controls,
          runtime.sharedOptionReadback, storedOptions.shared) });
  }

  async #readDisplayMetrics(observedMetricDefinitions) {
    const runtime = this.#profile.realRuntime;
    await this.#lease.page.waitForFunction(config => {
      const sections = [...document.querySelectorAll(config.statsSectionSelector)];
      const labels = new Set(sections.flatMap(section => [...section.querySelectorAll('li')]
        .map(row => row.querySelector(':scope > span')?.textContent?.trim()).filter(Boolean)));
      return sections.length >= Object.keys(config.categoryLabels).length + 1
        && config.requiredLabels.every(label => labels.has(label));
    }, {
      statsSectionSelector: runtime.statsSectionSelector,
      categoryLabels: runtime.categoryLabels,
      requiredLabels: runtime.metricLabelAllowlist ?? [],
    }, { timeout: runtime.captureTimeoutMs ?? 30_000 });
    const rows = await this.#lease.page.evaluate(config => {
      const output = [];
      for (const section of document.querySelectorAll(config.statsSectionSelector)) {
        const heading = (section.querySelector('h3')?.textContent ?? '').trim();
        const sectionKey = config.categoryLabels[heading.toUpperCase()]
          ?? (heading === '' ? 'summary' : null);
        if (!sectionKey) continue;
        for (const row of section.querySelectorAll('li')) {
          const spans = row.querySelectorAll(':scope > span');
          if (spans.length < 2) continue;
          output.push({
            section: sectionKey,
            label: spans[0].textContent.trim(),
            displayValue: spans[1].textContent.trim(),
          });
        }
      }
      return output;
    }, {
      statsSectionSelector: runtime.statsSectionSelector,
      categoryLabels: runtime.categoryLabels,
    });
    const displayCatalog = this.#profile.realRuntime.metricDisplayCatalog
      ?? this.#profile.metricCatalog;
    const catalog = new Map(displayCatalog
      .map(metric => [`${metric.category}|${metric.name}`, metric]));
    const totals = new Map();
    for (const row of rows) {
      const key = `${row.section}|${row.label}`;
      totals.set(key, (totals.get(key) ?? 0) + 1);
    }
    const occurrences = new Map();
    return rows.map(row => {
      const definition = catalog.get(`${row.section}|${row.label}`);
      const observedIds = observedMetricDefinitions.get(row.label);
      const observedInternalId = observedIds?.size === 1 ? [...observedIds][0] : null;
      const internalId = definition?.internalId ?? observedInternalId ?? null;
      const baseAnchor = `${row.section}|${row.label}`;
      const occurrence = (occurrences.get(baseAnchor) ?? 0) + 1;
      occurrences.set(baseAnchor, occurrence);
      return Object.freeze({
        metricId: internalId == null ? null : `maxroll.heroDetails.${internalId}`,
        internalId,
        labelAnchor: totals.get(baseAnchor) > 1 ? `${baseAnchor}#${occurrence}` : baseAnchor,
        section: row.section,
        label: row.label,
        displayValue: row.displayValue,
        unit: row.displayValue.endsWith('%') ? '%' : null,
        status: 'OBSERVED',
        provenance: 'MAXROLL_UI_DOM',
      });
    });
  }

  async #finalizeDiscoveredMetrics(capture) {
    const runtime = this.#profile.realRuntime;
    const rows = await this.#lease.page.waitForFunction(config => {
      const sections = [...document.querySelectorAll(config.statsSectionSelector)];
      const values = sections.flatMap(section => {
        const heading = (section.querySelector('h3')?.textContent ?? '').trim();
        const sectionKey = config.categoryLabels[heading.toUpperCase()]
          ?? (heading === '' ? 'summary' : null);
        if (!sectionKey) return [];
        return [...section.querySelectorAll('li')].map(row => ({ section: sectionKey,
          label: row.querySelector(':scope > span')?.textContent?.trim() }))
          .filter(row => Boolean(row.label));
      });
      const unique = [...new Set(values.map(row => row.label))];
      const requiredComplete = !config.requiredLabels
        || config.requiredLabels.every(label => unique.includes(label));
      return sections.length >= Object.keys(config.categoryLabels).length + 1
        && values.length && requiredComplete
        ? values : false;
    }, {
      statsSectionSelector: runtime.statsSectionSelector,
      categoryLabels: runtime.categoryLabels,
      requiredLabels: runtime.metricLabelAllowlist ?? null,
    }, { timeout: runtime.captureTimeoutMs ?? 30_000 }).then(handle => handle.jsonValue());
    const configured = runtime.metricLabelAllowlist;
    const labels = [...new Set(rows.map(row => row.label))];
    const requiredLabels = Array.isArray(configured) ? configured : labels;
    const missingLabels = requiredLabels.filter(label => !labels.includes(label));
    if (missingLabels.length) throw new MaxrollProviderError(ERROR_CODES.METRICS_INCOMPLETE,
      'display metric enumeration is incomplete', { details: { missingLabels } });
    const applicableRows = rows.filter(row => requiredLabels.includes(row.label));
    const inventory = resolveApplicableMetricInventory({ rows: applicableRows,
      observedMetricDefinitions: capture.observedMetricDefinitions,
      metricCatalog: runtime.metricDisplayCatalog ?? this.#profile.metricCatalog,
      displayOnly: runtime.displayOnlyMetricInventory ?? [] });
    capture.accumulator.finalize(inventory.expectedIds);
    if (!capture.accumulator.complete) throw new MaxrollProviderError(ERROR_CODES.METRICS_INCOMPLETE,
      'runtime metric enumeration completed before all applicable raw metrics were captured', {
        details: { observedMetricIds: capture.accumulator.observedIds,
          missingMetricIds: capture.accumulator.missingIds },
      });
    capture.resolve();
  }

  #rawMetrics(capture, displayMetrics) {
    if (this.#profile.realRuntime.discoverMetricCatalog !== true) {
      return this.#profile.metricCatalog;
    }
    const displayed = new Map(displayMetrics
      .filter(metric => Number.isInteger(metric.internalId))
      .map(metric => [metric.internalId, metric]));
    return capture.accumulator.observedIds.map(internalId => {
      const display = displayed.get(internalId);
      return Object.freeze({
        id: `maxroll.heroDetails.${internalId}`,
        internalId,
        category: display?.section ?? 'runtime',
        name: capture.accumulator.label(internalId) ?? display?.label ?? String(internalId),
        rawValueType: 'finite-number',
      });
    });
  }

  #assertHealthy() {
    if (this.#closed) throw new MaxrollProviderError(ERROR_CODES.SESSION_INVALIDATED,
      'attestation observer is closed');
    if (this.#runtimeFailure) throw this.#runtimeFailure;
  }
}

function isNetworkUrl(value) {
  return typeof value === 'string' && /^(?:https?|wss?):\/\//i.test(value);
}

module.exports = {
  CalculationEpochAccumulator,
  MaxrollRuntimeAttestationObserver,
  exactOptionReadback,
  resolveApplicableMetricInventory,
  inputSemantics,
  normalizedExpectedOptions,
  normalizedProfile,
  resolveSharedOptionControls,
  semanticHash,
};
