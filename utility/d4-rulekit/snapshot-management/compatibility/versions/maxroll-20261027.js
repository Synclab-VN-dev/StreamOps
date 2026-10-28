'use strict';
// r03 TEST-ONLY support. Integrity/content identity is not production approval.
// Runtime coordinates/locals and option rules require independent offline evidence.
const {deepFreeze}=require('../contracts');
const {METRIC_CATALOG}=require('../../../providers/maxroll/src/metric-catalog');
const CODEC_VERSION = 'maxroll-native/3.2.1.73552-DfjsImpl-v1';
const DFJS_COMPATIBILITY = Object.freeze({
  gamePatch: '3.2.1.73552',
  snapshotId: 'maxroll-20261027T125615Z',
  snapshotManifestSha256: '823839198d5b7f5c4621664c44e62da50d50af86baed577ddc3ec22d04b67819',
  engineAssetSha256: 'f2ec59038e226775dd7d28ec6d4197bae65eb0d9871086016828edb6f00ad3d6',
  catalogVersion: '3.2.1.73552',
  catalogResourceSha256: '889facd9fa21a0a2baba3f8c28d53ac66b6e28a7514994f82ab8f00a3a5e1f93',
});
const MAXROLL_32173552_DFJSIMPL_REFERENCE = Object.freeze({
  gamePatch: '3.2.1.73552',
  applicationAssetPath: '/assets/export-DfjsImpl.js',
  applicationAssetSha256: 'f2ec59038e226775dd7d28ec6d4197bae65eb0d9871086016828edb6f00ad3d6',
  breakpoint: Object.freeze({ lineNumber: 754, columnNumber: 226096 }),
});

const APPLICABILITY = Object.freeze({ kind: 'pinned-engine-rendered-control',
  authority: 'sha256:f2ec59038e226775dd7d28ec6d4197bae65eb0d9871086016828edb6f00ad3d6:effects-ui-option-identity' });
const flag = (group, label) => Object.freeze({ group, labels: Object.freeze([label]),
  types: Object.freeze(['boolean']), applicability: APPLICABILITY });
const number = (group, label, min, max, extra = {}) => Object.freeze({ group,
  labels: Object.freeze(Array.isArray(label) ? label : [label]), applicability: APPLICABILITY,
  types: Object.freeze(['number']), min, max, ...extra });

// Versioned from export-DfjsImpl.js sharedFlags/sharedParams/sharedOptions. These
// identities are provider data, not client-owned trust metadata.
const definitions = {
  barrier: Object.freeze({ group: 'Player',
    labels: Object.freeze(['Barrier (%)', 'Barrier active']),
    types: Object.freeze(['boolean', 'number']), min: 0, max: 100,
    applicability: APPLICABILITY }),
  unhindered: flag('Player', 'Unhindered'),
  unstoppable: flag('Player', 'Unstoppable'),
  weapon_swapping: flag('Misc', 'Weapon swapping'),
  crowd_controlled: flag('Player', 'Crowd controlled'),
  moving: flag('Player', 'Moving'),
  paragon_level: number('Player', 'Paragon Level', 0, 300),
  health: number('Player', 'Health (%)', 0, 100),
  fortify: number('Player', 'Fortify (%)', 0, 100),
  primary_resource: number('Player', ['Fury', 'Mana', 'Spirit', 'Essence', 'Energy',
    'Vigor', 'Faith', 'Offering', 'Primary Resource'], 0, 100,
  { normalize: 'percent-of-max' }),
  secondary_resource: number('Player', 'Secondary Resource', 0, 100,
    { normalize: 'percent-of-max' }),
  shapeshift_form: number('Player', 'Shapeshift Form', 0, 2,
    { options: Object.freeze(['Human', 'Werebear', 'Werewolf']) }),
  active_minions: number('Player', 'Active Minions', 0, 15),
  kill_streak: number('Misc', 'Kill Streak', 0, 6, { options: Object.freeze([
    'None', 'Killstreak', 'Carnage (100+)', 'Devastation (250+)', 'Bloodbath (500+)',
    'Massacre (1000+)', 'Fresh Meat! (9001+)',
  ]) }),
  enemy_near: flag('Distance', 'Close'), enemy_far: flag('Distance', 'Distant'),
  enemy_health: number('Enemy', 'Health (%)', 0, 100),
  enemy_type: number('Enemy', 'Type', 0, 3,
    { options: Object.freeze(['Normal', 'Champion', 'Elite', 'Boss']) }),
};

