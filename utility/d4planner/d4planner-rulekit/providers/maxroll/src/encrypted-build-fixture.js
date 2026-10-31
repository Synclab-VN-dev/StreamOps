'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const BUILD_FIXTURES = Object.freeze({
  r01: Object.freeze({
    tag: 'test-fixture/enc-e2e-20261023-r01', asset: 'testdata-r01.zip.age',
    checksum: 'testdata-r01.zip.age.sha256', root: 'testdata-r01',
    encryptedSha256: '94e9bc3c494cdc66f02fd272faf7fcbe59ca3cd68d308acef5c550a05394e107',
    manifestSha256: '7cef606f80ac875fb7c676f9fd3bad4b5499e299e02c3143b2295b87c259d803',
  }),
  r02: Object.freeze({
    tag: 'test-fixture/enc-e2e-20261024-r02', asset: 'testdata-r02.zip.age',
    checksum: 'testdata-r02.zip.age.sha256', root: 'testdata-r02',
    encryptedSha256: '34eab25b83e335ed06fd2cf33b5ce23a6fedf1a68ba3f8a99d3c67e8d9c313de',
    manifestSha256: '309d5fe55b7aae48bfa5ac6e04b2c94eabc08e624bdf7410f86322c37610952b',
  }),
});

function digest(filename) {
  return crypto.createHash('sha256').update(fs.readFileSync(filename)).digest('hex');
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, { encoding: 'utf8', cwd: options.cwd,
    timeout: options.timeoutMs ?? 120_000, stdio: 'pipe' });
  if (result.error || result.status !== 0) throw new Error(result.error?.message
    ?? result.stderr?.trim() ?? `${path.basename(command)} exited ${result.status}`);
  return result.stdout ?? '';
}

function assertSafeEntries(entries, expectedRoot) {
  if (!entries.length) throw new Error('fixture archive is empty');
  for (const entry of entries) {
    if (entry.includes('\\') || path.posix.isAbsolute(entry)
        || entry.split('/').includes('..')) throw new Error(`unsafe ZIP path: ${entry}`);
  }
  const roots = new Set(entries.map(entry => entry.replace(/^\.\//, '').split('/')[0]));
  if (roots.size !== 1 || !roots.has(expectedRoot)) {
    throw new Error('fixture archive has an unexpected root');
  }
}

function declaredFiles(manifest) {
  if (Array.isArray(manifest.files)) return manifest.files;
  if (Array.isArray(manifest.fixtures)) return manifest.fixtures.flatMap(fixture =>
    [fixture.input, fixture.expectedStats].filter(Boolean)
      .map(file => ({ file: file.file, sha256: file.sha256 })));
  throw new Error('fixture manifest has no verifiable file inventory');
}

function verifyExtracted(root, spec) {
  const manifestPath = path.join(root, 'manifest.json');
  if (digest(manifestPath) !== spec.manifestSha256) {
    throw new Error('fixture package manifest SHA-256 mismatch');
  }
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  const files = declaredFiles(manifest);
  if (!files.length) throw new Error('fixture package inventory is empty');
  for (const entry of files) {
    if (typeof entry.file !== 'string' || !entry.file || entry.file.includes('\\')
        || path.posix.isAbsolute(entry.file) || entry.file.split('/').includes('..')) {
      throw new Error('fixture manifest contains an unsafe file path');
    }
    const filename = path.join(root, entry.file);
    const stat = fs.statSync(filename);
    if (!stat.isFile() || digest(filename) !== entry.sha256
        || entry.bytes != null && stat.size !== entry.bytes) {
      throw new Error(`fixture file integrity mismatch: ${entry.file}`);
    }
  }
  return Object.freeze({ root, manifestSha256: spec.manifestSha256,
    schemaVersion: manifest.schemaVersion, verifiedFiles: files.length });
}

async function withEncryptedBuildFixture({ encrypted, checksum, identity, ageBin, spec }, operation) {
  if (!spec || typeof operation !== 'function') throw new Error('fixture spec and operation are required');
  const checksumWords = fs.readFileSync(checksum, 'utf8').trim().split(/\s+/);
  if (checksumWords[0] !== spec.encryptedSha256
      || checksumWords[1]?.replace(/^\*/, '') !== spec.asset
      || digest(encrypted) !== spec.encryptedSha256) {
    throw new Error('encrypted build fixture SHA-256 mismatch');
  }
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'streamops-build-fixture-'));
  try {
    const plaintext = path.join(temporary, 'fixture.zip');
    const extracted = path.join(temporary, 'extracted');
    run(ageBin, ['--decrypt', '--identity', identity, '--output', plaintext, encrypted]);
    const entries = run('unzip', ['-Z1', plaintext]).split('\n').filter(Boolean);
    assertSafeEntries(entries, spec.root);
    fs.mkdirSync(extracted, { mode: 0o700 });
    run('unzip', ['-q', plaintext, '-d', extracted]);
    fs.rmSync(plaintext, { force: true });
    const verified = verifyExtracted(path.join(extracted, spec.root), spec);
    return await operation(verified);
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
}

module.exports = { BUILD_FIXTURES, assertSafeEntries, verifyExtracted,
  withEncryptedBuildFixture };
