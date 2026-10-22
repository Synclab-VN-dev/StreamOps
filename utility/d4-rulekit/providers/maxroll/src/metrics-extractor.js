'use strict';

const { ERROR_CODES, MaxrollProviderError } = require('./errors');
const { immutable } = require('./value');

class MaxrollMetricsExtractor {
  #profile;

  constructor(profile) { this.#profile = profile; }

  async extract(cdp, expectedPhase) {
    const selector = JSON.stringify(this.#profile.selectors.metrics);
    const expression = `(() => ({phase:Number(document.querySelector(${JSON.stringify(this.#profile.selectors.phase)})?.textContent),metrics:[...document.querySelectorAll(${selector})].map(node=>({id:node.dataset.metricId,raw:JSON.parse(node.dataset.raw),display:node.dataset.displayPresent==='true'?node.textContent:null,unit:node.dataset.unit||null,phase:Number(node.dataset.phase)}))}))()`;
    let evaluated;
    try {
      evaluated = await cdp.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    } catch (error) {
      throw new MaxrollProviderError(ERROR_CODES.RUNTIME_NOT_READY, 'CDP metric extraction failed', { cause: error });
    }
    const captured = evaluated?.result?.value;
    if (!captured || captured.phase !== expectedPhase || !Array.isArray(captured.metrics)) {
      throw new MaxrollProviderError(ERROR_CODES.STALE_METRICS, 'metric phase does not match current evaluation');
    }
    const byId = new Map();
    for (const metric of captured.metrics) {
      if (metric.phase !== expectedPhase) {
        throw new MaxrollProviderError(ERROR_CODES.STALE_METRICS, `stale metric: ${metric.id}`);
      }
      if (byId.has(metric.id)) {
        throw new MaxrollProviderError(ERROR_CODES.METRICS_INCOMPLETE, `duplicate metric: ${metric.id}`);
      }
      byId.set(metric.id, metric);
    }
    const missing = this.#profile.metricCatalog.filter(metric => !byId.has(metric.id));
    if (missing.length) {
      throw new MaxrollProviderError(ERROR_CODES.METRICS_INCOMPLETE,
        'provider-supported metric set is incomplete', { details: { missingCount: missing.length } });
    }
    return immutable(this.#profile.metricCatalog.map(definition => {
      const metric = byId.get(definition.id);
      if (definition.rawValueType !== 'finite-number' ||
          typeof metric.raw !== 'number' || !Number.isFinite(metric.raw)) {
        throw new MaxrollProviderError(ERROR_CODES.METRICS_INCOMPLETE,
          `raw metric violates ${definition.rawValueType}: ${definition.id}`);
      }
      if (metric.display !== null && typeof metric.display !== 'string' ||
          metric.unit !== null && (typeof metric.unit !== 'string' || !metric.unit)) {
        throw new MaxrollProviderError(ERROR_CODES.METRICS_INCOMPLETE,
          `metric display/unit schema is invalid: ${definition.id}`);
      }
      return {
        id: definition.id,
        name: definition.name,
        rawValue: metric.raw,
        displayValue: metric.display,
        unit: metric.unit,
        status: 'OBSERVED',
        provenance: {
          raw: this.#profile.provenanceSource,
          display: metric.display === null ? null : this.#profile.displayProvenanceSource,
          category: definition.category,
          phase: expectedPhase,
        },
      };
    }));
  }
}

module.exports = { MaxrollMetricsExtractor };
