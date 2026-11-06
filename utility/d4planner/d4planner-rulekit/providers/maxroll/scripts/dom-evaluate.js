#!/usr/bin/env node
'use strict';
const fs = require('node:fs/promises');
const { DomCalculationPath } = require('../src/dom-calculation');
async function run() {
  const [configFile, buildFile, outputFile] = process.argv.slice(2);
  if (!configFile || !buildFile || !outputFile) throw Error('Usage: node scripts/dom-evaluate.js config.json native-build.json result.json');
  const config = JSON.parse(await fs.readFile(configFile, 'utf8'));
  const build = JSON.parse(await fs.readFile(buildFile, 'utf8'));
  const runtime = new DomCalculationPath(config);
  try {
    const result = await runtime.evaluate(build);
    await fs.writeFile(outputFile, JSON.stringify(result, null, 2) + '\n', { mode: 0o600 });
    console.log(JSON.stringify({ status: result.status, coverage: result.coverage, timingsMs: result.timingsMs }));
  } finally { await runtime.close(); }
}
run().catch(error => { console.error(JSON.stringify({ code: error.code ?? 'DOM_ERROR', message: error.message })); process.exitCode = 1; });
