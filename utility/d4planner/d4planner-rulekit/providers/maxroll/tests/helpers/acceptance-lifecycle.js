'use strict';

const { throwAfterCleanup } = require('./adapter-acceptance');

async function initializeOwnedRuntime({
  createBrowser,
  createSnapshots,
  createProfile,
  createProvider,
  cleanup,
}) {
  const browser = await createBrowser();
  const runtime = {
    browser,
    resources: { lease: null, mount: null, networkProbe: null, ownedPid: null },
    snapshots: null,
    profile: null,
    provider: null,
    session: null,
  };
  let primaryError = null;
  let cleanupError = null;
  try {
    await browser.start();
    runtime.resources.ownedPid = browser.getStatus?.().pid ?? null;
    runtime.snapshots = await createSnapshots(browser);
    runtime.profile = await createProfile();
    runtime.provider = await createProvider(runtime);
    return runtime;
  } catch (error) {
    primaryError = error;
    try {
      await cleanup(runtime);
    } catch (cleanupFailure) {
      cleanupError = cleanupFailure;
    }
  }
  throwAfterCleanup(primaryError, cleanupError);
}

async function runOwnedAcceptance({ initialize, execute, cleanup }) {
  let runtime = null;
  let result;
  let primaryError = null;
  let cleanupError = null;
  try {
    runtime = await initialize();
    result = await execute(runtime);
  } catch (error) {
    primaryError = error;
  } finally {
    if (runtime) {
      try {
        await cleanup(runtime);
      } catch (error) {
        cleanupError = error;
      }
    }
  }
  throwAfterCleanup(primaryError, cleanupError);
  return result;
}

module.exports = { initializeOwnedRuntime, runOwnedAcceptance };
