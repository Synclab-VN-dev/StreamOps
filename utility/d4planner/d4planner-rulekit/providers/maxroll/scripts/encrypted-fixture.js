#!/usr/bin/env node
'use strict';

const {
  decryptAndVerify, packageEncrypted,
} = require('../src/encrypted-fixture');

function parse(argv) {
  const [command, ...rest] = argv;
  const options = { command };
  for (let index = 0; index < rest.length; index += 1) {
    const key = rest[index];
    const value = rest[index + 1];
    if (!['--snapshot', '--output-dir', '--encrypted', '--checksum', '--age-bin', '--identity', '--descriptor']
      .includes(key) || !value) throw new Error(`unsupported or incomplete argument: ${key}`);
    options[key.slice(2).replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase())] = value;
    index += 1;
  }
  if (command === 'package' && options.snapshot && options.outputDir &&
      options.ageBin && options.identity) return Object.freeze(options);
  if (command === 'verify' && options.encrypted && options.checksum &&
      options.ageBin && options.identity) return Object.freeze(options);
  throw new Error('usage: encrypted-fixture <package|verify> with required paths');
}

async function main() {
  const options = parse(process.argv.slice(2));
  const configured = options.descriptor
    ? { ...options, fixture: JSON.parse(require('node:fs').readFileSync(options.descriptor, 'utf8')) }
    : options;
  const result = options.command === 'package'
    ? await packageEncrypted(configured)
    : await decryptAndVerify(configured);
  process.stdout.write(`${JSON.stringify({
    status: 'PASS',
    encryptedAsset: result.encrypted ? require('node:path').basename(result.encrypted) : undefined,
    encryptedSha256: result.encryptedSha256,
    encryptedBytes: result.encryptedBytes,
    manifestSha256: result.verified?.manifestSha256 ?? result.manifestSha256,
    resources: result.verified?.resources ?? result.resources,
    uniqueBlobs: result.verified?.uniqueBlobs ?? result.uniqueBlobs,
    logicalBytes: result.verified?.logicalBytes ?? result.logicalBytes,
    temporaryDataCleanup: 'PASS',
  })}\n`);
}

if (require.main === module) {
  main().catch(error => {
    process.stderr.write(`${error.name}: ${error.message}\n`);
    process.exitCode = 1;
  });
}

module.exports = { parse };
