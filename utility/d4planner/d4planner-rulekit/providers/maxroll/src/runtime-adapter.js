'use strict';

const { ERROR_CODES, MaxrollProviderError } = require('./errors');
const { sha256 } = require('./value');

class MaxrollRuntimeAdapter {
  #lease;
  #profile;
  #cdp = null;

  constructor({ lease, profile }) {
    this.#lease = lease;
    this.#profile = profile;
  }

  async initialize() {
    this.#assertLease();
    this.#cdp = await this.#lease.createCDPSession();
    await this.#cdp.send('Runtime.enable');
    await this.#lease.page.goto(this.#profile.sourceUrl, { waitUntil: 'domcontentloaded', timeout: 15_000 });
    await this.#lease.page.locator(this.#profile.selectors.ready).waitFor({ state: 'attached', timeout: 10_000 });
    const identity = await this.#lease.page.evaluate(selectors => ({
      runtimeVersion: document.querySelector(selectors.runtimeVersion)?.textContent ?? null,
      gamePatch: document.querySelector(selectors.gamePatch)?.textContent ?? null,
      assetSha256: document.querySelector(selectors.assetSha256)?.textContent ?? null,
    }), this.#profile.selectors);
    if (identity.runtimeVersion !== this.#profile.runtimeVersion ||
        identity.gamePatch !== this.#profile.gamePatch ||
        identity.assetSha256 !== this.#profile.assetSha256) {
      throw new MaxrollProviderError(ERROR_CODES.RUNTIME_MISMATCH, 'runtime identity mismatch');
    }
    return identity;
  }

  async apply(desired, expectedFingerprint) {
    this.#assertLease();
    const phaseLocator = this.#lease.page.locator(this.#profile.selectors.phase);
    const priorPhase = Number(await phaseLocator.textContent());
    await this.#lease.page.locator(this.#profile.selectors.buildInput).fill(JSON.stringify(desired));
    await this.#lease.page.locator(this.#profile.selectors.applyButton).click();
    await this.#lease.page.waitForFunction(({ selector, prior }) =>
      Number(document.querySelector(selector)?.textContent) > prior,
    { selector: this.#profile.selectors.phase, prior: priorPhase }, { timeout: 10_000 });
    const phase = Number(await phaseLocator.textContent());
    let observed;
    try {
      observed = JSON.parse(await this.#lease.page.locator(this.#profile.selectors.readback).textContent());
    } catch (error) {
      throw new MaxrollProviderError(ERROR_CODES.APPLY_FAILED, 'runtime read-back is invalid', { cause: error });
    }
    if (sha256(observed) !== expectedFingerprint) {
      throw new MaxrollProviderError(ERROR_CODES.READBACK_MISMATCH, 'desired build read-back mismatch');
    }
    return { phase, observed };
  }

  get cdp() {
    if (!this.#cdp) throw new MaxrollProviderError(ERROR_CODES.RUNTIME_NOT_READY, 'runtime is not initialized');
    return this.#cdp;
  }

  #assertLease() {
    if (!this.#lease.valid) throw new MaxrollProviderError(ERROR_CODES.SESSION_INVALIDATED, 'browser lease is invalid');
  }
}

module.exports = { MaxrollRuntimeAdapter };
