'use strict';

const { FileSystemSnapshotStore } = require('@streamops/browser-infrastructure');
const { ERROR_CODES, MaxrollProviderError } = require('./errors');
const { immutable, sha256 } = require('./value');

const CANONICAL_SCHEMA_VERSION = 'd4-build/v1alpha1';
const CODEC_VERSION = 'maxroll-native/3.2.1.73552-D12aM6KT-b0';
const DATA_URL_PATTERN = /\/d4-tools\/game\/data\.min\.json(?:[?#].*)?$/;
const EXPORT_SCHEMA_VERSION = 'maxroll-native-build-export/v1';
const KNOWN_STATE_FIELDS = new Set([
  'activeEmbed', 'activeProfile', 'embeds', 'globalNotes', 'items', 'lootFilters', 'options',
  'pinnedStats', 'profiles', 'season', 'strAndWeak',
]);
const KNOWN_PROFILE_FIELDS = new Set([
  'class', 'elixirs', 'hidden', 'items', 'level', 'mercenary', 'name', 'paragon',
  'rotations', 'skillBar', 'skillTree', 'specialization', 'warPlans', 'widgetNotes',
  'world', 'worldTier',
]);
const KNOWN_ITEM_FIELDS = new Set([
  'aspects', 'explicits', 'id', 'mythic', 'name', 'power', 'sockets', 'tempered', 'upgrade',
]);
const KNOWN_MODIFIER_FIELDS = new Set([
  'greater', 'hidden', 'nid', 'uniquePriority', 'upgrade', 'values',
]);
const CANONICAL_ITEM_FIELDS = new Set([
  'affixes', 'aspects', 'baseItemId', 'customName', 'itemPower', 'mythic', 'sockets',
  'tempers', 'upgradeRank',
]);
const CANONICAL_MODIFIER_FIELDS = new Set([
  'entityId', 'greater', 'hidden', 'uniquePriority', 'upgradeRank', 'values',
]);

function fail(code, message, details) {
  throw new MaxrollProviderError(code, message, { details });
}

function clone(value) {
  return value === undefined ? undefined : structuredClone(value);
}

function assertPlain(value, name) {
  if (!value || typeof value !== 'object' || Array.isArray(value)
      || Object.getPrototypeOf(value) !== Object.prototype) {
    fail(ERROR_CODES.CANONICAL_BUILD_INVALID, `${name} must be a plain object`);
  }
}

function rejectUnknown(value, allowed, name) {
  const unknown = Object.keys(value).filter(key => !allowed.has(key));
  if (unknown.length) fail(ERROR_CODES.CANONICAL_MAPPING_INCOMPLETE,
    `${name} contains unmapped fields`, { path: name, fields: unknown.sort() });
}

function sortedEntries(value) {
  return Object.entries(value).sort(([left], [right]) => left.localeCompare(right,
    undefined, { numeric: true }));
}

function catalogIds(collection) {
  const ids = new Set(Object.keys(collection ?? {}).map(String));
  const values = Array.isArray(collection) ? collection : Object.values(collection ?? {});
  for (const entry of values) if (entry?.id != null) ids.add(String(entry.id));
  return ids;
}

function catalogById(collection) {
  const output = new Map();
  for (const [key, entry] of Object.entries(collection ?? {})) {
    output.set(String(key), entry);
    if (entry?.id != null) output.set(String(entry.id), entry);
  }
  return output;
}

class MaxrollEntityCatalog {
  #data;
  #ids;
  #byId;

  constructor(data, provenance = {}) {
    assertPlain(data, 'catalog');
    for (const family of [
      'affixes', 'classes', 'items', 'mercenaries', 'paragonBoards', 'paragonGlyphs',
      'skills', 'skillTrees', 'stones',
    ]) {
      if (!data[family] || typeof data[family] !== 'object') {
        fail(ERROR_CODES.CANONICAL_MAPPING_INCOMPLETE,
          `catalog family is missing: ${family}`, { family });
      }
    }
    this.#data = data;
    this.#ids = Object.fromEntries(Object.keys(data)
      .filter(key => data[key] && typeof data[key] === 'object')
      .map(key => [key, catalogIds(data[key])]));
    this.#byId = Object.fromEntries(Object.keys(this.#ids)
      .map(key => [key, catalogById(data[key])]));
    this.provenance = immutable(provenance);
    this.counts = immutable(Object.fromEntries(Object.entries(data)
      .filter(([, value]) => value && typeof value === 'object')
      .map(([key, value]) => [key, Array.isArray(value) ? value.length : Object.keys(value).length])));
  }

  require(family, id, path) {
    if (!this.#ids[family]?.has(String(id))) {
      fail(ERROR_CODES.ENTITY_NOT_FOUND, `entity is absent from pinned catalog: ${path}`, {
        family, id: String(id), path,
      });
    }
    return this.#byId[family].get(String(id));
  }

  requireAffix(id, path) {
    if (this.#ids.affixes.has(String(id)) || this.#ids.oldAffixes?.has(String(id))) return;
    fail(ERROR_CODES.ENTITY_NOT_FOUND, `modifier is absent from pinned catalog: ${path}`, {
      family: 'affixes', id: String(id), path,
    });
  }

  requireSocket(id, path) {
    if (this.#ids.items.has(String(id)) || this.#ids.stones.has(String(id))) return;
    fail(ERROR_CODES.ENTITY_NOT_FOUND, `socket entity is absent from pinned catalog: ${path}`, {
      family: 'items|stones', id: String(id), path,
    });
  }

  skillTreeForClass(classId) {
    const characterClass = this.require('classes', classId, 'character.classId');
    return this.require('skillTrees', characterClass.tree, 'skills.allocation');
  }

  board(id) { return this.require('paragonBoards', id, 'paragon.boards'); }
}

async function loadMaxrollEntityCatalog(options) {
  for (const name of ['snapshotRoot', 'snapshotId', 'expectedManifestSha256']) {
    if (typeof options?.[name] !== 'string' || !options[name]) {
      fail(ERROR_CODES.INVALID_INPUT, `${name} is required`);
    }
  }
  const store = options.store ?? new FileSystemSnapshotStore({ rootDir: options.snapshotRoot });
  const verified = await store.verify(options.snapshotId);
  if (verified.manifestSha256 !== options.expectedManifestSha256) {
    fail(ERROR_CODES.SNAPSHOT_MISMATCH, 'catalog snapshot manifest does not match trust anchor', {
      expected: options.expectedManifestSha256, actual: verified.manifestSha256,
    });
  }
  const snapshotPackage = await store.loadPackage(options.snapshotId);
  const candidates = snapshotPackage.manifest.resources.filter(resource =>
    DATA_URL_PATTERN.test(resource.url));
  if (candidates.length !== 1) fail(ERROR_CODES.CANONICAL_MAPPING_INCOMPLETE,
    'snapshot must contain exactly one versioned game data catalog', {
      observed: candidates.length,
    });
  const resource = candidates[0];
  const body = snapshotPackage.resources.get(resource.key)?.body;
  if (!body || sha256(body) !== resource.sha256) {
    fail(ERROR_CODES.SNAPSHOT_MISMATCH, 'game data catalog bytes failed integrity validation');
  }
  let data;
  try { data = JSON.parse(body.toString('utf8')); } catch (cause) {
    throw new MaxrollProviderError(ERROR_CODES.CANONICAL_MAPPING_INCOMPLETE,
      'game data catalog is invalid JSON', { cause });
  }
  return new MaxrollEntityCatalog(data, {
    snapshotId: options.snapshotId,
    snapshotManifestSha256: verified.manifestSha256,
    resourceUrl: resource.url,
    resourceSha256: resource.sha256,
    gameDataVersion: data.version ?? null,
  });
}

class MaxrollD12CanonicalCodec {
  #catalog;

  constructor({ catalog }) {
    if (!(catalog instanceof MaxrollEntityCatalog)) {
      fail(ERROR_CODES.INVALID_CONFIG, 'MaxrollEntityCatalog is required');
    }
    this.#catalog = catalog;
  }

  nativeToCanonical(fixture) {
    if (fixture?.schemaVersion !== EXPORT_SCHEMA_VERSION || fixture.format !== 'MAXROLL_NATIVE_STATE') {
      fail(ERROR_CODES.NATIVE_BUILD_INVALID, 'input is not a Maxroll native build export');
    }
    const state = fixture.nativeState;
    const index = fixture.selection?.profileIndex;
    const profile = state?.profiles?.[index];
    if (!profile || !state.items) fail(ERROR_CODES.NATIVE_BUILD_INVALID,
      'native build has no selected profile or item registry');
    rejectUnknown(state, KNOWN_STATE_FIELDS, 'native.state');
    rejectUnknown(profile, KNOWN_PROFILE_FIELDS, 'native.profile');
    this.#catalog.require('classes', profile.class, 'character.classId');

    const slots = sortedEntries(profile.items).filter(([, reference]) => Boolean(reference))
      .map(([slotId, reference]) => {
        const item = state.items[String(reference)];
        if (!item) fail(ERROR_CODES.NATIVE_BUILD_INVALID,
          `equipment slot ${slotId} references missing item ${reference}`);
        return { slotId, item: this.#decodeItem(item, `equipment.slots.${slotId}`) };
      });
    const skillStep = activeStep(profile.skillTree, 'skills');
    const paragonStep = activeStep(profile.paragon, 'paragon');
    const tree = this.#catalog.skillTreeForClass(profile.class);
    const treeNodes = new Set((tree.nodes ?? []).map(node => String(node.id)));
    const allocations = sortedEntries(skillStep.data).map(([nodeId, rank]) => {
      if (!treeNodes.has(String(nodeId))) fail(ERROR_CODES.ENTITY_NOT_FOUND,
        `skill node is absent from class tree: ${nodeId}`);
      return { nodeId: String(nodeId), rank };
    });
    for (const [position, skillId] of profile.skillBar.entries()) {
      if (skillId) this.#catalog.require('skills', skillId, `skills.bar.${position}`);
    }
    const boards = (paragonStep.data ?? []).map((board, boardIndex) =>
      this.#decodeBoard(board, boardIndex));

    const effects = {
      elixirs: clone(profile.elixirs ?? []),
      warPlans: clone(profile.warPlans ?? []),
    };
    if (profile.specialization !== undefined) effects.specialization = clone(profile.specialization);
    if (profile.mercenary !== undefined) effects.mercenary = this.#decodeMercenary(profile.mercenary);

    return immutable({
      schemaVersion: CANONICAL_SCHEMA_VERSION,
      game: { id: 'diablo-iv', patch: fixture.provenance?.runtimeVersion ?? null },
      character: {
        classId: String(profile.class), level: profile.level, worldTier: profile.worldTier,
      },
      equipment: { slots },
      skills: { allocations, bar: clone(profile.skillBar) },
      paragon: { boards },
      effects,
      world: clone(profile.world ?? {}),
      calculationContext: {
        season: state.season ?? null,
        options: clone(state.options ?? {}),
      },
      provenance: {
        codecVersion: CODEC_VERSION,
        sourceNativeStateSha256: fixture.integrity?.nativeStateSha256 ?? null,
        catalog: clone(this.#catalog.provenance),
      },
    });
  }

  canonicalToNative(build) {
    this.#validateCanonical(build);
    const itemRegistry = {};
    const itemSlots = {};
    let nextReference = 1;
    for (const slot of [...build.equipment.slots]
      .sort((left, right) => left.slotId.localeCompare(right.slotId, undefined, { numeric: true }))) {
      const reference = nextReference++;
      itemSlots[slot.slotId] = reference;
      itemRegistry[String(reference)] = this.#encodeItem(slot.item, `equipment.slots.${slot.slotId}`);
    }
    const profile = {
      name: 'Canonical Import', hidden: false,
      class: numericId(build.character.classId),
      level: build.character.level,
      worldTier: build.character.worldTier,
      items: itemSlots,
      elixirs: clone(build.effects.elixirs),
      skillTree: { position: 0, steps: [{ name: 'Imported', data: Object.fromEntries(
        build.skills.allocations.map(entry => [entry.nodeId, entry.rank])) }] },
      skillBar: clone(build.skills.bar),
      paragon: { position: 0, steps: [{ name: 'Imported', data: build.paragon.boards
        .map(board => this.#encodeBoard(board)) }] },
      rotations: [],
      warPlans: clone(build.effects.warPlans),
      world: clone(build.world),
      widgetNotes: emptyWidgetNotes(),
    };
    if (Object.hasOwn(build.effects, 'specialization')) {
      profile.specialization = clone(build.effects.specialization);
    }
    if (Object.hasOwn(build.effects, 'mercenary')) {
      profile.mercenary = this.#encodeMercenary(build.effects.mercenary);
    }
    return immutable({
      activeEmbed: -1,
      activeProfile: 0,
      embeds: [],
      globalNotes: emptyGlobalNotes(),
      items: itemRegistry,
      lootFilters: [],
      options: clone(build.calculationContext.options),
      pinnedStats: {},
      profiles: [profile],
      season: build.calculationContext.season,
      strAndWeak: { strengths: [], weaknesses: [] },
    });
  }

  #decodeItem(item, path) {
    assertPlain(item, path);
    rejectUnknown(item, KNOWN_ITEM_FIELDS, path);
    this.#catalog.require('items', item.id, `${path}.baseItemId`);
    const output = {
      baseItemId: String(item.id),
      itemPower: item.power,
      affixes: this.#decodeModifiers(item.explicits ?? [], `${path}.affixes`),
      aspects: this.#decodeModifiers(item.aspects ?? [], `${path}.aspects`),
      tempers: this.#decodeModifiers(item.tempered ?? [], `${path}.tempers`),
      sockets: (item.sockets ?? []).map((entityId, index) => {
        this.#catalog.requireSocket(entityId, `${path}.sockets.${index}`);
        return { entityId: String(entityId) };
      }),
    };
    if (item.name !== undefined) output.customName = item.name;
    if (item.upgrade !== undefined) output.upgradeRank = item.upgrade;
    if (item.mythic !== undefined) output.mythic = item.mythic;
    return output;
  }

  #encodeItem(item, path) {
    this.#catalog.require('items', item.baseItemId, `${path}.baseItemId`);
    const output = {
      id: String(item.baseItemId),
      power: item.itemPower,
      explicits: this.#encodeModifiers(item.affixes, `${path}.affixes`),
    };
    if (item.aspects.length) output.aspects = this.#encodeModifiers(item.aspects, `${path}.aspects`);
    if (item.tempers.length) output.tempered = this.#encodeModifiers(item.tempers, `${path}.tempers`);
    if (item.sockets.length) output.sockets = item.sockets.map((socket, index) => {
      this.#catalog.requireSocket(socket.entityId, `${path}.sockets.${index}`);
      return String(socket.entityId);
    });
    if (item.customName !== undefined) output.name = item.customName;
    if (item.upgradeRank !== undefined) output.upgrade = item.upgradeRank;
    if (item.mythic !== undefined) output.mythic = item.mythic;
    return output;
  }

  #decodeModifiers(modifiers, path) {
    if (!Array.isArray(modifiers)) fail(ERROR_CODES.CANONICAL_BUILD_INVALID,
      `${path} must be an array`);
    return modifiers.map((modifier, index) => {
      assertPlain(modifier, `${path}.${index}`);
      rejectUnknown(modifier, KNOWN_MODIFIER_FIELDS, `${path}.${index}`);
      this.#catalog.requireAffix(modifier.nid, `${path}.${index}.entityId`);
      const result = { entityId: String(modifier.nid), values: clone(modifier.values ?? []) };
      for (const [native, canonical] of [
        ['greater', 'greater'], ['hidden', 'hidden'], ['uniquePriority', 'uniquePriority'],
        ['upgrade', 'upgradeRank'],
      ]) if (modifier[native] !== undefined) result[canonical] = modifier[native];
      return result;
    });
  }

  #encodeModifiers(modifiers, path) {
    return modifiers.map((modifier, index) => {
      this.#catalog.requireAffix(modifier.entityId, `${path}.${index}.entityId`);
      const result = { nid: numericId(modifier.entityId), values: clone(modifier.values) };
      for (const [canonical, native] of [
        ['greater', 'greater'], ['hidden', 'hidden'], ['uniquePriority', 'uniquePriority'],
        ['upgradeRank', 'upgrade'],
      ]) if (modifier[canonical] !== undefined) result[native] = modifier[canonical];
      return result;
    });
  }

  #decodeBoard(board, index) {
    assertPlain(board, `paragon.boards.${index}`);
    const catalogBoard = this.#catalog.board(board.id);
    const allocations = sortedEntries(board.nodes ?? {}).map(([nodeId, value]) => {
      if (catalogBoard.nodes?.[Number(nodeId)] == null) fail(ERROR_CODES.ENTITY_NOT_FOUND,
        `Paragon node is absent from board ${board.id}: ${nodeId}`);
      return { nodeId: String(nodeId), value };
    });
    const result = {
      boardId: String(board.id), rotation: board.rotation ?? 0,
      allocations,
    };
    if (board.position !== undefined) result.position = clone(board.position);
    if (board.glyph) {
      this.#catalog.require('paragonGlyphs', board.glyph, `paragon.boards.${index}.glyphId`);
      result.glyph = { glyphId: String(board.glyph), level: board.glyphLevel };
    }
    return result;
  }

  #encodeBoard(board) {
    const catalogBoard = this.#catalog.board(board.boardId);
    const output = {
      id: String(board.boardId), rotation: board.rotation,
      nodes: Object.fromEntries(board.allocations.map(entry => {
        if (catalogBoard.nodes?.[Number(entry.nodeId)] == null) fail(ERROR_CODES.ENTITY_NOT_FOUND,
          `Paragon node is absent from board ${board.boardId}: ${entry.nodeId}`);
        return [entry.nodeId, entry.value];
      })),
    };
    if (board.position !== undefined) output.position = clone(board.position);
    if (board.glyph) {
      this.#catalog.require('paragonGlyphs', board.glyph.glyphId, 'paragon.glyph');
      output.glyph = String(board.glyph.glyphId);
      output.glyphLevel = board.glyph.level;
    }
    return output;
  }

  #decodeMercenary(mercenary) {
    this.#catalog.require('mercenaries', mercenary.id, 'effects.mercenary.id');
    return {
      id: String(mercenary.id), support: clone(mercenary.support),
      supportSkills: clone(mercenary.supportSkills ?? []),
      treeAllocations: sortedEntries(mercenary.tree ?? {})
        .map(([nodeId, value]) => ({ nodeId, value })),
    };
  }

  #encodeMercenary(mercenary) {
    this.#catalog.require('mercenaries', mercenary.id, 'effects.mercenary.id');
    return {
      id: String(mercenary.id), support: clone(mercenary.support),
      supportSkills: clone(mercenary.supportSkills),
      tree: Object.fromEntries(mercenary.treeAllocations.map(entry => [entry.nodeId, entry.value])),
    };
  }

  #validateCanonical(build) {
    assertPlain(build, 'build');
    rejectUnknown(build, new Set([
      'schemaVersion', 'game', 'character', 'equipment', 'skills', 'paragon', 'effects',
      'world', 'calculationContext', 'provenance',
    ]), 'build');
    if (build.schemaVersion !== CANONICAL_SCHEMA_VERSION || build.game?.id !== 'diablo-iv') {
      fail(ERROR_CODES.CANONICAL_BUILD_INVALID, 'unsupported canonical build schema or game');
    }
    for (const name of ['character', 'equipment', 'skills', 'paragon', 'effects',
      'world', 'calculationContext']) assertPlain(build[name], name);
    rejectUnknown(build.game, new Set(['id', 'patch']), 'game');
    rejectUnknown(build.character, new Set(['classId', 'level', 'worldTier']), 'character');
    rejectUnknown(build.equipment, new Set(['slots']), 'equipment');
    rejectUnknown(build.skills, new Set(['allocations', 'bar']), 'skills');
    rejectUnknown(build.paragon, new Set(['boards']), 'paragon');
    rejectUnknown(build.effects,
      new Set(['elixirs', 'warPlans', 'specialization', 'mercenary']), 'effects');
    rejectUnknown(build.calculationContext, new Set(['season', 'options']), 'calculationContext');
    this.#catalog.require('classes', build.character.classId, 'character.classId');
    if (!Number.isFinite(build.character.level) || !Number.isFinite(build.character.worldTier)
        || !Array.isArray(build.equipment.slots) || !Array.isArray(build.skills.allocations)
        || !Array.isArray(build.skills.bar) || !Array.isArray(build.paragon.boards)
        || !Array.isArray(build.effects.elixirs) || !Array.isArray(build.effects.warPlans)) {
      fail(ERROR_CODES.CANONICAL_BUILD_INVALID, 'canonical build section shape is invalid');
    }
    const slots = new Set();
    for (const slot of build.equipment.slots) {
      if (typeof slot?.slotId !== 'string' || !slot.slotId || slots.has(slot.slotId)) {
        fail(ERROR_CODES.CANONICAL_BUILD_INVALID, 'equipment slot IDs must be unique strings');
      }
      slots.add(slot.slotId);
      assertPlain(slot.item, `equipment.slots.${slot.slotId}.item`);
      rejectUnknown(slot.item, CANONICAL_ITEM_FIELDS,
        `equipment.slots.${slot.slotId}.item`);
      for (const field of ['affixes', 'aspects', 'tempers', 'sockets']) {
        if (!Array.isArray(slot.item[field])) fail(ERROR_CODES.CANONICAL_BUILD_INVALID,
          `equipment.slots.${slot.slotId}.item.${field} must be an array`);
      }
      for (const field of ['affixes', 'aspects', 'tempers']) {
        slot.item[field].forEach((modifier, index) => {
          assertPlain(modifier, `equipment.slots.${slot.slotId}.item.${field}.${index}`);
          rejectUnknown(modifier, CANONICAL_MODIFIER_FIELDS,
            `equipment.slots.${slot.slotId}.item.${field}.${index}`);
          if (modifier.entityId == null || !Array.isArray(modifier.values)) {
            fail(ERROR_CODES.CANONICAL_BUILD_INVALID,
              `equipment.slots.${slot.slotId}.item.${field}.${index} is invalid`);
          }
        });
      }
      slot.item.sockets.forEach((socket, index) => {
        assertPlain(socket, `equipment.slots.${slot.slotId}.item.sockets.${index}`);
        rejectUnknown(socket, new Set(['entityId']),
          `equipment.slots.${slot.slotId}.item.sockets.${index}`);
        if (socket.entityId == null) fail(ERROR_CODES.CANONICAL_BUILD_INVALID,
          `equipment.slots.${slot.slotId}.item.sockets.${index}.entityId is required`);
      });
    }
    const tree = this.#catalog.skillTreeForClass(build.character.classId);
    const nodes = new Set((tree.nodes ?? []).map(node => String(node.id)));
    for (const entry of build.skills.allocations) if (!nodes.has(String(entry.nodeId))) {
      fail(ERROR_CODES.ENTITY_NOT_FOUND, `skill node is absent from class tree: ${entry.nodeId}`);
    }
    for (const [position, skillId] of build.skills.bar.entries()) {
      if (skillId) this.#catalog.require('skills', skillId, `skills.bar.${position}`);
    }
    for (const [index, board] of build.paragon.boards.entries()) {
      assertPlain(board, `paragon.boards.${index}`);
      rejectUnknown(board,
        new Set(['allocations', 'boardId', 'glyph', 'position', 'rotation']),
        `paragon.boards.${index}`);
      if (board.boardId == null || !Array.isArray(board.allocations)) {
        fail(ERROR_CODES.CANONICAL_BUILD_INVALID, `paragon.boards.${index} is invalid`);
      }
    }
    if (Object.hasOwn(build.effects, 'mercenary')) {
      assertPlain(build.effects.mercenary, 'effects.mercenary');
      rejectUnknown(build.effects.mercenary,
        new Set(['id', 'support', 'supportSkills', 'treeAllocations']),
        'effects.mercenary');
      if (!Array.isArray(build.effects.mercenary.supportSkills)
          || !Array.isArray(build.effects.mercenary.treeAllocations)) {
        fail(ERROR_CODES.CANONICAL_BUILD_INVALID, 'effects.mercenary has invalid arrays');
      }
    }
  }
}

function activeStep(section, name) {
  if (!section || !Number.isInteger(section.position) || !section.steps?.[section.position]
      || !section.steps[section.position].data) {
    fail(ERROR_CODES.CANONICAL_MAPPING_INCOMPLETE,
      `native ${name} section has no active data step`);
  }
  return section.steps[section.position];
}

function numericId(value) {
  const numeric = Number(value);
  return Number.isSafeInteger(numeric) && String(numeric) === String(value) ? numeric : value;
}

function emptyNote() {
  return { root: { children: [], direction: null, format: '', indent: 0, type: 'root', version: 1 } };
}

function emptyWidgetNotes() {
  return { equipment: emptyNote(), mercenary: emptyNote(), skills: emptyNote() };
}

function emptyGlobalNotes() {
  return { changelog: emptyNote(), faqs: emptyNote(), intro: emptyNote(), summary: emptyNote() };
}

module.exports = {
  CANONICAL_SCHEMA_VERSION,
  CODEC_VERSION,
  MaxrollD12CanonicalCodec,
  MaxrollEntityCatalog,
  loadMaxrollEntityCatalog,
};
