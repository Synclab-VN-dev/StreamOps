#!/usr/bin/env node
'use strict';

const fs = require('node:fs/promises');
const path = require('node:path');
const { MaxrollClassFixtureCapturer } = require('../src/class-fixture-capture');
const { discoverBrowser } = require('../src/live-capture-orchestrator');

function parseArguments(argv) {
  const values = new Map([
    ['--output', 'outputRoot'],
    ['--snapshot-root', 'snapshotRoot'],
    ['--snapshot-id', 'snapshotId'],
    ['--manifest-sha256', 'expectedManifestSha256'],
    ['--chromium', 'chromiumExecutablePath'],
    ['--matrix', 'matrixPath'],
    ['--class', 'className'],
    ['--timeout-ms', 'timeoutMs'],
    ['--reuse-root', 'reuseRoot'],
  ]);
  const options = {};
  for (let index = 0; index < argv.length; index += 1) {
    const key = values.get(argv[index]);
    if (!key || argv[index + 1] === undefined) {
      throw new Error(`unsupported or incomplete argument: ${argv[index]}`);
    }
    options[key] = key === 'timeoutMs' ? Number(argv[index + 1]) : argv[index + 1];
    index += 1;
  }
  return options;
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  const matrixPath = path.resolve(options.matrixPath
    ?? path.join(__dirname, '..', 'fixture-sources.json'));
  const matrix = JSON.parse(await fs.readFile(matrixPath, 'utf8'));
  const selectedMatrix = options.className ? {
    ...matrix,
    fixtures: matrix.fixtures.filter(entry => entry.class === options.className),
  } : matrix;
  if (selectedMatrix.fixtures.length === 0) {
    throw new Error(`fixture class is not present in the matrix: ${options.className}`);
  }
  const chromiumExecutablePath = options.chromiumExecutablePath ?? discoverBrowser(process.env);
  const result = await new MaxrollClassFixtureCapturer().capture({
    ...options,
    matrix: selectedMatrix,
    chromiumExecutablePath,
  });
  process.stdout.write(`${JSON.stringify({
    status: result.status,
    outputRoot: result.outputRoot,
    fixtureCount: result.fixtures.length,
    fixtures: result.fixtures,
  })}\n`);
}

if (require.main === module) {
  main().catch(error => {
    process.stderr.write(`${JSON.stringify({ status: 'FAIL', code: error.code ?? error.name,
      message: error.message, details: error.details ?? null })}\n`);
    process.exitCode = 1;
  });
}

module.exports = { parseArguments };
