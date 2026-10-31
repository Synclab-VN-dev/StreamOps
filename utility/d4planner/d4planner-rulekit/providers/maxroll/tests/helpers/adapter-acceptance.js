'use strict';

class NetworkEgressProbe {
  #cdp;
  #closed = false;
  #diagnostics = {
    requestAttempts: 0,
    responseEvents: 0,
    loadingFailures: 0,
    webSocketAttempts: 0,
    webSocketHandshakes: 0,
    externalEgressCompleted: 0,
  };

  constructor(cdp) {
    this.#cdp = cdp;
  }

  static async attach(lease) {
    const cdp = await lease.context.newCDPSession(lease.page);
    const probe = new NetworkEgressProbe(cdp);
    await cdp.send('Network.enable');
    cdp.on('Network.requestWillBeSent', event => {
      if (isNetworkUrl(event.request?.url)) probe.#diagnostics.requestAttempts += 1;
    });
    cdp.on('Network.responseReceived', event => {
      if (!isNetworkUrl(event.response?.url)) return;
      probe.#diagnostics.responseEvents += 1;
      if (event.response?.remoteIPAddress) probe.#diagnostics.externalEgressCompleted += 1;
    });
    cdp.on('Network.loadingFailed', () => { probe.#diagnostics.loadingFailures += 1; });
    cdp.on('Network.webSocketCreated', event => {
      if (isNetworkUrl(event.url)) probe.#diagnostics.webSocketAttempts += 1;
    });
    cdp.on('Network.webSocketHandshakeResponseReceived', () => {
      probe.#diagnostics.webSocketHandshakes += 1;
      probe.#diagnostics.externalEgressCompleted += 1;
    });
    return probe;
  }

  getDiagnostics() {
    return Object.freeze({ ...this.#diagnostics, source: 'CDP.Network' });
  }

  async close() {
    if (this.#closed) return;
    this.#closed = true;
    await this.#cdp.send('Network.disable');
    await this.#cdp.detach();
  }
}

async function cleanupOwnedRuntime({ session, networkProbe, mount, lease, browser, ownedPid }) {
  const failures = [];
  await attempt(() => networkProbe?.close(), failures);
  await attempt(() => session?.close(), failures);

  const beforeStop = browser.getStatus();
  const metrics = browser.getMetrics();
  if (mount && mount.mounted !== false) failures.push(new Error('snapshot mount remained active'));
  if (lease && lease.valid !== false) failures.push(new Error('browser lease remained valid'));
  if (beforeStop.activeLeases !== 0) failures.push(new Error('browser retained active leases'));
  if (metrics.currentContexts !== 0) failures.push(new Error('browser retained owned contexts'));

  await attempt(() => browser.stop(), failures);
  const afterStop = browser.getStatus();
  if (afterStop.state !== 'stopped' || afterStop.pid !== null) {
    failures.push(new Error('browser did not reach stopped state'));
  }
  if (ownedPid && !await processExited(ownedPid)) {
    failures.push(new Error('owned Chromium process remained alive'));
  }
  if (failures.length) throw new AggregateError(failures, 'owned runtime cleanup failed');
  return Object.freeze({
    probeClosed: true,
    mountUnmounted: true,
    leaseReleased: true,
    activeLeases: beforeStop.activeLeases,
    currentContexts: metrics.currentContexts,
    browserState: afterStop.state,
    ownedProcessExited: true,
  });
}

function throwAfterCleanup(primaryError, cleanupError) {
  if (primaryError && cleanupError) {
    throw new AggregateError([primaryError, cleanupError],
      'adapter acceptance and cleanup both failed');
  }
  if (cleanupError) throw cleanupError;
  if (primaryError) throw primaryError;
}

async function attempt(operation, failures) {
  try {
    await operation();
  } catch (error) {
    failures.push(error);
  }
}

async function processExited(pid) {
  const deadline = Date.now() + 2_000;
  while (Date.now() <= deadline) {
    try {
      process.kill(pid, 0);
    } catch (error) {
      if (error.code === 'ESRCH') return true;
      if (error.code === 'EPERM') return false;
      throw error;
    }
    await new Promise(resolve => setTimeout(resolve, 25));
  }
  return false;
}

function isNetworkUrl(value) {
  return typeof value === 'string' && /^(?:https?|wss?):\/\//i.test(value);
}

module.exports = { NetworkEgressProbe, cleanupOwnedRuntime, throwAfterCleanup };
