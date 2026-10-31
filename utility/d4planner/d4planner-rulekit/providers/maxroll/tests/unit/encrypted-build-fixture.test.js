'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { assertSafeEntries, verifyExtracted } = require('../../src/encrypted-build-fixture');

const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

test('encrypted build fixture rejects archive path traversal and mixed roots', () => {
  assert.throws(() => assertSafeEntries(['testdata/ok', '../escape'], 'testdata'), /unsafe/);
  assert.throws(() => assertSafeEntries(['testdata/ok', 'other/no'], 'testdata'), /root/);
  assert.throws(() => assertSafeEntries(['testdata\\escape'], 'testdata'), /unsafe/);
});

test('extracted fixture verifies pinned manifest and every declared file fail-closed', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'build-fixture-unit-'));
  try {
    const body = Buffer.from('{"fixture":true}\n');
    fs.writeFileSync(path.join(root, 'input.json'), body);
    const manifest = Buffer.from(`${JSON.stringify({ files: [{ file: 'input.json',
      bytes: body.length, sha256: hash(body) }] })}\n`);
    fs.writeFileSync(path.join(root, 'manifest.json'), manifest);
    const spec = { manifestSha256: hash(manifest) };
    assert.equal(verifyExtracted(root, spec).verifiedFiles, 1);
    fs.writeFileSync(path.join(root, 'input.json'), '{"fixture":false}\n');
    assert.throws(() => verifyExtracted(root, spec), /integrity/);
    fs.writeFileSync(path.join(root, 'input.json'), body);
    assert.throws(() => verifyExtracted(root, { manifestSha256: '0'.repeat(64) }), /manifest/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
