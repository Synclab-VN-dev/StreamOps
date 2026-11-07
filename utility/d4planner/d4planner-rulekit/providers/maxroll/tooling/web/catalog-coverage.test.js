'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {entityDependencies,auxiliaryDependencies}=require('./catalog-coverage');
const {moduleDependencies,htmlDependencies}=require('./resource-dependencies');
const {dependencies}=require('./capture-ui');
test('selectable inventory includes class/sex artwork, not all raw records or stash instances',()=>{
  const data={items:{helm:{type:'Helm',image:12,images:[{male:13,female:14},{male:12,female:0}]},unused:{image:99}},itemSets:{set:{image:15}}};
  const coverage={groups:[{className:'Rogue',slot:4,categories:[{name:'Legendary',entities:['helm',42,'set']}]}]};
  const rows=entityDependencies(data,coverage);
  assert.equal(rows.length,1);assert.deepEqual(rows[0].images.map(i=>i.imageId),[12,13,14]);
  coverage.groups[0].categories[0].entities.push('unknown');assert.throws(()=>entityDependencies(data,coverage),/Unknown selectable/);
  assert.equal(auxiliaryDependencies(data)[0].imageId,15);
});
test('dependency closure preserves stylesheet/module origins, dynamic chunks and srcset',()=>{
  const base='https://assets-ng.maxroll.gg/d4-tools/assets/app.js';
  assert.deepEqual(moduleDependencies('import x from "./other.js"; import("./lazy.js"); import "./style.css";',base),[
    'https://assets-ng.maxroll.gg/d4-tools/assets/other.js','https://assets-ng.maxroll.gg/d4-tools/assets/lazy.js','https://assets-ng.maxroll.gg/d4-tools/assets/style.css']);
  assert.deepEqual(dependencies('@import "../main.css"; :before{mask-image:url(/mask.svg);border-image:url("frame.webp")}',base),[
    'https://assets-ng.maxroll.gg/mask.svg','https://assets-ng.maxroll.gg/d4-tools/assets/frame.webp','https://assets-ng.maxroll.gg/d4-tools/main.css']);
  assert.deepEqual(htmlDependencies('<link rel="preconnect" href="https://maxroll.gg"><img srcset="one.webp 1x, two.webp 2x"><script src="/app.js"></script>',base),[
    'https://assets-ng.maxroll.gg/d4-tools/assets/one.webp','https://assets-ng.maxroll.gg/d4-tools/assets/two.webp','https://assets-ng.maxroll.gg/app.js']);
});

test('auxiliary closure includes nested buff icons, glyph rarity arrays and socket catalog families',()=>{
  const data={skills:{skill:{buffs:[{icon:21}]}},paragonGlyphs:{glyph:{icon:[0,22,23]}},items:{rune:{type:'EffectRune',image:24},gem:{type:'Gem',image:25},soul:{type:'S15_SeasonalSocketable',image:26},quest:{type:'Quest',image:99}}};
  const rows=auxiliaryDependencies(data);assert.deepEqual([...new Set(rows.map(r=>r.imageId))].sort((a,b)=>a-b),[21,22,23,24,25,26]);
  assert(rows.some(r=>r.field==='buffs.0.icon'));assert(!rows.some(r=>r.entityId==='quest'),'Unrelated raw quest records do not establish selectable coverage');
});

test('new/uncovered native classes cannot silently receive UI validation',()=>{
  const {assertClassCoverage}=require('./catalog-coverage');
  const coverage={groups:[{className:'Rogue'},{className:'Rogue'}]};
  assert.doesNotThrow(()=>assertClassCoverage({classes:{0:{name:'Rogue'}}},coverage));
  assert.throws(()=>assertClassCoverage({classes:{0:{name:'Rogue'},1:{name:'New Native Class'}}},coverage),e=>e.code==='UNSUPPORTED_VERSION');
  assert.throws(()=>assertClassCoverage({classes:{}},coverage),e=>e.code==='UNSUPPORTED_VERSION');
});
