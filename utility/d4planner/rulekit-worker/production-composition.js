'use strict';
const runtimeLog = require('../../d4-rulekit/runtime-logging/src/logger');

const fs = require('node:fs');
const path = require('node:path');
const { D4RuleKitApplication } = require('../../d4-rulekit/application/src');
const {
  BrowserInfrastructure, FileSystemSnapshotStore, WebSnapshotManager,
} = require('../../d4-rulekit/browser-infra/src');
const {
  MaxrollComponentFactory, MaxrollPatchProfile, MaxrollProvider,
  REAL_MAXROLL_COMPONENT_FACTORY,
} = require('../../d4-rulekit/providers/maxroll/src');

function required(env, name) {
  if (typeof env[name] !== 'string' || env[name].length === 0) throw new Error(`${name} is required`);
  return env[name];
}

function positive(env, name, fallback) {
  const value = env[name] === undefined ? fallback : Number(env[name]);
  if (!Number.isInteger(value) || value <= 0) throw new Error(`${name} must be a positive integer`);
  return value;
}

async function createComposition(env) {
  if (env.D4_RULEKIT_DATA_ROOT) return require('./managed-snapshot-composition').createManagedComposition(env);
  const profilePath = path.resolve(required(env, 'D4_RULEKIT_PROFILE_JSON'));
  const snapshotRoot = path.resolve(required(env, 'D4_RULEKIT_SNAPSHOT_ROOT'));
  const profile = new MaxrollPatchProfile(JSON.parse(fs.readFileSync(profilePath, 'utf8')));
  const browser = new BrowserInfrastructure({logger:runtimeLog.browserEvent,
    executablePath: env.D4_RULEKIT_CHROMIUM_EXECUTABLE || undefined,
    headless: true,
    maxContexts: positive(env, 'D4_RULEKIT_MAX_CONTEXTS', 2),
    maxQueue: positive(env, 'D4_RULEKIT_BROWSER_MAX_QUEUE', 16),
    contextOptions: { serviceWorkers: 'block' },
  });
  await browser.start();
  const store = new FileSystemSnapshotStore({ rootDir: snapshotRoot });
  const snapshots = new WebSnapshotManager({ browser, store });
  const componentFactory = profile.runtimeKind === 'maxroll-ui-cdp-v1'
    ? REAL_MAXROLL_COMPONENT_FACTORY : new MaxrollComponentFactory();
  const provider = new MaxrollProvider({ browser, snapshots, profile, componentFactory });
  const application = new D4RuleKitApplication({
    providers: [provider],
    maxSessions: positive(env, 'D4_RULEKIT_MAX_SESSIONS', 8),
    sessionTtlMs: positive(env, 'D4_RULEKIT_SESSION_TTL_MS', 30 * 60_000),
    operationTimeoutMs: positive(env, 'D4_RULEKIT_OPERATION_TIMEOUT_MS', 15_000),
    cleanupTimeoutMs: positive(env, 'D4_RULEKIT_CLEANUP_TIMEOUT_MS', 5_000),
  });
  return { application, close: () => browser.stop() };
}

module.exports = { createComposition };
