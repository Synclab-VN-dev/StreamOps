'use strict';
const {test}=require('node:test');const assert=require('node:assert/strict');
const {verifyRuntimeItemProjection}=require('../../src/runtime-attestation');
const policy={kind:'runtime-input-projection/v1',omittableSlots:['2'],authority:'sha256:'+'a'.repeat(64)+':synthetic-slot-capacity'};
const expected={'1':{id:'main'},'2':{id:'optional'}};
const profile={items:{'1':10,'2':20}};
const readback={items:{10:expected['1'],20:expected['2']},resolvedItems:{'1':expected['1']}};
test('preserves complete observed input and proves separate runtime subset',()=>{
 const r=verifyRuntimeItemProjection(expected,profile,readback,policy);assert.deepEqual(r.inputItems,expected);assert.deepEqual(r.omittedSlots,['2']);assert.deepEqual(r.calculationItems,{'1':expected['1']});
});
test('rejects missing/changed input, changed active value, unknown omission and invented slot',()=>{
 for(const candidate of [{...readback,items:{10:expected['1']}},{...readback,items:{10:{id:'wrong'},20:expected['2']}},{...readback,resolvedItems:{'1':{id:'wrong'}}},{...readback,resolvedItems:{}},{...readback,resolvedItems:{...readback.resolvedItems,'3':{id:'extra'}}}])assert.throws(()=>verifyRuntimeItemProjection(expected,profile,candidate,policy),e=>e.code==='READBACK_MISMATCH');
 assert.throws(()=>verifyRuntimeItemProjection(expected,profile,readback,{...policy,kind:'unknown'}),e=>e.code==='INPUT_READBACK_UNVERIFIED');
});
