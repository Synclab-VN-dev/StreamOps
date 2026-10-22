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
  validateSafeUrl,
  validateSnapshotId,
} = require('./policy');
const { sha256 } = require('./store');

const DEFAULT_CAPTURE_OPTIONS = Object.freeze({
  timeoutMs: 30_000,
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
      if (error instanceof WebSnapshotError) throw error;
      if (abortKind === 'timeout') {
        throw snapshotError(SNAPSHOT_ERROR_CODES.CAPTURE_TIMEOUT,
          'snapshot capture timed out', error);
      }
      if (abortKind === 'cancelled' || controller.signal.aborted) {
        throw snapshotError(SNAPSHOT_ERROR_CODES.CAPTURE_CANCELLED,
          'snapshot capture was cancelled', error);
      }
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
    const fail = error => {
      if (!fatalError) fatalError = error;
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
        const requestAllowed = ['GET', 'HEAD'].includes(method)
          && !hasSensitiveRequestHeaders(request.headers())
          && (!options.allowResource || await options.allowResource(Object.freeze({
            method, url: safeUrl, resourceType: request.resourceType(),
          })));
        if (!requestAllowed) {
          blocked.push(Object.freeze({ method, url: sanitizeUrlForDiagnostics(safeUrl) }));
          await route.abort('blockedbyclient').catch(() => {});
          return;
        }
        await route.continue();
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
      void task.finally(() => pending.delete(task));
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
    try {
      const work = (async () => {
        await lease.page.goto(options.url, {
          waitUntil: 'networkidle',
          timeout: options.timeoutMs,
        });
        if (options.interact) {
          await options.interact(Object.freeze({ page: lease.page, signal }));
          await lease.page.waitForLoadState('networkidle', { timeout: options.timeoutMs });
        }
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
          blockedRequests: Object.freeze(blocked),
          serviceWorkerPolicy: 'block',
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
      ? Buffer.alloc(0) : await response.body();
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
      sensitiveJsonFields,
      sensitiveResponseNames,
    };
    for (const name of ['timeoutMs', 'maxResources', 'maxResourceBytes', 'maxTotalBytes']) {
      if (!Number.isInteger(normalized[name]) || normalized[name] < 1) {
        throw snapshotError(SNAPSHOT_ERROR_CODES.INVALID_OPTIONS,
          `${name} must be a positive integer`);
      }
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

  #log(event, fields) {
    try {
      this.#logger?.(Object.freeze({ component: 'web-snapshot-manager', event, ...fields }));
    } catch {
      // Diagnostics must not control snapshot lifecycle.
    }
  }
}

module.exports = { DEFAULT_CAPTURE_OPTIONS, WebSnapshotManager };
