'use strict';

const { ERROR_CODES, MaxrollProviderError } = require('./errors');
const { MaxrollRuntimeAttestationObserver } = require('./runtime-attestation');
const { validateCaptureEvidence } = require('./fixture-attestation');

class NativeStateMaxrollRuntimeAdapter {
  #lease;
  #profile;
  #codec;
  #plannerId;
  #profileUrl;
  #phase = 0;
  #captures = new Map();
  #observer = null;
  #closed = false;

  constructor({ lease, profile, codec, plannerId, profileUrl }) {
    if (!lease?.valid || !profile || !codec || typeof plannerId !== 'string' || !plannerId
        || typeof profileUrl !== 'string' || !profileUrl) {
      throw new MaxrollProviderError(ERROR_CODES.INVALID_CONFIG,
        'native-state runtime adapter dependencies are incomplete');
    }
    this.#lease = lease;
    this.#profile = profile;
    this.#codec = codec;
    this.#plannerId = plannerId;
    this.#profileUrl = profileUrl;
  }

  async initialize() {
    this.#assertActive();
    return Object.freeze({
      runtimeVersion: this.#profile.runtimeVersion,
      gamePatch: this.#profile.gamePatch,
      assetSha256: this.#profile.assetSha256,
      loader: 'MAXROLL_NATIVE_STATE_REPLAY',
    });
  }

  async apply(desired, expectedFingerprint) {
    this.#assertActive();
    const nativeState = this.#codec.canonicalToNative(desired);
    const identity = this.#codec.loaderIdentity(desired);
    const loaderMetadata = createD12NativeLoaderMetadata({
      plannerId: this.#plannerId,
      className: identity.className,
      season: identity.season,
    });
    const isNewObserver = this.#observer === null;
    const observer = this.#observer ?? new MaxrollRuntimeAttestationObserver({
      lease: this.#lease, profile: this.#profile, nativeState, profileIndex: 0,
    });
    if (isNewObserver) this.#observer = observer;
    let capture;
    try {
      if (isNewObserver) await observer.initialize();
      else observer.setInput(nativeState, 0);
      capture = await observer.capture({
        navigateUrl: this.#profile.sourceUrl,
        replayResponse: {
          url: this.#profileUrl,
          body: JSON.stringify({ ...loaderMetadata, data: JSON.stringify(nativeState) }),
        },
      });
      validateCaptureEvidence(capture);
    } catch (error) {
      try { await observer.close(); } catch (cleanupError) {
        throw new AggregateError([error, cleanupError],
          'native state evaluation and observer cleanup failed');
      }
      this.#observer = null;
      throw error;
    }
    this.#phase += 1;
    const phase = this.#phase;
    const displays = Object.fromEntries(capture.displayMetrics
      .map(metric => [metric.labelAnchor, metric.displayValue]));
    this.#captures.clear();
    this.#captures.set(phase, Object.freeze({
      phase,
      inputFingerprint: expectedFingerprint,
      raw: capture.rawMetrics.map(metric => Object.freeze({ ...metric })),
      displays: Object.freeze(displays),
      displayMetrics: Object.freeze(capture.displayMetrics.map(metric => Object.freeze({ ...metric }))),
      attestation: Object.freeze({
        engine: capture.engine,
        profileReadback: capture.profileReadback,
        calculationPhase: capture.phase,
        network: capture.network,
      }),
    }));
    const observed = this.#codec.runtimeStateToCanonical(capture.runtimeState,
      desired.provenance);
    return Object.freeze({ phase, observed, inputFingerprint: expectedFingerprint,
      attestation: Object.freeze({ engine: capture.engine,
        profileReadback: capture.profileReadback, calculationPhase: capture.phase,
        network: capture.network, displayMetrics: capture.displayMetrics }) });
  }

  takeCapture(phase, expectedFingerprint) {
    const capture = this.#captures.get(phase);
    if (!capture || capture.inputFingerprint !== expectedFingerprint) {
      throw new MaxrollProviderError(ERROR_CODES.STALE_METRICS,
        'native-state capture does not belong to the current canonical input');
    }
    this.#captures.delete(phase);
    return capture;
  }

  async close() {
    if (this.#closed) return;
    this.#closed = true;
    this.#captures.clear();
    const observer = this.#observer;
    this.#observer = null;
    if (observer) await observer.close();
  }

  #assertActive() {
    if (this.#closed || !this.#lease.valid) {
      throw new MaxrollProviderError(ERROR_CODES.SESSION_INVALIDATED,
        'native-state runtime adapter is not active');
    }
  }
}

function createD12NativeLoaderMetadata({ plannerId, className, season }) {
  if (typeof plannerId !== 'string' || !plannerId || typeof className !== 'string' || !className
      || !Number.isInteger(season)) {
    throw new MaxrollProviderError(ERROR_CODES.INVALID_INPUT,
      'native loader envelope identity is invalid');
  }
  return Object.freeze({
    accessed: 0,
    average_rating: 0,
    category: 'build',
    class: className,
    date: '',
    folder: 0,
    game: 'd4',
    id: plannerId,
    mainset: '',
    metadata: '{}',
    name: 'Canonical Import',
    public: false,
    search_metadata: Object.freeze({ items: [], skills: [], specializations: [] }),
    season: String(season),
    shared: false,
    tags: null,
    total_ratings: 0,
    type: '',
    user: Object.freeze({ active: 0, id: 0, username: 'Offline Fixture' }),
    userId: 0,
  });
}

module.exports = {
  NativeStateMaxrollRuntimeAdapter,
  createD12NativeLoaderMetadata,
};
