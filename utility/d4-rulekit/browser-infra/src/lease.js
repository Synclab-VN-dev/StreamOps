'use strict';

const { ERROR_CODES, infrastructureError } = require('./errors');

class BrowserLease {
  #owner;
  #valid = true;
  #invalidError = null;
  #cdpPromise = null;

  constructor({ id, context, page, owner }) {
    this.id = id;
    this.context = context;
    this.page = page;
    this.#owner = owner;
    Object.defineProperty(this, 'id', { writable: false });
    Object.defineProperty(this, 'context', { writable: false });
    Object.defineProperty(this, 'page', { writable: false });
  }

  get valid() {
    return this.#valid;
  }

  get invalidReason() {
    return this.#invalidError?.code ?? null;
  }

  async createCDPSession() {
    this.#assertValid();
    if (!this.#cdpPromise) {
      this.#cdpPromise = this.context.newCDPSession(this.page).catch(error => {
        this.#cdpPromise = null;
        this.#assertValid();
        throw error;
      });
    }
    const session = await this.#cdpPromise;
    this.#assertValid();
    return session;
  }

  async release() {
    return this.#owner.release(this.id);
  }

  _invalidate(error) {
    if (!this.#valid) return false;
    this.#valid = false;
    this.#invalidError = error;
    return true;
  }

  _error() {
    return this.#invalidError;
  }

  #assertValid() {
    if (!this.#valid) {
      throw this.#invalidError ?? infrastructureError(
        ERROR_CODES.LEASE_EXPIRED, `lease ${this.id} is invalid`);
    }
  }
}

module.exports = { BrowserLease };
