'use strict';
const path = require('node:path');
const { loadMaxrollEntityCatalog, CANONICAL_SCHEMA_VERSION, CODEC_VERSION,
  D12_COMPATIBILITY } = require('./canonical-codec');
const { canonical, sha256 } = require('./value');
const { writeAtomicExclusive } = require('./build-export');
const { MaxrollProviderError, ERROR_CODES } = require('./errors');
const buildSchema = require('../d4-build-v1.schema.json');
const CATALOG_EXPORT_SCHEMA_VERSION = 'maxroll-game-data-catalog/v1';
async function read(options) {
  if (!/^[a-f0-9]{64}$/.test(options?.expectedManifestSha256 ?? '')) {
    throw new MaxrollProviderError(ERROR_CODES.INVALID_INPUT, 'manifest SHA-256 is required');
  }
  const catalog = await loadMaxrollEntityCatalog(options);
  const data = catalog.exportFamilies(options.families);
  const counts = Object.fromEntries(Object.entries(data).map(([key, value]) =>
    [key, Array.isArray(value) ? value.length : Object.keys(value).length]));
  return { catalog, data, counts };
}
async function listMaxrollCatalogFamilies(options) {
  const { counts } = await read(options);
  return { schemaVersion: CATALOG_EXPORT_SCHEMA_VERSION, families: counts,
    familyCount: Object.keys(counts).length };
}
async function exportMaxrollGameDataCatalog(options) {
  if (typeof options?.outputPath !== 'string' || !options.outputPath.trim()) {
    throw new MaxrollProviderError(ERROR_CODES.INVALID_INPUT, 'outputPath is required');
  }
  const { catalog, data, counts } = await read(options);
  // Explicit allowlist: never serialize a whole loader, snapshot or runtime object.
  const p = catalog.provenance;
  const document = {
    schemaVersion: CATALOG_EXPORT_SCHEMA_VERSION,
    provenance: { snapshotId: p.snapshotId, snapshotManifestSha256: p.snapshotManifestSha256,
      resourceSha256: p.resourceSha256, gameDataVersion: p.gameDataVersion },
    contract: { game: 'diablo-iv', gamePatch: D12_COMPATIBILITY.gamePatch,
      canonicalSchemaVersion: CANONICAL_SCHEMA_VERSION, codecVersion: CODEC_VERSION,
      season: buildSchema.properties.calculationContext.properties.season.const },
    coverage: { meaning: 'CATALOG_FAMILIES_ONLY', combinationsVerified: false },
    familyCounts: counts, families: data,
  };
  const bytes = Buffer.from(canonical(document) + '\n');
  await writeAtomicExclusive(path.resolve(options.outputPath), bytes);
  return { schemaVersion: CATALOG_EXPORT_SCHEMA_VERSION, outputSha256: sha256(bytes),
    bytes: bytes.length, familyCounts: counts };
}
module.exports = { CATALOG_EXPORT_SCHEMA_VERSION, listMaxrollCatalogFamilies, exportMaxrollGameDataCatalog };
