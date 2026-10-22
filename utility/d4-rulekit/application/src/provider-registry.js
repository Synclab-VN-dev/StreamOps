'use strict';

const { ApplicationError, ERROR_CODES } = require('./errors');
const { immutableCopy } = require('./value');

class ProviderRegistry {
  #providers = new Map();

  constructor(providers) {
    if (!Array.isArray(providers) || providers.length === 0) {
      throw new ApplicationError(ERROR_CODES.INVALID_INPUT, 'providers must be a non-empty array');
    }
    for (const provider of providers) this.#register(provider);
  }

  #register(provider) {
    if (!provider || typeof provider.id !== 'string' || !provider.id ||
        typeof provider.version !== 'string' || !provider.version ||
        typeof provider.getCapabilities !== 'function' || typeof provider.createSession !== 'function') {
      throw new ApplicationError(ERROR_CODES.INVALID_INPUT, 'provider contract is invalid');
    }
    if (this.#providers.has(provider.id)) {
      throw new ApplicationError(ERROR_CODES.INVALID_INPUT, `duplicate provider: ${provider.id}`);
    }
    sanitizeCapabilities(provider.getCapabilities());
    this.#providers.set(provider.id, provider);
  }

  list() {
    return [...this.#providers.values()].map(provider => immutableCopy({
      id: provider.id,
      version: provider.version,
      available: provider.available !== false,
      capabilities: sanitizeCapabilities(provider.getCapabilities()),
    })).sort((a, b) => a.id.localeCompare(b.id));
  }

  get(id, version) {
    const provider = this.#providers.get(id);
    if (!provider) throw new ApplicationError(ERROR_CODES.PROVIDER_NOT_FOUND, `unknown provider: ${id}`);
    if (provider.available === false) {
      throw new ApplicationError(ERROR_CODES.PROVIDER_UNAVAILABLE, `provider unavailable: ${id}`);
    }
    if (version !== provider.version) {
      throw new ApplicationError(ERROR_CODES.PROVIDER_UNAVAILABLE, `provider version unavailable: ${id}@${version}`);
    }
    return provider;
  }
}

function sanitizeCapabilities(capabilities) {
  if (!capabilities || typeof capabilities.version !== 'string' ||
      !['stateful', 'stateless'].includes(capabilities.stateModel) ||
      !Array.isArray(capabilities.metricIds) || !Array.isArray(capabilities.changeTypes)) {
    throw new ApplicationError(ERROR_CODES.INVALID_INPUT, 'provider capabilities are invalid');
  }
  return {
    version: capabilities.version,
    policyVersion: capabilities.policyVersion ?? null,
    stateModel: capabilities.stateModel,
    metricIds: [...capabilities.metricIds],
    changeTypes: [...capabilities.changeTypes],
  };
}

module.exports = { ProviderRegistry };
