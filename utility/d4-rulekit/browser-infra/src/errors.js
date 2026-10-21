'use strict';

const ERROR_CODES = Object.freeze({
  NOT_RUNNING: 'NOT_RUNNING',
  CAPACITY_EXCEEDED: 'CAPACITY_EXCEEDED',
  QUEUE_TIMEOUT: 'QUEUE_TIMEOUT',
  LEASE_EXPIRED: 'LEASE_EXPIRED',
  BROWSER_DISCONNECTED: 'BROWSER_DISCONNECTED',
  CANCELLED: 'CANCELLED',
  INVALID_CONFIG: 'INVALID_CONFIG',
});

class BrowserInfrastructureError extends Error {
  constructor(code, message, options = {}) {
    super(message, options);
    this.name = 'BrowserInfrastructureError';
    this.code = code;
  }
}

function infrastructureError(code, message, cause) {
  return new BrowserInfrastructureError(code, message, cause ? { cause } : {});
}

module.exports = { BrowserInfrastructureError, ERROR_CODES, infrastructureError };
