#!/usr/bin/env node
'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const PIN = Object.freeze({
  asset: 'ci-data-pack-20261023-r01.zip.age',
  encryptedSha256: 'c0163e0627c385dfc8f92d1b6a41b8978d89c94d150c026a5a7b3810efd3a85e',
  manifestSha256: '638a283b8aa0cb822a35176d9d41c8d1751fb6f962ca0a2f7feaa20f1ef39e54',
  snapshotId: 'maxroll-20261023T034150Z',
  resources: 365,
  uniqueBlobs: 363,
  logicalBytes: 56_412_954,
});

function sha256(bytes) {
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

function run(command, args) {
  const result = spawnSync(command, args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
  if (result.error || result.status !== 0) {
    throw new Error(result.error?.message ?? result.stderr.trim() ?? `${command} exited ${result.status}`);
  }
  return result.stdout;
}

function safeEntries(entries) {
  if (!entries.length) throw new Error('fixture archive is empty');
  for (const entry of entries) {
    const normalized = path.posix.normalize(entry);
    if (path.posix.isAbsolute(entry) || entry.split('/').includes('..') ||
        normalized === '..' || normalized.startsWith('../')) {
      throw new Error('fixture archive contains an unsafe path');
    }
  }
  const roots = new Set(entries.map(entry => entry.replace(/^\.\//, '').split('/')[0]));
  if (roots.size !== 1 || !roots.has(PIN.snapshotId)) {
    throw new Error('fixture archive root does not match the pinned snapshot');
  }
}

function verifyExtracted(output) {
  const snapshot = path.join(output, PIN.snapshotId);
  const manifestBytes = fs.readFileSync(path.join(snapshot, 'manifest.json'));
  const anchor = fs.readFileSync(path.join(snapshot, 'manifest.sha256'), 'utf8').trim();
  const digest = sha256(manifestBytes);
  if (digest !== anchor || digest !== PIN.manifestSha256) {
    throw new Error('fixture manifest integrity mismatch');
  }
  const manifest = JSON.parse(manifestBytes);
  if (!Array.isArray(manifest.resources) || manifest.resources.length !== PIN.resources) {
    throw new Error('fixture resource count mismatch');
  }
  let logicalBytes = 0;
  const blobs = new Set();
  for (const resource of manifest.resources) {
    if (!/^blobs\/[a-f0-9]{64}\.bin$/.test(resource.blob) ||
        resource.sha256 !== path.basename(resource.blob, '.bin')) {
      throw new Error('fixture contains an invalid blob identity');
    }
    const body = fs.readFileSync(path.join(snapshot, resource.blob));
    if (body.length !== resource.size || sha256(body) !== resource.sha256) {
      throw new Error('fixture blob integrity mismatch');
    }
    blobs.add(resource.sha256);
    logicalBytes += body.length;
  }
  if (blobs.size !== PIN.uniqueBlobs || logicalBytes !== PIN.logicalBytes) {
    throw new Error('fixture aggregate metadata mismatch');
  }
  return { manifestSha256: digest, resources: manifest.resources.length,
    uniqueBlobs: blobs.size, logicalBytes };
}

function main(argv) {
  if (argv.length !== 4) {
    throw new Error('usage: provision-maxroll-fixture <encrypted> <age-bin> <identity> <output>');
  }
  const [encrypted, ageBin, identity, output] = argv.map(value => path.resolve(value));
  if (path.basename(encrypted) !== PIN.asset || sha256(fs.readFileSync(encrypted)) !== PIN.encryptedSha256) {
    throw new Error('encrypted fixture trust anchor mismatch');
  }
  if (fs.existsSync(output)) throw new Error('fixture output already exists');
  const temporaryZip = `${output}.zip`;
  try {
    run(ageBin, ['--decrypt', '--identity', identity, '--output', temporaryZip, encrypted]);
    fs.rmSync(identity, { force: true });
    const entries = run('unzip', ['-Z1', temporaryZip]).split('\n').filter(Boolean);
    safeEntries(entries);
    fs.mkdirSync(output, { recursive: true, mode: 0o700 });
    run('unzip', ['-q', temporaryZip, '-d', output]);
    fs.rmSync(temporaryZip, { force: true });
    const verified = verifyExtracted(output);
    process.stdout.write(`${JSON.stringify({ status: 'PASS', ...verified })}\n`);
  } catch (error) {
    fs.rmSync(output, { recursive: true, force: true });
    throw error;
  } finally {
    fs.rmSync(identity, { force: true });
    fs.rmSync(temporaryZip, { force: true });
  }
}

if (require.main === module) {
  try {
    main(process.argv.slice(2));
  } catch (error) {
    process.stderr.write(`${error.name}: ${error.message}\n`);
    process.exitCode = 1;
  }
}

module.exports = { PIN, main, safeEntries, verifyExtracted };
