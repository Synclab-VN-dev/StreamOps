'use strict';

const { ERROR_CODES, MaxrollProviderError } = require('./errors');
const { RealMaxrollMetricsExtractor } = require('./real-metrics-extractor');
const { NativeStateMaxrollRuntimeAdapter } = require('./native-state-runtime-adapter');
const { UniversalMaxrollBuildMapper } = require('./universal-build-mapper');

class UniversalMaxrollComponentFactory {
  runtimeKind = 'maxroll-ui-cdp-v1';
  #codec;
  #plannerId;
  #profileUrl;

  constructor({ codec, plannerId, profileUrl }) {
    if (!codec || typeof plannerId !== 'string' || !plannerId
        || typeof profileUrl !== 'string' || !profileUrl) {
      throw new MaxrollProviderError(ERROR_CODES.INVALID_CONFIG,
        'universal component factory dependencies are required');
    }
    this.#codec = codec;
    this.#plannerId = plannerId;
    this.#profileUrl = profileUrl;
  }

  createRuntimeAdapter({ lease, profile }) {
    return new NativeStateMaxrollRuntimeAdapter({
      lease, profile, codec: this.#codec, plannerId: this.#plannerId,
      profileUrl: this.#profileUrl,
    });
  }

  createBuildMapper(profile) {
    return new UniversalMaxrollBuildMapper(profile, { codec: this.#codec });
  }

  createMetricsExtractor(profile) { return new RealMaxrollMetricsExtractor(profile); }
}

module.exports = { UniversalMaxrollComponentFactory };
