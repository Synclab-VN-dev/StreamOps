'use strict';

const { ERROR_CODES, MaxrollProviderError } = require('./errors');
const { immutable } = require('./value');

class MaxrollPatchProfile {
  constructor(config) {
    const runtimeKind = config?.runtimeKind ?? 'synthetic-dom-v1';
    const requiredStrings = [
      'providerVersion', 'runtimeVersion', 'gamePatch', 'snapshotId',
      'snapshotManifestSha256', 'sourceUrl', 'assetUrl', 'assetSha256',
    ];
    if (!config || requiredStrings.some(key => typeof config[key] !== 'string' || !config[key]) ||
        !/^[a-f0-9]{64}$/i.test(config.snapshotManifestSha256) ||
        !/^[a-f0-9]{64}$/i.test(config.assetSha256) ||
        !Array.isArray(config.metricCatalog) || config.metricCatalog.length === 0 ||
        !['EXACT', 'DYNAMIC_APPLICABLE'].includes(config.metricCoverage ?? 'EXACT') ||
        !['synthetic-dom-v1', 'maxroll-ui-cdp-v1'].includes(runtimeKind)) {
      throw new MaxrollProviderError(ERROR_CODES.INVALID_CONFIG, 'invalid Maxroll patch profile');
    }
    if (runtimeKind === 'synthetic-dom-v1') {
      if (!config.selectors) {
        throw new MaxrollProviderError(ERROR_CODES.INVALID_CONFIG, 'synthetic selectors are required');
      }
      for (const key of ['ready', 'buildInput', 'applyButton', 'readback', 'phase', 'metrics']) {
        if (typeof config.selectors[key] !== 'string' || !config.selectors[key]) {
          throw new MaxrollProviderError(ERROR_CODES.INVALID_CONFIG, `missing selector: ${key}`);
        }
      }
    } else {
      if (typeof config.authorizationRef !== 'string' || !config.authorizationRef) {
        throw new MaxrollProviderError(ERROR_CODES.INVALID_CONFIG,
          'real Maxroll profile requires an authorization reference');
      }
      validateRealRuntime(config.realRuntime, config.metricCatalog.length);
    }
    Object.assign(this, immutable({
      ...config,
      runtimeKind,
      supportedBuildSchemaVersion: config.supportedBuildSchemaVersion ?? 'maxroll-build/rogue-l50-v1',
      supportedChangeTypes: config.supportedChangeTypes ?? ['effect.set'],
      capabilityRestrictions: config.capabilityRestrictions ?? {
        class: 'Rogue', level: 50, difficulty: 'Torment I',
      },
      provenanceSource: config.provenanceSource ?? 'MAXROLL_CDP_RUNTIME',
      displayProvenanceSource: config.displayProvenanceSource ?? 'MAXROLL_UI_DOM',
    }));
    Object.freeze(this);
  }

  capability() {
    return immutable({
      version: `maxroll-capabilities/${this.providerVersion}`,
      policyVersion: `maxroll-profile/${this.runtimeVersion}`,
      stateModel: 'stateful',
      metricCoverage: this.metricCoverage ?? 'EXACT',
      metricIds: this.metricCatalog.map(metric => metric.id),
      changeTypes: [...this.supportedChangeTypes],
      restrictions: {
        ...this.capabilityRestrictions,
        buildSchemaVersion: this.supportedBuildSchemaVersion,
        authorizedSnapshotRequired: true,
        runtimeKind: this.runtimeKind,
      },
    });
  }
}

function validateRealRuntime(runtime, metricCatalogLength) {
  const requiredStrings = [
    'assetUrlRegex', 'captureExpression', 'newProfileButton', 'levelSelector',
    'slotLabel', 'itemBaseName', 'addModifierLabel', 'modifierPickerLabel',
    'expectedModifierEffect', 'statsSectionSelector', 'itemModifierSelector',
    'gamePatchPattern', 'classPattern', 'difficultyPattern',
  ];
  if (!runtime || requiredStrings.some(key => typeof runtime[key] !== 'string' || !runtime[key]) ||
      !Number.isInteger(runtime.breakpoint?.lineNumber) || runtime.breakpoint.lineNumber < 0 ||
      !Number.isInteger(runtime.breakpoint?.columnNumber) || runtime.breakpoint.columnNumber < 0 ||
      !Number.isInteger(runtime.expectedRawMetrics) || runtime.expectedRawMetrics <= 0 ||
      runtime.expectedRawMetrics !== metricCatalogLength ||
      !Number.isFinite(runtime.captureTimeoutMs) || runtime.captureTimeoutMs <= 0 ||
      (runtime.metricLabelAllowlist !== undefined
        && (!Array.isArray(runtime.metricLabelAllowlist)
          || runtime.metricLabelAllowlist.length === 0
          || new Set(runtime.metricLabelAllowlist).size !== runtime.metricLabelAllowlist.length)) ||
      typeof runtime.requireLevelResetTransition !== 'boolean' ||
      !validOptionalStringSet([
        runtime.slotItemSelector,
        runtime.slotItemNameSelector,
      ]) ||
      !validOptionalStringSet([
        runtime.itemEditorSelector,
        runtime.itemEditorDialogSelector,
        runtime.itemEditorCloseSelector,
      ]) ||
      !validOptionalStringSet([
        runtime.discardChangesPrompt,
        runtime.discardChangesDialogSelector,
        runtime.discardChangesConfirmButton,
      ]) ||
      !validOptionalInputStateContract(runtime) ||
      !runtime.categoryLabels || typeof runtime.categoryLabels !== 'object') {
    throw new MaxrollProviderError(ERROR_CODES.INVALID_CONFIG,
      'maxroll-ui-cdp-v1 runtime contract is incomplete');
  }
}

function validOptionalInputStateContract(runtime) {
  const values = [runtime.inputStateBreakpoint, runtime.inputStateReadbackExpression,
    runtime.inputStateEpochExpression];
  if (values.every(value => value == null)) return true;
  return Number.isInteger(runtime.inputStateBreakpoint?.lineNumber)
    && runtime.inputStateBreakpoint.lineNumber >= 0
    && Number.isInteger(runtime.inputStateBreakpoint?.columnNumber)
    && runtime.inputStateBreakpoint.columnNumber >= 0
    && typeof runtime.inputStateReadbackExpression === 'string'
    && runtime.inputStateReadbackExpression.length > 0
    && typeof runtime.inputStateEpochExpression === 'string'
    && runtime.inputStateEpochExpression.length > 0;
}

function validOptionalString(value) {
  return value == null || (typeof value === 'string' && value.length > 0);
}

function validOptionalStringSet(values) {
  if (values.every(value => value == null)) return true;
  return values.every(value => typeof value === 'string' && value.length > 0);
}

module.exports = { MaxrollPatchProfile };
