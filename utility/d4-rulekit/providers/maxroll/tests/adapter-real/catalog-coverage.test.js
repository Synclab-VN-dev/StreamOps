'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const test = require('node:test');
const { loadMaxrollEntityCatalog } = require('../../src');

const SNAPSHOT_ID = 'maxroll-20261023T034150Z';
const MANIFEST_SHA = '638a283b8aa0cb822a35176d9d41c8d1751fb6f962ca0a2f7feaa20f1ef39e54';

test('B2-B7 pinned catalog coverage inventory is exhaustive and machine-readable', async () => {
  const snapshotRoot = process.env.MAXROLL_AUTHORIZED_SNAPSHOT_ROOT;
  if (!snapshotRoot) throw new Error('MAXROLL_AUTHORIZED_SNAPSHOT_ROOT is required');
  const catalog = await loadMaxrollEntityCatalog({
    snapshotRoot, snapshotId: SNAPSHOT_ID, expectedManifestSha256: MANIFEST_SHA,
  });
  const audit = catalog.auditCoverage();
  assert.deepEqual(catalog.coverageInventory(), {
    families: {
      classes: 8, items: 12195, itemTypes: 160, affixes: 6380, oldAffixes: 803,
      skills: 2910, skillTrees: 19, paragonBoards: 80, paragonGlyphs: 161,
      paragonNodes: 566, stones: 228, mercenaries: 4, warPlans: 7,
      temperingRecipes: 187, itemSets: 45, attributes: 1693,
    }, present: 16, total: 16, percent: 100,
  });
  assert.equal(audit.families.classes.percent, 100);
  assert.equal(audit.families.paragonBoards.percent, 100);
  assert.equal(audit.families.affixItemLegality.status,
    'BLOCKED_NO_AUTHORITATIVE_RELATION');
  assert.equal(audit.families.specializationTaxonomy.status,
    'BLOCKED_MISSING_DEDICATED_CATALOG');
  const documented = JSON.parse(await fs.readFile(path.resolve(__dirname,
    '../../UNIVERSAL-IMPORT-COVERAGE.json')));
  assert.equal(documented.catalog.classes.numerator, audit.families.classes.numerator);
  assert.equal(documented.catalog.equippableItemsWithClassAndSlotEvidence.numerator,
    audit.families.equippableItems.numerator);
  assert.equal(documented.catalog.paragonGlyphsWithClassEvidence.numerator,
    audit.families.paragonGlyphs.numerator);
  assert.equal(documented.status, 'PARTIAL_BLOCKED_COVERAGE');
});
