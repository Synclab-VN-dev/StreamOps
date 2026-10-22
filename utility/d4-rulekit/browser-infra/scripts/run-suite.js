#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const suite = process.argv[2];
if (!['unit', 'e2e'].includes(suite)) {
  process.stderr.write('usage: node scripts/run-suite.js <unit|e2e>\n');
  process.exit(2);
}

const root = path.resolve(__dirname, '..');
const artifacts = path.join(root, 'artifacts');
fs.mkdirSync(artifacts, { recursive: true });
const startedAt = new Date().toISOString();
const junitPath = path.join(artifacts, `${suite}.junit.xml`);
const jsonPath = path.join(artifacts, `${suite}.json`);
const tests = suite === 'unit'
  ? path.join(root, 'tests/unit/infrastructure.test.js')
  : path.join(root, 'tests/e2e/chromium.test.js');
const result = spawnSync(process.execPath, [
  '--test', '--test-concurrency=1',
  '--test-reporter=spec', '--test-reporter-destination=stdout',
  '--test-reporter=junit', `--test-reporter-destination=${junitPath}`,
  tests,
], {
  cwd: root,
  env: process.env,
  encoding: 'utf8',
});

process.stdout.write(result.stdout || '');
process.stderr.write(result.stderr || '');

function decodeXml(value) {
  return value.replaceAll('&quot;', '"').replaceAll('&apos;', "'")
    .replaceAll('&lt;', '<').replaceAll('&gt;', '>').replaceAll('&amp;', '&');
}

const report = {
  schemaVersion: 'browser-infrastructure-test-report/1',
  suite,
  startedAt,
  finishedAt: new Date().toISOString(),
  status: result.status === 0 ? 'PASS' : 'FAIL',
  tests: [],
  counts: { total: 0, passed: 0, failed: 0, skipped: 0 },
};
if (fs.existsSync(junitPath)) {
  const xml = fs.readFileSync(junitPath, 'utf8');
  const cases = xml.matchAll(/<testcase name="([^"]*)" time="([^"]*)"[^>]*(?:\/>|>([\s\S]*?)<\/testcase>)/g);
  for (const match of cases) {
    const body = match[3] || '';
    const status = body.includes('<failure') ? 'FAIL'
      : body.includes('<skipped') ? 'SKIP' : 'PASS';
    report.tests.push({
      name: decodeXml(match[1]),
      status,
      durationMs: Number(match[2]) * 1000,
    });
  }
  report.counts.total = report.tests.length;
  report.counts.passed = report.tests.filter(row => row.status === 'PASS').length;
  report.counts.failed = report.tests.filter(row => row.status === 'FAIL').length;
  report.counts.skipped = report.tests.filter(row => row.status === 'SKIP').length;
}
fs.writeFileSync(jsonPath, `${JSON.stringify(report, null, 2)}\n`);
process.exit(result.status ?? 1);
