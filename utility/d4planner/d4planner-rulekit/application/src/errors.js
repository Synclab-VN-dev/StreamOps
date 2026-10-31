'use strict';

const ERROR_CODES = Object.freeze({
  INVALID_INPUT: 'INVALID_INPUT',
  PROVIDER_NOT_FOUND: 'PROVIDER_NOT_FOUND',
  PROVIDER_UNAVAILABLE: 'PROVIDER_UNAVAILABLE',
  SESSION_NOT_FOUND: 'SESSION_NOT_FOUND',
  SESSION_CLOSED: 'SESSION_CLOSED',
  SESSION_QUARANTINED: 'SESSION_QUARANTINED',
  SESSION_EXPIRED: 'SESSION_EXPIRED',
  QUOTA_EXCEEDED: 'QUOTA_EXCEEDED',
  REVISION_CONFLICT: 'REVISION_CONFLICT',
  STALE_PREVIEW: 'STALE_PREVIEW',
  UNSUPPORTED_CHANGE: 'UNSUPPORTED_CHANGE',
  PROVIDER_FAILURE: 'PROVIDER_FAILURE',
  RECOVERY_FAILED: 'RECOVERY_FAILED',
  TIMEOUT: 'TIMEOUT',
  CANCELLED: 'CANCELLED',
});

class ApplicationError extends Error {
  constructor(code, message, options = {}) {
    super(message, options.cause ? { cause: options.cause } : undefined);
    this.name = 'ApplicationError';
    this.code = code;
    this.details = options.details ? Object.freeze({ ...options.details }) : undefined;
  }
}

module.exports = { ApplicationError, ERROR_CODES };
