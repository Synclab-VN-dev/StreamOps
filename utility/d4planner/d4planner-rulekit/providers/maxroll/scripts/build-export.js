#!/usr/bin/env node
'use strict';

const {
  exportMaxrollBuildFromSnapshot,
  listMaxrollBuildProfilesFromSnapshot,
} = require('../src/build-export');

function parseArguments(argv) {
  const options = {};
  const valued = new Map([
    ['--url', 'url'],
    ['--snapshot-root', 'snapshotRoot'],
    ['--snapshot-id', 'snapshotId'],
    ['--manifest-sha256', 'expectedManifestSha256'],
    ['--profile', 'profile'],
    ['--output', 'outputPath'],
  ]);
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === '--list-profiles') {
      options.listProfiles = true;
      continue;
    }
    const name = valued.get(argument);
    if (!name || argv[index + 1] === undefined) {
      throw new Error(`unsupported or incomplete argument: ${argument}`);
    }
    options[name] = name === 'profile' ? Number(argv[index + 1]) : argv[index + 1];
    index += 1;
  }
  return Object.freeze(options);
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  if (options.listProfiles) {
    const result = await listMaxrollBuildProfilesFromSnapshot(options);
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    return;
  }
  const result = await exportMaxrollBuildFromSnapshot(options);
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

if (require.main === module) {
  main().catch(error => {
    process.stderr.write(`${error.code ?? error.name}: ${error.message}\n`);
    process.exitCode = 1;
  });
}

module.exports = { parseArguments };
