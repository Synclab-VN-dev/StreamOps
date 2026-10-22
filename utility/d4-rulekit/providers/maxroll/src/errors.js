'use strict';

const ERROR_CODES = Object.freeze({
  INVALID_CONFIG: 'INVALID_CONFIG',
  INVALID_INPUT: 'INVALID_INPUT',
  UNSUPPORTED_INPUT: 'UNSUPPORTED_INPUT',
  SNAPSHOT_MISMATCH: 'SNAPSHOT_MISMATCH',
  RUNTIME_MISMATCH: 'RUNTIME_MISMATCH',
  RUNTIME_NOT_READY: 'RUNTIME_NOT_READY',
  APPLY_FAILED: 'APPLY_FAILED',
  READBACK_MISMATCH: 'READBACK_MISMATCH',
  METRICS_INCOMPLETE: 'METRICS_INCOMPLETE',
  STALE_METRICS: 'STALE_METRICS',
  SESSION_INVALIDATED: 'SESSION_INVALIDATED',
  TIMEOUT: 'TIMEOUT',
  CANCELLED: 'CANCELLED',
  CLEANUP_FAILED: 'CLEANUP_FAILED',
});

class MaxrollProviderError extends Error {
  constructor(code, message, options = {}) {
    super(message, options.cause ? { cause: options.cause } : undefined);
    this.name = 'MaxrollProviderError';
    this.code = code;
    this.details = options.details ? Object.freeze({ ...options.details }) : undefined;
  }
}

module.exports = { ERROR_CODES, MaxrollProviderError };
