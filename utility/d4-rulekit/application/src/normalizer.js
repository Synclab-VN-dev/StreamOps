'use strict';

const { ApplicationError, ERROR_CODES } = require('./errors');
const { immutableCopy } = require('./value');

const STATUSES = new Set(['OBSERVED', 'UNKNOWN', 'UNSUPPORTED', 'ERROR']);

function normalizeMetrics(metrics) {
  if (!Array.isArray(metrics)) throw new ApplicationError(ERROR_CODES.PROVIDER_FAILURE, 'provider metrics must be an array');
  const ids = new Set();
  const normalized = metrics.map(metric => {
    if (!metric || typeof metric.id !== 'string' || !metric.id || ids.has(metric.id) || !STATUSES.has(metric.status)) {
      throw new ApplicationError(ERROR_CODES.PROVIDER_FAILURE, 'provider returned invalid or duplicate metric');
    }
    ids.add(metric.id);
    if ((metric.status === 'UNKNOWN' || metric.status === 'UNSUPPORTED') &&
        (metric.rawValue !== null && metric.rawValue !== undefined)) {
      throw new ApplicationError(ERROR_CODES.PROVIDER_FAILURE, `${metric.status} metric must not fabricate rawValue`);
    }
    return {
      id: metric.id,
      name: metric.name ?? metric.id,
      rawValue: metric.rawValue ?? null,
      displayValue: metric.displayValue ?? null,
      unit: metric.unit ?? null,
      status: metric.status,
      provenance: metric.provenance ? immutableCopy(metric.provenance) : null,
    };
  });
  return immutableCopy(normalized.sort((a, b) => a.id.localeCompare(b.id)));
}

function metricDelta(before, after) {
  const prior = new Map(before.map(metric => [metric.id, metric]));
  return immutableCopy(after.map(metric => {
    const old = prior.get(metric.id);
    const numeric = old && typeof old.rawValue === 'number' && typeof metric.rawValue === 'number';
    return {
      id: metric.id,
      before: old?.rawValue ?? null,
      after: metric.rawValue,
      delta: numeric ? metric.rawValue - old.rawValue : null,
      unit: metric.unit,
      deltaKind: numeric && metric.unit === '%' ? 'PERCENTAGE_POINT' : numeric ? 'ABSOLUTE' : 'UNAVAILABLE',
      status: old ? metric.status : 'ADDED',
    };
  }));
}

module.exports = { metricDelta, normalizeMetrics };
