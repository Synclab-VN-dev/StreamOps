'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const {
  CANONICAL_SCHEMA_VERSION,
  ERROR_CODES,
  MaxrollD12CanonicalCodec,
  MaxrollEntityCatalog,
  UniversalMaxrollBuildMapper,
  createD12NativeLoaderMetadata,
} = require('../../src');

function catalog(provenanceOverrides = {}) {
  return new MaxrollEntityCatalog({
    version: 'test',
    classes: Object.fromEntries(Array.from({ length: 8 }, (_, id) => [id, {
      id, name: `Class ${id}`, tree: id === 3 ? 'rogue-tree' : `tree-${id}`,
      paragonBoards: id === 3 ? ['board-a'] : [],
    }])),
    items: { 'item-a': { id: 'item-a', type: 'Helm' }, 'socket-a': { id: 'socket-a' } },
    itemTypes: { Helm: { id: 'Helm', bodySlots: [4], itemLabels: [] } },
    affixes: { affix: { id: 101 }, aspect: { id: 102 }, temper: { id: 103 } },
    oldAffixes: {},
    skills: { skill: { id: 'skill-a' }, specialization: { id: 'combo-points' },
      support: { id: 'support-skill' } },
    skillTrees: Object.fromEntries([
      ['rogue-tree', { id: 'rogue-tree', nodes: [{ id: 10 }, { id: 11 }] }],
      ['merc-tree', { id: 'merc-tree', nodes: [{ id: 1 }] }],
      ...Array.from({ length: 8 }, (_, id) => [`tree-${id}`, { id: `tree-${id}`, nodes: [] }]),
    ]),
    stones: {},
    mercenaries: { merc: { id: 'merc-a', tree: 'merc-tree' } },
    paragonNodes: {}, temperingRecipes: {}, itemSets: {}, attributes: {}, warPlans: [],
    paragonBoards: { board: { id: 'board-a', nodes: [null, { id: 'node-a' }] } },
    paragonGlyphs: { glyph: { id: 'glyph-a' } },
  }, {
    snapshotId: 'maxroll-20261023T034150Z',
    snapshotManifestSha256: '638a283b8aa0cb822a35176d9d41c8d1751fb6f962ca0a2f7feaa20f1ef39e54',
    resourceSha256: '889facd9fa21a0a2baba3f8c28d53ac66b6e28a7514994f82ab8f00a3a5e1f93',
    gameDataVersion: '3.2.1.73552',
    ...provenanceOverrides,
  });
}

