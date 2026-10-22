'use strict';

const { MaxrollComponentFactory } = require('./component-factory');
const { MaxrollPatchProfile } = require('./patch-profile');
const { RealMaxrollMetricsExtractor } = require('./real-metrics-extractor');
const { RealMaxrollRuntimeAdapter } = require('./real-runtime-adapter');
const { MaxrollBuildMapper } = require('./build-mapper');

const MAXROLL_32173552_REFERENCE = Object.freeze({
  gamePatch: '3.2.1.73552',
  applicationAssetPath: '/assets/export-DOjdL1l3.js',
  applicationAssetSha256: 'e796b92751d0b07be8b10eed705727467e23ba0d99eb088e87de88942c57a1f4',
  breakpoint: Object.freeze({ lineNumber: 762, columnNumber: 226096 }),
});

function createMaxroll32173552RealProfile(config) {
  if (!config || typeof config !== 'object') {
    return new MaxrollPatchProfile(config);
  }
  return new MaxrollPatchProfile({
    ...config,
    providerVersion: config.providerVersion ?? 'maxroll-provider/3.2.1.73552-real-v1',
    runtimeVersion: config.runtimeVersion ?? 'maxroll-export-DOjdL1l3/e796b927',
    gamePatch: MAXROLL_32173552_REFERENCE.gamePatch,
    assetUrl: config.assetUrl ??
      `https://maxroll.gg${MAXROLL_32173552_REFERENCE.applicationAssetPath}`,
    assetSha256: MAXROLL_32173552_REFERENCE.applicationAssetSha256,
    runtimeKind: 'maxroll-ui-cdp-v1',
    provenanceSource: 'MAXROLL_CDP_RUNTIME',
    displayProvenanceSource: 'MAXROLL_UI_DOM',
    realRuntime: {
      assetUrlRegex: 'https://maxroll\\.gg/assets/export-DOjdL1l3\\.js(?:[?#].*)?$',
      breakpoint: MAXROLL_32173552_REFERENCE.breakpoint,
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
      gamePatchPattern: 'Game version:\\s*([^\\n]+)',
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
  MAXROLL_32173552_REFERENCE,
  REAL_MAXROLL_COMPONENT_FACTORY,
  createMaxroll32173552RealProfile,
};
