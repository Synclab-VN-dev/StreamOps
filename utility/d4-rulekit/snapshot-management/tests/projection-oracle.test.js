'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {assertProjectionOracle}=require('./real/projection-oracle');
// Synthetic comparator tests, NOT real compatibility evidence.
const projection={inputItemsSha256:'a'.repeat(64),calculationItemsSha256:'b'.repeat(64),calculationItemCount:15,omittedSlots:['24','25','26']};
const source={profileReadback:{calculationItemProjection:projection}};
const result=()=>({metrics:[{id:'unchanged',rawValue:100}],provenance:{provider:{runtimeAttestation:{profileReadback:{calculationItemProjection:structuredClone(projection)}}}}});
test('source projection comparison detects drift even when metrics remain identical',()=>{
 assertProjectionOracle(result(),source,true,'baseline');
 for(const [field,value] of Object.entries({inputItemsSha256:'c'.repeat(64),calculationItemsSha256:'d'.repeat(64),calculationItemCount:18,omittedSlots:[]})){
  const r=result();r.provenance.provider.runtimeAttestation.profileReadback.calculationItemProjection[field]=value;
  assert.deepEqual(r.metrics,result().metrics);
  assert.throws(()=>assertProjectionOracle(r,source,true,'mutated'),{code:'ERR_ASSERTION'});
 }
});
test('requires independent projection on both sides, without fallback; D12 absence stays explicit',()=>{
 assert.throws(()=>assertProjectionOracle(result(),{},true,'missing source'));
 const r=result();delete r.provenance.provider.runtimeAttestation.profileReadback.calculationItemProjection;
 assert.throws(()=>assertProjectionOracle(r,source,true,'missing replay'));
 assertProjectionOracle(r,{profileReadback:{}},false,'legacy');
 assert.throws(()=>assertProjectionOracle(result(),{profileReadback:{}},false,'unexpected policy'));
});
