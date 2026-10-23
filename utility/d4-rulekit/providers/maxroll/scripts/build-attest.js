#!/usr/bin/env node
'use strict';

const { attestMaxrollBuildFixture } = require('../src');

function args(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 2) {
    if (!argv[index]?.startsWith('--') || argv[index + 1] === undefined) {
      throw new Error(`invalid argument: ${argv[index] ?? '<missing>'}`);
    }
    parsed[argv[index].slice(2)] = argv[index + 1];
  }
  return parsed;
}

async function main() {
  const options = args(process.argv.slice(2));
  const result = await attestMaxrollBuildFixture({
    inputPath: options.input,
    outputPath: options.output,
    snapshotRoot: options['snapshot-root'],
    snapshotId: options['snapshot-id'],
    expectedManifestSha256: options['manifest-sha256'],
    chromiumExecutablePath: options.chromium,
    timeoutMs: options['timeout-ms'] ? Number(options['timeout-ms']) : undefined,
  });
  process.stdout.write(`${JSON.stringify({ status: 'PASS', ...result })}\n`);
}

main().catch(error => {
  process.stderr.write(`${JSON.stringify({ status: 'FAIL', code: error.code ?? 'UNEXPECTED',
    message: error.message })}\n`);
  process.exitCode = 1;
});
