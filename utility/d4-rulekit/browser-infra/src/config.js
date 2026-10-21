'use strict';

const { ERROR_CODES, infrastructureError } = require('./errors');

const DEFAULT_CONFIG = Object.freeze({
  maxContexts: 2,
  maxQueue: 32,
  acquireTimeoutMs: 10_000,
  leaseTimeoutMs: 60_000,
  headless: true,
  executablePath: undefined,
  launchOptions: {},
  contextOptions: {},
  logger: undefined,
});

function positiveInteger(value, name, { allowZero = false } = {}) {
  const minimum = allowZero ? 0 : 1;
  if (!Number.isInteger(value) || value < minimum) {
    throw infrastructureError(ERROR_CODES.INVALID_CONFIG,
      `${name} must be an integer >= ${minimum}`);
  }
}

function validateConfig(input = {}) {
  if (input === null || typeof input !== 'object' || Array.isArray(input)) {
    throw infrastructureError(ERROR_CODES.INVALID_CONFIG, 'config must be an object');
  }
  const config = { ...DEFAULT_CONFIG, ...input };
  positiveInteger(config.maxContexts, 'maxContexts');
  positiveInteger(config.maxQueue, 'maxQueue', { allowZero: true });
  positiveInteger(config.acquireTimeoutMs, 'acquireTimeoutMs');
  positiveInteger(config.leaseTimeoutMs, 'leaseTimeoutMs');
  if (typeof config.headless !== 'boolean') {
    throw infrastructureError(ERROR_CODES.INVALID_CONFIG, 'headless must be boolean');
  }
  if (config.executablePath !== undefined && typeof config.executablePath !== 'string') {
    throw infrastructureError(ERROR_CODES.INVALID_CONFIG, 'executablePath must be a string');
  }
  if (config.logger !== undefined && typeof config.logger !== 'function') {
    throw infrastructureError(ERROR_CODES.INVALID_CONFIG, 'logger must be a function');
  }
  for (const name of ['launchOptions', 'contextOptions']) {
    if (config[name] === null || typeof config[name] !== 'object' || Array.isArray(config[name])) {
      throw infrastructureError(ERROR_CODES.INVALID_CONFIG, `${name} must be an object`);
    }
  }
  return Object.freeze({
    ...config,
    launchOptions: Object.freeze({ ...config.launchOptions }),
    contextOptions: Object.freeze({ ...config.contextOptions }),
  });
}

function validateLeaseOptions(options = {}, config) {
  if (options === null || typeof options !== 'object' || Array.isArray(options)) {
    throw infrastructureError(ERROR_CODES.INVALID_CONFIG, 'lease options must be an object');
  }
  const timeoutMs = options.timeoutMs ?? config.acquireTimeoutMs;
  const leaseTimeoutMs = options.leaseTimeoutMs ?? config.leaseTimeoutMs;
  positiveInteger(timeoutMs, 'timeoutMs');
  positiveInteger(leaseTimeoutMs, 'leaseTimeoutMs');
  if (options.signal !== undefined && !(options.signal instanceof AbortSignal)) {
    throw infrastructureError(ERROR_CODES.INVALID_CONFIG, 'signal must be an AbortSignal');
  }
  return { timeoutMs, leaseTimeoutMs, signal: options.signal };
}

module.exports = { DEFAULT_CONFIG, validateConfig, validateLeaseOptions };
