'use strict';

const { MaxrollBuildMapper } = require('./build-mapper');
const { ERROR_CODES, MaxrollProviderError } = require('./errors');
const { MaxrollMetricsExtractor } = require('./metrics-extractor');
const { MaxrollRuntimeAdapter } = require('./runtime-adapter');

class MaxrollComponentFactory {
  constructor({
    runtimeKind = 'synthetic-dom-v1',
    RuntimeAdapter = MaxrollRuntimeAdapter,
    BuildMapper = MaxrollBuildMapper,
    MetricsExtractor = MaxrollMetricsExtractor,
  } = {}) {
    if (!['synthetic-dom-v1', 'maxroll-ui-cdp-v1'].includes(runtimeKind)) {
      throw new MaxrollProviderError(ERROR_CODES.INVALID_CONFIG, 'invalid component runtime kind');
    }
    for (const [name, Component] of Object.entries({ RuntimeAdapter, BuildMapper, MetricsExtractor })) {
      if (typeof Component !== 'function') {
        throw new MaxrollProviderError(ERROR_CODES.INVALID_CONFIG, `${name} must be constructable`);
      }
    }
    this.runtimeKind = runtimeKind;
    this.RuntimeAdapter = RuntimeAdapter;
    this.BuildMapper = BuildMapper;
    this.MetricsExtractor = MetricsExtractor;
    Object.freeze(this);
  }

  createRuntimeAdapter(options) { return new this.RuntimeAdapter(options); }
  createBuildMapper(profile) { return new this.BuildMapper(profile); }
  createMetricsExtractor(profile) { return new this.MetricsExtractor(profile); }
}

module.exports = { MaxrollComponentFactory };
