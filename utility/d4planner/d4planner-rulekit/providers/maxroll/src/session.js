'use strict';

const { bounded, SerialExecutor } = require('./async');
const { ERROR_CODES, MaxrollProviderError } = require('./errors');
const { immutable, sha256 } = require('./value');

class MaxrollSession {
  #adapter;
  #mapper;
  #extractor;
  #profile;
  #mount;
  #lease;
  #executor = new SerialExecutor();
  #status = 'ACTIVE';
  #stableBuild = null;
  #lastMetrics = null;
  #closePromise = null;
  #timeoutMs;

  constructor({ adapter, mapper, extractor, profile, mount, lease, timeoutMs = 15_000 }) {
    this.#adapter = adapter;
    this.#mapper = mapper;
    this.#extractor = extractor;
    this.#profile = profile;
    this.#mount = mount;
    this.#lease = lease;
    this.#timeoutMs = timeoutMs;
  }

  async initialize(build, buildSchemaVersion, options = {}) {
    const mapped = this.#mapper.map(build, [], buildSchemaVersion);
    const evaluated = await this.#evaluateMapped(mapped, options);
    this.#stableBuild = mapped.desired;
    this.#lastMetrics = evaluated.metrics;
    return evaluated;
  }

  evaluate(input) {
    return this.#executor.run(async () => {
      this.#assertActive();
      const mapped = this.#mapper.map(input.build, input.changes ?? [], input.buildSchemaVersion);
      const previous = this.#stableBuild;
      try {
        const evaluated = await this.#evaluateMapped(mapped, input);
        this.#stableBuild = mapped.desired;
        this.#lastMetrics = evaluated.metrics;
        return evaluated;
      } catch (error) {
        if (error instanceof MaxrollProviderError &&
            [ERROR_CODES.TIMEOUT, ERROR_CODES.CANCELLED, ERROR_CODES.SESSION_INVALIDATED,
              ERROR_CODES.RUNTIME_NOT_READY]
              .includes(error.code)) {
          this.#invalidate();
          throw error;
        }
        if (previous) {
          try {
            await this.#restoreBuild(previous, input);
          } catch (recoveryError) {
            this.#invalidate();
            throw new MaxrollProviderError(ERROR_CODES.SESSION_INVALIDATED,
              'evaluation recovery failed; session invalidated', { cause: recoveryError });
          }
        }
        throw error;
      }
    });
  }

  checkpoint() {
    this.#assertActive();
    return Promise.resolve(immutable({ build: this.#stableBuild, fingerprint: sha256(this.#stableBuild) }));
  }

  restore(checkpoint, options = {}) {
    return this.#executor.run(async () => {
      this.#assertActive();
      if (!checkpoint?.build || sha256(checkpoint.build) !== checkpoint.fingerprint) {
        this.#invalidate();
        throw new MaxrollProviderError(ERROR_CODES.INVALID_INPUT, 'invalid session checkpoint');
      }
      try {
        return await this.#restoreBuild(checkpoint.build, options);
      } catch (error) {
        this.#invalidate();
        throw new MaxrollProviderError(ERROR_CODES.SESSION_INVALIDATED,
          'checkpoint restore failed; session invalidated', { cause: error });
      }
    });
  }

  close() {
    if (this.#closePromise) return this.#closePromise;
    this.#closePromise = (async () => {
      if (this.#status === 'CLOSED') return;
      this.#status = 'CLOSING';
      const failures = [];
      try { await this.#adapter?.close?.(); } catch (error) { failures.push(error); }
      try { await this.#mount?.unmount(); } catch (error) { failures.push(error); }
      try { await this.#lease?.release(); } catch (error) { failures.push(error); }
      this.#status = failures.length ? 'INVALIDATED' : 'CLOSED';
      this.#stableBuild = null;
      this.#lastMetrics = null;
      if (failures.length) {
        throw new MaxrollProviderError(ERROR_CODES.CLEANUP_FAILED,
          'provider session cleanup could not be confirmed', { cause: failures[0] });
      }
    })();
    return this.#closePromise;
  }

  async #evaluateMapped(mapped, options) {
    return bounded(async () => {
      if (options.signal?.aborted) throw new MaxrollProviderError(ERROR_CODES.CANCELLED, 'evaluation cancelled');
      const applied = await this.#adapter.apply(mapped.desired, mapped.fingerprint);
      if (!applied?.observed || sha256(applied.observed) !== mapped.fingerprint) {
        throw new MaxrollProviderError(ERROR_CODES.READBACK_MISMATCH,
          'provider runtime semantic read-back does not match the requested build');
      }
      if (options.signal?.aborted) throw new MaxrollProviderError(ERROR_CODES.CANCELLED, 'evaluation cancelled');
      const metrics = await this.#extractor.extract(this.#adapter, applied);
      const networkReplay = this.#mount?.getDiagnostics?.() ?? null;
      if (networkReplay && networkReplay.transportOffline !== true) {
        throw new MaxrollProviderError(ERROR_CODES.RUNTIME_NOT_READY,
          'offline-strict transport policy is not active');
      }
      return immutable({
        build: mapped.desired,
        metrics,
        provenance: {
          provider: 'maxroll', providerVersion: this.#profile.providerVersion,
          runtimeVersion: this.#profile.runtimeVersion, gamePatch: this.#profile.gamePatch,
          snapshotId: this.#profile.snapshotId,
          snapshotManifestSha256: this.#profile.snapshotManifestSha256,
          assetSha256: this.#profile.assetSha256,
          authorizationRef: this.#profile.authorizationRef ?? null,
          inputFingerprint: mapped.fingerprint,
          phase: applied.phase,
          runtimeAttestation: applied.attestation ?? null,
          networkReplay,
        },
      });
    }, { signal: options.signal, timeoutMs: options.timeoutMs ?? this.#timeoutMs });
  }

  async #restoreBuild(build, options) {
    const mapped = this.#mapper.map(build, [], this.#profile.supportedBuildSchemaVersion);
    const result = await this.#evaluateMapped(mapped, { timeoutMs: options.timeoutMs });
    this.#stableBuild = mapped.desired;
    this.#lastMetrics = result.metrics;
    return result;
  }

  #assertActive() {
    if (this.#status !== 'ACTIVE' || !this.#lease?.valid) {
      throw new MaxrollProviderError(ERROR_CODES.SESSION_INVALIDATED, 'provider session is not active');
    }
  }

  #invalidate() {
    if (this.#status !== 'ACTIVE') return;
    this.#status = 'INVALIDATED';
    this.#stableBuild = null;
    this.#lastMetrics = null;
    void this.close().catch(() => {});
  }
}

module.exports = { MaxrollSession };
