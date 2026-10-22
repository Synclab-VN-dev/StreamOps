'use strict';

const { ERROR_CODES, MaxrollProviderError } = require('./errors');
const { immutable, sha256 } = require('./value');

const ALLOWED_TOP = new Set(['class', 'level', 'difficulty', 'equipment']);
const ALLOWED_ITEM = new Set(['itemId', 'modifiers']);

class MaxrollBuildMapper {
  #profile;

  constructor(profile) { this.#profile = profile; }

  map(build, changes = [], buildSchemaVersion) {
    if (buildSchemaVersion !== this.#profile.supportedBuildSchemaVersion) {
      throw new MaxrollProviderError(ERROR_CODES.UNSUPPORTED_INPUT,
        `unsupported build schema: ${buildSchemaVersion}`);
    }
    assertPlainObject(build, 'build');
    rejectUnknownKeys(build, ALLOWED_TOP, 'build');
    if (build.class !== 'Rogue' || build.level !== 50 || build.difficulty !== 'Torment I') {
      throw new MaxrollProviderError(ERROR_CODES.UNSUPPORTED_INPUT,
        'only the proven Rogue level 50 / Torment I fixture is supported');
    }
    assertPlainObject(build.equipment, 'equipment');
    if (Object.keys(build.equipment).some(slot => slot !== 'Helm')) {
      throw new MaxrollProviderError(ERROR_CODES.UNSUPPORTED_INPUT, 'only Helm is supported');
    }
    const helm = build.equipment.Helm;
    assertPlainObject(helm, 'equipment.Helm');
    rejectUnknownKeys(helm, ALLOWED_ITEM, 'equipment.Helm');
    if (helm.itemId !== 'runic-skullcap' || !Array.isArray(helm.modifiers)) {
      throw new MaxrollProviderError(ERROR_CODES.UNSUPPORTED_INPUT, 'unsupported Helm identity');
    }
    let modifiers = new Set(helm.modifiers);
    for (const modifier of modifiers) {
      if (modifier !== 'of-dampening') {
        throw new MaxrollProviderError(ERROR_CODES.UNSUPPORTED_INPUT, `unsupported modifier: ${modifier}`);
      }
    }
    if (!Array.isArray(changes)) {
      throw new MaxrollProviderError(ERROR_CODES.INVALID_INPUT, 'changes must be an array');
    }
    for (const change of changes) {
      if (!change || change.type !== 'effect.set' || change.effectId !== 'of-dampening' ||
          typeof change.active !== 'boolean') {
        throw new MaxrollProviderError(ERROR_CODES.UNSUPPORTED_INPUT, 'unsupported change request');
      }
      modifiers = new Set(modifiers);
      if (change.active) modifiers.add(change.effectId);
      else modifiers.delete(change.effectId);
    }
    const desired = immutable({
      class: 'Rogue', level: 50, difficulty: 'Torment I',
      equipment: { Helm: { itemId: 'runic-skullcap', modifiers: [...modifiers].sort() } },
    });
    return immutable({ desired, fingerprint: sha256(desired) });
  }
}

function assertPlainObject(value, name) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.getPrototypeOf(value) !== Object.prototype) {
    throw new MaxrollProviderError(ERROR_CODES.INVALID_INPUT, `${name} must be a plain object`);
  }
}

function rejectUnknownKeys(value, allowed, name) {
  const unknown = Object.keys(value).filter(key => !allowed.has(key));
  if (unknown.length) throw new MaxrollProviderError(ERROR_CODES.UNSUPPORTED_INPUT, `${name} contains unsupported fields`);
}

module.exports = { MaxrollBuildMapper };
