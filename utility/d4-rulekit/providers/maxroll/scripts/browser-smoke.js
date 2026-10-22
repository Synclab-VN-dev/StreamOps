#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const artifacts = path.join(root, 'artifacts');
const reportPath = path.join(artifacts, 'browser-smoke.json');
const executablePath = process.env.BROWSER_INFRA_CHROMIUM_PATH;
const report = {
  schemaVersion: 'maxroll-provider-browser-smoke/1',
  startedAt: new Date().toISOString(),
  executablePath: executablePath ?? null,
  nodeVersion: process.version,
  playwrightVersion: null,
  browserVersion: null,
  navigation: null,
  cleanup: null,
  status: 'FAIL',
};

let infrastructure = null;
let lease = null;

async function run() {
  if (!executablePath || !fs.existsSync(executablePath)) {
    throw new Error('BROWSER_INFRA_CHROMIUM_PATH must point to a preinstalled executable');
  }
  report.playwrightVersion = require('playwright-core/package.json').version;
  const { BrowserInfrastructure } = require('@streamops/browser-infrastructure');
  infrastructure = new BrowserInfrastructure({
    executablePath,
    headless: true,
    maxContexts: 1,
    maxQueue: 1,
    acquireTimeoutMs: 5_000,
    cleanupTimeoutMs: 5_000,
    contextOptions: { serviceWorkers: 'block' },
  });
  await infrastructure.start();
  report.browserVersion = await infrastructure.withLease({}, async probeLease =>
    probeLease.context.browser()?.version() ?? null);
  lease = await infrastructure.acquire({ timeoutMs: 5_000, leaseTimeoutMs: 10_000 });
  const response = await lease.page.goto(
    'data:text/html,<title>streamops-browser-smoke</title><main id="ready">ready</main>',
    { waitUntil: 'load', timeout: 5_000 },
  );
  const observed = await lease.page.evaluate(() => ({
    title: document.title,
    ready: document.querySelector('#ready')?.textContent ?? null,
  }));
  if (response !== null || observed.title !== 'streamops-browser-smoke' || observed.ready !== 'ready') {
    throw new Error('preinstalled browser navigation smoke returned unexpected state');
  }
  report.navigation = 'PASS';
  await lease.release();
  lease = null;
  if (infrastructure.getStatus().activeLeases !== 0) {
    throw new Error('browser smoke lease cleanup was not confirmed');
  }
  await infrastructure.stop();
  if (infrastructure.getStatus().state !== 'stopped') {
    throw new Error('browser smoke stop cleanup was not confirmed');
  }
  report.cleanup = 'PASS';
  report.status = 'PASS';
}

(async () => {
  let failure = null;
  try {
    await run();
  } catch (error) {
    failure = error;
    report.error = { name: error.name, message: error.message };
  } finally {
    if (lease) await lease.release().catch(() => {});
    if (infrastructure) await infrastructure.stop().catch(() => {});
    report.finishedAt = new Date().toISOString();
    fs.mkdirSync(artifacts, { recursive: true });
    fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`);
    process.stdout.write(`${JSON.stringify(report)}\n`);
  }
  if (failure) throw failure;
})().catch(error => {
  process.stderr.write(`${error.stack ?? error.message}\n`);
  process.exitCode = 1;
});
