'use strict';

const { CANONICAL_SCHEMA_VERSION } = require('./canonical-codec');
const { ERROR_CODES, MaxrollProviderError } = require('./errors');
const { immutable, sha256 } = require('./value');

const CHANGE_TYPES = Object.freeze([
  'build.replace',
  'equipment.setSlot',
  'skill.setRank',
  'paragon.setBoards',
  'effect.set',
  'calculationOption.set',
]);
const EFFECT_SECTIONS = Object.freeze([
  'elixirs', 'warPlans', 'mercenary', 'specialization', 'enchants', 'spiritBoons',
  'arsenal', 'expertise', 'technique', 'weaponSlot', 'minionSpec', 'minionUpgrades',
  'animalSpirits', 'oath', 'warlockFragment', 'warlockShard',
]);

class UniversalMaxrollBuildMapper {
  #codec;

  constructor(profile, { codec } = {}) {
    if (!codec || typeof codec.canonicalToNative !== 'function'
        || profile?.supportedBuildSchemaVersion !== CANONICAL_SCHEMA_VERSION) {
      throw new MaxrollProviderError(ERROR_CODES.INVALID_CONFIG,
        'universal mapper requires the pinned canonical codec and d4-build/v1 profile');
    }
    this.#codec = codec;
  }

  map(build, changes = [], buildSchemaVersion) {
    if (buildSchemaVersion !== CANONICAL_SCHEMA_VERSION) {
      throw new MaxrollProviderError(ERROR_CODES.UNSUPPORTED_INPUT,
        `unsupported build schema: ${buildSchemaVersion}`);
    }
    if (!Array.isArray(changes)) {
      throw new MaxrollProviderError(ERROR_CODES.INVALID_INPUT, 'changes must be an array');
    }
    // Validate the committed baseline before addressing nested paths so malformed input
    // always fails with the codec's typed contract instead of a JavaScript TypeError.
    this.#codec.canonicalToNative(build);
    let desired = structuredClone(build);
    for (const change of changes) desired = applyChange(desired, change);
    // Native conversion is the validation boundary. It resolves every declared entity
    // against the trusted catalog and rejects incomplete or illegal combinations.
    this.#codec.canonicalToNative(desired);
    desired = immutable(desired);
    return immutable({ desired, fingerprint: sha256(desired) });
  }
}

function applyChange(build, change) {
  if (!change || typeof change !== 'object' || Array.isArray(change)
      || !CHANGE_TYPES.includes(change.type)) {
    throw new MaxrollProviderError(ERROR_CODES.UNSUPPORTED_INPUT,
      'unsupported canonical build change');
  }
  if (change.type === 'build.replace') return structuredClone(change.build);
  const next = structuredClone(build);
  if (change.type === 'equipment.setSlot') {
    requireString(change.slotId, 'equipment.setSlot.slotId');
    const index = next.equipment.slots.findIndex(slot => slot.slotId === change.slotId);
    if (change.item === null) {
      if (index >= 0) next.equipment.slots.splice(index, 1);
    } else if (index >= 0) next.equipment.slots[index] = { slotId: change.slotId,
      item: structuredClone(change.item) };
    else next.equipment.slots.push({ slotId: change.slotId, item: structuredClone(change.item) });
  } else if (change.type === 'skill.setRank') {
    requireString(change.nodeId, 'skill.setRank.nodeId');
    if (!Number.isInteger(change.rank) || change.rank < 0) invalid('skill.setRank.rank');
    const index = next.skills.allocations.findIndex(entry => entry.nodeId === change.nodeId);
    if (change.rank === 0) {
      if (index >= 0) next.skills.allocations.splice(index, 1);
    } else if (index >= 0) next.skills.allocations[index] = { nodeId: change.nodeId,
      rank: change.rank };
    else next.skills.allocations.push({ nodeId: change.nodeId, rank: change.rank });
  } else if (change.type === 'paragon.setBoards') {
    if (!Array.isArray(change.boards)) invalid('paragon.setBoards.boards');
    next.paragon.boards = structuredClone(change.boards);
  } else if (change.type === 'effect.set') {
    if (!EFFECT_SECTIONS.includes(change.effect)) {
      throw new MaxrollProviderError(ERROR_CODES.UNSUPPORTED_INPUT,
        `unsupported effect section: ${change.effect}`);
    }
    if (change.value === null) delete next.effects[change.effect];
    else next.effects[change.effect] = structuredClone(change.value);
  } else if (change.type === 'calculationOption.set') {
    requireString(change.optionId, 'calculationOption.set.optionId');
    if (change.value === null) delete next.calculationContext.options[change.optionId];
    else next.calculationContext.options[change.optionId] = structuredClone(change.value);
  }
  return next;
}

function requireString(value, path) {
  if (typeof value !== 'string' || !value) invalid(path);
}

function invalid(path) {
  throw new MaxrollProviderError(ERROR_CODES.INVALID_INPUT, `${path} is invalid`);
}

module.exports = { CHANGE_TYPES, EFFECT_SECTIONS, UniversalMaxrollBuildMapper };
