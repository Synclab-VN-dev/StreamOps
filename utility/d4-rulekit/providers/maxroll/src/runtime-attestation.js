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
  return sha256(Buffer.from(JSON.stringify(canonicalize(value))));
}

function normalizedProfile(profile) {
  const normalized = structuredClone(profile);
  delete normalized.id;
  return normalized;
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
    sections: Object.freeze(Object.fromEntries([
      'items', 'skillTree', 'skillBar', 'paragon', 'warPlans', 'world',
      'specialization', 'mercenary',
    ].map(name => [name, semanticHash(profile[name])]))),
  });
}

class CalculationEpochAccumulator {
  #expected;
  #epochKey = null;
  #values = new Map();
  #labels = new Map();
  #consistentDuplicates = 0;

  constructor(expectedInternalIds) {
    this.#expected = new Set(expectedInternalIds);
    if (this.#expected.size === 0) {
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
    if (!this.#expected.has(internalId)) return this.complete;
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

  get complete() { return this.#values.size === this.#expected.size; }
  get size() { return this.#values.size; }
  get epochKey() { return this.#epochKey; }
  get consistentDuplicates() { return this.#consistentDuplicates; }
  value(internalId) { return this.#values.get(internalId); }
  label(internalId) { return this.#labels.get(internalId); }

  assertComplete() {
    if (!this.complete) {
      throw new MaxrollProviderError(ERROR_CODES.METRICS_INCOMPLETE,
        `calculation epoch ended with ${this.#values.size}/${this.#expected.size} metrics`);
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
    return Object.freeze({ initialBreakpointLocations: breakpoint.locations?.length ?? 0 });
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
      await capture.completion;
      await this.#pauseChain;
      const engine = await this.#engineEvidence();
      const displayMetrics = await this.#readDisplayMetrics(capture.observedMetricDefinitions);
      result = Object.freeze({
        captureId: capture.id,
        profileReadback: Object.freeze({ ...capture.profileReadback }),
        engine,
        rawMetrics: Object.freeze(this.#profile.metricCatalog.map(definition => Object.freeze({
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
    let resolveCompletion;
    let rejectCompletion;
    const completion = new Promise((resolve, reject) => {
      resolveCompletion = resolve;
      rejectCompletion = reject;
    });
    const capture = {
      id: crypto.randomUUID(),
      expected,
      accumulator: new CalculationEpochAccumulator(expected),
      observedMetricDefinitions: new Map(),
      epochObjectId: null,
      epochIdentitySha256: null,
      epochComparisons: 0,
      pauseOrdinal: 0,
      matchedPauseOrdinal: null,
      firstMetricPauseOrdinal: null,
      lastMetricPauseOrdinal: null,
      profileReadback: null,
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
        : 'timed out waiting for exact runtime semantic read-back')),
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
      if (!capture || !frame) return;
      capture.pauseOrdinal += 1;
      capture.pauseScriptId ??= frame.location?.scriptId ?? null;
      const readback = await this.#evaluate(frame.callFrameId,
        this.#profile.realRuntime.attestationReadbackExpression);
      const observedProfile = readback?.profile;
      const observedItems = readback?.items;
      const sameIdentity = observedProfile?.name === this.#semantics.identity.name
        && observedProfile?.class === this.#semantics.identity.class
        && observedProfile?.level === this.#semantics.identity.level
        && observedProfile?.worldTier === this.#semantics.identity.worldTier;
      if (!sameIdentity) return;
      const profileSha256 = semanticHash(normalizedProfile(observedProfile));
      const itemsSha256 = semanticHash(observedItems);
      if (profileSha256 !== this.#semantics.profileSha256
          || itemsSha256 !== this.#semantics.itemsSha256) {
        throw new MaxrollProviderError(ERROR_CODES.READBACK_MISMATCH,
          'runtime semantic state does not match the exported build', {
            details: { profileSha256, itemsSha256 },
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
        capture.observedMetricDefinitions.set(metric.label, internalId);
      }
      if (!capture.expected.has(internalId)) return;
      capture.firstMetricPauseOrdinal ??= capture.pauseOrdinal;
      capture.lastMetricPauseOrdinal = capture.pauseOrdinal;
      if (capture.accumulator.observe({ epochKey, internalId, rawValue: metric.raw,
        label: metric.label })) capture.resolve();
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
      capture.epochObjectId = currentObjectId;
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
    if (!capture.epochObjectId) return;
    const objectId = capture.epochObjectId;
    capture.epochObjectId = null;
    await this.#cdp.send('Runtime.releaseObject', { objectId });
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

  async #readDisplayMetrics(observedMetricDefinitions) {
    const runtime = this.#profile.realRuntime;
    await this.#lease.page.waitForFunction(config => {
      const sections = [...document.querySelectorAll(config.statsSectionSelector)];
      const rows = sections.reduce((count, section) => count + section.querySelectorAll('li').length, 0);
      return sections.length >= Object.keys(config.categoryLabels).length + 1
        && rows >= config.expectedRawMetrics;
    }, {
      statsSectionSelector: runtime.statsSectionSelector,
      categoryLabels: runtime.categoryLabels,
      expectedRawMetrics: runtime.expectedRawMetrics,
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
    const catalog = new Map(this.#profile.metricCatalog
      .map(metric => [`${metric.category}|${metric.name}`, metric]));
    return rows.map(row => {
      const definition = catalog.get(`${row.section}|${row.label}`);
      const observedInternalId = observedMetricDefinitions.get(row.label);
      const internalId = definition?.internalId ?? observedInternalId ?? null;
      return Object.freeze({
        metricId: internalId == null ? null : `maxroll.heroDetails.${internalId}`,
        internalId,
        labelAnchor: `${row.section}|${row.label}`,
        section: row.section,
        label: row.label,
        displayValue: row.displayValue,
        unit: row.displayValue.endsWith('%') ? '%' : null,
        status: 'OBSERVED',
        provenance: 'MAXROLL_UI_DOM',
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
  inputSemantics,
  normalizedProfile,
  semanticHash,
};
