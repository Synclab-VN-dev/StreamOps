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
