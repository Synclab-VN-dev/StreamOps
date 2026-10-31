'use strict';

const { MaxrollComponentFactory } = require('./component-factory');
const { MaxrollPatchProfile } = require('./patch-profile');
const { RealMaxrollMetricsExtractor } = require('./real-metrics-extractor');
const { RealMaxrollRuntimeAdapter } = require('./real-runtime-adapter');
const { MaxrollBuildMapper } = require('./build-mapper');
const { METRIC_CATALOG } = require('./metric-catalog');

function createRealProfile(config, reference, strategy, runtimeDefaults) {
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
      ...runtimeDefaults(strategy, reference),
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

function createProfileFamily(definition) {
function createCandidateProfile(config) {
  const defaults=(strategy,reference)=>({...definition.runtimeDefaults(strategy,reference),
    ...(definition.itemProjection ? {itemProjection:definition.itemProjection} : {})});
  return createRealProfile(config,definition.reference,definition.candidateStrategy,defaults);
}
function createUniversalProfile(config) {
  const metricCatalog = config?.metricCatalog ?? config?.catalog?.metricCatalog?.();
  const optionReadbackDefinitions = config?.realRuntime?.optionReadbackDefinitions
    ?? Object.fromEntries(Object.entries(config?.catalog?.optionReadbackDefinitions?.() ?? {})
      .map(([optionId, optionDefinition]) => [optionId,
        { ...optionDefinition, ...(definition.optionRules[optionId] ?? {}) }]));
  const { catalog: _catalog, ...profileConfig } = config ?? {};
  return createCandidateProfile({
    ...profileConfig,
    metricCatalog,
    providerVersion: profileConfig.providerVersion
      ?? definition.bindings.find(row=>row.family==='native-state/v1').providerVersion,
    supportedBuildSchemaVersion: 'd4-build/v1',
    supportedChangeTypes: [
      'build.replace', 'equipment.setSlot', 'skill.setRank', 'paragon.setBoards',
      'effect.set', 'calculationOption.set',
    ],
    capabilityRestrictions: {
      gamePatch: definition.identity.gamePatch,
      classes: 'catalog-driven:8',
      authorizedSnapshotRequired: true,
      coverageStatus: 'BLOCKED_COVERAGE',
    },
    metricCoverage: 'DYNAMIC_APPLICABLE',
    realRuntime: { ...profileConfig.realRuntime, optionReadbackDefinitions },
  });
}

return Object.freeze({createCandidateProfile,createUniversalProfile});
}
module.exports={createProfileFamily,createRealProfile,REAL_MAXROLL_COMPONENT_FACTORY};
