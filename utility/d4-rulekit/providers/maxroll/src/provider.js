'use strict';

const { bounded } = require('./async');
const { MaxrollBuildMapper } = require('./build-mapper');
const { ERROR_CODES, MaxrollProviderError } = require('./errors');
const { MaxrollMetricsExtractor } = require('./metrics-extractor');
const { MaxrollRuntimeAdapter } = require('./runtime-adapter');
const { MaxrollSession } = require('./session');

class MaxrollProvider {
  id = 'maxroll';

  constructor({ browser, snapshots, profile, sessionTimeoutMs = 15_000 }) {
    if (!browser || typeof browser.acquire !== 'function' ||
        !snapshots || !['verify', 'load', 'mount'].every(method => typeof snapshots[method] === 'function') ||
        !profile) {
      throw new MaxrollProviderError(ERROR_CODES.INVALID_CONFIG,
        'browser, snapshots and patch profile dependencies are required');
    }
    this.version = profile.providerVersion;
    this.browser = browser;
    this.snapshots = snapshots;
    this.profile = profile;
    this.sessionTimeoutMs = sessionTimeoutMs;
  }

  getCapabilities() { return this.profile.capability(); }

  async createSession(options) {
    this.#validateOptions(options);
    let verification;
    let manifest;
    try {
      verification = await this.snapshots.verify(this.profile.snapshotId);
      manifest = await this.snapshots.load(this.profile.snapshotId);
    } catch (error) {
      throw new MaxrollProviderError(ERROR_CODES.SNAPSHOT_MISMATCH,
        'snapshot verification failed', { cause: error });
    }
    this.#validateSnapshot(verification, manifest);
    let lease = null;
    let mount = null;
    let session = null;
    let abandoned = false;
    const cleanup = async () => {
      await mount?.unmount().catch(() => {});
      await lease?.release().catch(() => {});
    };
    const creation = (async () => {
      lease = await this.browser.acquire({
        signal: options.signal,
        timeoutMs: options.timeoutMs ?? this.sessionTimeoutMs,
        leaseTimeoutMs: Math.max((options.timeoutMs ?? this.sessionTimeoutMs) * 3, 30_000),
      });
      if (abandoned) { await cleanup(); throw new MaxrollProviderError(ERROR_CODES.CANCELLED, 'session creation abandoned'); }
      mount = await this.snapshots.mount(lease, this.profile.snapshotId, {
        mode: 'offline-strict', onMissingResource: 'abort',
      });
      if (abandoned) { await cleanup(); throw new MaxrollProviderError(ERROR_CODES.CANCELLED, 'session creation abandoned'); }
      const adapter = new MaxrollRuntimeAdapter({ lease, profile: this.profile });
      await adapter.initialize();
      session = new MaxrollSession({
        adapter,
        mapper: new MaxrollBuildMapper(this.profile),
        extractor: new MaxrollMetricsExtractor(this.profile),
        profile: this.profile,
        mount,
        lease,
        timeoutMs: this.sessionTimeoutMs,
      });
      await session.initialize(options.build, options.buildSchemaVersion, options);
      if (abandoned) { await session.close().catch(() => {}); throw new MaxrollProviderError(ERROR_CODES.CANCELLED, 'session creation abandoned'); }
      return session;
    })();
    try {
      return await bounded(() => creation, {
        signal: options.signal,
        timeoutMs: options.timeoutMs ?? this.sessionTimeoutMs,
      });
    } catch (error) {
      abandoned = true;
      if (session) await session.close().catch(() => {});
      else await cleanup();
      void creation.catch(() => {});
      if (error instanceof MaxrollProviderError) throw error;
      throw new MaxrollProviderError(ERROR_CODES.RUNTIME_NOT_READY,
        'provider session initialization failed', { cause: error });
    }
  }

  #validateOptions(options) {
    if (!options || options.contractVersion !== undefined && options.contractVersion !== 'd4-rulekit-application/v1' ||
        options.providerVersion !== undefined && options.providerVersion !== this.version ||
        options.snapshotId !== this.profile.snapshotId ||
        options.snapshotManifestSha256 !== this.profile.snapshotManifestSha256 ||
        options.buildSchemaVersion !== this.profile.supportedBuildSchemaVersion ||
        !options.build) {
      throw new MaxrollProviderError(ERROR_CODES.SNAPSHOT_MISMATCH,
        'session options do not match the pinned Maxroll profile');
    }
    if (options.expectedGamePatch !== undefined && options.expectedGamePatch !== this.profile.gamePatch) {
      throw new MaxrollProviderError(ERROR_CODES.RUNTIME_MISMATCH, 'expected game patch does not match pinned profile');
    }
  }

  #validateSnapshot(verification, manifest) {
    const asset = manifest.resources.find(resource => resource.url === this.profile.assetUrl);
    if (verification.manifestSha256 !== this.profile.snapshotManifestSha256 ||
        manifest.snapshotId !== this.profile.snapshotId ||
        manifest.sourceUrl !== this.profile.sourceUrl ||
        !asset || asset.sha256 !== this.profile.assetSha256) {
      throw new MaxrollProviderError(ERROR_CODES.SNAPSHOT_MISMATCH,
        'snapshot manifest or runtime asset identity mismatch');
    }
  }
}

module.exports = { MaxrollProvider };
