'use strict';

const { ERROR_CODES, MaxrollProviderError } = require('./errors');
const { immutable } = require('./value');

class RealMaxrollMetricsExtractor {
  #profile;

  constructor(profile) { this.#profile = profile; }

  async extract(adapter, evaluation) {
    if (!adapter || typeof adapter.takeCapture !== 'function') {
      throw new MaxrollProviderError(ERROR_CODES.INVALID_CONFIG,
        'real metrics extractor requires a real runtime adapter');
    }
    const capture = adapter.takeCapture(evaluation?.phase, evaluation?.inputFingerprint);
    const byInternalId = new Map();
    for (const metric of capture.raw) {
      if (byInternalId.has(metric.internalId)) {
        throw new MaxrollProviderError(ERROR_CODES.METRICS_INCOMPLETE,
          `duplicate real metric: ${metric.internalId}`);
      }
      byInternalId.set(metric.internalId, metric.rawValue);
    }
    const definitions = this.#profile.realRuntime?.discoverMetricCatalog === true
      ? capture.raw.map(metric => ({ id: metric.metricId,
        internalId: metric.internalId, category: metric.category, name: metric.label,
        rawValueType: 'finite-number' }))
      : this.#profile.metricCatalog;
    const missing = definitions.filter(metric => !byInternalId.has(metric.internalId));
    if (missing.length) {
      throw new MaxrollProviderError(ERROR_CODES.METRICS_INCOMPLETE,
        'real provider-supported metric set is incomplete', {
          details: { missingCount: missing.length },
        });
    }
    return immutable(definitions.map(definition => {
      const rawValue = byInternalId.get(definition.internalId);
      if (definition.rawValueType !== 'finite-number' ||
          typeof rawValue !== 'number' || !Number.isFinite(rawValue)) {
        throw new MaxrollProviderError(ERROR_CODES.METRICS_INCOMPLETE,
          `real raw metric violates ${definition.rawValueType}: ${definition.id}`);
      }
      const displayKey = `${definition.category}|${definition.name}`;
      const displayValue = Object.hasOwn(capture.displays, displayKey)
        ? capture.displays[displayKey] : null;
      if (displayValue !== null && typeof displayValue !== 'string') {
        throw new MaxrollProviderError(ERROR_CODES.METRICS_INCOMPLETE,
          `real display metric is invalid: ${definition.id}`);
      }
      return {
        id: definition.id,
        name: definition.name,
        rawValue,
        displayValue,
        unit: displayValue?.endsWith('%') ? '%' : null,
        status: 'OBSERVED',
        provenance: {
          raw: this.#profile.provenanceSource,
          display: displayValue === null ? null : this.#profile.displayProvenanceSource,
          category: definition.category,
          phase: capture.phase,
        },
      };
    }));
  }
}

module.exports = { RealMaxrollMetricsExtractor };
