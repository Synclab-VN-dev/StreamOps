'use strict';

const crypto = require('crypto');
const { bounded, SerialExecutor } = require('./async');
const { BuildStateManager } = require('./build-state-manager');
const { ResultCache } = require('./cache');
const { CalculationOrchestrator } = require('./calculation-orchestrator');
const { ApplicationError, ERROR_CODES } = require('./errors');
const { metricDelta, normalizeMetrics } = require('./normalizer');
const { ProviderRegistry } = require('./provider-registry');
const { SessionManager } = require('./session-manager');
const { clone, immutableCopy, sha256 } = require('./value');

const CONTRACT_VERSION = 'd4-rulekit-application/v1';

class D4RuleKitApplication {
  #registry;
  #sessions;
  #cache = new ResultCache();
  #orchestrator;
  #clock;
  #operationTimeoutMs;

  constructor(options = {}) {
    this.#registry = new ProviderRegistry(options.providers);
    this.#clock = options.clock ?? (() => Date.now());
    const maxSessions = positiveInteger(options.maxSessions, 100, 'maxSessions');
    const sessionTtlMs = positiveInteger(options.sessionTtlMs, 30 * 60_000, 'sessionTtlMs');
    this.#operationTimeoutMs = positiveInteger(options.operationTimeoutMs, 5_000, 'operationTimeoutMs');
    const cleanupTimeoutMs = positiveInteger(options.cleanupTimeoutMs, 1_000, 'cleanupTimeoutMs');
    this.#sessions = new SessionManager({
      maxSessions, ttlMs: sessionTtlMs, clock: this.#clock, scheduler: options.scheduler,
    });
    this.#orchestrator = new CalculationOrchestrator({ operationTimeoutMs: this.#operationTimeoutMs, cleanupTimeoutMs });
  }

  listProviders() {
    return this.#registry.list();
  }

  async createSession(options) {
    validateCreate(options);
    await this.#expireSessions();
    this.#sessions.reserve();
    let provider;
    let capabilities;
    let build;
    let buildState;
    try {
      provider = this.#registry.get(options.providerId, options.providerVersion);
      capabilities = immutableCopy(provider.getCapabilities());
      build = immutableCopy(options.build);
      buildState = new BuildStateManager(build);
    } catch (error) {
      this.#sessions.releaseReservation();
      throw error;
    }
    const sessionId = crypto.randomUUID();
    let abandoned = false;
    let providerRuntime;
    let creation;
    try {
      providerRuntime = await bounded(signal => {
        creation = Promise.resolve().then(() => provider.createSession({
          contractVersion: CONTRACT_VERSION,
          build: clone(build),
          buildSchemaVersion: options.buildSchemaVersion,
          snapshotId: options.snapshotId ?? null,
          snapshotManifestSha256: options.snapshotManifestSha256 ?? null,
          signal,
        }));
        return creation;
      }, {
        timeoutMs: options.timeoutMs ?? this.#operationTimeoutMs, signal: options.signal,
      });
    } catch (error) {
      abandoned = true;
      if (!creation) {
        this.#sessions.releaseReservation();
        throw error;
      }
      void creation.then(async runtime => {
        if (!abandoned || typeof runtime?.close !== 'function') return;
        try {
          await this.#orchestrator.close(runtime);
          this.#sessions.releaseReservation();
        } catch {
          // The runtime may still own resources. Retain capacity fail-closed until
          // the Application instance is replaced; never overcommit an unknown lease.
        }
      }, () => {
        this.#sessions.releaseReservation();
      });
      throw error;
    }
    if (!providerRuntime || typeof providerRuntime.evaluate !== 'function' || typeof providerRuntime.close !== 'function') {
      if (typeof providerRuntime?.close === 'function') await this.#orchestrator.close(providerRuntime).catch(() => undefined);
      this.#sessions.releaseReservation();
      throw new ApplicationError(ERROR_CODES.PROVIDER_FAILURE, 'provider returned invalid session runtime');
    }
    let baselineCheckpoint = null;
    if (capabilities.stateModel === 'stateful') {
      if (typeof providerRuntime.checkpoint !== 'function' || typeof providerRuntime.restore !== 'function') {
        await this.#orchestrator.close(providerRuntime).catch(() => undefined);
        this.#sessions.releaseReservation();
        throw new ApplicationError(ERROR_CODES.PROVIDER_FAILURE, 'stateful provider requires checkpoint and restore');
      }
      try {
        baselineCheckpoint = await this.#orchestrator.checkpoint(providerRuntime, options);
      } catch (error) {
        await this.#orchestrator.close(providerRuntime).catch(() => undefined);
        this.#sessions.releaseReservation();
        throw error;
      }
    }
    const now = this.#clock();
    const session = {
      id: sessionId,
      provider,
      providerRuntime,
      capabilities,
      providerVersion: provider.version,
      snapshotId: options.snapshotId ?? null,
      snapshotManifestSha256: options.snapshotManifestSha256 ?? null,
      buildSchemaVersion: options.buildSchemaVersion,
      contractVersion: CONTRACT_VERSION,
      buildState,
      initialCheckpoint: baselineCheckpoint,
      status: 'ACTIVE',
      createdAt: now,
      touchedAt: now,
      executor: new SerialExecutor(),
      diagnostics: { evaluations: 0, previews: 0, commits: 0, resets: 0, failures: 0, cacheHits: 0 },
    };
    this.#sessions.addReserved(session, current => this.#expireIdle(current));
    return this.#publicSession(session);
  }

  async evaluate(sessionId, options = {}) {
    const session = this.#active(sessionId);
    return session.executor.run(async () => {
      this.#touchAndAssert(session);
      const key = this.#cacheKey(session);
      if (!options.bypassCache) {
        const cached = this.#cache.get(key);
        if (cached) {
          session.diagnostics.cacheHits += 1;
          return immutableCopy({ ...cached, cache: { hit: true, key } });
        }
      }
      const started = this.#clock();
      const { output } = await this.#evaluateUncached(session, options);
      const result = this.#result(session, output, started, { hit: false, key });
      session.diagnostics.evaluations += 1;
      this.#cache.set(key, result);
      return result;
    });
  }

  async previewChanges(sessionId, request) {
    validateChangeRequest(request, true);
    const session = this.#active(sessionId);
    return session.executor.run(async () => {
      this.#touchAndAssert(session);
      this.#assertRevision(session, request.expectedRevision);
      this.#validateChanges(session, request.changes);
      const before = await this.#evaluateUncached(session, { signal: request.signal, timeoutMs: request.timeoutMs });
      const checkpoint = await this.#checkpoint(session, request);
      let output;
      try {
        output = await this.#callProvider(session, {
          build: clone(session.buildState.committed), changes: clone(request.changes), mode: 'PREVIEW',
        }, request);
      } catch (error) {
        if (error instanceof ApplicationError &&
            (error.code === ERROR_CODES.TIMEOUT || error.code === ERROR_CODES.CANCELLED)) {
          this.#quarantine(session, error);
          throw error;
        }
        await this.#recoverOrQuarantine(session, checkpoint, error, request);
        throw error;
      }
      await this.#recoverOrQuarantine(session, checkpoint, null, request);
      const candidateBuild = immutableCopy(output.build);
      const issued = session.buildState.issuePreview({
        sessionId,
        providerId: session.provider.id, providerVersion: session.providerVersion,
        snapshotManifestSha256: session.snapshotManifestSha256,
      }, request.changes, candidateBuild);
      session.diagnostics.previews += 1;
      const afterMetrics = normalizeMetrics(output.metrics);
      return immutableCopy({
        sessionId, revision: session.buildState.revision, previewToken: issued.token,
        baseBuildFingerprint: session.buildState.fingerprint,
        candidateBuildFingerprint: issued.payload.candidateFingerprint,
        before: before.metrics, after: afterMetrics, delta: metricDelta(before.metrics, afterMetrics),
        provenance: this.#provenance(session, output.provenance),
      });
    });
  }

  async commitChanges(sessionId, request) {
    validateChangeRequest(request, true);
    if (typeof request.previewToken !== 'string' || !request.previewToken) {
      throw new ApplicationError(ERROR_CODES.INVALID_INPUT, 'previewToken is required');
    }
    const session = this.#active(sessionId);
    return session.executor.run(async () => {
      this.#touchAndAssert(session);
      this.#assertRevision(session, request.expectedRevision);
      this.#validateChanges(session, request.changes);
      const preview = session.buildState.validatePreview(request.previewToken, request.changes);
      const checkpoint = await this.#checkpoint(session, request);
      let output;
      const started = this.#clock();
      try {
        output = await this.#callProvider(session, {
          build: clone(session.buildState.committed), changes: clone(request.changes), mode: 'COMMIT',
        }, request);
        if (sha256(output.build) !== preview.candidateFingerprint) {
          throw new ApplicationError(ERROR_CODES.STALE_PREVIEW, 'provider commit differs from preview');
        }
      } catch (error) {
        if (error instanceof ApplicationError &&
            (error.code === ERROR_CODES.TIMEOUT || error.code === ERROR_CODES.CANCELLED)) {
          this.#quarantine(session, error);
          throw error;
        }
        await this.#recoverOrQuarantine(session, checkpoint, error, request);
        throw error;
      }
      session.buildState.commit(output.build, preview.candidateFingerprint);
      session.diagnostics.commits += 1;
      this.#cache.deleteSession(session.id);
      const result = this.#result(session, output, started, { hit: false, key: this.#cacheKey(session) });
      return immutableCopy({ session: this.#publicSession(session), result });
    });
  }

  async resetSession(sessionId, options = {}) {
    const session = this.#active(sessionId);
    return session.executor.run(async () => {
      this.#touchAndAssert(session);
      if (options.expectedRevision !== undefined) this.#assertRevision(session, options.expectedRevision);
      let output;
      if (session.capabilities.stateModel === 'stateful') {
        try {
          await this.#orchestrator.restore(session.providerRuntime, session.initialCheckpoint, {
            ...options, propagateCancellation: true,
          });
          output = await this.#callProvider(session, {
            build: clone(session.buildState.initial), changes: [], mode: 'RESET',
          }, options);
        } catch (error) {
          this.#quarantine(session, error);
          throw new ApplicationError(ERROR_CODES.RECOVERY_FAILED, 'reset failed; session quarantined', { cause: error });
        }
      } else {
        output = await this.#callProvider(session, {
          build: clone(session.buildState.initial), changes: [], mode: 'RESET',
        }, options);
      }
      if (sha256(output.build) !== sha256(session.buildState.initial)) {
        this.#quarantine(session, new Error('provider reset build mismatch'));
        throw new ApplicationError(ERROR_CODES.RECOVERY_FAILED, 'provider did not restore baseline');
      }
      session.buildState.reset(output.build);
      session.diagnostics.resets += 1;
      this.#cache.deleteSession(session.id);
      return this.#publicSession(session);
    });
  }

  getSession(sessionId) {
    const session = this.#session(sessionId);
    this.#expireOne(session);
    return this.#publicSession(session);
  }

  async closeSession(sessionId) {
    const session = this.#sessions.find(sessionId);
    if (!session) return immutableCopy({ sessionId, closed: true, alreadyClosed: true });
    return session.executor.run(async () => {
      if (session.status === 'CLOSED') return immutableCopy({ sessionId, closed: true, alreadyClosed: true });
      session.status = 'CLOSING';
      try {
        await this.#orchestrator.close(session.providerRuntime);
      } catch (error) {
        session.status = 'QUARANTINED';
        session.diagnostics.failures += 1;
        throw new ApplicationError(ERROR_CODES.RECOVERY_FAILED, 'provider cleanup failed', { cause: error });
      }
      session.status = 'CLOSED';
      this.#sessions.delete(sessionId);
      this.#cache.deleteSession(sessionId);
      return immutableCopy({ sessionId, closed: true, alreadyClosed: false });
    });
  }

  #session(id) {
    return this.#sessions.get(id);
  }

  #active(id) {
    const session = this.#session(id);
    this.#expireOne(session);
    this.#touchAndAssert(session);
    return session;
  }

  #touchAndAssert(session) {
    if (session.status === 'QUARANTINED') throw new ApplicationError(ERROR_CODES.SESSION_QUARANTINED, 'session is quarantined');
    if (session.status !== 'ACTIVE') throw new ApplicationError(ERROR_CODES.SESSION_CLOSED, 'session is not active');
    this.#sessions.touch(session);
  }

  async #expireSessions() {
    for (const session of this.#sessions.values()) {
      if (session.status === 'ACTIVE' && !this.#sessions.isExpired(session)) continue;
      await this.#expireIdle(session);
    }
  }

  async #expireIdle(session) {
    if (this.#sessions.find(session.id) !== session) return;
    if (session.status === 'ACTIVE' && !this.#sessions.isExpired(session)) {
      this.#sessions.reschedule(session);
      return;
    }
    return session.executor.run(async () => {
      if (this.#sessions.find(session.id) !== session) return;
      if (session.status === 'ACTIVE' && !this.#sessions.isExpired(session)) {
        this.#sessions.reschedule(session);
        return;
      }
      if (session.status === 'ACTIVE') session.status = 'EXPIRED';
      if (session.status !== 'EXPIRED') return;
      this.#cache.deleteSession(session.id);
      try {
        await this.#orchestrator.close(session.providerRuntime);
        session.status = 'CLOSED';
        this.#sessions.delete(session.id);
      } catch (error) {
        session.status = 'QUARANTINED';
        session.diagnostics.failures += 1;
        session.diagnostics.lastFailure = 'RECOVERY_FAILED';
        this.#sessions.cancelExpiry(session.id);
      }
    });
  }

  #expireOne(session) {
    if (session.status === 'ACTIVE' && this.#sessions.isExpired(session)) {
      session.status = 'EXPIRED';
      this.#cache.deleteSession(session.id);
      void this.#expireIdle(session);
    }
    if (session.status === 'EXPIRED') throw new ApplicationError(ERROR_CODES.SESSION_EXPIRED, 'session expired');
  }

  #publicSession(session) {
    return immutableCopy({
      sessionId: session.id, status: session.status, revision: session.buildState.revision,
      providerId: session.provider.id, providerVersion: session.providerVersion,
      snapshotId: session.snapshotId, snapshotManifestSha256: session.snapshotManifestSha256,
      contractVersion: session.contractVersion, buildSchemaVersion: session.buildSchemaVersion,
      buildFingerprint: session.buildState.fingerprint, createdAt: session.createdAt, touchedAt: session.touchedAt,
      diagnostics: { ...session.diagnostics, cache: this.#cache.diagnostics() },
    });
  }

  #assertRevision(session, expected) {
    if (!Number.isInteger(expected)) throw new ApplicationError(ERROR_CODES.INVALID_INPUT, 'expectedRevision is required');
    if (expected !== session.buildState.revision) {
      throw new ApplicationError(ERROR_CODES.REVISION_CONFLICT, 'revision conflict', {
        details: { expectedRevision: expected, actualRevision: session.buildState.revision },
      });
    }
  }

  #validateChanges(session, changes) {
    const supported = new Set(session.capabilities.changeTypes ?? []);
    for (const change of changes) {
      if (!change || typeof change.type !== 'string' || !change.type) {
        throw new ApplicationError(ERROR_CODES.INVALID_INPUT, 'each change requires a type');
      }
      if (!supported.has(change.type)) {
        throw new ApplicationError(ERROR_CODES.UNSUPPORTED_CHANGE, `unsupported change: ${change.type}`);
      }
    }
  }

  async #checkpoint(session, options) {
    if (session.capabilities.stateModel !== 'stateful') return null;
    try {
      return await this.#orchestrator.checkpoint(session.providerRuntime, options);
    } catch (error) {
      if (error instanceof ApplicationError &&
          (error.code === ERROR_CODES.TIMEOUT || error.code === ERROR_CODES.CANCELLED)) {
        this.#quarantine(session, error);
      }
      throw error;
    }
  }

  async #recoverOrQuarantine(session, checkpoint, originalError, options) {
    if (session.capabilities.stateModel !== 'stateful') return;
    try {
      await this.#orchestrator.restore(session.providerRuntime, checkpoint, options);
    } catch (recoveryError) {
      this.#quarantine(session, recoveryError);
      throw new ApplicationError(ERROR_CODES.RECOVERY_FAILED, 'provider rollback failed; session quarantined', {
        cause: recoveryError, details: { operationFailed: Boolean(originalError) },
      });
    }
  }

  #quarantine(session, error) {
    if (session.status === 'QUARANTINED') return;
    session.status = 'QUARANTINED';
    session.buildState.invalidatePreviews();
    session.diagnostics.failures += 1;
    session.diagnostics.lastFailure = error instanceof ApplicationError ? error.code : 'PROVIDER_FAILURE';
    this.#cache.deleteSession(session.id);
    this.#sessions.cancelExpiry(session.id);
    this.#orchestrator.close(session.providerRuntime).catch(() => undefined);
  }

  async #callProvider(session, input, options) {
    try {
      const output = await this.#orchestrator.evaluate(session.providerRuntime, {
        ...input, contractVersion: CONTRACT_VERSION, buildSchemaVersion: session.buildSchemaVersion,
        snapshotId: session.snapshotId, snapshotManifestSha256: session.snapshotManifestSha256,
      }, options);
      const actualIds = new Set(output.metrics.map(metric => metric.id));
      const missingIds = (session.capabilities.metricIds ?? []).filter(id => !actualIds.has(id));
      const metricCoverage = session.capabilities.metricCoverage ?? 'EXACT';
      const unknownIds = metricCoverage === 'DYNAMIC_APPLICABLE'
        ? [...actualIds].filter(id => !(session.capabilities.metricIds ?? []).includes(id)) : [];
      if (missingIds.length > 0 && metricCoverage === 'EXACT' || unknownIds.length > 0) {
        throw new ApplicationError(ERROR_CODES.PROVIDER_FAILURE, 'provider metric coverage mismatch', {
          details: {
            coverage: metricCoverage, expected: session.capabilities.metricIds.length,
            actual: actualIds.size, missingIds, unknownIds,
          },
        });
      }
      return output;
    } catch (error) {
      session.diagnostics.failures += 1;
      if (error instanceof ApplicationError) {
        if (error.code === ERROR_CODES.TIMEOUT || error.code === ERROR_CODES.CANCELLED) this.#quarantine(session, error);
        throw error;
      }
      throw new ApplicationError(ERROR_CODES.PROVIDER_FAILURE, 'provider evaluation failed', { cause: error });
    }
  }

  async #evaluateUncached(session, options) {
    const checkpoint = await this.#checkpoint(session, options);
    let output;
    try {
      output = await this.#callProvider(session, {
        build: clone(session.buildState.committed), changes: [], mode: 'EVALUATE',
      }, options);
      this.#assertOutputBuild(session, output.build, session.buildState.fingerprint);
    } catch (error) {
      if (error instanceof ApplicationError &&
          (error.code === ERROR_CODES.TIMEOUT || error.code === ERROR_CODES.CANCELLED)) {
        this.#quarantine(session, error);
        throw error;
      }
      await this.#recoverOrQuarantine(session, checkpoint, error, options);
      throw error;
    }
    return { metrics: normalizeMetrics(output.metrics), output };
  }

  #assertOutputBuild(session, build, expectedFingerprint) {
    if (sha256(build) !== expectedFingerprint) {
      this.#quarantine(session, new Error('provider returned mismatched build'));
      throw new ApplicationError(ERROR_CODES.PROVIDER_FAILURE, 'provider returned stale or mismatched build');
    }
  }

  #result(session, output, startedAt, cache) {
    return immutableCopy({
      sessionId: session.id, revision: session.buildState.revision,
      providerId: session.provider.id, providerVersion: session.providerVersion,
      snapshotId: session.snapshotId, snapshotManifestSha256: session.snapshotManifestSha256,
      inputFingerprint: session.buildState.fingerprint, metrics: normalizeMetrics(output.metrics),
      provenance: this.#provenance(session, output.provenance),
      timing: { durationMs: Math.max(0, this.#clock() - startedAt) }, cache,
    });
  }

  #provenance(session, providerProvenance) {
    return immutableCopy({
      contractVersion: CONTRACT_VERSION, providerId: session.provider.id,
      providerVersion: session.providerVersion, snapshotId: session.snapshotId,
      snapshotManifestSha256: session.snapshotManifestSha256,
      provider: providerProvenance ?? null,
    });
  }

  #cacheKey(session) {
    return sha256({
      sessionId: session.id,
      providerId: session.provider.id, providerVersion: session.providerVersion,
      snapshotManifestSha256: session.snapshotManifestSha256,
      buildFingerprint: session.buildState.fingerprint, contractVersion: CONTRACT_VERSION,
      buildSchemaVersion: session.buildSchemaVersion,
      capabilityVersion: session.capabilities.version ?? null,
      policyVersion: session.capabilities.policyVersion ?? null,
    });
  }

}

