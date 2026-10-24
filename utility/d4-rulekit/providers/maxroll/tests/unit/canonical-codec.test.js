'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const {
  CANONICAL_SCHEMA_VERSION,
  ERROR_CODES,
  MaxrollD12CanonicalCodec,
  MaxrollEntityCatalog,
} = require('../../src');

function catalog() {
  return new MaxrollEntityCatalog({
    version: 'test',
    classes: { 3: { id: 3, tree: 'rogue-tree' } },
    items: { 'item-a': { id: 'item-a' }, 'socket-a': { id: 'socket-a' } },
    affixes: { affix: { id: 101 }, aspect: { id: 102 }, temper: { id: 103 } },
    oldAffixes: {},
    skills: { skill: { id: 'skill-a' } },
    skillTrees: { 'rogue-tree': { id: 'rogue-tree', nodes: [{ id: 10 }, { id: 11 }] } },
    stones: {},
    mercenaries: { merc: { id: 'merc-a' } },
    paragonBoards: { board: { id: 'board-a', nodes: [null, { id: 'node-a' }] } },
    paragonGlyphs: { glyph: { id: 'glyph-a' } },
  }, { snapshotId: 'snapshot-a', resourceSha256: 'a'.repeat(64) });
}

function fixture() {
  return {
    schemaVersion: 'maxroll-native-build-export/v1',
    format: 'MAXROLL_NATIVE_STATE',
    provenance: { runtimeVersion: '3.2.1.73552' },
    selection: { profileIndex: 1 },
    integrity: { nativeStateSha256: 'b'.repeat(64) },
    nativeState: {
      activeProfile: 1, season: 15, options: { optionA: true },
      items: { 9: {
        id: 'item-a', name: 'Named item', power: 800, upgrade: 2,
        explicits: [{ nid: 101, values: [1], greater: true }],
        aspects: [{ nid: 102, values: [2] }],
        tempered: [{ nid: 103, values: [3], upgrade: 1 }],
        sockets: ['socket-a'],
      } },
      profiles: [{ name: 'Other' }, {
        name: 'Fixture-specific name', hidden: false, class: 3, level: 70, worldTier: 8,
        items: { 4: 9 }, elixirs: [],
        skillTree: { position: 1, steps: [
          { name: 'Other', data: { 11: 1 } }, { name: 'Active', data: { 10: 5 } },
        ] },
        skillBar: ['skill-a'],
        paragon: { position: 0, steps: [{ name: 'Active', data: [{
          id: 'board-a', rotation: 2, position: { x: 0, y: 0 }, nodes: { 1: true },
          glyph: 'glyph-a', glyphLevel: 100,
        }] }] },
        rotations: [], warPlans: [], specialization: 'combo-points',
        mercenary: { id: 'merc-a', support: 'support-a', supportSkills: ['support-skill'],
          tree: { 1: 1 } },
        world: { renownSkills: 10, renownParagon: 20 },
        widgetNotes: {},
      }],
    },
  };
}

test('native -> canonical -> native is semantic, deterministic and excludes loader/profile baggage', () => {
  const codec = new MaxrollD12CanonicalCodec({ catalog: catalog() });
  const canonical = codec.nativeToCanonical(fixture());
  assert.equal(canonical.schemaVersion, CANONICAL_SCHEMA_VERSION);
  assert.equal(canonical.character.classId, '3');
  assert.equal(canonical.equipment.slots[0].item.baseItemId, 'item-a');
  assert.equal(canonical.skills.allocations[0].nodeId, '10');
  assert.equal(canonical.paragon.boards[0].boardId, 'board-a');
  assert.equal(Object.hasOwn(canonical, 'nativeState'), false);
  assert.equal(Object.hasOwn(canonical, 'loaderMetadata'), false);
  assert.equal(JSON.stringify(canonical).includes('Fixture-specific name'), false);

  const first = codec.canonicalToNative(canonical);
  const second = codec.canonicalToNative(structuredClone(canonical));
  assert.deepEqual(first, second);
  assert.equal(first.profiles.length, 1);
  assert.equal(Object.keys(first.items).length, 1);
  assert.equal(first.activeProfile, 0);
  assert.equal(first.profiles[0].items['4'], 1);
  assert.deepEqual(first.profiles[0].skillTree.steps[0].data, { 10: 5 });
  assert.deepEqual(first.profiles[0].paragon.steps[0].data[0].nodes, { 1: true });
  assert.equal(first.items['1'].explicits[0].nid, 101);
  assert.equal(first.items['1'].tempered[0].upgrade, 1);
});

test('same codec accepts a second build without fixture-specific branches', () => {
  const codec = new MaxrollD12CanonicalCodec({ catalog: catalog() });
  const second = fixture();
  second.nativeState.items[10] = structuredClone(second.nativeState.items[9]);
  second.nativeState.items[10].power = 925;
  second.nativeState.profiles[1].items[4] = 10;
  second.nativeState.profiles[1].skillTree.steps[1].data = { 11: 3 };
  const canonical = codec.nativeToCanonical(second);
  assert.equal(canonical.equipment.slots[0].item.itemPower, 925);
  assert.deepEqual(canonical.skills.allocations, [{ nodeId: '11', rank: 3 }]);
  assert.equal(codec.canonicalToNative(canonical).items['1'].power, 925);
});

test('unknown native fields and missing catalog entities fail closed with typed errors', () => {
  const codec = new MaxrollD12CanonicalCodec({ catalog: catalog() });
  const unknown = fixture();
  unknown.nativeState.profiles[1].futureMechanic = { enabled: true };
  assert.throws(() => codec.nativeToCanonical(unknown),
    error => error.code === ERROR_CODES.CANONICAL_MAPPING_INCOMPLETE);

  const missing = fixture();
  missing.nativeState.items[9].id = 'not-in-catalog';
  assert.throws(() => codec.nativeToCanonical(missing),
    error => error.code === ERROR_CODES.ENTITY_NOT_FOUND);

  const extended = structuredClone(codec.nativeToCanonical(fixture()));
  extended.futureSection = {};
  assert.throws(() => codec.canonicalToNative(extended),
    error => error.code === ERROR_CODES.CANONICAL_MAPPING_INCOMPLETE);

  const invalidCanonical = codec.nativeToCanonical(fixture());
  assert.throws(() => {
    invalidCanonical.equipment.slots[0].item.baseItemId = 'cannot-mutate-frozen';
  }, TypeError);
  assert.equal(invalidCanonical.equipment.slots[0].item.baseItemId, 'item-a');
});
