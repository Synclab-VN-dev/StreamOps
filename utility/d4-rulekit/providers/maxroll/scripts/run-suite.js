#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const suite = process.argv[2];
if (!['unit', 'contract', 'e2e', 'real'].includes(suite)) {
  process.stderr.write('usage: node scripts/run-suite.js <unit|contract|e2e|real>\n');
  process.exit(2);
}
const root = path.resolve(__dirname, '..');
const artifacts = path.join(root, 'artifacts');
fs.mkdirSync(artifacts, { recursive: true });
const startedAt = new Date().toISOString();
const startedNs = process.hrtime.bigint();
const junitPath = path.join(artifacts, `${suite}.junit.xml`);
const jsonPath = path.join(artifacts, `${suite}.json`);
const tests = fs.readdirSync(path.join(root, `tests/${suite}`))
  .filter(name => name.endsWith('.test.js')).sort()
  .map(name => path.join(root, `tests/${suite}`, name));
const result = spawnSync(process.execPath, [
  '--test', '--test-concurrency=1',
  '--test-reporter=spec', '--test-reporter-destination=stdout',
  '--test-reporter=junit', `--test-reporter-destination=${junitPath}`,
  ...tests,
], { cwd: root, env: process.env, encoding: 'utf8', timeout: 180_000 });
process.stdout.write(result.stdout || '');
process.stderr.write(result.stderr || '');
fs.writeFileSync(jsonPath, `${JSON.stringify({
  schemaVersion: 'maxroll-provider-test-report/1', suite, startedAt,
  finishedAt: new Date().toISOString(),
  durationMs: Number(process.hrtime.bigint() - startedNs) / 1e6,
  status: result.status === 0 ? 'PASS' : 'FAIL', signal: result.signal,
}, null, 2)}\n`);
process.exit(result.status ?? 1);
