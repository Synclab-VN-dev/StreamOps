'use strict';

const { randomUUID } = require('crypto');
const { chromium } = require('playwright-core');
const { validateConfig, validateLeaseOptions } = require('./config');
const { BrowserLease } = require('./lease');
const { ERROR_CODES, infrastructureError } = require('./errors');

class BrowserInfrastructure {
  #config;
  #launcher;
  #browser = null;
  #pid = null;
  #state = 'stopped';
  #leases = new Map();
  #queue = [];
  #creating = 0;
  #creationPromises = new Set();
  #lifecycle = Promise.resolve();
  #generation = 0;
  #startedAt = null;
  #expectedClose = new WeakSet();
  #metrics = {
    launchCount: 0,
    launchFailures: 0,
    restartCount: 0,
    crashCount: 0,
    acquireRequested: 0,
    acquireSucceeded: 0,
    releaseCount: 0,
    queueTimeoutCount: 0,
    cancellationCount: 0,
    leaseExpirationCount: 0,
    peakContexts: 0,
    totalAcquireWaitMs: 0,
    lastLaunchDurationMs: null,
  };

  constructor(config = {}, dependencies = {}) {
    this.#config = validateConfig(config);
    this.#launcher = dependencies.launcher ?? chromium;
  }

  start(config) {
    return this.#serialize(async () => {
      if (this.#state === 'running') {
        if (config !== undefined) {
          const candidate = validateConfig({ ...this.#config, ...config });
          if (JSON.stringify(candidate) !== JSON.stringify(this.#config)) {
            throw infrastructureError(ERROR_CODES.INVALID_CONFIG,
              'cannot change config while infrastructure is running');
          }
        }
        return;
      }
      if (config !== undefined) this.#config = validateConfig({ ...this.#config, ...config });
      await this.#launch();
    });
  }

  stop() {
    return this.#serialize(async () => {
      if (this.#state === 'stopped') return;
      this.#state = 'stopped';
      await this.#shutdown(ERROR_CODES.CANCELLED, 'browser infrastructure stopped');
      this.#startedAt = null;
      this.#log('stopped');
    });
  }

  restart() {
    return this.#serialize(async () => {
      this.#state = 'restarting';
      await this.#shutdown(ERROR_CODES.BROWSER_DISCONNECTED,
        'lease invalidated by browser restart');
      this.#metrics.restartCount += 1;
      await this.#launch();
    });
  }

  getStatus() {
    return Object.freeze({
      state: this.#state,
      pid: this.#pid,
      activeLeases: this.#leases.size,
      pendingQueue: this.#queue.length,
      restartCount: this.#metrics.restartCount,
      uptimeMs: this.#startedAt === null ? 0 : Math.max(0, Date.now() - this.#startedAt),
    });
  }

  getMetrics() {
    return Object.freeze({
      ...this.#metrics,
      currentContexts: this.#leases.size + this.#creating,
      pendingQueue: this.#queue.length,
      averageAcquireWaitMs: this.#metrics.acquireSucceeded === 0
        ? 0 : this.#metrics.totalAcquireWaitMs / this.#metrics.acquireSucceeded,
    });
  }

  async acquire(options = {}) {
    const normalized = validateLeaseOptions(options, this.#config);
    this.#metrics.acquireRequested += 1;
    if (this.#state !== 'running' || !this.#browser?.isConnected()) {
      throw infrastructureError(ERROR_CODES.NOT_RUNNING, 'browser infrastructure is not running');
    }
    if (normalized.signal?.aborted) {
      this.#metrics.cancellationCount += 1;
      throw infrastructureError(ERROR_CODES.CANCELLED, 'lease acquisition cancelled');
    }
    const requestedAt = Date.now();
    if (this.#hasCapacity()) {
      return this.#reserveAndCreate(normalized, requestedAt);
    }
    if (this.#queue.length >= this.#config.maxQueue) {
      throw infrastructureError(ERROR_CODES.CAPACITY_EXCEEDED, 'lease queue capacity exceeded');
    }
    return new Promise((resolve, reject) => {
      const request = { normalized, requestedAt, resolve, reject, settled: false };
      request.timer = setTimeout(() => {
        if (!this.#removeQueued(request)) return;
        this.#metrics.queueTimeoutCount += 1;
        reject(infrastructureError(ERROR_CODES.QUEUE_TIMEOUT, 'lease acquisition timed out'));
      }, normalized.timeoutMs);
      if (normalized.signal) {
        request.onAbort = () => {
          if (!this.#removeQueued(request)) return;
          this.#metrics.cancellationCount += 1;
          reject(infrastructureError(ERROR_CODES.CANCELLED, 'lease acquisition cancelled'));
        };
        normalized.signal.addEventListener('abort', request.onAbort, { once: true });
      }
      this.#queue.push(request);
      this.#log('queued', { pendingQueue: this.#queue.length });
    });
  }

  async release(leaseId) {
    const record = this.#leases.get(leaseId);
    if (!record) return;
    this.#leases.delete(leaseId);
    clearTimeout(record.expiryTimer);
    record.lease._invalidate(infrastructureError(
      ERROR_CODES.LEASE_EXPIRED, `lease ${leaseId} has been released`));
    await this.#closeContext(record.context);
    this.#metrics.releaseCount += 1;
    this.#log('released', { leaseId });
    this.#dispatchQueue();
  }

  async withLease(options, run) {
    if (typeof run !== 'function') {
      throw infrastructureError(ERROR_CODES.INVALID_CONFIG, 'withLease run must be a function');
    }
    const lease = await this.acquire(options);
    try {
      return await run(lease);
    } finally {
      await lease.release();
    }
  }

  #serialize(operation) {
    const result = this.#lifecycle.then(operation, operation);
    this.#lifecycle = result.catch(() => {});
    return result;
  }

  async #launch() {
    const started = Date.now();
    try {
      const launchOptions = {
        ...this.#config.launchOptions,
        headless: this.#config.headless,
      };
      if (this.#config.executablePath) launchOptions.executablePath = this.#config.executablePath;
      const browser = await this.#launcher.launch(launchOptions);
      this.#browser = browser;
      this.#pid = await this.#readBrowserPid(browser);
      this.#generation += 1;
      const generation = this.#generation;
      browser.on('disconnected', () => this.#handleDisconnect(browser, generation));
      this.#state = 'running';
      this.#startedAt = Date.now();
      this.#metrics.launchCount += 1;
      this.#metrics.lastLaunchDurationMs = Date.now() - started;
      this.#log('started');
    } catch (error) {
      this.#state = 'stopped';
      this.#browser = null;
      this.#metrics.launchFailures += 1;
      throw error;
    }
  }

  async #shutdown(code, message) {
    const error = infrastructureError(code, message);
    const browser = this.#browser;
    this.#browser = null;
    this.#pid = null;
    this.#generation += 1;
    if (browser) this.#expectedClose.add(browser);
    this.#rejectQueue(error);
    await Promise.allSettled([...this.#creationPromises]);
    const records = [...this.#leases.values()];
    this.#leases.clear();
    await Promise.allSettled(records.map(record => {
      clearTimeout(record.expiryTimer);
      record.lease._invalidate(error);
      return this.#closeContext(record.context);
    }));
    if (browser) {
      await browser.close().catch(() => {});
    }
  }

  #handleDisconnect(browser, generation) {
    if (this.#expectedClose.has(browser) || generation !== this.#generation) return;
    if (browser !== this.#browser) return;
    this.#browser = null;
    this.#pid = null;
    this.#state = 'degraded';
    this.#metrics.crashCount += 1;
    const error = infrastructureError(ERROR_CODES.BROWSER_DISCONNECTED,
      'browser disconnected; explicit restart required');
    this.#rejectQueue(error);
    const records = [...this.#leases.values()];
    this.#leases.clear();
    for (const record of records) {
      clearTimeout(record.expiryTimer);
      record.lease._invalidate(error);
      this.#closeContext(record.context);
    }
    this.#log('disconnected');
  }

  #hasCapacity() {
    return this.#leases.size + this.#creating < this.#config.maxContexts;
  }

  #reserveAndCreate(options, requestedAt) {
    this.#creating += 1;
    const promise = this.#createReserved(options, requestedAt);
    this.#creationPromises.add(promise);
    return promise.finally(() => {
      this.#creationPromises.delete(promise);
      this.#creating -= 1;
      this.#dispatchQueue();
    });
  }

  async #createReserved(options, requestedAt) {
    const browser = this.#browser;
    const generation = this.#generation;
    try {
      const context = await browser.newContext(this.#config.contextOptions);
      if (options.signal?.aborted) {
        await this.#closeContext(context);
        this.#metrics.cancellationCount += 1;
        throw infrastructureError(ERROR_CODES.CANCELLED, 'lease acquisition cancelled');
      }
      if (this.#state !== 'running' || browser !== this.#browser || generation !== this.#generation) {
        await this.#closeContext(context);
        throw infrastructureError(ERROR_CODES.BROWSER_DISCONNECTED,
          'browser disconnected while creating lease');
      }
      const page = await context.newPage();
      if (options.signal?.aborted) {
        await this.#closeContext(context);
        this.#metrics.cancellationCount += 1;
        throw infrastructureError(ERROR_CODES.CANCELLED, 'lease acquisition cancelled');
      }
      const id = randomUUID();
      const lease = new BrowserLease({ id, context, page, owner: this });
      const expiryTimer = setTimeout(() => this.#expireLease(id), options.leaseTimeoutMs);
      expiryTimer.unref?.();
      this.#leases.set(id, { lease, context, expiryTimer });
      this.#metrics.acquireSucceeded += 1;
      this.#metrics.totalAcquireWaitMs += Date.now() - requestedAt;
      this.#metrics.peakContexts = Math.max(this.#metrics.peakContexts, this.#leases.size);
      context.once?.('close', () => this.#contextClosed(id));
      this.#log('acquired', { leaseId: id });
      return lease;
    } catch (error) {
      if (error?.code) throw error;
      throw infrastructureError(ERROR_CODES.BROWSER_DISCONNECTED,
        'failed to create browser context', error);
    }
  }

  #dispatchQueue() {
    while (this.#state === 'running' && this.#hasCapacity() && this.#queue.length > 0) {
      const request = this.#queue.shift();
      this.#settleQueueRequest(request);
      this.#reserveAndCreate(request.normalized, request.requestedAt)
        .then(request.resolve, request.reject);
    }
  }

  #removeQueued(request) {
    const index = this.#queue.indexOf(request);
    if (index === -1) return false;
    this.#queue.splice(index, 1);
    this.#settleQueueRequest(request);
    return true;
  }

  #settleQueueRequest(request) {
    clearTimeout(request.timer);
    if (request.normalized.signal && request.onAbort) {
      request.normalized.signal.removeEventListener('abort', request.onAbort);
    }
    request.settled = true;
  }

  #rejectQueue(error) {
    const queue = this.#queue.splice(0);
    for (const request of queue) {
      this.#settleQueueRequest(request);
      request.reject(error);
    }
  }

  async #expireLease(id) {
    const record = this.#leases.get(id);
    if (!record) return;
    this.#leases.delete(id);
    record.lease._invalidate(infrastructureError(
      ERROR_CODES.LEASE_EXPIRED, `lease ${id} expired`));
    this.#metrics.leaseExpirationCount += 1;
    await this.#closeContext(record.context);
    this.#dispatchQueue();
  }

  #contextClosed(id) {
    setImmediate(() => {
      const record = this.#leases.get(id);
      if (!record) return;
      this.#leases.delete(id);
      clearTimeout(record.expiryTimer);
      const disconnected = this.#state === 'degraded' || !this.#browser?.isConnected();
      record.lease._invalidate(infrastructureError(
        disconnected ? ERROR_CODES.BROWSER_DISCONNECTED : ERROR_CODES.LEASE_EXPIRED,
        disconnected ? 'browser disconnected' : `lease ${id} context closed`));
      this.#metrics.releaseCount += 1;
      this.#dispatchQueue();
    });
  }

  async #closeContext(context) {
    await context.close().catch(() => {});
  }

  async #readBrowserPid(browser) {
    if (typeof browser.newBrowserCDPSession !== 'function') return null;
    let session;
    try {
      session = await browser.newBrowserCDPSession();
      const result = await session.send('SystemInfo.getProcessInfo');
      const process = result.processInfo?.find(entry => entry.type === 'browser');
      return Number.isInteger(process?.id) ? process.id : null;
    } catch {
      return null;
    } finally {
      await session?.detach().catch(() => {});
    }
  }

  #log(event, fields = {}) {
    this.#config.logger?.(Object.freeze({
      component: 'browser-infrastructure',
      event,
      state: this.#state,
      ...fields,
    }));
  }
}

module.exports = { BrowserInfrastructure };