function fixture() {
  return {
    schemaVersion: 'maxroll-native-build-export/v1',
    format: 'MAXROLL_NATIVE_STATE',
    provenance: {
      snapshotId: 'maxroll-20261023T034150Z',
      snapshotManifestSha256: '638a283b8aa0cb822a35176d9d41c8d1751fb6f962ca0a2f7feaa20f1ef39e54',
      runtimeVersion: '3.2.1.73552',
      runtimeAssetSha256: '891c1f82717c50e598450575068394c6d2fe1c8d26de26f2eeed028d028997db',
    },
    selection: { profileIndex: 1 },
    integrity: { nativeStateSha256: 'b'.repeat(64) },
    nativeState: {
      activeProfile: 1, season: 15, options: { 'skill-a': { flags: [true] } },
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

test('B0-REV-01 rejects unknown transformed nested fields and preserves board position', () => {
  const codec = new MaxrollD12CanonicalCodec({ catalog: catalog() });
  const unknownBoard = fixture();
  unknownBoard.nativeState.profiles[1].paragon.steps[0].data[0].futureMechanic = {
    enabled: true,
  };
  assert.throws(() => codec.nativeToCanonical(unknownBoard),
    error => error.code === ERROR_CODES.CANONICAL_MAPPING_INCOMPLETE);

  const unknownMercenary = fixture();
  unknownMercenary.nativeState.profiles[1].mercenary.futureEffect = { stacks: 2 };
  assert.throws(() => codec.nativeToCanonical(unknownMercenary),
    error => error.code === ERROR_CODES.CANONICAL_MAPPING_INCOMPLETE);

  const opaque = fixture();
  opaque.nativeState.profiles[1].paragon.steps[0].data[0].position.futureCoordinate = {
    axis: 'kept', value: 42,
  };
  const canonical = codec.nativeToCanonical(opaque);
  const roundTrip = codec.canonicalToNative(canonical);
  assert.deepEqual(roundTrip.profiles[0].paragon.steps[0].data[0].position,
    opaque.nativeState.profiles[1].paragon.steps[0].data[0].position);

  const unknownOption = fixture();
  unknownOption.nativeState.options.futureOption = { flags: [true] };
  assert.throws(() => codec.nativeToCanonical(unknownOption),
    error => error.code === ERROR_CODES.ENTITY_NOT_FOUND);
});

test('B0-REV-02 rejects wrong/missing patch and mismatched trusted provenance', () => {
  const codec = new MaxrollD12CanonicalCodec({ catalog: catalog() });
  const valid = codec.nativeToCanonical(fixture());
  assert.doesNotThrow(() => codec.canonicalToNative(valid));

  const wrongPatch = structuredClone(valid);
  wrongPatch.game.patch = '9.9.9.99999';
  assert.throws(() => codec.canonicalToNative(wrongPatch),
    error => error.code === ERROR_CODES.RUNTIME_MISMATCH);

  const missingPatch = structuredClone(valid);
  delete missingPatch.game.patch;
  assert.throws(() => codec.canonicalToNative(missingPatch),
    error => error.code === ERROR_CODES.RUNTIME_MISMATCH);

  const wrongProvenance = fixture();
  wrongProvenance.provenance.snapshotManifestSha256 = 'f'.repeat(64);
  assert.throws(() => codec.nativeToCanonical(wrongProvenance),
    error => error.code === ERROR_CODES.SNAPSHOT_MISMATCH);

  const wrongEngine = fixture();
  wrongEngine.provenance.runtimeAssetSha256 = 'e'.repeat(64);
  assert.throws(() => codec.nativeToCanonical(wrongEngine),
    error => error.code === ERROR_CODES.RUNTIME_MISMATCH);

  const missingRuntimeVersion = fixture();
  delete missingRuntimeVersion.provenance.runtimeVersion;
  assert.throws(() => codec.nativeToCanonical(missingRuntimeVersion),
    error => error.code === ERROR_CODES.RUNTIME_MISMATCH);

  const scratch = structuredClone(valid);
  delete scratch.provenance;
  assert.doesNotThrow(() => codec.canonicalToNative(scratch));

  const forgedUserTrust = structuredClone(valid);
  forgedUserTrust.provenance.compatibility = { catalogVersion: '0.0.0' };
  assert.throws(() => codec.canonicalToNative(forgedUserTrust),
    error => error.code === ERROR_CODES.CANONICAL_MAPPING_INCOMPLETE);

  assert.throws(() => new MaxrollD12CanonicalCodec({
    catalog: catalog({ resourceSha256: '0'.repeat(64) }),
  }), error => error.code === ERROR_CODES.SNAPSHOT_MISMATCH);
});

test('B1 scratch canonical builds for all eight pinned classes need no native fixture provenance', () => {
  const codec = new MaxrollD12CanonicalCodec({ catalog: catalog() });
  for (let classId = 0; classId < 8; classId += 1) {
    const build = {
      schemaVersion: CANONICAL_SCHEMA_VERSION,
      game: { id: 'diablo-iv', patch: '3.2.1.73552' },
      character: { classId: String(classId), level: 1, worldTier: 0 },
      equipment: { slots: [] }, skills: { allocations: [], bar: [] },
      paragon: { boards: [] }, effects: { elixirs: [], warPlans: [] },
      world: {}, calculationContext: { season: 15, options: {} },
    };
    const native = codec.canonicalToNative(build);
    assert.equal(native.profiles[0].class, classId);
    assert.equal(native.profiles[0].name, 'Canonical Import');
    assert.deepEqual(codec.loaderIdentity(build), { className: `Class ${classId}`, season: 15 });
  }
});

test('B3 versioned loader envelope is deterministic and contains no source account metadata', () => {
  const metadata = createD12NativeLoaderMetadata({
    plannerId: '1g1any0x', className: 'Sorcerer', season: 15,
  });
  assert.equal(metadata.class, 'Sorcerer');
  assert.equal(metadata.season, '15');
  assert.equal(metadata.user.id, 0);
  assert.equal(metadata.userId, 0);
  assert.deepEqual(metadata.user, { active: 0, id: 0, username: 'Offline Fixture' });
  assert.throws(() => createD12NativeLoaderMetadata({
    plannerId: '', className: 'Rogue', season: 15,
  }), error => error.code === ERROR_CODES.INVALID_INPUT);
});

test('B2 catalog resolver rejects wrong class, slot, board and forged trust provenance', () => {
  const strictCatalog = catalog();
  const codec = new MaxrollD12CanonicalCodec({ catalog: strictCatalog });
  const build = codec.nativeToCanonical(fixture());
  const wrongSlot = structuredClone(build);
  wrongSlot.equipment.slots[0].slotId = '5';
  assert.throws(() => codec.canonicalToNative(wrongSlot),
    error => error.code === ERROR_CODES.ILLEGAL_COMBINATION);
  const wrongClass = structuredClone(build);
  wrongClass.character.classId = '0';
  assert.throws(() => codec.canonicalToNative(wrongClass),
    error => [ERROR_CODES.ENTITY_NOT_FOUND, ERROR_CODES.ILLEGAL_COMBINATION].includes(error.code));
  assert.deepEqual(strictCatalog.coverageInventory(), {
    families: {
      classes: 8, items: 2, itemTypes: 1, affixes: 3, oldAffixes: 0,
      skills: 3, skillTrees: 10, paragonBoards: 1, paragonGlyphs: 1,
      paragonNodes: 0, stones: 0, mercenaries: 1, warPlans: 0,
      temperingRecipes: 0, itemSets: 0, attributes: 0,
    }, present: 16, total: 16, percent: 100,
  });
});

test('B6 universal mapper applies generic build and section mutations without fixture branches', () => {
  const codec = new MaxrollD12CanonicalCodec({ catalog: catalog() });
  const mapper = new UniversalMaxrollBuildMapper({
    supportedBuildSchemaVersion: CANONICAL_SCHEMA_VERSION,
  }, { codec });
  const baseline = codec.nativeToCanonical(fixture());
  const mapped = mapper.map(baseline, [
    { type: 'skill.setRank', nodeId: '10', rank: 3 },
    { type: 'calculationOption.set', optionId: 'skill-a', value: { params: [2] } },
  ], CANONICAL_SCHEMA_VERSION);
  assert.equal(mapped.desired.skills.allocations[0].rank, 3);
  assert.deepEqual(mapped.desired.calculationContext.options['skill-a'], { params: [2] });
  assert.doesNotThrow(() => codec.canonicalToNative(mapped.desired));
  assert.throws(() => mapper.map(baseline, [{ type: 'skill.setRank', nodeId: 'unknown', rank: 1 }],
    CANONICAL_SCHEMA_VERSION), error => error.code === ERROR_CODES.ENTITY_NOT_FOUND);
  const malformed = structuredClone(baseline);
  delete malformed.skills;
  assert.throws(() => mapper.map(malformed,
    [{ type: 'skill.setRank', nodeId: '10', rank: 1 }], CANONICAL_SCHEMA_VERSION),
  error => error.code === ERROR_CODES.CANONICAL_BUILD_INVALID);
});
