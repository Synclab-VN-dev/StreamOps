'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { MaxrollEntityCatalog, D12_COMPATIBILITY: pin } = require('../../src');
const families = ['classes','items','itemTypes','affixes','oldAffixes','skills','skillTrees','paragonBoards','paragonGlyphs','paragonNodes','stones','mercenaries','warPlans','temperingRecipes','itemSets','attributes'];
function fixture(overrides = {}, provenance = {}) {
 return new MaxrollEntityCatalog({ ...Object.fromEntries(families.map(f => [f, { stable: { id: 'stable', name: f } }])), profile: { secret: true }, ...overrides }, {
 snapshotId: pin.snapshotId, snapshotManifestSha256: pin.snapshotManifestSha256,
 gameDataVersion: pin.catalogVersion, resourceSha256: pin.catalogResourceSha256, ...provenance });
}
test('export preserves all 16 exact families and stable data, excluding non-catalog fields', () => {
 const data = fixture().exportFamilies();
 assert.deepEqual(Object.keys(data), families);
 assert.deepEqual(data.items.stable, {id:'stable',name:'items'});
 assert.equal(data.profile, undefined);
 assert.ok(Object.isFrozen(data.items.stable));
});
test('selection validates exact keys, missing families and codec provenance', () => {
 assert.deepEqual(Object.keys(fixture().exportFamilies(['skills','items'])), ['items','skills']);
 for(const selected of [[],['gems'],['items','items']]) assert.throws(() => fixture().exportFamilies(selected));
 assert.throws(() => fixture({attributes:undefined}).exportFamilies());
 assert.throws(() => fixture({}, {gameDataVersion:'wrong'}).exportFamilies(), {code:'SNAPSHOT_MISMATCH'});
});
const { parseArguments } = require('../../scripts/catalog-export');
test('CLI rejects ambiguous flags and parses exact subsets', () => {
 assert.deepEqual(parseArguments(['--families','items,skills','--list-families']), {families:['items','skills'],listFamilies:true});
 for(const args of [['--output'],['--unknown','x'],['--list-families','--output','x'],['--families','items','--families','skills']]) assert.throws(()=>parseArguments(args));
});
test('API output is deterministic, private, count-consistent and refuses overwrite', async t => {
 const fs=require('node:fs/promises'); const os=require('node:os'); const path=require('node:path');
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'catalog-export-'));
 t.after(()=>fs.rm(dir,{recursive:true,force:true}));
 const loader=require('../../src/canonical-codec'); const original=loader.loadMaxrollEntityCatalog;
 loader.loadMaxrollEntityCatalog=async()=>fixture();
 delete require.cache[require.resolve('../../src/catalog-export')];
 const api=require('../../src/catalog-export'); loader.loadMaxrollEntityCatalog=original;
 const options={expectedManifestSha256:pin.snapshotManifestSha256,outputPath:path.join(dir,'a.json')};
 await api.exportMaxrollGameDataCatalog(options);
 await api.exportMaxrollGameDataCatalog({...options,outputPath:path.join(dir,'b.json')});
 assert.deepEqual(await fs.readFile(options.outputPath),await fs.readFile(path.join(dir,'b.json')));
 const doc=JSON.parse(await fs.readFile(options.outputPath));
 assert.deepEqual(doc.familyCounts,(await api.listMaxrollCatalogFamilies(options)).families);
 assert.equal((await fs.stat(options.outputPath)).mode&0o777,0o600);
 assert.equal(doc.families.profile,undefined);
 await assert.rejects(api.exportMaxrollGameDataCatalog(options),{code:'OUTPUT_EXISTS'});
 await assert.rejects(api.exportMaxrollGameDataCatalog({...options,expectedManifestSha256:'bad'}),{code:'INVALID_INPUT'});
});
