'use strict';

const { bounded } = require('./async');
const { ApplicationError, ERROR_CODES } = require('./errors');
const { normalizeMetrics } = require('./normalizer');

class CalculationOrchestrator {
  #operationTimeoutMs;
  #cleanupTimeoutMs;

  constructor({ operationTimeoutMs, cleanupTimeoutMs }) {
    this.#operationTimeoutMs = operationTimeoutMs;
    this.#cleanupTimeoutMs = cleanupTimeoutMs;
  }

  async evaluate(runtime, input, options = {}) {
    try {
      const output = await bounded(signal => runtime.evaluate({ ...input, signal }), {
        timeoutMs: options.timeoutMs ?? this.#operationTimeoutMs,
        signal: options.signal,
      });
      if (!output || !output.build || !Array.isArray(output.metrics)) {
        throw new ApplicationError(ERROR_CODES.PROVIDER_FAILURE, 'provider returned invalid evaluation result');
      }
      normalizeMetrics(output.metrics);
      return output;
    } catch (error) {
      if (error instanceof ApplicationError) throw error;
      throw new ApplicationError(ERROR_CODES.PROVIDER_FAILURE, 'provider evaluation failed', { cause: error });
    }
  }

  checkpoint(runtime, options = {}) {
    return bounded(signal => runtime.checkpoint({ signal }), {
      timeoutMs: options.timeoutMs ?? this.#operationTimeoutMs,
      signal: options.signal,
    });
  }

  restore(runtime, checkpoint, options = {}) {
    return bounded(signal => runtime.restore(checkpoint, { signal }), {
      timeoutMs: options.timeoutMs ?? this.#operationTimeoutMs,
      signal: options.propagateCancellation ? options.signal : undefined,
    });
  }

  close(runtime) {
    return bounded(signal => runtime.close({ signal }), { timeoutMs: this.#cleanupTimeoutMs });
  }
}

module.exports = { CalculationOrchestrator };
