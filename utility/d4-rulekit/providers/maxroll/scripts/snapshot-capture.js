#!/usr/bin/env node
'use strict';

const { MaxrollSnapshotCapturer } = require('../src/snapshot-capturer');
const { discoverBrowser } = require('../src/live-capture-orchestrator');

function parseArguments(argv) {
  const options = {};
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === '--output' && argv[index + 1]) {
      options.output = argv[index + 1];
      index += 1;
      continue;
    }
    throw new Error(`unsupported or incomplete argument: ${argv[index]}`);
  }
  if (!options.output) throw new Error('usage: snapshot:capture -- --output <folder>');
  return Object.freeze(options);
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  const controller = new AbortController();
  const abort = () => controller.abort();
  process.once('SIGINT', abort);
  process.once('SIGTERM', abort);
  const report = await new MaxrollSnapshotCapturer().capture({
    ...options,
    executablePath: discoverBrowser(process.env),
    signal: controller.signal,
  });
  process.stdout.write(`${JSON.stringify({
    status: report.status,
    validation: report.validation,
    realE2E: report.realE2E,
    outputPath: report.outputPath,
    runtime: report.runtime,
    capture: report.capture,
    integrity: report.integrity,
    cleanup: report.cleanup,
  })}\n`);
}

if (require.main === module) {
  main().catch(error => {
    process.stderr.write(`${error.code ?? error.name}: ${error.message}\n`);
    process.exitCode = 1;
  });
}

module.exports = { parseArguments };
