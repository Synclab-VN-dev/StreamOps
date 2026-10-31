#!/usr/bin/env node
'use strict';

const path = require('node:path');
const {
  MaxrollLiveCaptureOrchestrator,
  discoverBrowser,
} = require('../src/live-capture-orchestrator');

async function main() {
  const packageRoot = path.resolve(__dirname, '..');
  const executablePath = discoverBrowser(process.env);
  const orchestrator = new MaxrollLiveCaptureOrchestrator();
  const controller = new AbortController();
  const abort = () => controller.abort();
  process.once('SIGINT', abort);
  process.once('SIGTERM', abort);
  const report = await orchestrator.run({
    packageRoot, executablePath, signal: controller.signal,
  });
  process.stdout.write(`${JSON.stringify({
    status: report.status,
    runtime: report.runtime,
    capture: report.capture,
    offline: report.offline,
    cleanup: report.cleanup,
  })}\n`);
}

main().catch(error => {
  process.stderr.write(`${error.code ?? error.name}: ${error.message}\n`);
  if (error.report) {
    process.stderr.write(`${JSON.stringify({
      status: error.report.status,
      runtime: error.report.runtime,
      capture: error.report.capture,
      cleanup: error.report.cleanup,
    })}\n`);
  }
  process.exitCode = 1;
});
