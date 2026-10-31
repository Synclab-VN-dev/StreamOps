'use strict';

const crypto = require('node:crypto');
const playwrightPackage = require('playwright-core/package.json');
const { NetworkInterceptor, resourceKey } = require('./interceptor');
const { SNAPSHOT_ERROR_CODES, WebSnapshotError, snapshotError } = require('./errors');
const {
  DEFAULT_SENSITIVE_JSON_NAMES,
  DEFAULT_SENSITIVE_QUERY_NAMES,
  containsSensitiveLocation,
  hasSensitiveRequestHeaders,
  normalizeOrigins,
  redactSensitiveJson,
  sanitizeResponseHeaders,
  sanitizeUrlForDiagnostics,
  stripSensitiveRequestHeaders,
  validateSafeUrl,
  validateSnapshotId,
} = require('./policy');
const { sha256 } = require('./store');

const DEFAULT_CAPTURE_OPTIONS = Object.freeze({
  timeoutMs: 30_000,
  responseBodyTimeoutMs: 30_000,
  maxResources: 5_000,
  maxResourceBytes: 32 * 1024 * 1024,
  maxTotalBytes: 256 * 1024 * 1024,
});

class WebSnapshotManager {
  #browser;
  #store;
  #interceptor;
  #logger;

  constructor({ browser, store, interceptor = new NetworkInterceptor(), logger } = {}) {
    if (!browser || typeof browser.withLease !== 'function') {
      throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS,
        'WebSnapshotManager requires BrowserInfrastructure-compatible composition');
    }
    if (!store || !['save', 'load', 'list', 'verify', 'loadPackage']
      .every(method => typeof store[method] === 'function')) {
      throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS,
        'WebSnapshotManager requires a SnapshotStore-compatible implementation');
    }
    if (!interceptor || typeof interceptor.mount !== 'function') {
      throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS,
        'WebSnapshotManager requires a NetworkInterceptor-compatible implementation');
    }
    if (logger !== undefined && typeof logger !== 'function') {
      throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS, 'logger must be a function');
    }
    this.#browser = browser;
    this.#store = store;
    this.#interceptor = interceptor;
    this.#logger = logger;
  }

  async capture(options = {}) {
    const normalized = this.#validateCaptureOptions(options);
    const controller = new AbortController();
    let abortKind = null;
    const onExternalAbort = () => {
      abortKind = 'cancelled';
      controller.abort();
    };
    if (normalized.signal?.aborted) onExternalAbort();
    else normalized.signal?.addEventListener('abort', onExternalAbort, { once: true });
    const timer = setTimeout(() => {
      abortKind = 'timeout';
      controller.abort();
    }, normalized.timeoutMs);
    const started = Date.now();
    try {
      return await this.#browser.withLease({
        signal: controller.signal,
        timeoutMs: normalized.timeoutMs,
        leaseTimeoutMs: Math.max(normalized.timeoutMs + 1_000, normalized.timeoutMs * 2),
      }, lease => this.#captureWithLease(lease, normalized, controller.signal, started));
    } catch (error) {
      if (abortKind === 'timeout') {
        throw snapshotError(SNAPSHOT_ERROR_CODES.CAPTURE_TIMEOUT,
          'snapshot capture timed out', error);
      }
      if (abortKind === 'cancelled' || controller.signal.aborted) {
        throw snapshotError(SNAPSHOT_ERROR_CODES.CAPTURE_CANCELLED,
          'snapshot capture was cancelled', error);
      }
      if (error instanceof WebSnapshotError) throw error;
      throw error;
    } finally {
      clearTimeout(timer);
      normalized.signal?.removeEventListener('abort', onExternalAbort);
    }
  }

  async save(snapshot) {
    return this.#store.save(snapshot);
  }

  async load(snapshotId) {
    return this.#store.load(snapshotId);
  }

  async list(filter) {
    return this.#store.list(filter);
  }

  async verify(snapshotId) {
    return this.#store.verify(snapshotId);
  }

  async mount(lease, snapshotId, options) {
    validateSnapshotId(snapshotId);
    const snapshotPackage = await this.#store.loadPackage(snapshotId);
    return this.#interceptor.mount(lease, snapshotPackage, options);
  }

  async #captureWithLease(lease, options, signal, started) {
    const resources = new Map();
    const blocked = [];
    const pending = new Set();
    let totalBytes = 0;
    let fatalError = null;
    let blockedWebSocketCount = 0;
    let excludedResponseCount = 0;
    let redactedResponseCount = 0;
    let strippedSensitiveRequestCount = 0;
    const activeRequests = new Set();
    const discovered = new Map();
    const failedRequests = new Map();
    let lastActivity = Date.now();
    let wakeCompletion = null;
    const activity = () => { lastActivity = Date.now(); wakeCompletion?.(); };
    const finishRequest = (request, failed = false) => {
      if (!activeRequests.delete(request)) return;
      const method = request.method().toUpperCase();
      const url = validateSafeUrl(request.url(), options.allowedOrigins, options.sensitiveQueryParameters);
      if (failed) failedRequests.set(`${method} ${url}`, {method, url});
      activity();
    };
    const requestFinished = request => finishRequest(request);
    const requestFailed = request => finishRequest(request, true);
    const waitActivity = milliseconds => new Promise((resolve, reject) => {
      let timer;
      const cleanup = () => { clearTimeout(timer); signal.removeEventListener('abort', aborted); wakeCompletion = null; };
      const done = () => { cleanup(); resolve(); };
      const aborted = () => { cleanup(); reject(snapshotError(SNAPSHOT_ERROR_CODES.CAPTURE_CANCELLED, 'capture completion aborted')); };
      wakeCompletion = done;
      signal.addEventListener('abort', aborted, {once:true});
      if (signal.aborted) aborted();
      else if (milliseconds !== null) timer = setTimeout(done, milliseconds);
    });
    const awaitCompletion = async () => {
      const minimumUntil = Date.now() + options.completion.minimumObservationMs;
      while (true) {
        if (fatalError) throw fatalError;
        if (signal.aborted) throw snapshotError(SNAPSHOT_ERROR_CODES.CAPTURE_CANCELLED, 'capture completion aborted');
        if (activeRequests.size === 0 && pending.size === 0) {
          const remaining = Math.max(minimumUntil, lastActivity + options.completion.quietWindowMs) - Date.now();
          if (remaining <= 0) break;
          await waitActivity(remaining);
        } else await waitActivity(null);
      }
      const missing = [...discovered.keys()].filter(key => !resources.has(key));
      if (missing.length) throw snapshotError(SNAPSHOT_ERROR_CODES.RESOURCE_MISSING, 'capture ended with missing in-scope request bodies');
      for (const resource of resources.values()) {
        if (resource.method !== 'GET' || resource.status < 200 || resource.status >= 300) {
          throw snapshotError(SNAPSHOT_ERROR_CODES.RESOURCE_MISSING, 'capture cannot confirm an in-scope entity body');
        }
      }
    };
    const fail = error => {
      if (!fatalError) fatalError = error;
      activity();
      void lease.page.close().catch(() => {});
    };
    const routeHandler = async route => {
      try {
        const request = route.request();
        const method = request.method().toUpperCase();
        let safeUrl;
        try {
          safeUrl = validateSafeUrl(request.url(), options.allowedOrigins,
            options.sensitiveQueryParameters);
        } catch {
          blocked.push(Object.freeze({ method, url: sanitizeUrlForDiagnostics(request.url()) }));
          await route.abort('blockedbyclient').catch(() => {});
          return;
        }
        const freshAnonymous = options.requestHeaderPolicy === 'fresh-anonymous-context';
        const requestHeaders = freshAnonymous ? null : request.headers();
        const hasSensitiveHeaders = freshAnonymous ? false :
          hasSensitiveRequestHeaders(requestHeaders);
        const stripSensitiveHeaders = hasSensitiveHeaders &&
          options.requestHeaderPolicy === 'strip-sensitive';
        const requestAllowed = ['GET', 'HEAD'].includes(method)
          && (!hasSensitiveHeaders || stripSensitiveHeaders)
          && (!options.allowResource || await options.allowResource(Object.freeze({
            method, url: safeUrl, resourceType: request.resourceType(),
          })));
        if (!requestAllowed) {
          blocked.push(Object.freeze({ method, url: sanitizeUrlForDiagnostics(safeUrl) }));
          await route.abort('blockedbyclient').catch(() => {});
          return;
        }
        if (options.completion) {
          activeRequests.add(request);
          const key = `${method} ${safeUrl}`;
          if (!discovered.has(key)) discovered.set(key, {method, url:safeUrl, resourceType:request.resourceType()});
          activity();
        }
        if (stripSensitiveHeaders) {
          strippedSensitiveRequestCount += 1;
          await route.continue({ headers: stripSensitiveRequestHeaders(requestHeaders) });
        } else {
          await route.continue();
        }
      } catch (error) {
        fail(error);
        await route.abort('failed').catch(() => {});
      }
    };
    const responseHandler = response => {
      const task = this.#recordResponse(response, resources, options, currentTotal => {
        totalBytes = currentTotal;
      }, () => totalBytes, event => {
        if (event === 'excluded') excludedResponseCount += 1;
        if (event === 'redacted') redactedResponseCount += 1;
      }).catch(fail);
      pending.add(task);
      void task.finally(() => { pending.delete(task); if (options.completion) activity(); });
    };
    const abortPromise = new Promise((_, reject) => {
      if (signal.aborted) {
        reject(snapshotError(SNAPSHOT_ERROR_CODES.CAPTURE_CANCELLED,
          'snapshot capture was cancelled'));
        return;
      }
      signal.addEventListener('abort', () => {
        void lease.page.close().catch(() => {});
        reject(snapshotError(SNAPSHOT_ERROR_CODES.CAPTURE_CANCELLED,
          'snapshot capture was cancelled'));
      }, { once: true });
    });
    await lease.context.addInitScript(() => {
      try {
        Object.defineProperty(globalThis, 'WebSocket', {
          configurable: true,
          value: class BlockedSnapshotWebSocket {
            constructor() { throw new Error('web sockets disabled during snapshot capture'); }
          },
        });
        if (navigator.serviceWorker) {
          Object.defineProperty(navigator.serviceWorker, 'register', {
            configurable: true,
            value: () => Promise.reject(new Error('service workers disabled during snapshot capture')),
          });
        }
      } catch {
        // Browser context serviceWorkers=block remains the primary policy.
      }
    });
    if (typeof lease.context.routeWebSocket === 'function') {
      await lease.context.routeWebSocket('**/*', async webSocket => {
        blockedWebSocketCount += 1;
        await webSocket.close({ code: 1008, reason: 'snapshot capture excludes WebSocket traffic' })
          .catch(() => {});
      });
    }
    await lease.context.route('**/*', routeHandler);
    lease.page.on('response', responseHandler);
    if (options.completion) {
      lease.page.on('requestfinished', requestFinished);
      lease.page.on('requestfailed', requestFailed);
    }
    try {
      const work = (async () => {
        await lease.page.goto(options.url, {
          waitUntil: options.navigationWaitUntil,
          timeout: options.timeoutMs,
        });
        if (options.interact) {
          await options.interact(Object.freeze({ page: lease.page, signal }));
          await lease.page.waitForLoadState(options.settleWaitUntil,
            { timeout: options.timeoutMs });
        }
        if (options.completion) await awaitCompletion();
        await Promise.all([...pending]);
        if (fatalError) throw fatalError;
      })();
      try {
        await Promise.race([work, abortPromise]);
      } catch (error) {
        if (fatalError) throw fatalError;
        throw error;
      }
      if (fatalError) throw fatalError;
      const browserVersion = lease.context.browser()?.version?.() ?? null;
      const draft = Object.freeze({
        schemaVersion: 'web-snapshot-draft/v1',
        snapshotId: options.snapshotId,
        sourceUrl: options.url,
        capturedAt: new Date().toISOString(),
        allowedOrigins: options.allowedOrigins,
        site: options.site,
        version: options.version,
        browserVersion,
        playwrightVersion: playwrightPackage.version,
        resources: Object.freeze([...resources.values()]
          .sort((left, right) => left.key.localeCompare(right.key))),
        capture: Object.freeze({
          durationMs: Date.now() - started,
          blockedRequestCount: blocked.length,
          blockedWebSocketCount,
          excludedResponseCount,
          redactedResponseCount,
          strippedSensitiveRequestCount,
          blockedRequests: Object.freeze(blocked),
          serviceWorkerPolicy: 'block',
          ...(options.completion ? {completion: Object.freeze({
            policy: 'bounded-quiescence/v1',
            minimumObservationMs: options.completion.minimumObservationMs,
            quietWindowMs: options.completion.quietWindowMs,
            pendingRequests: activeRequests.size + pending.size,
            failedRequests: Object.freeze([...failedRequests.entries()].filter(([key]) => !resources.has(key)).map(([,value]) => value)),
            nodes: Object.freeze([...discovered.values()]),
            roots: Object.freeze([{method:'GET',url:options.url}]),
            // Actual routed requests attributed to this navigation, not nodes
            // fabricated later from the saved manifest resource list.
            edges: Object.freeze([...discovered.values()].filter(node => node.url !== options.url || node.method !== 'GET').map(node => ({from:{method:'GET',url:options.url},to:{method:node.method,url:node.url}}))),
          })} : {}),
        }),
      });
      this.#log('captured', {
        snapshotId: draft.snapshotId,
        resourceCount: draft.resources.length,
        totalBytes,
      });
      return draft;
    } finally {
      lease.page.off('response', responseHandler);
      lease.page.off('requestfinished', requestFinished);
      lease.page.off('requestfailed', requestFailed);
      await lease.context.unroute('**/*', routeHandler).catch(() => {});
      await Promise.allSettled([...pending]);
    }
  }

  async #recordResponse(response, resources, options, setTotal, getTotal, onPolicy) {
    const request = response.request();
    const method = request.method().toUpperCase();
    if (!['GET', 'HEAD'].includes(method)) return;
    let url;
    try {
      url = validateSafeUrl(response.url(), options.allowedOrigins,
        options.sensitiveQueryParameters);
    } catch {
      return;
    }
    let body = method === 'HEAD' || [204, 205, 304].includes(response.status())
      || (response.status() >= 300 && response.status() < 400)
      ? Buffer.alloc(0) : await this.#readResponseBody(response, options.responseBodyTimeoutMs);
    if (body.length > options.maxResourceBytes) {
      throw snapshotError(SNAPSHOT_ERROR_CODES.RESOURCE_LIMIT,
        'captured resource exceeds maxResourceBytes');
    }
    let headers = sanitizeResponseHeaders(await response.allHeaders());
    const descriptor = Object.freeze({
      method,
      url,
      status: response.status(),
      headers: Object.freeze({ ...headers }),
      contentType: headers['content-type'] ?? null,
      body: Buffer.from(body),
    });
    const decision = options.responsePolicy
      ? await options.responsePolicy(descriptor)
      : undefined;
    if (decision !== undefined
        && (!decision || typeof decision !== 'object' || Array.isArray(decision))) {
      throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS,
        'responsePolicy must return an action object');
    }
    const action = decision?.action ?? 'default';
    if (!['default', 'exclude', 'redact', 'include-sensitive'].includes(action)) {
      throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS,
        'responsePolicy returned an unsupported action');
    }
    if (action === 'exclude') {
      onPolicy('excluded');
      return;
    }
    if (action === 'redact') {
      if (decision.body === undefined) {
        throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS,
          'responsePolicy redact action requires body');
      }
      try {
        body = Buffer.from(decision.body);
      } catch (error) {
        throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS,
          'responsePolicy redact body must be a string or byte array', error);
      }
      if (decision.headers !== undefined) headers = sanitizeResponseHeaders(decision.headers);
      onPolicy('redacted');
    }
    if (action !== 'include-sensitive') {
      const location = headers.location;
      if (location && containsSensitiveLocation(location, url, options.sensitiveResponseNames)) {
        throw snapshotError(SNAPSHOT_ERROR_CODES.SENSITIVE_RESPONSE,
          'redirect Location contains a sensitive parameter');
      }
      if (action === 'default') {
        const redacted = redactSensitiveJson(body, headers['content-type'],
          options.sensitiveJsonFields);
        if (redacted.redactedFields.length > 0) {
          body = redacted.body;
          onPolicy('redacted');
        }
      }
    }
    if (body.length > options.maxResourceBytes) {
      throw snapshotError(SNAPSHOT_ERROR_CODES.RESOURCE_LIMIT,
        'captured resource exceeds maxResourceBytes after response policy');
    }
    const key = resourceKey(method, url);
    const digest = sha256(body);
    const existing = resources.get(key);
    if (existing) {
      if (sha256(existing.body) !== digest || existing.status !== response.status()) {
        throw snapshotError(SNAPSHOT_ERROR_CODES.RESOURCE_CONFLICT,
          'same request identity produced conflicting responses');
      }
      return;
    }
    if (resources.size >= options.maxResources) {
      throw snapshotError(SNAPSHOT_ERROR_CODES.RESOURCE_LIMIT,
        'captured resource count exceeds maxResources');
    }
    const nextTotal = getTotal() + body.length;
    if (nextTotal > options.maxTotalBytes) {
      throw snapshotError(SNAPSHOT_ERROR_CODES.STORAGE_LIMIT,
        'captured bytes exceed maxTotalBytes');
    }
    setTotal(nextTotal);
    resources.set(key, Object.freeze({
      key,
      method,
      url,
      status: response.status(),
      headers,
      redirectedFrom: request.redirectedFrom()?.url() ?? null,
      body,
    }));
  }

  #validateCaptureOptions(options) {
    if (!options || typeof options !== 'object' || Array.isArray(options)) {
      throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS,
        'capture options must be an object');
    }
    const allowedOrigins = normalizeOrigins(options.allowedOrigins);
    const sensitiveQueryParameters = [
      ...DEFAULT_SENSITIVE_QUERY_NAMES,
      ...(options.capturePolicy?.sensitiveQueryParameters ?? []),
    ];
    const sensitiveJsonFields = [
      ...DEFAULT_SENSITIVE_JSON_NAMES,
      ...(options.capturePolicy?.sensitiveJsonFields ?? []),
    ];
    const sensitiveResponseNames = [
      ...DEFAULT_SENSITIVE_QUERY_NAMES,
      ...(options.capturePolicy?.sensitiveResponseNames ?? []),
    ];
    const url = validateSafeUrl(options.url, allowedOrigins, sensitiveQueryParameters);
    const snapshotId = options.snapshotId === undefined
      ? `snapshot-${Date.now()}-${crypto.randomUUID()}`
      : validateSnapshotId(options.snapshotId);
    const normalized = {
      ...DEFAULT_CAPTURE_OPTIONS,
      ...options,
      ...(options.capturePolicy ?? {}),
      snapshotId,
      url,
      allowedOrigins,
      sensitiveQueryParameters,
      signal: options.signal,
      interact: options.interact,
      allowResource: options.capturePolicy?.allowResource,
      responsePolicy: options.capturePolicy?.responsePolicy,
      requestHeaderPolicy: options.capturePolicy?.requestHeaderPolicy ?? 'block-sensitive',
      navigationWaitUntil: options.capturePolicy?.navigationWaitUntil ?? 'networkidle',
      settleWaitUntil: options.capturePolicy?.settleWaitUntil ?? 'networkidle',
      completion: options.capturePolicy?.completion ?? null,
      sensitiveJsonFields,
      sensitiveResponseNames,
    };
    for (const name of ['timeoutMs', 'responseBodyTimeoutMs', 'maxResources',
      'maxResourceBytes', 'maxTotalBytes']) {
      if (!Number.isInteger(normalized[name]) || normalized[name] < 1) {
        throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS,
          `${name} must be a positive integer`);
      }
    }
    if (normalized.completion !== null) {
      const completion = normalized.completion;
      if (!completion || typeof completion !== 'object' || Array.isArray(completion) ||
          Object.keys(completion).some(key => !['minimumObservationMs','quietWindowMs'].includes(key)) ||
          !Number.isInteger(completion.minimumObservationMs) || completion.minimumObservationMs < 1 ||
          !Number.isInteger(completion.quietWindowMs) || completion.quietWindowMs < 1 ||
          completion.minimumObservationMs >= normalized.timeoutMs || completion.quietWindowMs >= normalized.timeoutMs) {
        throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS, 'capture completion windows must be positive and bounded by operation timeout');
      }
      normalized.completion = Object.freeze({...completion});
    }
    if (normalized.interact !== undefined && typeof normalized.interact !== 'function') {
      throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS, 'interact must be a function');
    }
    if (normalized.allowResource !== undefined && typeof normalized.allowResource !== 'function') {
      throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS,
        'capturePolicy.allowResource must be a function');
    }
    if (normalized.responsePolicy !== undefined && typeof normalized.responsePolicy !== 'function') {
      throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS,
        'capturePolicy.responsePolicy must be a function');
    }
    if (!['block-sensitive', 'strip-sensitive', 'fresh-anonymous-context']
      .includes(normalized.requestHeaderPolicy)) {
      throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS,
        'capturePolicy.requestHeaderPolicy is invalid');
    }
    if (!['load', 'domcontentloaded', 'networkidle', 'commit']
      .includes(normalized.navigationWaitUntil)) {
      throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS,
        'capturePolicy.navigationWaitUntil is invalid');
    }
    if (!['load', 'domcontentloaded', 'networkidle'].includes(normalized.settleWaitUntil)) {
      throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS,
        'capturePolicy.settleWaitUntil is invalid');
    }
    for (const name of ['sensitiveJsonFields', 'sensitiveResponseNames']) {
      if (!Array.isArray(normalized[name])
          || normalized[name].some(value => typeof value !== 'string' || value.length === 0)) {
        throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS,
          `${name} must contain non-empty strings`);
      }
    }
    if (normalized.signal !== undefined && !(normalized.signal instanceof AbortSignal)) {
      throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS, 'signal must be an AbortSignal');
    }
    return Object.freeze(normalized);
  }

  async #readResponseBody(response, timeoutMs) {
    let timer;
    try {
      return await Promise.race([
        response.body(),
        new Promise((_, reject) => {
          timer = setTimeout(() => reject(snapshotError(
            SNAPSHOT_ERROR_CODES.CAPTURE_TIMEOUT,
            `response body capture timed out: ${sanitizeUrlForDiagnostics(response.url())}`)),
          timeoutMs);
        }),
      ]);
    } finally {
      clearTimeout(timer);
    }
  }

  #log(event, fields) {
    try {
      this.#logger?.(Object.freeze({ component: 'web-snapshot-manager', event, ...fields }));
    } catch {
      // Diagnostics must not control snapshot lifecycle.
    }
  }
}

module.exports = { DEFAULT_CAPTURE_OPTIONS, WebSnapshotManager };
