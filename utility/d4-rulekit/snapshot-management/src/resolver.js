'use strict';
const { fail, SnapshotError } = require('./trust');

/** Rule Kit owns the strategy catalog. Neither BE nor configuration can supply
 * executable strategy classes or map an unknown ID to a convenient fallback. */
class CompatibilityResolver {
  constructor({ registry, strategies }) { this.registry=registry; this.strategies=Object.freeze({...strategies}); }
  resolve(entryId, profile, manifest) {
    const entry=this.registry.resolve(entryId);
    const strategy=this.strategies[entry.strategyId];
    fail(strategy, 'RUNTIME_STRATEGY_UNAVAILABLE');
    fail(!strategy.executionVersion || entry.ruleKitVersion===strategy.executionVersion,'IMPLEMENTATION_APPROVAL_MISMATCH');
    fail(strategy.codecVersions.includes(entry.codecVersion) && strategy.canonicalSchemas.includes(entry.canonicalSchemaVersion), 'CODEC_STRATEGY_INCOMPATIBLE');
    fail(strategy.providerVersions.includes(entry.providerVersion), 'PROVIDER_STRATEGY_INCOMPATIBLE');
    fail(this.registry.scope!=='PRODUCTION' || strategy.evidenceClass==='REAL_PROVIDER','TEST_STRATEGY_NOT_PRODUCTION');
    for (const [field,expected] of Object.entries({providerVersion:entry.providerVersion,snapshotId:entry.snapshotId,snapshotManifestSha256:entry.snapshotManifestSha256,gamePatch:entry.gamePatch,sourceUrl:entry.sourceUrl,assetUrl:entry.engineAsset.url,assetSha256:entry.engineAsset.sha256,supportedBuildSchemaVersion:entry.canonicalSchemaVersion})) {
      fail(profile[field]===expected,'PROFILE_BINDING_MISMATCH:'+field);
    }
    fail(manifest.snapshotId===entry.snapshotId && manifest.sourceUrl===entry.sourceUrl,'SNAPSHOT_BINDING_MISMATCH');
    for (const resource of [entry.engineAsset,entry.catalog]) {
      fail(manifest.resources.some(row=>row.url===resource.url && row.sha256===resource.sha256),'SNAPSHOT_ASSET_BINDING_MISMATCH');
    }
    strategy.validateProfile(profile,entry);
    return {entry,strategy};
  }
}
module.exports={CompatibilityResolver};
