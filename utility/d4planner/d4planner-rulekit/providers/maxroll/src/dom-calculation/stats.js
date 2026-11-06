'use strict';

const { METRIC_CATALOG } = require('../metric-catalog');
const SECTION_NAMES = { 0: 'Core Stats', 1: 'Offensive', 2: 'Defensive', 3: 'Utility', 4: 'PVP', 6: 'Resistances', 7: '' };
function fail(code, message) { throw Object.assign(new Error(message), { code }); }

function catalogFrom(data, locale, classId) {
  const playerClass = data.classes?.[classId];
  if (!playerClass || !Array.isArray(data.heroDetails) || !Array.isArray(locale.heroDetails)) {
    fail('DOM_CATALOG_UNSUPPORTED', 'Character Stats catalog/class is unavailable');
  }
  const resource = kind => locale.uiStrings?.resourceType?.[playerClass[kind]?.type];
  const variables = { PRIMARY_RESOURCE: resource('primaryResource'), SECONDARY_RESOURCE: resource('secondaryResource') };
  const result = [];
  data.heroDetails.forEach((entries, section) => entries.forEach((entry, index) => {
    if (!Object.hasOwn(SECTION_NAMES, section)) return;
    const localized = locale.heroDetails[section]?.[index];
    const template = localized?.name ?? entry.name;
    if (typeof template !== 'string') fail('DOM_CATALOG_UNSUPPORTED', 'Stat localization is missing');
    let unresolved = false;
    const name = template.replace(/\{(\w+)\}/g, (_, key) => {
      if (variables[key] === undefined) { unresolved = true; return `{${key}}`; }
      return variables[key];
    });
    result.push({ id: `maxroll.heroDetails.${entry.id}`, internalId: entry.id, name,
      section: SECTION_NAMES[section], applicable: entry.classFilter?.[classId] === true,
      collapse: entry.collapse === true, format: entry.values?.[0] ?? {}, unresolved });
  }));
  if (new Set(result.map(x => x.id)).size !== result.length) fail('DOM_CATALOG_UNSUPPORTED', 'Duplicate metric IDs');
  return result;
}

function parseDisplay(displayValue, format) {
  // English snapshot renderer only. Never eval the formula or infer an unrounded value.
  if (typeof displayValue !== 'string' || !/^[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?$/.test(displayValue)) {
    fail('DOM_VALUE_UNSUPPORTED', `Unrecognized numeric display: ${displayValue}`);
  }
  const percent = displayValue.endsWith('%');
  if (percent !== (format.percent === true)) fail('DOM_VALUE_UNSUPPORTED', 'Stat unit differs from the verified catalog');
  const digits = displayValue.replace('%', '').split('.')[1]?.length ?? 0;
  const scale = percent ? 100 : 1;
  const value = Number(displayValue.replaceAll(',', '').replace('%', '')) / scale;
  if (!Number.isFinite(value)) fail('DOM_VALUE_UNSUPPORTED', 'Nonfinite stat');
  const quantum = 10 ** -digits / scale;
  return { displayNumber: value, precision: { kind: 'DISPLAY_QUANTIZED', quantum,
    // Conservative half-step bounds; endpoints are not claimed as native rounding ties.
    lower: value - quantum / 2, upper: value + quantum / 2 } };
}

function extractStats(rows, catalog, metricIds = METRIC_CATALOG.map(m => m.id)) {
  if (!Array.isArray(metricIds) || !metricIds.length || new Set(metricIds).size !== metricIds.length) {
    fail('DOM_INVALID_INPUT', 'metricIds must be a nonempty unique list');
  }
  const known = new Map(catalog.map(m => [m.id, m]));
  for (const id of metricIds) if (!known.has(id)) fail('DOM_CATALOG_UNSUPPORTED', `Unknown stat ID ${id}`);
  const observed = new Map();
  for (const row of rows) {
    const candidates = catalog.filter(m => m.applicable && !m.unresolved && m.section === row.section && m.name === row.name);
    if (candidates.length !== 1) fail('DOM_SCHEMA_MISMATCH', `Unmapped or ambiguous stat: ${row.section}/${row.name}`);
    const metric = candidates[0];
    if (observed.has(metric.id)) fail('DOM_SCHEMA_MISMATCH', `Duplicate DOM stat ${metric.id}`);
    observed.set(metric.id, { ...row, ...parseDisplay(row.displayValue, metric.format) });
  }
  // Every non-collapsible applicable row must exist, even if the caller only requested a subset.
  for (const metric of catalog) if (metric.applicable && !metric.collapse && !observed.has(metric.id)) {
    fail('DOM_INCOMPLETE', `Required DOM stat absent: ${metric.id}`);
  }
  function result(id) {
    const metric = known.get(id), row = observed.get(id);
    const base = { id, name: metric.name, section: metric.section, rawValue: null };
    if (!metric.applicable) return { ...base, status: 'NOT_APPLICABLE', displayValue: null, displayNumber: null };
    if (metric.unresolved) fail('DOM_CATALOG_UNSUPPORTED', `Unresolved label: ${id}`);
    if (!row) return { ...base, status: 'NOT_RENDERED', displayValue: null, displayNumber: null,
      reason: 'COLLAPSIBLE_ROW_ABSENT', inferredZero: false };
    return { ...base, status: 'DISPLAY_OBSERVED', displayValue: row.displayValue,
      displayNumber: row.displayNumber, precision: row.precision, selector: row.selector };
  }
  const metrics = metricIds.map(result);
  const additionalMetrics = [...observed.keys()].filter(id => !metricIds.includes(id)).map(result);
  return { metrics, additionalMetrics, coverage: { requested: metrics.length,
    observed: metrics.filter(m => m.status === 'DISPLAY_OBSERVED').length,
    notRendered: metrics.filter(m => m.status === 'NOT_RENDERED').length,
    notApplicable: metrics.filter(m => m.status === 'NOT_APPLICABLE').length,
    exactRaw: 0, allVisibleRows: rows.length } };
}

// Only standard DOM APIs: no React internals, engine globals, or private JavaScript bindings.
function readStatsDom() {
  const widgets = document.querySelectorAll('.StatsTest');
  if (widgets.length !== 1) return { rows: [], ready: false };
  const rows = [];
  for (const [si, section] of [...widgets[0].querySelectorAll('[class*="stats_StatSection"]')].entries()) {
    const name = section.querySelector('h3')?.textContent?.trim() ?? '';
    for (const [ri, li] of [...section.querySelectorAll('li')].entries()) {
      const spans = li.querySelectorAll(':scope > span');
      if (spans.length !== 2) return { rows: [], ready: false };
      rows.push({ section: name, name: spans[0].textContent.trim(), displayValue: spans[1].textContent.trim(),
        selector: `.StatsTest [class*="stats_StatSection"] >> nth=${si} >> li >> nth=${ri} >> span:last-child` });
    }
  }
  return { rows, ready: rows.length > 0, level: rows.find(row => row.section === 'Core Stats' && row.name === 'Level')?.displayValue,
    className: document.querySelector('[class*="header_ClassOption"]')?.textContent?.trim() };
}
module.exports = { catalogFrom, extractStats, parseDisplay, readStatsDom, fail };
