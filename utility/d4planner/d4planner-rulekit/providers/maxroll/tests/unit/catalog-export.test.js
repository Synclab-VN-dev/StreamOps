'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { MaxrollEntityCatalog, D12_COMPATIBILITY } = require('../../src/canonical-codec');
const { CATALOG_FAMILIES, CATALOG_EXPORT_SCHEMA, selectFamilies, makeExport,
  listCatalogFamilies, exportCatalogFromSnapshot } = require('../../src/catalog-export');
const { parseArguments } = require('../../scripts/catalog-export');

function fixture() {
  const data = Object.fromEntries(CATALOG_FAMILIES.map(name => [name, {}]));
  data.classes = { 3: { id: 3, name: 'Rogue', tree: 'tree-rogue', paragonBoards: ['board-a'] } };
  data.items = { 10: { id: 10, type: 'helm', classFilter: [false, false, false, true] } };
  data.skills = { 99: { id: 99, class: 3, name: 'Skill' } };
  data.skillTrees = { 'tree-rogue': { nodes: [] } };
  data.paragonBoards = { 'board-a': { nodes: [] } };
  return new MaxrollEntityCatalog(data, {
    snapshotId: D12_COMPATIBILITY.snapshotId,
    snapshotManifestSha256: D12_COMPATIBILITY.snapshotManifestSha256,
    resourceSha256: D12_COMPATIBILITY.catalogResourceSha256,
    gameDataVersion: D12_COMPATIBILITY.catalogVersion,
  });
}

test('export selects 16 approved families, retains IDs and trusted provenance', () => {
  const catalog = fixture();
  const result = makeExport(catalog);
  assert.equal(result.schemaVersion, CATALOG_EXPORT_SCHEMA);
  assert.deepEqual(result.selectedFamilies, CATALOG_FAMILIES);
  assert.deepEqual(result.data.items['10'], { id: 10, type: 'helm',
    classFilter: [false, false, false, true] });
  assert.equal(result.game.season, 15);
  assert.equal(result.provenance.manifestSha256, D12_COMPATIBILITY.snapshotManifestSha256);
  assert.equal(result.counts.classes, 1);
  assert.equal(JSON.stringify(result).includes('nativeState'), false);
});

test('subset and list behavior preserves allowlisted ordering and correct counts', () => {
  const subset = makeExport(fixture(), ['skills', 'items']);
  assert.deepEqual(subset.selectedFamilies, ['items', 'skills']);
  assert.deepEqual(Object.keys(subset.counts), ['items', 'skills']);
  assert.equal(subset.counts.items, 1);
  assert.equal(subset.counts.skills, 1);
  assert.deepEqual(selectFamilies(['skills', 'items']), ['items', 'skills']);
});

test('unknown, duplicate, empty or untrusted families fail closed', () => {
  for (const value of [[], ['nativeProfiles'], ['items', 'items'], [1], null]) {
    assert.throws(() => selectFamilies(value), error => error.code === 'INVALID_INPUT');
  }
  assert.throws(() => fixture().exportDataFamilies(['futureMechanic']),
    error => error.code === 'INVALID_INPUT');
});

test('catalog exposure is detached/immutable, does not expose hidden catalog families', () => {
  const catalog = fixture();
  const result = catalog.exportDataFamilies(['items']);
  assert.deepEqual(Object.keys(result), ['items']);
  assert.throws(() => { result.items['10'].type = 'corrupt'; }, TypeError);
  assert.equal(catalog.exportDataFamilies(['items']).items['10'].type, 'helm');
});

test('CLI parses required options and rejects unsupported flags', () => {
  assert.deepEqual(parseArguments(['--families', 'skills,items', '--output', '/private/data.json']),
    { families: ['skills', 'items'], outputPath: '/private/data.json' });
  assert.throws(() => parseArguments(['--families']), /incomplete/);
  assert.throws(() => parseArguments(['--list-families', '--output', 'x']), /cannot be combined/);
});

test('entry points reject missing snapshot or output before producing any export', async () => {
  await assert.rejects(() => listCatalogFamilies({}), error => error.code === 'INVALID_INPUT');
  await assert.rejects(() => exportCatalogFromSnapshot({}), error => error.code === 'INVALID_INPUT');
  await assert.rejects(() => exportCatalogFromSnapshot({ snapshotRoot: '/x', snapshotId: 'y',
    expectedManifestSha256: '0'.repeat(64) }), error => error.code === 'INVALID_INPUT');
});
