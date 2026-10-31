#!/usr/bin/env node
'use strict';

// Internal process entrypoint, not an Application API or package export.
// Rule Kit owns composition; the host supplies only its IPC adapter path.
const path = require('node:path');
const { createComposition } = require('./production-composition');

async function boot() {
  const adapterPath = process.argv[2];
  if (!adapterPath || !path.isAbsolute(adapterPath)) throw new Error('absolute IPC adapter path required');
  const adapter = require(adapterPath);
  if (typeof adapter.main !== 'function') throw new Error('invalid IPC adapter');
  if (!process.env.D4_RULEKIT_WORKER_INSTANCE_ID ||
      !Number.isInteger(Number(process.env.D4_RULEKIT_WORKER_GENERATION)) ||
      Number(process.env.D4_RULEKIT_WORKER_GENERATION) <= 0) {
    throw new Error('managed worker identity is required');
  }
  const composition = await createComposition(process.env);
  try {
    const manager = composition.snapshotManagement;
    // Only approved calls cross into the host adapter. Registry, resolver,
    // quiescing state and the manager object stay inside Rule Kit.
    const application = Object.fromEntries([
      'listProviders', 'createSession', 'evaluate', 'previewChanges',
      'commitChanges', 'resetSession', 'getSession', 'closeSession',
    ].map(method => [method, (...args) => {
      if (manager?.quiescing && method !== 'closeSession') {
        throw Object.assign(new Error('snapshot binding requires worker restart'),
          { code: 'WORKER_RESTART_REQUIRED' });
      }
      return composition.application[method](...args);
    }]));
    await adapter.main({
      application,
      snapshotManagement: manager ? { invoke: (method, params) => manager.invoke(method, params) } : undefined,
      calculationAvailability: composition.calculationAvailability,
      calculationReason: composition.calculationReason,
      close: composition.close,
    });
  } catch (error) {
    await composition.close?.();
    throw error;
  }
}

boot().catch(error => {
  process.stderr.write(`Rule Kit worker startup failed: ${error?.message ?? 'unknown error'}\n`);
  process.exitCode = 1;
});