function positiveInteger(value, fallback, name) {
  if (value === undefined) return fallback;
  if (!Number.isInteger(value) || value <= 0) throw new ApplicationError(ERROR_CODES.INVALID_INPUT, `${name} must be positive`);
  return value;
}

function validateCreate(options) {
  if (!options || options.contractVersion !== CONTRACT_VERSION ||
      typeof options.providerId !== 'string' || typeof options.providerVersion !== 'string' ||
      typeof options.buildSchemaVersion !== 'string' || !options.build || typeof options.build !== 'object') {
    throw new ApplicationError(ERROR_CODES.INVALID_INPUT, 'invalid createSession options');
  }
  const snapshotPair = [options.snapshotId, options.snapshotManifestSha256];
  if (snapshotPair.some(value => value != null) && snapshotPair.some(value => typeof value !== 'string' || !value)) {
    throw new ApplicationError(ERROR_CODES.INVALID_INPUT, 'snapshot ID and digest must both be null or non-empty strings');
  }
  if (options.snapshotManifestSha256 != null && !/^[a-f0-9]{64}$/i.test(options.snapshotManifestSha256)) {
    throw new ApplicationError(ERROR_CODES.INVALID_INPUT, 'snapshotManifestSha256 must be a SHA-256 hex digest');
  }
  assertJsonValue(options.build, 'build');
}

function validateChangeRequest(request, requireChanges) {
  if (!request || (requireChanges && (!Array.isArray(request.changes) || request.changes.length === 0))) {
    throw new ApplicationError(ERROR_CODES.INVALID_INPUT, 'changes must be a non-empty array');
  }
  assertJsonValue(request.changes, 'changes');
}

function assertJsonValue(value, label, seen = new Set()) {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return;
  if (typeof value === 'number' && Number.isFinite(value)) return;
  if (!value || typeof value !== 'object' || seen.has(value)) {
    throw new ApplicationError(ERROR_CODES.INVALID_INPUT, `${label} must be finite, acyclic JSON data`);
  }
  if (!Array.isArray(value) && Object.getPrototypeOf(value) !== Object.prototype) {
    throw new ApplicationError(ERROR_CODES.INVALID_INPUT, `${label} must contain plain JSON objects`);
  }
  seen.add(value);
  const values = Array.isArray(value) ? value : Object.values(value);
  for (const child of values) assertJsonValue(child, label, seen);
  seen.delete(value);
}

module.exports = { CONTRACT_VERSION, D4RuleKitApplication };
