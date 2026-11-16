#!/usr/bin/env node
'use strict';

const { listCatalogFamilies, exportCatalogFromSnapshot } = require('../src/catalog-export');

function parseArguments(argv) {
  const options = {};
  const named = new Map([
    ['--snapshot-root', 'snapshotRoot'], ['--snapshot-id', 'snapshotId'],
    ['--manifest-sha256', 'expectedManifestSha256'], ['--output', 'outputPath'],
    ['--families', 'families'],
  ]);
  for (let index = 0; index < argv.length; index++) {
    const arg = argv[index];
    if (arg === '--list-families') {
      if (options.listFamilies) throw Error('duplicate --list-families');
      options.listFamilies = true;
      continue;
    }
    const key = named.get(arg);
    if (!key || argv[index + 1] === undefined || argv[index + 1].startsWith('--')
        || options[key] !== undefined) throw Error(`unsupported or incomplete argument: ${arg}`);
    options[key] = key === 'families' ? argv[++index].split(',') : argv[++index];
  }
  if (options.listFamilies && (options.outputPath || options.families)) {
    throw Error('--list-families cannot be combined with --output or --families');
  }
  return options;
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  const result = options.listFamilies
    ? await listCatalogFamilies(options) : await exportCatalogFromSnapshot(options);
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

if (require.main === module) main().catch(error => {
  process.stderr.write(`${error.code ?? error.name}: ${error.message}\n`);
  process.exitCode = 1;
});
module.exports = { parseArguments };
