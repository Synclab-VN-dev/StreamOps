'use strict';

const { ERROR_CODES, MaxrollProviderError } = require('./errors');
const { immutable } = require('./value');

class MaxrollPatchProfile {
  constructor(config) {
    const requiredStrings = [
      'providerVersion', 'runtimeVersion', 'gamePatch', 'snapshotId',
      'snapshotManifestSha256', 'sourceUrl', 'assetUrl', 'assetSha256',
    ];
    if (!config || requiredStrings.some(key => typeof config[key] !== 'string' || !config[key]) ||
        !/^[a-f0-9]{64}$/i.test(config.snapshotManifestSha256) ||
        !/^[a-f0-9]{64}$/i.test(config.assetSha256) ||
        !config.selectors || !Array.isArray(config.metricCatalog) || config.metricCatalog.length === 0) {
      throw new MaxrollProviderError(ERROR_CODES.INVALID_CONFIG, 'invalid Maxroll patch profile');
    }
    for (const key of ['ready', 'buildInput', 'applyButton', 'readback', 'phase', 'metrics']) {
      if (typeof config.selectors[key] !== 'string' || !config.selectors[key]) {
        throw new MaxrollProviderError(ERROR_CODES.INVALID_CONFIG, `missing selector: ${key}`);
      }
    }
    Object.assign(this, immutable({
      ...config,
      supportedBuildSchemaVersion: config.supportedBuildSchemaVersion ?? 'maxroll-build/rogue-l50-v1',
      supportedChangeTypes: config.supportedChangeTypes ?? ['effect.set'],
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
      metricIds: this.metricCatalog.map(metric => metric.id),
      changeTypes: [...this.supportedChangeTypes],
      restrictions: {
        class: 'Rogue', level: 50, difficulty: 'Torment I',
        buildSchemaVersion: this.supportedBuildSchemaVersion,
        authorizedSnapshotRequired: true,
      },
    });
  }
}

module.exports = { MaxrollPatchProfile };