for (const [key, label] of Object.entries({
  enemy_slow: 'Slowed', enemy_immobilize: 'Immobilized', enemy_stun: 'Stunned',
  enemy_charm: 'Charmed', enemy_taunt: 'Taunted', enemy_weakened: 'Weakened',
  enemy_confused: 'Confused', enemy_disabled: 'Disabled', enemy_knockback: 'Knocked back',
  enemy_chill: 'Chilled', enemy_frozen: 'Frozen', enemy_knockdown: 'Knocked down',
  enemy_tethered: 'Tethered', enemy_fear: 'Feared', enemy_bleeding: 'Bleeding',
  enemy_burning: 'Burning', enemy_poisoned: 'Poisoned', enemy_corrupted: 'Corrupted',
  enemy_cursed: 'Cursed', enemy_trapped: 'Trapped',
  enemy_blooded: 'Affected by Blood skills', enemy_unstoppable: 'Unstoppable',
  enemy_staggered: 'Staggered', enemy_vulnerable: 'Vulnerable', enemy_moving: 'Moving',
})) definitions[key] = flag('Enemy', label);

definitions.enemy_hexed = Object.freeze({ group: 'Enemy', labels: Object.freeze(['Hexed']),
  types: Object.freeze(['boolean', 'number']), min: 0, max: 4,
  applicability: APPLICABILITY });

const DFJS_SHARED_OPTION_DEFINITIONS = Object.freeze(definitions);


const ENGINE_SHA = 'f2ec59038e226775dd7d28ec6d4197bae65eb0d9871086016828edb6f00ad3d6';
const authority = suffix => `sha256:${ENGINE_SHA}:${suffix}`;

