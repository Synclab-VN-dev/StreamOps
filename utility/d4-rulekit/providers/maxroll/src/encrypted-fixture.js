'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { FileSystemSnapshotStore } = require('@streamops/browser-infrastructure');

const FIXTURE = Object.freeze({
  snapshotId: 'maxroll-20261023T034150Z',
  manifestSha256: '638a283b8aa0cb822a35176d9d41c8d1751fb6f962ca0a2f7feaa20f1ef39e54',
  resources: 365,
  uniqueBlobs: 363,
  logicalBytes: 56_412_954,
  recipient: 'age1q9x3chgd0ycxe6y692cme82906a7qvcm08a02mwp9scdrtyupgzqhhwfrj',
  encryptedSha256: 'c0163e0627c385dfc8f92d1b6a41b8978d89c94d150c026a5a7b3810efd3a85e',
  assetName: 'ci-data-pack-20261023-r01.zip.age',
  checksumName: 'ci-data-pack-20261023-r01.zip.age.sha256',
});

const ALLOWED_ROOT_FILES = new Set([
  'manifest.json', 'manifest.sha256', 'capture-report.json', 'resource-inventory.json',
]);
const SENSITIVE_QUERY = /^(?:access_?token|auth(?:orization)?|api_?key|session|secret)$/i;
const SENSITIVE_HEADERS = new Set(['authorization', 'cookie', 'proxy-authorization', 'set-cookie']);

function digestFile(filename) {
  return crypto.createHash('sha256').update(fs.readFileSync(filename)).digest('hex');
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd, encoding: 'utf8', stdio: options.inherit ? 'inherit' : 'pipe',
    timeout: options.timeoutMs ?? 120_000,
  });
  if (result.error || result.status !== 0) {
    throw new Error(result.error?.message ?? result.stderr?.trim() ??
      `${path.basename(command)} exited ${result.status}`);
  }
  return result.stdout ?? '';
}

function assertSafeArchiveEntries(entries) {
  if (!entries.length) throw new Error('encrypted fixture ZIP is empty');
  for (const entry of entries) {
    const normalized = path.posix.normalize(entry);
    if (path.posix.isAbsolute(entry) || entry.split('/').includes('..') ||
        normalized === '..' || normalized.startsWith('../')) {
      throw new Error(`unsafe ZIP path: ${entry}`);
    }
  }
  const roots = new Set(entries.map(entry => entry.replace(/^\.\//, '').split('/')[0]));
  if (roots.size !== 1 || !roots.has(FIXTURE.snapshotId)) {
    throw new Error('ZIP does not contain exactly the pinned snapshot root');
  }
}

function inventoryFiles(root) {
  const files = [];
  const walk = (directory, relative = '') => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const next = path.join(directory, entry.name);
      const name = path.posix.join(relative, entry.name);
      if (entry.isSymbolicLink()) throw new Error(`snapshot contains a symlink: ${name}`);
      if (entry.isDirectory()) walk(next, name);
      else if (entry.isFile()) files.push(name);
      else throw new Error(`snapshot contains unsupported filesystem entry: ${name}`);
    }
  };
  walk(root);
  return files.sort();
}

function scanPackage(snapshotPath, manifest) {
  const files = inventoryFiles(snapshotPath);
  const unexpected = files.filter(filename =>
    !ALLOWED_ROOT_FILES.has(filename) && !/^blobs\/[a-f0-9]{64}\.bin$/.test(filename));
  if (unexpected.length) throw new Error(`snapshot contains unexpected files: ${unexpected.join(', ')}`);

  for (const resource of manifest.resources) {
    const url = new URL(resource.url);
    if ([...url.searchParams.keys()].some(key => SENSITIVE_QUERY.test(key))) {
      throw new Error('snapshot resource URL contains a sensitive query parameter');
    }
    if (Object.keys(resource.headers ?? {}).some(header => SENSITIVE_HEADERS.has(header.toLowerCase()))) {
      throw new Error('snapshot resource contains a sensitive response header');
    }
  }
  for (const filename of files) {
    const bytes = fs.readFileSync(path.join(snapshotPath, filename));
    if (bytes.includes(Buffer.from(`AGE-${'SECRET'}-KEY-`)) ||
        bytes.includes(Buffer.from('-----BEGIN PRIVATE KEY-----'))) {
      throw new Error('snapshot contains a private-key marker');
    }
  }
  return Object.freeze({ files: files.length, sensitiveFindings: 0 });
}

async function verifySnapshot(rootDir) {
  const store = new FileSystemSnapshotStore({ rootDir });
  const verification = await store.verify(FIXTURE.snapshotId);
  const manifest = await store.load(FIXTURE.snapshotId);
  const logicalBytes = manifest.resources.reduce((total, resource) => total + resource.size, 0);
  const uniqueBlobs = new Set(manifest.resources.map(resource => resource.sha256)).size;
  if (!verification.valid || verification.manifestSha256 !== FIXTURE.manifestSha256 ||
      manifest.resources.length !== FIXTURE.resources || uniqueBlobs !== FIXTURE.uniqueBlobs ||
      logicalBytes !== FIXTURE.logicalBytes) {
    throw new Error('snapshot integrity or expected metadata mismatch');
  }
  const security = scanPackage(path.join(rootDir, FIXTURE.snapshotId), manifest);
  return Object.freeze({
    manifestSha256: verification.manifestSha256,
    resources: manifest.resources.length, uniqueBlobs, logicalBytes, security,
  });
}

function compareTrees(leftRoot, rightRoot) {
  const left = inventoryFiles(leftRoot);
  const right = inventoryFiles(rightRoot);
  if (JSON.stringify(left) !== JSON.stringify(right)) throw new Error('round-trip file inventory mismatch');
  for (const filename of left) {
    if (digestFile(path.join(leftRoot, filename)) !== digestFile(path.join(rightRoot, filename))) {
      throw new Error(`round-trip content mismatch: ${filename}`);
    }
  }
  return left.length;
}

async function decryptAndVerify({
  encrypted, checksum, ageBin, identity,
  expectedEncryptedSha256 = FIXTURE.encryptedSha256,
}) {
  const expectedLine = fs.readFileSync(checksum, 'utf8').trim().split(/\s+/);
  if (expectedLine.length < 2 || expectedLine[1].replace(/^\*/, '') !== path.basename(encrypted) ||
      expectedLine[0] !== expectedEncryptedSha256 ||
      expectedLine[0] !== digestFile(encrypted)) throw new Error('encrypted asset SHA-256 mismatch');
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'streamops-encrypted-fixture-'));
  const plaintext = path.join(temporary, 'fixture.zip');
  const extracted = path.join(temporary, 'extracted');
  try {
    run(ageBin, ['--decrypt', '--identity', identity, '--output', plaintext, encrypted]);
    const entries = run('unzip', ['-Z1', plaintext]).split('\n').filter(Boolean);
    assertSafeArchiveEntries(entries);
    fs.mkdirSync(extracted);
    run('unzip', ['-q', plaintext, '-d', extracted]);
    const verified = await verifySnapshot(extracted);
    return Object.freeze({ ...verified, archiveEntries: entries.length });
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
}

