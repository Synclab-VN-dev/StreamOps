'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {assertProjectionOracle}=require('./real/projection-oracle');
// Synthetic comparator tests, NOT real compatibility evidence.
const {createHash}=require('node:crypto');
const input={'1':{id:'main'},'24':{id:'optional'}};
const digest=x=>createHash('sha256').update(JSON.stringify(x)).digest('hex');
const projection={inputItemsSha256:digest(input),calculationItemsSha256:digest({'1':input['1']}),calculationItemCount:1,omittedSlots:['24']};
const source={runtimeState:{items:input},profileReadback:{calculationItemProjection:projection}};
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

test('only empty optional aspects are canonicalized; source tamper and nonempty loss fail',()=>{
 const originalItems={'1':{aspects:[],id:'main'},'24':input['24']};
 const s={runtimeState:{items:originalItems},profileReadback:{calculationItemProjection:{...projection,inputItemsSha256:digest(originalItems),calculationItemsSha256:digest({'1':originalItems['1']})}}};
 const evidence=assertProjectionOracle(result(),s,true,'empty collection');
 assert.deepEqual(evidence.normalizedPaths,['items.1.aspects']);
 assert.notEqual(evidence.originalSource.inputItemsSha256,evidence.actual.inputItemsSha256);
 const nonempty=structuredClone(s);nonempty.runtimeState.items['1'].aspects=[{nid:1,values:[3]}];
 // Stale source integrity fails before any normalization.
 assert.throws(()=>assertProjectionOracle(result(),nonempty,true,'tampered source'));
 nonempty.profileReadback.calculationItemProjection.inputItemsSha256=digest(nonempty.runtimeState.items);
 nonempty.profileReadback.calculationItemProjection.calculationItemsSha256=digest({'1':nonempty.runtimeState.items['1']});
 // Even with consistent source hashes, losing a nonempty aspect must fail.
 assert.throws(()=>assertProjectionOracle(result(),nonempty,true,'lost aspect'));
});
