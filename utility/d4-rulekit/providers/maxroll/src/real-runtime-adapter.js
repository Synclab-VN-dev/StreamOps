'use strict';

const { ERROR_CODES, MaxrollProviderError } = require('./errors');
const { sha256 } = require('./value');

class RealMaxrollRuntimeAdapter {
  #lease;
  #profile;
  #cdp = null;
  #pauseChain = Promise.resolve();
  #activeCapture = null;
  #captures = new Map();
  #phase = 0;
  #breakpointLocations = 0;
  #runtimeFailure = null;
  #closed = false;

  constructor({ lease, profile }) {
    this.#lease = lease;
    this.#profile = profile;
  }

  async initialize() {
    this.#assertLease();
    if (this.#profile.runtimeKind !== 'maxroll-ui-cdp-v1') {
      throw new MaxrollProviderError(ERROR_CODES.INVALID_CONFIG,
        'real runtime adapter requires maxroll-ui-cdp-v1 profile');
    }
    const runtime = this.#profile.realRuntime;
    this.#cdp = await this.#lease.createCDPSession();
    await this.#cdp.send('Debugger.enable');
    this.#cdp.on('Debugger.breakpointResolved', () => { this.#breakpointLocations += 1; });
    this.#cdp.on('Debugger.paused', event => { this.#queuePause(event); });
    const disconnect = () => this.#recordRuntimeFailure(new MaxrollProviderError(
      ERROR_CODES.RUNTIME_NOT_READY, 'CDP disconnected while the real runtime was active'));
    this.#cdp.on('close', disconnect);
    const breakpoint = await this.#cdp.send('Debugger.setBreakpointByUrl', {
      urlRegex: runtime.assetUrlRegex,
      lineNumber: runtime.breakpoint.lineNumber,
      columnNumber: runtime.breakpoint.columnNumber,
    });
    this.#breakpointLocations += breakpoint.locations?.length ?? 0;

    await this.#lease.page.goto(this.#profile.sourceUrl, {
      waitUntil: 'domcontentloaded', timeout: runtime.navigationTimeoutMs ?? 30_000,
    });
    await this.#lease.page.getByRole('button', {
      name: runtime.newProfileButton, exact: true,
    }).waitFor({ state: 'visible', timeout: runtime.navigationTimeoutMs ?? 30_000 });

    const identity = await this.#lease.page.evaluate(({ patchPattern, assetPattern }) => {
      const body = document.body?.innerText ?? '';
      const patch = body.match(new RegExp(patchPattern))?.[1]?.trim() ?? null;
      const assets = performance.getEntriesByType('resource').map(entry => entry.name);
      return {
        gamePatch: patch,
        assetMatched: assets.some(url => new RegExp(assetPattern).test(url)),
      };
    }, {
      patchPattern: runtime.gamePatchPattern,
      assetPattern: runtime.assetUrlRegex,
    });
    if (identity.gamePatch !== this.#profile.gamePatch || !identity.assetMatched ||
        this.#breakpointLocations === 0) {
      throw new MaxrollProviderError(ERROR_CODES.RUNTIME_MISMATCH,
        'real Maxroll runtime identity or breakpoint does not match the pinned profile', {
          details: { gamePatch: identity.gamePatch, breakpointLocations: this.#breakpointLocations },
        });
    }
    await this.#pauseChain;
    this.#assertRuntimeHealthy();
    return {
      runtimeVersion: this.#profile.runtimeVersion,
      gamePatch: identity.gamePatch,
      assetSha256: this.#profile.assetSha256,
      breakpointLocations: this.#breakpointLocations,
    };
  }

  async apply(desired, expectedFingerprint) {
    this.#assertLease();
    this.#assertRuntimeHealthy();
    const runtime = this.#profile.realRuntime;
    await this.#dismissOptionalOverlay();
    await this.#lease.page.getByRole('button', {
      name: runtime.newProfileButton, exact: true,
    }).click();
    const level = this.#lease.page.locator(runtime.levelSelector).first();
    await level.waitFor({ state: 'visible', timeout: runtime.interactionTimeoutMs ?? 10_000 });
    await this.#lease.page.waitForFunction(({ selector, desired }) =>
      Number(document.querySelector(selector)?.value) !== desired,
    { selector: runtime.levelSelector, desired: desired.level },
    { timeout: runtime.interactionTimeoutMs ?? 10_000 });
    await level.fill(String(desired.level));
    await level.press('Enter');
    await this.#lease.page.waitForFunction(({ selector, expected }) =>
      Number(document.querySelector(selector)?.value) === expected,
    { selector: runtime.levelSelector, expected: desired.level },
    { timeout: runtime.interactionTimeoutMs ?? 10_000 });

    await this.#lease.page.getByText(runtime.slotLabel, { exact: true }).first().evaluate(element => {
      const target = element.parentElement?.querySelector('[class*=Slot__item]');
      if (!target) throw new Error('slot item target not found');
      target.click();
    });
    const item = this.#lease.page.getByText(runtime.itemBaseName, { exact: true }).first();
    await item.waitFor({ state: 'visible', timeout: runtime.interactionTimeoutMs ?? 10_000 });

    const modifierActive = desired.equipment.Helm.modifiers.includes('of-dampening');
    let capturePromise;
    try {
      if (!modifierActive) capturePromise = (await this.#beginCapture()).completion;
      await item.click();
      if (modifierActive) {
        const addModifier = this.#lease.page.getByText(runtime.addModifierLabel, { exact: true }).first();
        await addModifier.waitFor({ state: 'visible', timeout: runtime.interactionTimeoutMs ?? 10_000 });
        await addModifier.click();
        const option = this.#lease.page.getByText(runtime.modifierPickerLabel, { exact: true });
        if (await option.count() !== 1) {
          throw new MaxrollProviderError(ERROR_CODES.APPLY_FAILED,
            'real modifier identity is missing or ambiguous');
        }
        capturePromise = (await this.#beginCapture()).completion;
        await option.click();
      }
    } catch (error) {
      this.#abortCapture(error);
      if (capturePromise) await capturePromise.catch(() => {});
      throw error;
    }

    const raw = await capturePromise;
    const observedUi = await this.#readUi();
    const expectedModifierCount = modifierActive ? 1 : 0;
    if (observedUi.modifierCount !== expectedModifierCount ||
        observedUi.modifierPresent !== modifierActive) {
      throw new MaxrollProviderError(ERROR_CODES.READBACK_MISMATCH,
        'real Maxroll modifier read-back is partial or ambiguous');
    }
    const observed = {
      class: observedUi.class,
      level: observedUi.level,
      difficulty: observedUi.difficulty,
      equipment: {
        Helm: {
          itemId: observedUi.itemPresent ? 'runic-skullcap' : null,
          modifiers: observedUi.modifierPresent ? ['of-dampening'] : [],
        },
      },
    };
    if (sha256(observed) !== expectedFingerprint) {
      throw new MaxrollProviderError(ERROR_CODES.READBACK_MISMATCH,
        'real Maxroll desired-state read-back mismatch');
    }
    this.#phase += 1;
    const phase = this.#phase;
    this.#captures.clear();
    this.#captures.set(phase, Object.freeze({
      phase,
      inputFingerprint: expectedFingerprint,
      raw: Object.freeze(raw.map(value => Object.freeze({ ...value }))),
      displays: Object.freeze({ ...observedUi.displays }),
    }));
    return { phase, observed, inputFingerprint: expectedFingerprint };
  }

  takeCapture(phase, expectedFingerprint) {
    const capture = this.#captures.get(phase);
    if (!capture || capture.inputFingerprint !== expectedFingerprint) {
      throw new MaxrollProviderError(ERROR_CODES.STALE_METRICS,
        'real metric capture does not belong to the current input phase');
    }
    this.#captures.delete(phase);
    return capture;
  }

  get cdp() {
    if (!this.#cdp) throw new MaxrollProviderError(ERROR_CODES.RUNTIME_NOT_READY,
      'real runtime is not initialized');
    return this.#cdp;
  }

  async close() {
    if (this.#closed) return;
    this.#closed = true;
    this.#recordRuntimeFailure(new MaxrollProviderError(ERROR_CODES.SESSION_INVALIDATED,
      'real runtime adapter closed while a capture was pending'));
  }

  async #beginCapture() {
    await this.#pauseChain;
    this.#assertRuntimeHealthy();
    if (this.#activeCapture) {
      throw new MaxrollProviderError(ERROR_CODES.RUNTIME_NOT_READY,
        'a real metric capture is already active');
    }
    const runtime = this.#profile.realRuntime;
    const expected = new Set(this.#profile.metricCatalog.map(metric => metric.internalId));
    let resolveCapture;
    let rejectCapture;
    const promise = new Promise((resolve, reject) => {
      resolveCapture = resolve;
      rejectCapture = reject;
    });
    const capture = {
      expected,
      values: new Map(),
      timer: null,
      settled: false,
      resolve: values => {
        if (capture.settled) return;
        capture.settled = true;
        clearTimeout(capture.timer);
        if (this.#activeCapture === capture) this.#activeCapture = null;
        resolveCapture(values);
      },
      reject: error => {
        if (capture.settled) return;
        capture.settled = true;
        clearTimeout(capture.timer);
        if (this.#activeCapture === capture) this.#activeCapture = null;
        rejectCapture(error);
      },
    };
    capture.timer = setTimeout(() => capture.reject(new MaxrollProviderError(
      ERROR_CODES.METRICS_INCOMPLETE,
      'timed out waiting for the complete real metric catalog')),
    runtime.captureTimeoutMs);
    this.#activeCapture = capture;
    return { completion: promise };
  }

  #abortCapture(error) {
    const capture = this.#activeCapture;
    if (!capture) return;
    capture.reject(error);
  }

  #queuePause(event) {
    this.#pauseChain = this.#pauseChain
      .then(() => this.#runtimeFailure ? this.#resumePausedTarget() : this.#handlePause(event))
      .catch(error => { this.#recordRuntimeFailure(error); });
  }

  async #handlePause(event) {
    let captureError = null;
    let completedCapture = null;
    let completedValues = null;
    try {
      const capture = this.#activeCapture;
      if (!capture) return;
      const frame = event.callFrames?.[0];
      if (!frame) return;
      const evaluated = await this.#cdp.send('Debugger.evaluateOnCallFrame', {
        callFrameId: frame.callFrameId,
        expression: this.#profile.realRuntime.captureExpression,
        returnByValue: true,
      });
      const value = evaluated.result?.value;
      const internalId = Number(value?.id);
      if (capture.expected.has(internalId)) {
        capture.values.set(internalId, { internalId, rawValue: value.raw });
        if (capture.values.size === capture.expected.size) {
          completedCapture = capture;
          completedValues = [...capture.values.values()];
        }
      }
    } catch (error) {
      captureError = this.#runtimeError('CDP call-frame evaluation failed', error);
    } finally {
      try {
        await this.#resumePausedTarget();
      } catch (error) {
        throw this.#runtimeError('CDP could not resume a paused target', error);
      }
    }
    if (captureError) throw captureError;
    completedCapture?.resolve(completedValues);
  }

  async #resumePausedTarget() {
    await this.#cdp.send('Debugger.resume');
  }

  #recordRuntimeFailure(error) {
    const failure = error instanceof MaxrollProviderError ? error :
      this.#runtimeError('real Maxroll CDP runtime failed', error);
    if (!this.#runtimeFailure) this.#runtimeFailure = failure;
    this.#abortCapture(this.#runtimeFailure);
  }

  #runtimeError(message, cause) {
    return new MaxrollProviderError(ERROR_CODES.RUNTIME_NOT_READY, message, { cause });
  }

  #assertRuntimeHealthy() {
    if (this.#closed) {
      throw new MaxrollProviderError(ERROR_CODES.SESSION_INVALIDATED,
        'real runtime adapter is closed');
    }
    if (this.#runtimeFailure) throw this.#runtimeFailure;
  }

  async #dismissOptionalOverlay() {
    const label = this.#profile.realRuntime.dismissButton;
    if (!label) return;
    const button = this.#lease.page.getByRole('button', { name: label, exact: true }).first();
    if (await button.count() && await button.isVisible()) await button.click();
  }

  async #readUi() {
    const runtime = this.#profile.realRuntime;
    return this.#lease.page.evaluate(config => {
      const categories = config.categoryLabels;
      const stats = {};
      for (const section of document.querySelectorAll(config.statsSectionSelector)) {
        const title = (section.querySelector('h3')?.textContent ?? '').trim().toUpperCase();
        const category = categories[title] ?? (title === '' ? 'summary' : null);
        if (!category) continue;
        for (const row of section.querySelectorAll('li')) {
          const spans = row.querySelectorAll(':scope > span');
          if (spans.length >= 2) stats[`${category}|${spans[0].textContent.trim()}`] = spans[1].textContent.trim();
        }
      }
      const body = document.body?.innerText ?? '';
      const modifiers = [...document.querySelectorAll(config.itemModifierSelector)]
        .map(row => (row.innerText ?? '').trim()).filter(Boolean);
      return {
        class: body.match(new RegExp(config.classPattern))?.[1]?.trim() ?? null,
        level: Number(document.querySelector(config.levelSelector)?.value),
        difficulty: body.match(new RegExp(config.difficultyPattern))?.[1]?.trim() ?? null,
        itemPresent: [...document.querySelectorAll('*')]
          .filter(element => element.children.length === 0 && element.textContent?.trim() === config.slotLabel)
          .some(element => element.parentElement?.querySelector('[class*=Slot__item]')
            ?.textContent?.includes(config.itemBaseName)),
        modifierPresent: modifiers.some(value => value.includes(config.expectedModifierEffect)),
        modifierCount: modifiers.length,
        displays: stats,
      };
    }, runtime);
  }

  #assertLease() {
    if (!this.#lease.valid) throw new MaxrollProviderError(ERROR_CODES.SESSION_INVALIDATED,
      'browser lease is invalid');
  }
}

module.exports = { RealMaxrollRuntimeAdapter };
