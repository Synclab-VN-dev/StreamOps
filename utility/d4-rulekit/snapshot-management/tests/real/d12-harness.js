'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const {trust}=require('../helpers');
const {TrustedRegistry,digest}=require('../../src/trust');
const {CompatibilityResolver}=require('../../src/resolver');
const {STRATEGIES,RULEKIT_VERSION}=require('../../src/strategies');
const {createCodecFamily}=require('../../../providers/maxroll/src/canonical-codec-core');
const {createProfileFamily}=require('../../../providers/maxroll/src/real-profile-core');
const {loadCatalog}=require('../../compatibility/loader');
const definition=loadCatalog().definitions.find(d=>d.definitionId===(process.env.COMPATIBILITY_TEST_DEFINITION??'maxroll-20261023'));
assert.ok(definition,'trusted test definition must be installed');
const {MaxrollProvider}=require('../../../providers/maxroll/src/provider');
const {METRIC_CATALOG}=require('../../../providers/maxroll/src/metric-catalog');
const {BrowserInfrastructure,WebSnapshotManager,FileSystemSnapshotStore}=require('../../../browser-infra/src');
const {D4RuleKitApplication}=require('../../../application/src');
// ISOLATED_TEST only: ephemeral signing key, real verified D12 bytes/provider.
async function createHarness(){
 const snapshotRoot=process.env.MAXROLL_AUTHORIZED_SNAPSHOT_ROOT;
 const fixtureRoot=process.env.MAXROLL_B0_FIXTURE_ROOT;
 assert.ok(snapshotRoot&&fixtureRoot&&process.env.BROWSER_INFRA_CHROMIUM_PATH,'explicit private offline test environment required');
 const fixture=JSON.parse(await fs.readFile(path.join(fixtureRoot,'rogue-midgame.json')));
 const expected=JSON.parse(await fs.readFile(path.join(fixtureRoot,'rogue-midgame.stats.json')));
 const family=createCodecFamily(definition),identity=definition.identity;
 const catalog=await family.loadMaxrollEntityCatalog({snapshotRoot,snapshotId:identity.snapshotId,expectedManifestSha256:identity.snapshotManifestSha256});
 const build=new family.BoundCanonicalCodec({catalog}).nativeToCanonical(fixture);
 const config={snapshotId:identity.snapshotId,snapshotManifestSha256:identity.snapshotManifestSha256,sourceUrl:fixture.provenance.sourceUrl,catalog,metricCatalog:METRIC_CATALOG,authorizationRef:'ISSUE154_ISOLATED_OFFLINE_TEST',nativeRuntime:{plannerId:fixture.provenance.plannerId,profileUrl:`https://planners.maxroll.gg/profiles/load/d4/${fixture.provenance.plannerId}`}};
 const profile=createProfileFamily(definition).createUniversalProfile(config);
 const binding=definition.bindings.find(b=>b.family==='native-state/v1');
 const entry={entryId:'d12-test',status:'APPROVED',ruleKitVersion:RULEKIT_VERSION,providerId:'maxroll',providerVersion:profile.providerVersion,codecVersion:definition.codecVersion,canonicalSchemaVersion:binding.schema,strategyId:binding.id,profileId:'d12-test',profileSha256:digest(Buffer.from(JSON.stringify(profile))),snapshotId:identity.snapshotId,snapshotManifestSha256:identity.snapshotManifestSha256,gamePatch:identity.gamePatch,sourceUrl:profile.sourceUrl,engineAsset:{url:profile.assetUrl,sha256:profile.assetSha256},catalog:{url:catalog.provenance.resourceUrl,sha256:catalog.provenance.resourceSha256},capabilities:profile.capability(),approval:{reference:'ISOLATED_TEST_NOT_PRODUCTION',evidenceSha256:digest(Buffer.from(JSON.stringify(expected))),testClass:'REAL_PROVIDER'},distribution:{permission:'PRIVATE_ONLY',reference:'EXISTING_OFFLINE_FIXTURE'}};
 entry.capabilities={stateModel:entry.capabilities.stateModel,metricIds:entry.capabilities.metricIds,changeTypes:entry.capabilities.changeTypes};
 const signed=trust([entry]);const registry=new TrustedRegistry({anchors:{TEST_ONLY:{publicKey:signed.publicKey}},ruleKitVersion:RULEKIT_VERSION,scope:'ISOLATED_TEST'});registry.accept(signed.envelope);
 const store=new FileSystemSnapshotStore({rootDir:snapshotRoot});const manifest=(await store.loadPackage(identity.snapshotId)).manifest;
 const resolver=new CompatibilityResolver({registry,strategies:STRATEGIES});
 const {strategy}=resolver.resolve(entry.entryId,profile,manifest);
 const factory=await strategy.createFactory({entry,profile,storeRoot:snapshotRoot});
 const browser=new BrowserInfrastructure({executablePath:process.env.BROWSER_INFRA_CHROMIUM_PATH,headless:true,maxContexts:1,maxQueue:1,contextOptions:{serviceWorkers:'block'}});
 const provider=new MaxrollProvider({browser,snapshots:new WebSnapshotManager({browser,store}),profile,componentFactory:factory,sessionTimeoutMs:60000});
 const alternate=JSON.parse(await fs.readFile(path.join(fixtureRoot,'rogue-endgame.json')));
 const alternateExpected=JSON.parse(await fs.readFile(path.join(fixtureRoot,'rogue-endgame.stats.json')));
 const alternateBuild=new family.BoundCanonicalCodec({catalog}).nativeToCanonical(alternate);
 return {browser,provider,build,expected,identity,alternateBuild,alternateExpected,projectionRequired:Boolean(profile.realRuntime.itemProjection)};
}
async function createComposition(){
 const h=await createHarness();await h.browser.start();
 return {application:new D4RuleKitApplication({providers:[h.provider],operationTimeoutMs:60000,cleanupTimeoutMs:30000}),close:async()=>{await h.browser.stop();assert.equal(h.browser.getStatus().state,'stopped');assert.equal(h.browser.getMetrics().currentContexts,0);}};
}
module.exports={createHarness,createComposition};
