'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const { MaxrollProvider, MaxrollSession } = require('../../src');

test('provider surface matches CalculationProvider without duplicating Application APIs', () => {
  const providerMethods = Object.getOwnPropertyNames(MaxrollProvider.prototype)
    .filter(name => name !== 'constructor').sort();
  assert.deepEqual(providerMethods, ['createSession', 'getCapabilities']);
  const sessionMethods = Object.getOwnPropertyNames(MaxrollSession.prototype)
    .filter(name => name !== 'constructor').sort();
  assert.deepEqual(sessionMethods, ['checkpoint', 'close', 'evaluate', 'initialize', 'restore']);
});

test('provider production source composes browser ports and contains no Application orchestration APIs', () => {
  const sourceRoot = path.resolve(__dirname, '../../src');
  const source = fs.readdirSync(sourceRoot).filter(name => name.endsWith('.js'))
    .map(name => fs.readFileSync(path.join(sourceRoot, name), 'utf8')).join('\n');
  assert.doesNotMatch(source, /listProviders|previewChanges|commitChanges|resetSession|getSession|closeSession/);
  assert.doesNotMatch(source, /chromium\.launch|newContext\(/);
});
