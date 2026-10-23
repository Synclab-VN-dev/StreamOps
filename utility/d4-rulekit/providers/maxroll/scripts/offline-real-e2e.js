#!/usr/bin/env node
'use strict';

const { runOfflineRealE2e } = require('../src/offline-real-e2e');

function parse(argv, env = process.env) {
  const options = {
    identity: env.MAXROLL_FIXTURE_AGE_IDENTITY_FILE,
    ageBin: env.AGE_BIN,
    chromium: env.BROWSER_INFRA_CHROMIUM_PATH,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!['--identity', '--age-bin', '--chromium', '--gh-bin'].includes(key) || !value) {
      throw new Error(`unsupported or incomplete argument: ${key}`);
    }
    options[key.slice(2).replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase())] = value;
    index += 1;
  }
  return Object.freeze(options);
}

async function main() {
  const report = await runOfflineRealE2e(parse(process.argv.slice(2)));
  process.stdout.write(`${JSON.stringify(report)}\n`);
}

if (require.main === module) {
  main().catch(error => {
    process.stderr.write(`${error.name}: ${error.message}\n`);
    process.exitCode = 1;
  });
}

module.exports = { parse };
