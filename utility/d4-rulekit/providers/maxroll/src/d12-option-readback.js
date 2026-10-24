'use strict';

const ENGINE_SHA = '891c1f82717c50e598450575068394c6d2fe1c8d26de26f2eeed028d028997db';
const authority = suffix => `sha256:${ENGINE_SHA}:${suffix}`;

// Version-specific semantic rules observed against the pinned engine definitions.
// They are keyed by stable option/parameter identity and never selected by comparing
// runtime output with the requested value.
const D12_OPTION_READBACK_RULES = Object.freeze({
  Druid_WolfPack: Object.freeze({ flags: Object.freeze({ trailingDefault: false,
    authority: authority('registerSkill:Druid_WolfPack:flags.defaults') }) }),
  Paladin_PreTrailZeal: Object.freeze({ flags: Object.freeze({ trailingDefault: false,
    authority: authority('registerSkill:Paladin_PreTrailZeal:flags.defaults') }) }),
  Spiritborn_Centipede_Ultimate: Object.freeze({ flags: Object.freeze({ trailingDefault: false,
    authority: authority('registerSkill:Spiritborn_Centipede_Ultimate:resolved-flags.defaults') }),
  ignoredNativeFields: Object.freeze(['flags']) }),
  ParagonGlyph_008: Object.freeze({ params: Object.freeze({
    0: Object.freeze({ kind: 'exact' }),
  }), nativeParamCanonicalization: Object.freeze({
    0: Object.freeze({ kind: 'clamp-max', max: 5,
      authority: authority('registerPower:ParagonGlyph_008:params[0].max') }),
  }) }),
  Spiritborn_Plains_Passive: Object.freeze({ params: Object.freeze({
    0: Object.freeze({ kind: 'max', boundControl: Object.freeze({
      group: 'Ferocity', label: 'Stacks' }),
      authority: authority('registerSkill:Spiritborn_Plains_Passive:params[0].max') }),
  }) }),
  Spiritborn_Gorilla_Passive: Object.freeze({ params: Object.freeze({
    0: Object.freeze({ kind: 'max', boundControl: Object.freeze({
      group: 'Resolve', label: 'Stacks' }),
      authority: authority('registerSkill:Spiritborn_Gorilla_Passive:params[0].max') }),
  }) }),
  Paladin_Fervor: Object.freeze({ params: Object.freeze({
    0: Object.freeze({ kind: 'max', boundControl: Object.freeze({
      group: 'Fervor', label: 'Stacks' }),
      authority: authority('registerSkill:Paladin_Fervor:params[0].max') }),
  }) }),
  Paladin_Offensive_Aura: Object.freeze({ params: Object.freeze({
    0: Object.freeze({ kind: 'max', boundControl: Object.freeze({
      group: 'Fanaticism Aura', label: 'Stacks' }),
      authority: authority('registerSkill:Paladin_Offensive_Aura:params[0].max') }),
  }) }),
});

module.exports = { D12_OPTION_READBACK_RULES };
