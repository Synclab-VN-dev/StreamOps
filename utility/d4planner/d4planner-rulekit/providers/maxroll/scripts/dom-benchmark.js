#!/usr/bin/env node
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
const { performance } = require('node:perf_hooks');
const { DomCalculationPath } = require('../src/dom-calculation');

function distribution(values) {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!sorted.length) return null;
  const q = p => sorted[Math.max(0, Math.ceil(p * sorted.length) - 1)];
  return { count: sorted.length, min: sorted[0], p50: q(0.5), p95: q(0.95), max: sorted.at(-1) };
}
class LinuxProcessSampler {
  constructor() {
    this.ticks = Number(execFileSync('getconf', ['CLK_TCK'], { encoding: 'utf8' }));
    this.pageSize = Number(execFileSync('getconf', ['PAGESIZE'], { encoding: 'utf8' }));
    this.previous = new Map(); this.cpuMs = 0; this.peakRssBytes = 0; this.samples = 0;
    this.sample(true); this.timer = setInterval(() => this.sample(), 100);
  }
  sample(baseline = false) {
    const processes = new Map();
    for (const name of fs.readdirSync('/proc')) {
      if (!/^\d+$/.test(name)) continue;
      try {
        const value = fs.readFileSync(`/proc/${name}/stat`, 'utf8');
        const fields = value.slice(value.lastIndexOf(')') + 2).split(' ');
        processes.set(Number(name), { parent: Number(fields[1]), cpu: Number(fields[11]) + Number(fields[12]), rss: Number(fields[21]) * this.pageSize });
      } catch { /* processes can exit between listing and reading */ }
    }
    const selected = new Set([process.pid]);
    for (let changed = true; changed;) {
      changed = false;
      for (const [pid, info] of processes) if (!selected.has(pid) && selected.has(info.parent)) { selected.add(pid); changed = true; }
    }
    let rss = 0;
    for (const pid of selected) {
      const info = processes.get(pid); if (!info) continue;
      const previous = this.previous.get(pid);
      if (!baseline) this.cpuMs += Math.max(0, info.cpu - (previous ?? 0)) / this.ticks * 1000;
      this.previous.set(pid, info.cpu); rss += info.rss;
    }
    this.peakRssBytes = Math.max(this.peakRssBytes, rss); this.samples += 1;
  }
  stop(wallMs) { clearInterval(this.timer); this.sample(); return { cpuMs: this.cpuMs,
    cpuPercentOneCore: this.cpuMs / wallMs * 100, peakRssBytes: this.peakRssBytes, samples: this.samples }; }
}
function compare(result, expected) {
  const expectedMap = new Map(expected.flatMap(s => s.rows.map(r => [`${s.section}\0${r.name}`, r.value])));
  const actual = [...result.metrics, ...result.additionalMetrics].filter(r => r.status === 'DISPLAY_OBSERVED');
  const differences = [];
  for (const r of actual) if (expectedMap.get(`${r.section}\0${r.name}`) !== r.displayValue) differences.push({ id: r.id,
    expected: expectedMap.get(`${r.section}\0${r.name}`) ?? null, actual: r.displayValue });
  if (actual.length !== expectedMap.size) differences.push({ expectedRows: expectedMap.size, actualRows: actual.length });
  return { status: differences.length ? 'FAIL' : 'PASS', compared: actual.length, differences };
}
async function run(config) {
  if (process.platform !== 'linux') throw Error('CPU/RAM sampler requires Linux /proc; use a platform-specific sampler on Windows');
  fs.mkdirSync(config.outputDirectory, { recursive: true, mode: 0o700 });
  const oracleBytes = fs.readFileSync(config.oracleFile);
  const oracle = JSON.parse(oracleBytes);
  const builds = Object.fromEntries(Object.entries(config.buildFiles).map(([key, file]) => [key, JSON.parse(fs.readFileSync(file))]));
  for (const key of ['A', 'BItem', 'BEffect']) if (!builds[key] || !oracle[key]) throw Error(`Missing independently prepared build/oracle ${key}`);
  const report = { schemaVersion: 'dom-calculation-benchmark/v1', startedAt: new Date().toISOString(),
    head: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: path.resolve(__dirname, '..'), encoding: 'utf8' }).trim(),
    dirty: execFileSync('git', ['status', '--porcelain'], { cwd: path.resolve(__dirname, '..'), encoding: 'utf8' }).trim(),
    oracleSha256: crypto.createHash('sha256').update(oracleBytes).digest('hex'),
    buildSha256: Object.fromEntries(Object.entries(config.buildFiles).map(([key, file]) => [key, crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')])),
    measurement: { clock: 'performance.now', quantiles: 'nearest-rank',
      warm: 'browser warm; new isolated context + full native load/readback every evaluate',
      calculation: 'DOM completion/settle barrier, not exclusive engine execution time (calculation overlaps build apply)',
      cpu: '100ms sampled /proc CPU ticks for Node + observed descendant processes; 100%=one core; short-lived processes between samples may be missed',
      ram: 'maximum sampled sum RSS for Node + descendants; shared pages counted per process; not PSS',
      accuracy: 'exact DOM display strings versus frozen separate original-engine DOM execution; raw precision intentionally unavailable' }, rows: [] };
  const save = () => fs.writeFileSync(path.join(config.outputDirectory, 'benchmark.json'), JSON.stringify(report, null, 2) + '\n');
  let warm;
  async function evaluate(group, index, label, cold = false) {
    const runtime = cold ? new DomCalculationPath(config) : warm;
    const sampler = new LinuxProcessSampler(), start = performance.now();
    let row = { group, index, label };
    try {
      const result = await runtime.evaluate(builds[label]);
      row = { ...row, status: 'PASS', timingsMs: result.timingsMs, coverage: result.coverage,
        evaluationId: result.evaluationId, inputFingerprint: result.inputFingerprint, accuracy: compare(result, oracle[label]) };
      if (row.accuracy.status !== 'PASS') row.status = 'FAIL';
      if (report.rows.some(r => r.evaluationId === row.evaluationId)) throw Error('Reused evaluation identity');
    } catch (error) { row = { ...row, status: 'FAIL', code: error.code, message: error.message }; }
    finally {
      const wallMs = performance.now() - start;
      row.resources = sampler.stop(wallMs); row.measuredWallMs = wallMs;
      if (cold) await runtime.close();
      report.rows.push(row); save(); console.log(group, index, label, row.status, Math.round(wallMs));
    }
  }
  try {
    for (let i = 0; i < 5; i++) await evaluate('cold', i, 'A', true);
    warm = new DomCalculationPath(config); await warm.start();
    for (let i = 0; i < 30; i++) await evaluate('warm', i, 'A');
    for (let i = 0; i < 30; i++) await evaluate('item-effect-change', i, i % 2 ? 'BEffect' : 'BItem');
    for (let i = 0; i < 10; i++) for (const [step, label] of ['A', i % 2 ? 'BEffect' : 'BItem', 'A'].entries()) {
      await evaluate('A-B-A', i * 3 + step, label);
    }
  } finally { await warm?.close(); }
  report.groups = {};
  for (const group of ['cold', 'warm', 'item-effect-change', 'A-B-A']) {
    const rows = report.rows.filter(r => r.group === group);
    report.groups[group] = { runs: rows.length, passed: rows.filter(r => r.status === 'PASS').length,
      timeouts: rows.filter(r => r.code === 'DOM_TIMEOUT').length,
      timingsMs: Object.fromEntries(['endToEnd', 'buildApply', 'calculation', 'domExtraction'].map(key => [key, distribution(rows.map(r => r.timingsMs?.[key]))])),
      cpuMs: distribution(rows.map(r => r.resources.cpuMs)), cpuPercentOneCore: distribution(rows.map(r => r.resources.cpuPercentOneCore)),
      peakRssBytes: distribution(rows.map(r => r.resources.peakRssBytes)) };
  }
  report.status = report.rows.length === 95 && report.rows.every(r => r.status === 'PASS') ? 'PASS' : 'FAIL';
  report.finishedAt = new Date().toISOString(); save();
  if (report.status !== 'PASS') process.exitCode = 1;
}
if (require.main === module) run(JSON.parse(fs.readFileSync(process.argv[2], 'utf8'))).catch(error => { console.error(error); process.exitCode = 1; });
module.exports = { distribution, compare };