// Version-specific semantic rules observed against the pinned engine definitions.
// They are keyed by stable option/parameter identity and never selected by comparing
// runtime output with the requested value.
const DFJS_OPTION_READBACK_RULES = Object.freeze({
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


const candidateStrategy={
    providerVersion: 'maxroll-provider/3.2.1.73552-DfjsImpl-candidate-v1',
    runtimeVersion: 'maxroll-export-DfjsImpl/f2ec5903-candidate',
    assetUrlRegex: 'https://maxroll\\.gg/assets/export-DfjsImpl\\.js(?:[?#].*)?$',
    requireLevelResetTransition: false,
    slotItemSelector: '[class*="equipment_slot-4"]',
    slotItemNameSelector: '[class*="Slot__title"]',
    itemEditorSelector: '.d4t-ItemEditor',
    itemEditorDialogSelector: '[class*="_Dialog_"]',
    itemEditorCloseSelector: ':scope > [class*="DialogHeader"] button',
    discardChangesPrompt: 'Discard unsaved changes and start from a blank profile?',
    discardChangesDialogSelector: '[class*="_Dialog_"]',
    discardChangesConfirmButton: 'Yes',
    inputStateBreakpoint: Object.freeze({ lineNumber: 662, columnNumber: 42067 }),
    inputStateReadbackExpression:
      '({profile:JSON.parse(JSON.stringify(T)),options:JSON.parse(JSON.stringify(D||{}))})',
    inputStateEpochExpression: 'K.context',
    attestationReadbackExpression:
      '({profile:JSON.parse(JSON.stringify(l.profile)),items:JSON.parse(JSON.stringify(l.items)),'
      + 'optionEntries:JSON.parse(JSON.stringify(l.optionEntries||[])),'
      + 'contextPrimitives:(()=>{const out={},seen=new WeakSet();const walk=(value,path,depth)=>{'
      + 'if(!value||typeof value!=="object"||depth>4||seen.has(value))return;seen.add(value);'
      + 'for(const [key,child] of Object.entries(value)){const next=path?path+"."+key:key;'
      + 'if(["boolean","number","string"].includes(typeof child))out[next]=child;'
      + 'else walk(child,next,depth+1)}};walk(l.context||{},"",0);return out})()})',
    calculationEpochExpression: 'l.context',
    sharedOptionReadback: DFJS_SHARED_OPTION_DEFINITIONS,
    metricDisplayCatalog: METRIC_CATALOG,
    displayOnlyMetricInventory: Object.freeze([
      ['summary', 'Damage'], ['summary', 'Poison Damage'], ['summary', 'Ring Damage'],
      ['summary', 'Shrapnel Damage'], ['summary', 'Swarm Damage'],
      ['summary', 'Swarm Poison Damage'], ['utility', 'Maximum Ferocity'],
      ['utility', 'Maximum Resolve'],
    ].map(([section, label]) => Object.freeze({ section, label,
      reason: 'pinned-DFJS-runtime-ui-row-without-heroDetails-id' }))),
};
function runtimeDefaults(strategy, reference) { return {
      assetUrlRegex: strategy.assetUrlRegex,
      breakpoint: reference.breakpoint,
      captureExpression: '({id:u&&u.id,label:f,raw:_,values:u&&u.values})',
      expectedRawMetrics: 50,
      captureTimeoutMs: 30_000,
      navigationTimeoutMs: 30_000,
      interactionTimeoutMs: 10_000,
      newProfileButton: 'New Profile',
      dismissButton: 'No Thanks',
      levelSelector: 'input[type=number][min="1"][max="70"]',
      slotLabel: 'Helm',
      itemBaseName: 'Runic Skullcap',
      addModifierLabel: 'Add Modifier',
      modifierPickerLabel: 'Dampening / Of Dampening',
      expectedModifierEffect: '+2800 Fire Resistance',
      statsSectionSelector: 'div[class*="stats_StatSection"]',
      itemModifierSelector: 'ul.d4t-item-mods > li:not(.d4t-empty)',
      requireLevelResetTransition: strategy.requireLevelResetTransition,
      slotItemSelector: strategy.slotItemSelector ?? null,
      slotItemNameSelector: strategy.slotItemNameSelector ?? null,
      itemEditorSelector: strategy.itemEditorSelector ?? null,
      itemEditorDialogSelector: strategy.itemEditorDialogSelector ?? null,
      itemEditorCloseSelector: strategy.itemEditorCloseSelector ?? null,
      discardChangesPrompt: strategy.discardChangesPrompt ?? null,
      discardChangesDialogSelector: strategy.discardChangesDialogSelector ?? null,
      discardChangesConfirmButton: strategy.discardChangesConfirmButton ?? null,
      gamePatchPattern: 'Game version:\\s*([^\\n]+)',
      attestationReadbackExpression: strategy.attestationReadbackExpression ?? null,
      calculationEpochExpression: strategy.calculationEpochExpression ?? null,
      inputStateBreakpoint: strategy.inputStateBreakpoint ?? null,
      inputStateReadbackExpression: strategy.inputStateReadbackExpression ?? null,
      inputStateEpochExpression: strategy.inputStateEpochExpression ?? null,
      sharedOptionReadback: strategy.sharedOptionReadback ?? null,
      metricDisplayCatalog: strategy.metricDisplayCatalog ?? null,
      displayOnlyMetricInventory: strategy.displayOnlyMetricInventory ?? [],
      statsWidgetSelector: '.StatsTest',
      effectsTabLabel: 'Effects',
      settingsGroupSelector: 'div[class*="settings_Group__1UIcq"]',
      settingsGroupTitleSelector: ':scope > div[class*="settings_Group__title"]',
      classPattern: 'Class\\s*\\n([^\\n]+)',
      difficultyPattern: 'Stats\\s*\\n([^\\n]+)',
      categoryLabels: {
        'CORE STATS': 'core', RESISTANCES: 'resistances', OFFENSIVE: 'offensive',
        DEFENSIVE: 'defensive', UTILITY: 'utility', PVP: 'pvp',
      },
}; }
module.exports=deepFreeze({
 definitionId:"maxroll-20261027", contractVersion:"compatibility-definition/v1",
 identity:DFJS_COMPATIBILITY, codecVersion:CODEC_VERSION,
 reference:MAXROLL_32173552_DFJSIMPL_REFERENCE,
 candidateStrategy, runtimeDefaults, sharedOptions:DFJS_SHARED_OPTION_DEFINITIONS, optionRules:DFJS_OPTION_READBACK_RULES,
 bindings:[
 {id:"maxroll-native-DFJS-v1",family:"native-state/v1",schema:"d4-build/v1",providerVersion:"maxroll-provider/3.2.1.73552-DfjsImpl-universal-v1",guardCode:"DFJS_CANONICAL_GUARD_MISMATCH"}
 ], evidenceClass:"REAL_PROVIDER"
});
