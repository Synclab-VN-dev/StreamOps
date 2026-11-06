'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { BrowserInfrastructure } = require('@streamops/browser-infrastructure');
const { DomCalculationPath } = require('../../src/dom-calculation');
const { compare } = require('../../scripts/dom-benchmark');
const config = process.env.MAXROLL_DOM_REAL_CONFIG ? JSON.parse(fs.readFileSync(process.env.MAXROLL_DOM_REAL_CONFIG, 'utf8')) : null;

test('real offline Native JSON: item/effect changes and A-B-A without CDP observation', { skip: !config, timeout: 90000 }, async () => {
  const browser = new BrowserInfrastructure({ executablePath: config.executablePath, headless: true, maxContexts: 1, maxQueue: 1,
    contextOptions: { serviceWorkers: 'block' } });
  const contexts = new Set();
  const acquire = browser.acquire.bind(browser);
  browser.acquire = async (...args) => {
    const lease = await acquire(...args);
    assert(!contexts.has(lease.context), 'Every evaluate must have a new context'); contexts.add(lease.context);
    lease.createCDPSession = () => { throw Error('DOM path must not create an observation CDP session'); };
    return lease;
  };
  const runtime = new DomCalculationPath({ ...config, browser });
  const oracle = JSON.parse(fs.readFileSync(config.oracleFile));
  const results = [];
  try {
    for (const label of ['A', 'BItem', 'A', 'BEffect', 'A']) {
      const result = await runtime.evaluate(JSON.parse(fs.readFileSync(config.buildFiles[label])));
      assert.equal(compare(result, oracle[label]).status, 'PASS');
      assert.equal(result.provenance.offline, true);
      assert.equal(result.completion.rawCalculationAttestation, false);
      assert(result.metrics.every(m => m.rawValue === null));
      results.push(result);
    }
    assert.equal(new Set(results.map(r => r.evaluationId)).size, 5);
    assert.equal(results[0].inputFingerprint, results[2].inputFingerprint);
    assert.equal(results[0].inputFingerprint, results[4].inputFingerprint);
    assert.notEqual(results[0].inputFingerprint, results[1].inputFingerprint);
    assert.notEqual(results[0].inputFingerprint, results[3].inputFingerprint);
    const values = r => r.metrics.map(m => m.displayValue);
    assert.deepEqual(values(results[0]), values(results[2]));
    assert.deepEqual(values(results[0]), values(results[4]));
    assert.notDeepEqual(values(results[0]), values(results[1]));
    assert.notDeepEqual(values(results[0]), values(results[3]));
  } finally { await runtime.close(); }
});
test('same Native JSON works on existing UI snapshot without recapture', { skip: !config?.ui, timeout: 30000 }, async () => {
  const runtime = new DomCalculationPath({ ...config, ...config.ui });
  try {
    const result = await runtime.evaluate(JSON.parse(fs.readFileSync(config.buildFiles.A)));
    assert.equal(compare(result, JSON.parse(fs.readFileSync(config.oracleFile)).A).status, 'PASS');
  } finally { await runtime.close(); }
});
test('timeout releases context and never returns an earlier evaluation', { skip: !config, timeout: 30000 }, async () => {
  const browser = new BrowserInfrastructure({ executablePath: config.executablePath, headless: true, maxContexts: 1, maxQueue: 1,
    contextOptions: { serviceWorkers: 'block' } });
  const acquire = browser.acquire.bind(browser); let page;
  browser.acquire = async (...args) => {
    const lease = await acquire(...args); page = lease.page;
    // Force the real loader to remain pending. All network remains offline.
    const route = page.route.bind(page);
    page.route = async (url, handler) => route(url, url.includes('/profiles/load/') ? async () => {} : handler);
    return lease;
  };
  const runtime = new DomCalculationPath({ ...config, browser, timeoutMs: 1000 });
  try { await assert.rejects(runtime.evaluate(JSON.parse(fs.readFileSync(config.buildFiles.A))), { code: 'DOM_TIMEOUT' }); }
  finally { await runtime.close(); }
  assert.equal(page.isClosed(), true);
});
test('real Sorcerer and zero rows remain class-aware and never invent raw zero', { skip: !config?.buildFiles?.Sorcerer, timeout: 60000 }, async () => {
  const runtime = new DomCalculationPath(config);
  const oracle = JSON.parse(fs.readFileSync(config.oracleFile));
  try {
    for (const label of ['Sorcerer', 'RogueZero']) {
      const result = await runtime.evaluate(JSON.parse(fs.readFileSync(config.buildFiles[label])));
      assert.equal(compare(result, oracle[label]).status, 'PASS');
      assert.equal(result.coverage.notRendered, label === 'Sorcerer' ? 14 : 16);
      assert.equal(result.coverage.notApplicable, label === 'Sorcerer' ? 6 : 0);
      for (const metric of result.metrics.filter(m => m.status !== 'DISPLAY_OBSERVED')) {
        assert.equal(metric.rawValue, null); assert.equal(metric.displayNumber, null);
      }
      if (label === 'Sorcerer') {
        assert.equal(result.metrics.find(m => m.id === 'maxroll.heroDetails.81').name, 'Maximum Mana');
        assert.deepEqual(result.additionalMetrics.map(m => m.id).sort(), ['maxroll.heroDetails.86', 'maxroll.heroDetails.292', 'maxroll.heroDetails.300'].sort());
      }
    }
  } finally { await runtime.close(); }
});
