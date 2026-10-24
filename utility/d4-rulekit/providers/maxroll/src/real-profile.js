'use strict';

const { MaxrollComponentFactory } = require('./component-factory');
const { MaxrollPatchProfile } = require('./patch-profile');
const { RealMaxrollMetricsExtractor } = require('./real-metrics-extractor');
const { RealMaxrollRuntimeAdapter } = require('./real-runtime-adapter');
const { MaxrollBuildMapper } = require('./build-mapper');
const { D12_SHARED_OPTION_DEFINITIONS } = require('./d12-shared-options');

const MAXROLL_32173552_REFERENCE = Object.freeze({
  gamePatch: '3.2.1.73552',
  applicationAssetPath: '/assets/export-DOjdL1l3.js',
  applicationAssetSha256: 'e796b92751d0b07be8b10eed705727467e23ba0d99eb088e87de88942c57a1f4',
  breakpoint: Object.freeze({ lineNumber: 762, columnNumber: 226096 }),
});

const MAXROLL_32173552_D12AM6KT_REFERENCE = Object.freeze({
  gamePatch: '3.2.1.73552',
  applicationAssetPath: '/assets/export-D12aM6KT.js',
  applicationAssetSha256: '891c1f82717c50e598450575068394c6d2fe1c8d26de26f2eeed028d028997db',
  breakpoint: Object.freeze({ lineNumber: 762, columnNumber: 226096 }),
});

function createMaxroll32173552RealProfile(config) {
  return createRealProfile(config, MAXROLL_32173552_REFERENCE, {
    providerVersion: 'maxroll-provider/3.2.1.73552-real-v1',
    runtimeVersion: 'maxroll-export-DOjdL1l3/e796b927',
    assetUrlRegex: 'https://maxroll\\.gg/assets/export-DOjdL1l3\\.js(?:[?#].*)?$',
    requireLevelResetTransition: true,
  });
}

function createMaxroll32173552D12aM6KTCandidateProfile(config) {
  return createRealProfile(config, MAXROLL_32173552_D12AM6KT_REFERENCE, {
    providerVersion: 'maxroll-provider/3.2.1.73552-D12aM6KT-candidate-v1',
    runtimeVersion: 'maxroll-export-D12aM6KT/891c1f82-candidate',
    assetUrlRegex: 'https://maxroll\\.gg/assets/export-D12aM6KT\\.js(?:[?#].*)?$',
    requireLevelResetTransition: false,
    slotItemSelector: '[class*="equipment_slot-4"]',
    slotItemNameSelector: '[class*="Slot__title"]',
    itemEditorSelector: '.d4t-ItemEditor',
    itemEditorDialogSelector: '[class*="_Dialog_"]',
    itemEditorCloseSelector: ':scope > [class*="DialogHeader"] button',
    discardChangesPrompt: 'Discard unsaved changes and start from a blank profile?',
    discardChangesDialogSelector: '[class*="_Dialog_"]',
    discardChangesConfirmButton: 'Yes',
    attestationReadbackExpression:
      '({profile:JSON.parse(JSON.stringify(l.profile)),items:JSON.parse(JSON.stringify(l.items)),'
      + 'optionEntries:JSON.parse(JSON.stringify(l.optionEntries||[])),'
      + 'contextPrimitives:(()=>{const out={},seen=new WeakSet();const walk=(value,path,depth)=>{'
      + 'if(!value||typeof value!=="object"||depth>4||seen.has(value))return;seen.add(value);'
      + 'for(const [key,child] of Object.entries(value)){const next=path?path+"."+key:key;'
      + 'if(["boolean","number","string"].includes(typeof child))out[next]=child;'
      + 'else walk(child,next,depth+1)}};walk(l.context||{},"",0);return out})()})',
    calculationEpochExpression: 'l.context',
    sharedOptionReadback: D12_SHARED_OPTION_DEFINITIONS,
  });
}

function createMaxroll32173552D12aM6KTUniversalProfile(config) {
  const metricCatalog = config?.metricCatalog ?? config?.catalog?.metricCatalog?.();
  const { catalog: _catalog, ...profileConfig } = config ?? {};
  return createMaxroll32173552D12aM6KTCandidateProfile({
    ...profileConfig,
    metricCatalog,
    providerVersion: profileConfig.providerVersion
      ?? 'maxroll-provider/3.2.1.73552-D12aM6KT-universal-v1',
    supportedBuildSchemaVersion: 'd4-build/v1',
    supportedChangeTypes: [
      'build.replace', 'equipment.setSlot', 'skill.setRank', 'paragon.setBoards',
      'effect.set', 'calculationOption.set',
    ],
    capabilityRestrictions: {
      gamePatch: '3.2.1.73552',
      classes: 'catalog-driven:8',
      authorizedSnapshotRequired: true,
      coverageStatus: 'BLOCKED_COVERAGE',
    },
    metricCoverage: 'DYNAMIC_APPLICABLE',
  });
}

function createRealProfile(config, reference, strategy) {
  if (!config || typeof config !== 'object') {
    return new MaxrollPatchProfile(config);
  }
  return new MaxrollPatchProfile({
    ...config,
    providerVersion: config.providerVersion ?? strategy.providerVersion,
    runtimeVersion: config.runtimeVersion ?? strategy.runtimeVersion,
    gamePatch: reference.gamePatch,
    assetUrl: config.assetUrl ??
      `https://maxroll.gg${reference.applicationAssetPath}`,
    assetSha256: reference.applicationAssetSha256,
    runtimeKind: 'maxroll-ui-cdp-v1',
    provenanceSource: 'MAXROLL_CDP_RUNTIME',
    displayProvenanceSource: 'MAXROLL_UI_DOM',
    realRuntime: {
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
      sharedOptionReadback: strategy.sharedOptionReadback ?? null,
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
      ...config.realRuntime,
    },
  });
}

const REAL_MAXROLL_COMPONENT_FACTORY = new MaxrollComponentFactory({
  runtimeKind: 'maxroll-ui-cdp-v1',
  RuntimeAdapter: RealMaxrollRuntimeAdapter,
  BuildMapper: MaxrollBuildMapper,
  MetricsExtractor: RealMaxrollMetricsExtractor,
});

module.exports = {
  MAXROLL_32173552_D12AM6KT_REFERENCE,
  MAXROLL_32173552_REFERENCE,
  REAL_MAXROLL_COMPONENT_FACTORY,
  createMaxroll32173552D12aM6KTCandidateProfile,
  createMaxroll32173552D12aM6KTUniversalProfile,
  createMaxroll32173552RealProfile,
};
