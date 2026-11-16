'use strict';

const crypto = require('node:crypto');
const { loadMaxrollEntityCatalog, D12_COMPATIBILITY } = require('./canonical-codec');
const { ERROR_CODES, MaxrollProviderError } = require('./errors');
const { writeAtomicExclusive, serialize } = require('./build-export');
const path = require('node:path');

const CATALOG_EXPORT_SCHEMA = 'd4-game-catalog-export/v1';
const CATALOG_FAMILIES = Object.freeze([
  'classes', 'items', 'itemTypes', 'affixes', 'oldAffixes', 'skills', 'skillTrees',
  'paragonBoards', 'paragonGlyphs', 'paragonNodes', 'stones', 'mercenaries',
  'warPlans', 'temperingRecipes', 'itemSets', 'attributes',
]);
const DIGEST = /^[a-f0-9]{64}$/;
const fail = (message) => { throw new MaxrollProviderError(ERROR_CODES.INVALID_INPUT, message); };

function selectFamilies(value) {
  if (value === undefined) return [...CATALOG_FAMILIES];
  if (!Array.isArray(value) || !value.length || !value.every(x => typeof x === 'string')) {
    fail('families must be a non-empty array of names');
  }
  const selected = [...new Set(value)];
  if (selected.length !== value.length || selected.some(x => !CATALOG_FAMILIES.includes(x))) {
    fail('families contain an unknown or duplicate name');
  }
  return CATALOG_FAMILIES.filter(x => selected.includes(x));
}

function validateSource(options) {
  for (const key of ['snapshotRoot', 'snapshotId', 'expectedManifestSha256']) {
    if (typeof options?.[key] !== 'string' || !options[key]) fail(`${key} is required`);
  }
  if (!DIGEST.test(options.expectedManifestSha256)) fail('invalid expectedManifestSha256');
}

async function openCatalog(options) {
  validateSource(options);
  // loadMaxrollEntityCatalog checks every snapshot blob, manifest and catalog identity.
  const catalog = await loadMaxrollEntityCatalog(options);
  if (catalog.provenance.snapshotId !== D12_COMPATIBILITY.snapshotId
    || catalog.provenance.snapshotManifestSha256 !== options.expectedManifestSha256
    || catalog.provenance.resourceSha256 !== D12_COMPATIBILITY.catalogResourceSha256
    || catalog.provenance.gameDataVersion !== D12_COMPATIBILITY.catalogVersion) {
    throw new MaxrollProviderError(ERROR_CODES.SNAPSHOT_MISMATCH,
      'catalog does not match pinned versioned compatibility binding');
  }
  return catalog;
}

function makeExport(catalog, families) {
  const chosen = selectFamilies(families);
  const data = catalog.exportDataFamilies(chosen);
  return {
    schemaVersion: CATALOG_EXPORT_SCHEMA,
    game: { id: 'diablo-iv', patch: D12_COMPATIBILITY.gamePatch, season: 15 },
    provenance: {
      source: 'VERIFIED_PRIVATE_OFFLINE_SNAPSHOT',
      snapshotId: catalog.provenance.snapshotId,
      manifestSha256: catalog.provenance.snapshotManifestSha256,
      catalogSha256: catalog.provenance.resourceSha256,
      gameDataVersion: catalog.provenance.gameDataVersion,
    },
    selectedFamilies: chosen,
    counts: Object.fromEntries(chosen.map(x => [x, Array.isArray(data[x])
      ? data[x].length : Object.keys(data[x]).length])),
    data,
  };
}

async function listCatalogFamilies(options) {
  const catalog = await openCatalog(options);
  const counts = catalog.counts;
  for (const name of CATALOG_FAMILIES) {
    if (counts[name] === undefined) throw new MaxrollProviderError(
      ERROR_CODES.CANONICAL_MAPPING_INCOMPLETE, `missing catalog family: ${name}`);
  }
  return Object.freeze({ schemaVersion: CATALOG_EXPORT_SCHEMA,
    snapshotId: catalog.provenance.snapshotId,
    gamePatch: D12_COMPATIBILITY.gamePatch,
    families: Object.fromEntries(CATALOG_FAMILIES.map(x => [x, counts[x]])) });
}

async function exportCatalogFromSnapshot(options) {
  validateSource(options);
  if (typeof options.outputPath !== 'string' || !options.outputPath) fail('outputPath is required');
  const catalog = await openCatalog(options);
  const output = makeExport(catalog, options.families);
  const bytes = Buffer.from(serialize(output));
  const outputPath = path.resolve(options.outputPath);
  await writeAtomicExclusive(outputPath, bytes);
  return Object.freeze({ schemaVersion: CATALOG_EXPORT_SCHEMA, outputPath,
    bytes: bytes.length,
    sha256: crypto.createHash('sha256').update(bytes).digest('hex'),
    snapshotId: output.provenance.snapshotId,
    families: output.selectedFamilies,
    counts: output.counts });
}

module.exports = { CATALOG_EXPORT_SCHEMA, CATALOG_FAMILIES, selectFamilies,
  makeExport, listCatalogFamilies, exportCatalogFromSnapshot };
