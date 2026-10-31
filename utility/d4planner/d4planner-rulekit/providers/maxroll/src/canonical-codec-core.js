'use strict';

const { FileSystemSnapshotStore } = require('@streamops/browser-infrastructure');
const { validateCanonicalSchema } = require('./canonical-schema-validator');
const { ERROR_CODES, MaxrollProviderError } = require('./errors');
const { immutable, sha256 } = require('./value');

function createCodecFamily(definition) {
const COMPATIBILITY=definition.identity;
const CODEC_VERSION=definition.codecVersion;
const SHARED_OPTIONS=definition.sharedOptions;
const OPTION_RULES=definition.optionRules;
const CANONICAL_SCHEMA_VERSION='d4-build/v1';
const DATA_URL_PATTERN = /\/d4-tools\/game\/data\.min\.json(?:[?#].*)?$/;
const EXPORT_SCHEMA_VERSION = 'maxroll-native-build-export/v1';
const KNOWN_STATE_FIELDS = new Set([
  'activeEmbed', 'activeProfile', 'buildGuide', 'embeds', 'globalNotes', 'items', 'lootFilters', 'options',
  'pinnedStats', 'profiles', 'season', 'strAndWeak',
]);
const KNOWN_PROFILE_FIELDS = new Set([
  'animalSpirits', 'arsenal', 'class', 'elixirs', 'enchants', 'expertise', 'hidden',
  'items', 'level', 'mercenary', 'minionSpec', 'minionUpgrades', 'name', 'oath',
  'paragon', 'rotations', 'skillBar', 'skillTree', 'specialization', 'spiritBoons',
  'technique', 'warlockFragment', 'warlockShard', 'warPlans', 'weaponSlot',
  'widgetNotes', 'world', 'worldTier',
]);
const CLASS_MECHANIC_FIELDS = Object.freeze({
  0: Object.freeze(['enchants']),
  1: Object.freeze(['spiritBoons']),
  2: Object.freeze(['arsenal', 'expertise', 'technique', 'weaponSlot']),
  3: Object.freeze(['specialization']),
  4: Object.freeze(['minionSpec', 'minionUpgrades']),
  5: Object.freeze(['animalSpirits']),
  6: Object.freeze(['oath']),
  7: Object.freeze(['warlockFragment', 'warlockShard']),
});
const ALL_CLASS_MECHANIC_FIELDS = Object.freeze(
  [...new Set(Object.values(CLASS_MECHANIC_FIELDS).flat())]);
const KNOWN_ITEM_FIELDS = new Set([
  'aspects', 'explicits', 'id', 'implicits', 'mythic', 'name', 'power', 'sockets', 'tempered', 'upgrade',
]);
const KNOWN_MODIFIER_FIELDS = new Set([
  'greater', 'hidden', 'nid', 'uniquePriority', 'upgrade', 'values',
]);
const CANONICAL_ITEM_FIELDS = new Set([
  'affixes', 'aspects', 'baseItemId', 'customName', 'implicits', 'itemPower', 'mythic', 'sockets',
  'tempers', 'upgradeRank',
]);
const CANONICAL_MODIFIER_FIELDS = new Set([
  'entityId', 'greater', 'hidden', 'uniquePriority', 'upgradeRank', 'values',
]);
const KNOWN_PARAGON_BOARD_FIELDS = new Set([
  'glyph', 'glyphLevel', 'id', 'nodes', 'position', 'rotation',
]);
const KNOWN_MERCENARY_FIELDS = new Set([
  'id', 'support', 'supportSkills', 'tree',
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
    `${name} contains unmapped fields: ${unknown.sort().join(', ')}`,
    { path: name, fields: unknown.sort() });
}

function sortedEntries(value) {
  return Object.entries(value).sort(([left], [right]) => left.localeCompare(right,
    undefined, { numeric: true }));
}

function catalogIds(collection) {
  const ids = new Set(Object.keys(collection ?? {}).map(String));
  const values = Array.isArray(collection) ? collection : Object.values(collection ?? {});
  for (const entry of values) {
    if (entry?.id != null) ids.add(String(entry.id));
    else if (entry == null || ['string', 'number'].includes(typeof entry)) ids.add(String(entry));
  }
  return ids;
}

function catalogById(collection) {
  const output = new Map();
  for (const [key, entry] of Object.entries(collection ?? {})) {
    output.set(String(key), entry);
    if (entry?.id != null) output.set(String(entry.id), entry);
    else if (entry == null || ['string', 'number'].includes(typeof entry)) {
      output.set(String(entry), entry);
    }
  }
  return output;
}

class MaxrollEntityCatalog {
  #data;
  #ids;
  #byId;

  constructor(data, provenance = {}, runtimeDefinitions = {}) {
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
    this.runtimeDefinitions = immutable(runtimeDefinitions);
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

  classIndex(classId) {
    const numeric = Number(classId);
    if (!Number.isInteger(numeric) || numeric < 0 || numeric > 7) {
      fail(ERROR_CODES.ENTITY_NOT_FOUND, `invalid class identity: ${classId}`, { classId });
    }
    this.require('classes', classId, 'character.classId');
    return numeric;
  }

  className(classId) {
    const entry = this.require('classes', classId, 'character.classId');
    if (typeof entry.name !== 'string' || !entry.name) {
      fail(ERROR_CODES.CANONICAL_MAPPING_INCOMPLETE,
        `class ${classId} has no stable catalog name`);
    }
    return entry.name;
  }

  requireClassCompatible(family, id, classId, path) {
    const entity = this.require(family, id, path);
    const index = this.classIndex(classId);
    if (Array.isArray(entity?.classFilter) && index < entity.classFilter.length
        && entity.classFilter[index] !== true) {
      fail(ERROR_CODES.ILLEGAL_COMBINATION, `${path} is not legal for class ${classId}`, {
        family, id: String(id), classId: String(classId), path,
      });
    }
    return entity;
  }

  requireItemForSlot(itemId, slotId, classId, path) {
    if (!Object.hasOwn(this.#data.items, String(itemId))) {
      fail(ERROR_CODES.ENTITY_NOT_FOUND, `${path} is not a stable native item ID`, {
        family: 'items', id: String(itemId), path,
      });
    }
    const item = this.requireClassCompatible('items', itemId, classId, path);
    const type = this.require('itemTypes', item.type, `${path}.type`);
    if (!Array.isArray(type.bodySlots) || !type.bodySlots.includes(Number(slotId))) {
      fail(ERROR_CODES.ILLEGAL_COMBINATION, `${path} cannot be equipped in slot ${slotId}`, {
        itemId: String(itemId), itemType: item.type, slotId: String(slotId),
      });
    }
    return { item, type };
  }

  requireModifierForItem(id, classId, path) {
    const entity = this.#byId.affixes.get(String(id)) ?? this.#byId.oldAffixes?.get(String(id));
    if (!entity) {
      this.requireAffix(id, path);
      return;
    }
    const index = this.classIndex(classId);
    if (Array.isArray(entity.classFilter) && index < entity.classFilter.length
        && entity.classFilter[index] !== true) {
      fail(ERROR_CODES.ILLEGAL_COMBINATION, `${path} is not legal for class ${classId}`);
    }
    // itemLabels are an acquisition/picker taxonomy, not a complete legality relation:
    // pinned Unique items contain valid native affixes whose labels intentionally do not
    // intersect their base item type. Treat them as coverage metadata, never as authority.
  }

  requireSocket(id, path) {
    if (this.#ids.items.has(String(id)) || this.#ids.stones.has(String(id))) return;
    fail(ERROR_CODES.ENTITY_NOT_FOUND, `socket entity is absent from pinned catalog: ${path}`, {
      family: 'items|stones', id: String(id), path,
    });
  }

  requireCalculationOption(id, classId, path) {
    if (id === 'shared') return;
    const families = ['skills', 'items', 'affixes', 'oldAffixes', 'paragonGlyphs',
      'paragonNodes', 'stones'];
    const candidate = families.map(family => this.#byId[family]?.get(String(id))).find(Boolean);
    if (!candidate) fail(ERROR_CODES.ENTITY_NOT_FOUND,
      `calculation option has no pinned entity: ${id}`, { id: String(id), path });
    const index = this.classIndex(classId);
    if (candidate.class != null && Number(candidate.class) !== index
        || Array.isArray(candidate.classFilter) && index < candidate.classFilter.length
          && candidate.classFilter[index] !== true) {
      fail(ERROR_CODES.ILLEGAL_COMBINATION, `${path} is not legal for class ${classId}`);
    }
  }

  has(family, id) { return this.#ids[family]?.has(String(id)) ?? false; }

  requireMercenaryTreeNode(mercenaryId, nodeId, path) {
    const mercenary = this.require('mercenaries', mercenaryId, 'effects.mercenary.id');
    const tree = this.require('skillTrees', mercenary.tree, 'effects.mercenary.tree');
    if (!(tree.nodes ?? []).some(node => String(node.id) === String(nodeId))) {
      fail(ERROR_CODES.ENTITY_NOT_FOUND, `mercenary tree node is absent: ${nodeId}`, { path });
    }
  }

  requireWarPlanNode(index, nodeId, path) {
    const plan = this.#data.warPlans?.[index];
    if (!plan) fail(ERROR_CODES.ILLEGAL_COMBINATION, `war plan index is invalid: ${index}`);
    const tree = this.require('skillTrees', plan.tree, `effects.warPlans.${index}`);
    if (!(tree.nodes ?? []).some(node => String(node.id) === String(nodeId))) {
      fail(ERROR_CODES.ENTITY_NOT_FOUND, `war plan tree node is absent: ${nodeId}`, { path });
    }
  }

  skillTreeForClass(classId) {
    const characterClass = this.require('classes', classId, 'character.classId');
    return this.require('skillTrees', characterClass.tree, 'skills.allocation');
  }

  requireSkillForClass(skillId, classId, path) {
    const skill = this.require('skills', skillId, path);
    if (skill.class != null && Number(skill.class) !== this.classIndex(classId)) {
      fail(ERROR_CODES.ILLEGAL_COMBINATION, `${path} is not legal for class ${classId}`);
    }
    return skill;
  }

  requireBoardForClass(boardId, classId, path) {
    const characterClass = this.require('classes', classId, 'character.classId');
    if (!characterClass.paragonBoards?.map(String).includes(String(boardId))) {
      fail(ERROR_CODES.ILLEGAL_COMBINATION, `${path} is not legal for class ${classId}`);
    }
    return this.require('paragonBoards', boardId, path);
  }

  requireGlyphForClass(glyphId, classId, path) {
    return this.requireClassCompatible('paragonGlyphs', glyphId, classId, path);
  }

  coverageInventory() {
    const families = [
      'classes', 'items', 'itemTypes', 'affixes', 'oldAffixes', 'skills', 'skillTrees',
      'paragonBoards', 'paragonGlyphs', 'paragonNodes', 'stones', 'mercenaries',
      'warPlans', 'temperingRecipes', 'itemSets', 'attributes',
    ];
    const present = families.filter(family => Number.isInteger(this.counts[family]));
    return immutable({
      families: Object.fromEntries(families.map(family => [family, this.counts[family] ?? 0])),
      present: present.length,
      total: families.length,
      percent: Number(((present.length / families.length) * 100).toFixed(2)),
    });
  }

  auditCoverage() {
    const classes = Object.values(this.#data.classes);
    const classBoardIds = new Set(classes.flatMap(entry => entry.paragonBoards ?? []).map(String));
    const equipmentItems = Object.values(this.#data.items).filter(item => {
      const type = this.#byId.itemTypes?.get(String(item.type));
      return Array.isArray(type?.bodySlots) && type.bodySlots.length > 0;
    });
    const classSkills = Object.values(this.#data.skills)
      .filter(skill => Number.isInteger(skill?.class) && skill.class >= 0 && skill.class <= 7);
    const glyphs = Object.values(this.#data.paragonGlyphs);
    const mercenaries = Object.values(this.#data.mercenaries);
    const warPlans = Object.values(this.#data.warPlans);
    const ratio = (numerator, denominator, status = 'PRESENT') => Object.freeze({
      numerator, denominator,
      percent: denominator ? Number(((numerator / denominator) * 100).toFixed(2)) : null,
      status,
    });
    return immutable({
      schemaVersion: 'maxroll-catalog-coverage/v1',
      identity: clone(this.provenance),
      families: {
        classes: ratio(classes.filter(entry => this.#byId.skillTrees.has(String(entry.tree))
          && entry.paragonBoards?.every(id => this.#ids.paragonBoards.has(String(id)))).length,
        classes.length),
        equippableItems: ratio(equipmentItems.filter(item => Array.isArray(item.classFilter)
          && item.classFilter.length === 8 && item.classFilter.some(Boolean)).length,
        equipmentItems.length),
        affixIdentity: ratio(this.counts.affixes, this.counts.affixes),
        affixItemLegality: ratio(this.counts.affixes, this.counts.affixes,
          'DELEGATED_TO_EXACT_NATIVE_READBACK'),
        classSkills: ratio(classSkills.filter(skill => this.#ids.classes.has(String(skill.class))).length,
          classSkills.length),
        paragonBoards: ratio(classBoardIds.size, this.counts.paragonBoards),
        paragonGlyphs: ratio(glyphs.filter(glyph => Array.isArray(glyph.classFilter)
          && glyph.classFilter.length === 8 && glyph.classFilter.some(Boolean)).length,
        glyphs.length),
        stones: ratio(this.counts.stones, this.counts.stones, 'IDENTITY_ONLY'),
        mercenaries: ratio(mercenaries.filter(entry => this.#ids.skillTrees.has(String(entry.tree))).length,
          mercenaries.length),
        warPlans: ratio(warPlans.filter(entry => this.#ids.skillTrees.has(String(entry.tree))).length,
          warPlans.length),
        specializationTaxonomy: ratio(classSkills.length, classSkills.length,
          'RESOLVED_THROUGH_CLASS_SKILL_CATALOG'),
        conditionalOptions: ratio(0, 0, 'RUNTIME_APPLICABILITY_ENUMERATION'),
      },
    });
  }

  metricCatalog(classId = null) {
    const classIndex = classId == null ? null : this.classIndex(classId);
    const definitions = classIndex == null
      ? Object.values(this.#data.heroDetails).flat()
      : this.#data.heroDetails?.[classIndex] ?? [];
    const byId = new Map();
    for (const definition of definitions) {
      if (!Number.isInteger(definition?.id)) continue;
      if (classIndex != null && Array.isArray(definition.classFilter)
          && definition.classFilter[classIndex] !== true) continue;
      const label = definition.values?.find(value => typeof value?.value === 'string')?.value;
      if (!byId.has(definition.id)) byId.set(definition.id, Object.freeze({
        id: `maxroll.heroDetails.${definition.id}`,
        internalId: definition.id,
        category: 'runtime',
        name: label || String(definition.id),
        rawValueType: 'finite-number',
      }));
    }
    return immutable([...byId.values()].sort((left, right) => left.internalId - right.internalId));
  }

  firstEquippable(classId) {
    const index = this.classIndex(classId);
    const candidates = Object.entries(this.#data.items).filter(([, item]) => {
      const type = this.#byId.itemTypes?.get(String(item.type));
      return item?.id != null && Array.isArray(item.classFilter) && item.classFilter[index] === true
        && Array.isArray(type?.bodySlots)
        && type.bodySlots.some(slot => Number(slot) >= 4 && Number(slot) <= 26);
    }).sort(([leftKey, left], [rightKey, right]) => {
      const leftComplexity = (left.affixes?.length ?? 0) + (left.implicits?.length ?? 0);
      const rightComplexity = (right.affixes?.length ?? 0) + (right.implicits?.length ?? 0);
      return leftComplexity - rightComplexity || leftKey.localeCompare(rightKey);
    });
    if (!candidates.length) fail(ERROR_CODES.ENTITY_NOT_FOUND,
      `pinned catalog has no equippable item for class ${classId}`);
    const [itemId, item] = candidates[0];
    const type = this.require('itemTypes', item.type, 'catalog.firstEquippable.type');
    return immutable({ itemId,
      slotId: String(type.bodySlots.find(slot => Number(slot) >= 4 && Number(slot) <= 26)) });
  }

  starterParagonBoard(classId) {
    const characterClass = this.require('classes', classId, 'character.classId');
    const boardId = characterClass.paragonBoards?.[0];
    if (boardId == null) fail(ERROR_CODES.ENTITY_NOT_FOUND,
      `pinned catalog has no starter Paragon board for class ${classId}`);
    this.require('paragonBoards', boardId, 'paragon.boards.0.boardId');
    return String(boardId);
  }

  board(id) { return this.require('paragonBoards', id, 'paragon.boards'); }

  optionReadbackDefinitions() {
    return immutable(clone(this.runtimeDefinitions.calculationOptions ?? {}));
  }

  canonicalCalculationOptions(options) {
    const output = clone(options ?? {});
    for (const [optionId, option] of Object.entries(output)) {
      const definition = this.runtimeDefinitions.calculationOptions?.[optionId];
      for (const field of definition?.ignoredNativeFields ?? []) delete option[field];
      for (const [index, rule] of Object.entries(
        definition?.nativeParamCanonicalization ?? {})) {
        if (rule.kind === 'clamp-max' && Number.isFinite(option.params?.[index])) {
          option.params[index] = Math.min(option.params[index], rule.max);
        }
      }
      if (Object.keys(option).length === 0) delete output[optionId];
    }
    return immutable(output);
  }
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
  const engineResource = snapshotPackage.manifest.resources.find(entry =>
    entry.sha256 === COMPATIBILITY.engineAssetSha256);
  const engineBody = engineResource
    ? snapshotPackage.resources.get(engineResource.key)?.body : null;
  if (!engineBody || sha256(engineBody) !== COMPATIBILITY.engineAssetSha256) {
    fail(ERROR_CODES.SNAPSHOT_MISMATCH,
      'pinned calculation engine bytes are unavailable for option authority');
  }
  const calculationOptions = {};
  const registration = /\.register(?:Power|Skill)\)\("([^"]+)"/g;
  let match;
  const source = engineBody.toString('utf8');
  while ((match = registration.exec(source)) !== null) {
    calculationOptions[match[1]] = {
      applicability: { kind: 'pinned-engine-enumeration', registered: true,
        authority: `sha256:${COMPATIBILITY.engineAssetSha256}` },
      ...(OPTION_RULES[match[1]] ?? {}),
    };
  }
  for (const [family, entries] of Object.entries(data)) {
    if (!entries || typeof entries !== 'object') continue;
    for (const [key, entry] of Object.entries(entries)) {
      for (const id of [key, entry?.id].filter(value => value != null).map(String)) {
        calculationOptions[id] ??= {
          applicability: { kind: 'pinned-game-catalog-option', registered: true,
            family, authority: `sha256:${resource.sha256}` },
        };
      }
    }
  }
  for (const [optionId, rule] of Object.entries(OPTION_RULES)) {
    calculationOptions[optionId] = { ...(calculationOptions[optionId] ?? {}), ...rule };
  }
  if (Object.keys(calculationOptions).length === 0) fail(
    ERROR_CODES.CANONICAL_MAPPING_INCOMPLETE,
    'pinned calculation engine contains no registered option definitions');
  return new MaxrollEntityCatalog(data, {
    snapshotId: options.snapshotId,
    snapshotManifestSha256: verified.manifestSha256,
    resourceUrl: resource.url,
    resourceSha256: resource.sha256,
    gameDataVersion: data.version ?? null,
  }, { calculationOptions });
}

class BoundCanonicalCodec {
  #catalog;

  constructor({ catalog }) {
    if (!(catalog instanceof MaxrollEntityCatalog)) {
      fail(ERROR_CODES.INVALID_CONFIG, 'MaxrollEntityCatalog is required');
    }
    assertCatalogCompatibility(catalog.provenance);
    this.#catalog = catalog;
  }

  nativeToCanonical(fixture) {
    if (fixture?.schemaVersion !== EXPORT_SCHEMA_VERSION || fixture.format !== 'MAXROLL_NATIVE_STATE') {
      fail(ERROR_CODES.NATIVE_BUILD_INVALID, 'input is not a Maxroll native build export');
    }
    assertFixtureCompatibility(fixture.provenance);
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
    for (const field of CLASS_MECHANIC_FIELDS[profile.class] ?? []) {
      if (profile[field] !== undefined) effects[field] = clone(profile[field]);
    }
    if (profile.mercenary !== undefined) effects.mercenary = this.#decodeMercenary(profile.mercenary);

    const canonical = {
      schemaVersion: CANONICAL_SCHEMA_VERSION,
      game: { id: 'diablo-iv', patch: COMPATIBILITY.gamePatch },
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
          options: clone(this.#catalog.canonicalCalculationOptions(state.options ?? {})),
      },
      provenance: {
        codecVersion: CODEC_VERSION,
        sourceNativeStateSha256: fixture.integrity?.nativeStateSha256 ?? null,
        source: 'MAXROLL_NATIVE_EXPORT',
      },
    };
    this.#validateCanonical(canonical);
    return immutable(canonical);
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
      itemRegistry[String(reference)] = this.#encodeItem(slot.item,
        `equipment.slots.${slot.slotId}`, slot.slotId, build.character.classId);
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
        .map(board => this.#encodeBoard(board, build.character.classId)) }] },
      rotations: [],
      warPlans: clone(build.effects.warPlans),
      world: clone(build.world),
      widgetNotes: emptyWidgetNotes(),
    };
    for (const field of CLASS_MECHANIC_FIELDS[Number(build.character.classId)] ?? []) {
      if (Object.hasOwn(build.effects, field)) profile[field] = clone(build.effects[field]);
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

  loaderIdentity(build) {
    this.#validateCanonical(build);
    if (!Number.isInteger(build.calculationContext.season)) {
      fail(ERROR_CODES.CANONICAL_BUILD_INVALID,
        'calculationContext.season is required by the native loader');
    }
    return immutable({
      className: this.#catalog.className(build.character.classId),
      season: build.calculationContext.season,
    });
  }

  runtimeStateToCanonical(runtimeState, provenance) {
    assertPlain(runtimeState, 'runtimeState');
    assertPlain(runtimeState.profile, 'runtimeState.profile');
    assertPlain(runtimeState.items, 'runtimeState.items');
    assertPlain(runtimeState.options, 'runtimeState.options');
    const items = {};
    const references = {};
    let reference = 1;
    for (const [slotId, item] of sortedEntries(runtimeState.items)) {
      references[slotId] = reference;
      items[String(reference)] = clone(item);
      reference += 1;
    }
    const profile = clone(runtimeState.profile);
    delete profile.id;
    profile.items = references;
    const decoded = this.nativeToCanonical({
      schemaVersion: EXPORT_SCHEMA_VERSION,
      format: 'MAXROLL_NATIVE_STATE',
      provenance: {
        snapshotId: COMPATIBILITY.snapshotId,
        snapshotManifestSha256: COMPATIBILITY.snapshotManifestSha256,
        runtimeVersion: COMPATIBILITY.gamePatch,
        runtimeAssetSha256: COMPATIBILITY.engineAssetSha256,
      },
      selection: { profileIndex: 0 },
      integrity: { nativeStateSha256: null },
      nativeState: {
        activeProfile: 0, profiles: [profile], items,
        options: clone(runtimeState.options), season: runtimeState.season,
      },
    });
    const observed = structuredClone(decoded);
    if (provenance === undefined) delete observed.provenance;
    else observed.provenance = clone(provenance);
    this.#validateCanonical(observed);
    return immutable(observed);
  }

  #decodeItem(item, path) {
    assertPlain(item, path);
    rejectUnknown(item, KNOWN_ITEM_FIELDS, path);
    this.#catalog.require('items', item.id, `${path}.baseItemId`);
    const output = {
      baseItemId: String(item.id),
      itemPower: item.power,
      affixes: this.#decodeModifiers(item.explicits ?? [], `${path}.affixes`),
      implicits: this.#decodeModifiers(item.implicits ?? [], `${path}.implicits`),
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

  #encodeItem(item, path, slotId, classId) {
    this.#catalog.requireItemForSlot(item.baseItemId, slotId, classId,
      `${path}.baseItemId`);
    const output = {
      id: String(item.baseItemId),
      power: item.itemPower,
      explicits: this.#encodeModifiers(item.affixes, `${path}.affixes`, classId),
    };
    if (item.implicits.length) output.implicits = this.#encodeModifiers(item.implicits,
      `${path}.implicits`, classId);
    if (item.aspects.length) output.aspects = this.#encodeModifiers(item.aspects,
      `${path}.aspects`, classId);
    if (item.tempers.length) output.tempered = this.#encodeModifiers(item.tempers,
      `${path}.tempers`, classId);
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

  #encodeModifiers(modifiers, path, classId) {
    return modifiers.map((modifier, index) => {
      this.#catalog.requireModifierForItem(modifier.entityId, classId,
        `${path}.${index}.entityId`);
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
    rejectUnknown(board, KNOWN_PARAGON_BOARD_FIELDS, `paragon.boards.${index}`);
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

  #encodeBoard(board, classId) {
    const catalogBoard = this.#catalog.requireBoardForClass(board.boardId, classId,
      'paragon.board');
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
      this.#catalog.requireGlyphForClass(board.glyph.glyphId, classId, 'paragon.glyph');
      output.glyph = String(board.glyph.glyphId);
      output.glyphLevel = board.glyph.level;
    }
    return output;
  }

  #decodeMercenary(mercenary) {
    assertPlain(mercenary, 'effects.mercenary');
    rejectUnknown(mercenary, KNOWN_MERCENARY_FIELDS, 'effects.mercenary');
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
    if (build.game.patch !== COMPATIBILITY.gamePatch) {
      fail(ERROR_CODES.RUNTIME_MISMATCH,
        'canonical build game patch is incompatible with this codec', {
          expected: COMPATIBILITY.gamePatch, actual: build.game.patch ?? null,
        });
    }
    // Preserve the codec's more specific fail-closed errors for unknown fields and
    // runtime compatibility before applying the public structural contract.
    validateCanonicalSchema(build);
    for (const name of ['character', 'equipment', 'skills', 'paragon', 'effects',
      'world', 'calculationContext']) assertPlain(build[name], name);
    rejectUnknown(build.game, new Set(['id', 'patch']), 'game');
    rejectUnknown(build.character, new Set(['classId', 'level', 'worldTier']), 'character');
    rejectUnknown(build.equipment, new Set(['slots']), 'equipment');
    rejectUnknown(build.skills, new Set(['allocations', 'bar']), 'skills');
    rejectUnknown(build.paragon, new Set(['boards']), 'paragon');
    rejectUnknown(build.effects,
      new Set(['elixirs', 'warPlans', 'mercenary', ...ALL_CLASS_MECHANIC_FIELDS]), 'effects');
    rejectUnknown(build.calculationContext, new Set(['season', 'options']), 'calculationContext');
    rejectUnknown(build.world, new Set(['renownSkills', 'renownParagon']), 'world');
    if (build.provenance !== undefined) {
      assertPlain(build.provenance, 'provenance');
      rejectUnknown(build.provenance,
        new Set(['codecVersion', 'sourceNativeStateSha256', 'source']), 'provenance');
    }
    this.#catalog.require('classes', build.character.classId, 'character.classId');
    if (!Number.isInteger(build.character.level) || build.character.level < 1
        || build.character.level > 70 || !Number.isInteger(build.character.worldTier)
        || build.character.worldTier < 0
        || !Array.isArray(build.equipment.slots) || !Array.isArray(build.skills.allocations)
        || !Array.isArray(build.skills.bar) || !Array.isArray(build.paragon.boards)
        || build.paragon.boards.length === 0
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
      for (const field of ['affixes', 'implicits', 'aspects', 'tempers', 'sockets']) {
        if (!Array.isArray(slot.item[field])) fail(ERROR_CODES.CANONICAL_BUILD_INVALID,
          `equipment.slots.${slot.slotId}.item.${field} must be an array`);
      }
      this.#catalog.requireItemForSlot(slot.item.baseItemId, slot.slotId,
        build.character.classId, `equipment.slots.${slot.slotId}.item.baseItemId`);
      if (!Number.isFinite(slot.item.itemPower) || slot.item.itemPower < 0) {
        fail(ERROR_CODES.CANONICAL_BUILD_INVALID,
          `equipment.slots.${slot.slotId}.item.itemPower is invalid`);
      }
      for (const field of ['affixes', 'implicits', 'aspects', 'tempers']) {
        slot.item[field].forEach((modifier, index) => {
          assertPlain(modifier, `equipment.slots.${slot.slotId}.item.${field}.${index}`);
          rejectUnknown(modifier, CANONICAL_MODIFIER_FIELDS,
            `equipment.slots.${slot.slotId}.item.${field}.${index}`);
          if (modifier.entityId == null || !Array.isArray(modifier.values)) {
            fail(ERROR_CODES.CANONICAL_BUILD_INVALID,
              `equipment.slots.${slot.slotId}.item.${field}.${index} is invalid`);
          }
          this.#catalog.requireModifierForItem(modifier.entityId, build.character.classId,
            `equipment.slots.${slot.slotId}.item.${field}.${index}.entityId`);
          if (modifier.values.some(value => typeof value !== 'number' || !Number.isFinite(value))) {
            fail(ERROR_CODES.CANONICAL_BUILD_INVALID,
              `equipment.slots.${slot.slotId}.item.${field}.${index}.values is invalid`);
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
    const allocated = new Set();
    for (const entry of build.skills.allocations) {
      if (!nodes.has(String(entry.nodeId))) {
        fail(ERROR_CODES.ENTITY_NOT_FOUND, `skill node is absent from class tree: ${entry.nodeId}`);
      }
      if (allocated.has(String(entry.nodeId)) || !Number.isInteger(entry.rank) || entry.rank < 0) {
        fail(ERROR_CODES.ILLEGAL_COMBINATION,
          `skill allocation is duplicate or invalid: ${entry.nodeId}`);
      }
      allocated.add(String(entry.nodeId));
    }
    for (const [position, skillId] of build.skills.bar.entries()) {
      if (skillId) this.#catalog.requireSkillForClass(skillId, build.character.classId,
        `skills.bar.${position}`);
    }
    for (const [index, board] of build.paragon.boards.entries()) {
      assertPlain(board, `paragon.boards.${index}`);
      rejectUnknown(board,
        new Set(['allocations', 'boardId', 'glyph', 'position', 'rotation']),
        `paragon.boards.${index}`);
      if (board.boardId == null || !Array.isArray(board.allocations)) {
        fail(ERROR_CODES.CANONICAL_BUILD_INVALID, `paragon.boards.${index} is invalid`);
      }
      const catalogBoard = this.#catalog.requireBoardForClass(board.boardId,
        build.character.classId, `paragon.boards.${index}.boardId`);
      if (![0, 1, 2, 3].includes(board.rotation)) {
        fail(ERROR_CODES.ILLEGAL_COMBINATION,
          `paragon.boards.${index}.rotation must be 0, 1, 2 or 3`);
      }
      const allocatedNodes = new Set();
      for (const allocation of board.allocations) {
        if (allocatedNodes.has(String(allocation.nodeId))
            || catalogBoard.nodes?.[Number(allocation.nodeId)] == null
            || ![0, 1, false, true].includes(allocation.value)) {
          fail(ERROR_CODES.ILLEGAL_COMBINATION,
            `paragon.boards.${index} has duplicate or invalid node ${allocation.nodeId}`);
        }
        allocatedNodes.add(String(allocation.nodeId));
      }
      if (board.glyph) this.#catalog.requireGlyphForClass(board.glyph.glyphId,
        build.character.classId, `paragon.boards.${index}.glyph.glyphId`);
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
      this.#catalog.require('mercenaries', build.effects.mercenary.id,
        'effects.mercenary.id');
      this.#catalog.require('mercenaries', build.effects.mercenary.support,
        'effects.mercenary.support');
      for (const [index, skillId] of build.effects.mercenary.supportSkills.entries()) {
        if (!/^trigger_[a-z_]+$/.test(String(skillId))) {
          this.#catalog.require('skills', skillId,
            `effects.mercenary.supportSkills.${index}`);
        }
      }
      for (const allocation of build.effects.mercenary.treeAllocations) {
        this.#catalog.requireMercenaryTreeNode(build.effects.mercenary.id,
          allocation.nodeId, 'effects.mercenary.treeAllocations');
      }
    }
    this.#validateClassMechanics(build);
    if (build.effects.warPlans.length !== this.#catalog.counts.warPlans) {
      fail(ERROR_CODES.ILLEGAL_COMBINATION,
        'effects.warPlans must represent every pinned runtime plan');
    }
    for (const [planIndex, allocations] of build.effects.warPlans.entries()) {
      assertPlain(allocations, `effects.warPlans.${planIndex}`);
      for (const [nodeId, value] of Object.entries(allocations)) {
        this.#catalog.requireWarPlanNode(planIndex, nodeId,
          `effects.warPlans.${planIndex}.${nodeId}`);
        if (![0, 1, false, true].includes(value)) fail(ERROR_CODES.CANONICAL_BUILD_INVALID,
          `effects.warPlans.${planIndex}.${nodeId} is invalid`);
      }
    }
    for (const [optionId, option] of Object.entries(build.calculationContext.options)) {
      this.#catalog.requireCalculationOption(optionId, build.character.classId,
        `calculationContext.options.${optionId}`);
      assertPlain(option, `calculationContext.options.${optionId}`);
      if (optionId === 'shared') {
        for (const [key, value] of Object.entries(option)) {
          const definition = SHARED_OPTIONS[key];
          if (!definition) fail(ERROR_CODES.ENTITY_NOT_FOUND,
            `shared calculation option is absent from pinned runtime definitions: ${key}`);
          if (!definition.types.includes(typeof value)
              || typeof value === 'number' && (!Number.isFinite(value)
                || value < definition.min || value > definition.max)) {
            fail(ERROR_CODES.CANONICAL_BUILD_INVALID,
              `calculationContext.options.shared.${key} is invalid`);
          }
        }
        continue;
      }
      rejectUnknown(option, new Set(['active', 'flags', 'params']),
        `calculationContext.options.${optionId}`);
      if (option.active !== undefined && typeof option.active !== 'boolean') {
        fail(ERROR_CODES.CANONICAL_BUILD_INVALID,
          `calculationContext.options.${optionId}.active is invalid`);
      }
      if (option.flags !== undefined && (!Array.isArray(option.flags)
          || option.flags.some(value => typeof value !== 'boolean'))) {
        fail(ERROR_CODES.CANONICAL_BUILD_INVALID,
          `calculationContext.options.${optionId}.flags is invalid`);
      }
      if (option.params !== undefined && (!Array.isArray(option.params)
          || option.params.some(value => typeof value !== 'string'
            && (typeof value !== 'number' || !Number.isFinite(value))))) {
        fail(ERROR_CODES.CANONICAL_BUILD_INVALID,
          `calculationContext.options.${optionId}.params is invalid`);
      }
    }
  }

  #validateClassMechanics(build) {
    const classId = Number(build.character.classId);
    const allowed = new Set(CLASS_MECHANIC_FIELDS[classId] ?? []);
    for (const field of ALL_CLASS_MECHANIC_FIELDS) {
      if (Object.hasOwn(build.effects, field) && !allowed.has(field)) {
        fail(ERROR_CODES.ILLEGAL_COMBINATION,
          `effects.${field} is not legal for class ${classId}`);
      }
    }
    const requireSkills = (field, values) => {
      for (const [index, id] of values.entries()) this.#catalog.requireSkillForClass(id,
        build.character.classId, `effects.${field}.${index}`);
    };
    for (const field of ['enchants', 'spiritBoons', 'minionUpgrades', 'animalSpirits']) {
      if (Object.hasOwn(build.effects, field)) requireSkills(field, build.effects[field]);
    }
    for (const field of ['specialization', 'technique', 'oath', 'warlockFragment',
      'warlockShard']) {
      if (Object.hasOwn(build.effects, field)) this.#catalog.requireSkillForClass(
        build.effects[field], build.character.classId, `effects.${field}`);
    }
    if (Object.hasOwn(build.effects, 'arsenal')) {
      for (const skillId of Object.keys(build.effects.arsenal)) this.#catalog.requireSkillForClass(
        skillId, build.character.classId, `effects.arsenal.${skillId}`);
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

function assertCatalogCompatibility(provenance) {
  const mismatches = [];
  for (const [field, expected] of [
    ['snapshotId', COMPATIBILITY.snapshotId],
    ['snapshotManifestSha256', COMPATIBILITY.snapshotManifestSha256],
    ['gameDataVersion', COMPATIBILITY.catalogVersion],
    ['resourceSha256', COMPATIBILITY.catalogResourceSha256],
  ]) if (provenance?.[field] !== expected) {
    mismatches.push({ field, expected, actual: provenance?.[field] ?? null });
  }
  if (mismatches.length) fail(ERROR_CODES.SNAPSHOT_MISMATCH,
    'catalog provenance is incompatible with the approved codec contract', { mismatches });
}

function assertFixtureCompatibility(provenance) {
  const snapshotMismatches = [];
  for (const [field, expected] of [
    ['snapshotId', COMPATIBILITY.snapshotId],
    ['snapshotManifestSha256', COMPATIBILITY.snapshotManifestSha256],
  ]) if (provenance?.[field] !== expected) {
    snapshotMismatches.push({ field, expected, actual: provenance?.[field] ?? null });
  }
  if (snapshotMismatches.length) fail(ERROR_CODES.SNAPSHOT_MISMATCH,
    'native fixture snapshot provenance is incompatible with this codec', {
      mismatches: snapshotMismatches,
    });
  const runtimeMismatches = [];
  for (const [field, expected] of [
    ['runtimeVersion', COMPATIBILITY.gamePatch],
    ['runtimeAssetSha256', COMPATIBILITY.engineAssetSha256],
  ]) if (provenance?.[field] !== expected) {
    runtimeMismatches.push({ field, expected, actual: provenance?.[field] ?? null });
  }
  if (runtimeMismatches.length) fail(ERROR_CODES.RUNTIME_MISMATCH,
    'native fixture runtime provenance is incompatible with this codec', {
      mismatches: runtimeMismatches,
    });
}

return Object.freeze({CANONICAL_SCHEMA_VERSION,CODEC_VERSION,BoundCanonicalCodec,MaxrollEntityCatalog,loadMaxrollEntityCatalog});
}
module.exports={createCodecFamily};
