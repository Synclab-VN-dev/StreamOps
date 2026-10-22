'use strict';

const crypto = require('node:crypto');

function canonical(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
}

function sha256(value) {
  return crypto.createHash('sha256').update(typeof value === 'string' || Buffer.isBuffer(value)
    ? value : canonical(value)).digest('hex');
}

function immutable(value) {
  const copy = structuredClone(value);
  const visit = current => {
    if (!current || typeof current !== 'object' || Object.isFrozen(current)) return current;
    Object.freeze(current);
    for (const child of Object.values(current)) visit(child);
    return current;
  };
  return visit(copy);
}

module.exports = { canonical, immutable, sha256 };