async function packageEncrypted({ snapshot, outputDir, ageBin, identity }) {
  const sourceRoot = path.dirname(path.resolve(snapshot));
  if (path.basename(path.resolve(snapshot)) !== FIXTURE.snapshotId) {
    throw new Error('source snapshot ID does not match the pinned fixture');
  }
  const verified = await verifySnapshot(sourceRoot);
  fs.mkdirSync(outputDir, { recursive: true, mode: 0o700 });
  const encrypted = path.join(outputDir, FIXTURE.assetName);
  const checksum = path.join(outputDir, FIXTURE.checksumName);
  if (fs.existsSync(encrypted) || fs.existsSync(checksum)) {
    throw new Error('immutable encrypted fixture output already exists');
  }
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'streamops-fixture-package-'));
  const plaintext = path.join(temporary, 'fixture.zip');
  try {
    run('zip', ['-q', '-r', plaintext, FIXTURE.snapshotId], { cwd: sourceRoot });
    run(ageBin, ['--encrypt', '--recipient', FIXTURE.recipient, '--output', encrypted, plaintext]);
    fs.chmodSync(encrypted, 0o600);
    const encryptedSha256 = digestFile(encrypted);
    fs.writeFileSync(checksum, `${encryptedSha256}  ${FIXTURE.assetName}\n`, { mode: 0o600 });
    const roundTrip = await decryptAndVerify({
      encrypted, checksum, ageBin, identity, expectedEncryptedSha256: encryptedSha256,
    });

    const checkTemporary = fs.mkdtempSync(path.join(os.tmpdir(), 'streamops-fixture-compare-'));
    try {
      const decrypted = path.join(checkTemporary, 'fixture.zip');
      const extracted = path.join(checkTemporary, 'extracted');
      run(ageBin, ['--decrypt', '--identity', identity, '--output', decrypted, encrypted]);
      assertSafeArchiveEntries(run('unzip', ['-Z1', decrypted]).split('\n').filter(Boolean));
      fs.mkdirSync(extracted);
      run('unzip', ['-q', decrypted, '-d', extracted]);
      compareTrees(path.join(sourceRoot, FIXTURE.snapshotId),
        path.join(extracted, FIXTURE.snapshotId));
    } finally {
      fs.rmSync(checkTemporary, { recursive: true, force: true });
    }
    return Object.freeze({
      status: 'PASS', encrypted, checksum, encryptedSha256,
      encryptedBytes: fs.statSync(encrypted).size, verified, roundTrip,
    });
  } catch (error) {
    fs.rmSync(encrypted, { force: true });
    fs.rmSync(checksum, { force: true });
    throw error;
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
}

module.exports = {
  FIXTURE, assertSafeArchiveEntries, compareTrees, decryptAndVerify,
  digestFile, packageEncrypted, verifySnapshot,
};
