'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const { CONTRACT_VERSION, D4RuleKitApplication } = require('../../src');
const { createOptions, makeStatelessProvider } = require('../helpers/providers');

const EXPECTED_APIS = [
  'closeSession', 'commitChanges', 'createSession', 'evaluate',
  'getSession', 'listProviders', 'previewChanges', 'resetSession',
];

test('public application surface has exactly the eight Owner-approved operations', () => {
  const methods = Object.getOwnPropertyNames(D4RuleKitApplication.prototype)
    .filter(name => name !== 'constructor').sort();
  assert.deepEqual(methods, EXPECTED_APIS);
  assert.equal(CONTRACT_VERSION, 'd4-rulekit-application/v1');
});

test('package smoke imports without browser or provider-specific dependencies', () => {
  const sourceRoot = path.resolve(__dirname, '../../src');
  const sources = fs.readdirSync(sourceRoot).filter(name => name.endsWith('.js'))
    .map(name => fs.readFileSync(path.join(sourceRoot, name), 'utf8')).join('\n');
  assert.doesNotMatch(sources, /maxroll|playwright|chromium|cdp/i);
  assert.equal(typeof require('../..').D4RuleKitApplication, 'function');
});

test('a conforming provider is substitutable without application changes', async () => {
  const fixture = makeStatelessProvider({ id: 'provider-b.synthetic', version: '9.1.0' });
  const app = new D4RuleKitApplication({ providers: [fixture.provider] });
  const session = await app.createSession(createOptions('provider-b.synthetic', '9.1.0'));
  const result = await app.evaluate(session.sessionId);
  assert.equal(result.providerId, 'provider-b.synthetic');
  assert.equal(result.metrics.every(metric => metric.status !== 'VERIFIED'), true);
});
