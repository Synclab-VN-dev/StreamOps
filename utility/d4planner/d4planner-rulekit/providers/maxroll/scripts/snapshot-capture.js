#!/usr/bin/env node
'use strict';

const { MaxrollSnapshotCapturer } = require('../src/snapshot-capturer');
const { discoverBrowser } = require('../src/live-capture-orchestrator');

function parseArguments(argv) {
  const options = {};
  for (let index = 0; index < argv.length; index += 1) {
    if (['--output', '--mode', '--config'].includes(argv[index]) && argv[index + 1] && !argv[index + 1].startsWith('--')) {
      const key = argv[index].slice(2);
      if (options[key]) throw new Error('duplicate argument: ' + argv[index]);
      options[key] = argv[index + 1];
      index += 1;
      continue;
    }
    throw new Error(`unsupported or incomplete argument: ${argv[index]}`);
  }
  if (options.mode && !['ui', 'calculation', 'all'].includes(options.mode)) throw new Error('unsupported mode');
  if (options.mode === 'all' && options.output) throw new Error('all uses two immutable stores; --output is ambiguous');
  return Object.freeze(options);
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  const controller = new AbortController();
  const abort = () => controller.abort();
  process.once('SIGINT', abort);
  process.once('SIGTERM', abort);
  if (!options.output || options.mode === 'ui' || options.mode === 'all' || options.config) {
    const {run} = require('../src/capture-workflow');
    const report = await run({...options, signal: controller.signal});
    process.stdout.write(JSON.stringify(report) + '\n');
    return;
  }
  // Legacy --output calculation contract remains independent of new private settings.
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
