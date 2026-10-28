'use strict';
// Test-only independent source comparison. Never imports the Provider/Codec under test.
const assert=require('node:assert/strict');
const {createHash}=require('node:crypto');
function ordered(value){
 if(Array.isArray(value))return value.map(ordered);
 if(value&&typeof value==='object')return Object.fromEntries(Object.keys(value).sort().map(k=>[k,ordered(value[k])]));
 return value;
}
const hash=value=>createHash('sha256').update(JSON.stringify(ordered(value))).digest('hex');
const FIELDS=['inputItemsSha256','calculationItemsSha256','calculationItemCount','omittedSlots'];
const select=row=>Object.fromEntries(FIELDS.map(key=>[key,key==='omittedSlots'?[...row[key]].sort():row[key]]));
function assertProjectionOracle(result,source,required,label){
 const actual=result.provenance?.provider?.runtimeAttestation?.profileReadback?.calculationItemProjection;
 const original=source.profileReadback?.calculationItemProjection;
 if(!required){assert.equal(original,undefined,label+': source has no projection policy');assert.equal(actual,undefined,label+': replay has no projection policy');return;}
 assert.ok(original,label+': independent source projection required');
 assert.ok(actual,label+': replay projection required');
 for(const row of [original,actual]){
  for(const key of FIELDS.slice(0,2))assert.match(row[key],/^[a-f0-9]{64}$/);
  assert.ok(Number.isInteger(row.calculationItemCount)&&row.calculationItemCount>=0);
  assert.ok(Array.isArray(row.omittedSlots)&&row.omittedSlots.every(x=>typeof x==='string'));
  assert.equal(new Set(row.omittedSlots).size,row.omittedSlots.length);
 }
 const input=source.runtimeState?.items;
 assert.ok(input&&typeof input==='object'&&!Array.isArray(input),label+': frozen source raw items required');
 for(const slot of original.omittedSlots)assert.ok(Object.hasOwn(input,slot));
 const active=items=>Object.fromEntries(Object.entries(items).filter(([slot])=>!original.omittedSlots.includes(slot)));
 assert.equal(hash(input),original.inputItemsSha256,label+': source input integrity');
 assert.equal(hash(active(input)),original.calculationItemsSha256,label+': source active integrity');
 assert.equal(Object.keys(active(input)).length,original.calculationItemCount,label+': source count integrity');
 // Existing canonical item contract: absent aspects and [] decode to the same empty
 // collection; encode omits it. Pinned source aspect iterator yields zero in both.
 // Never normalize nonempty arrays, other fields, item membership or numeric values.
 const wire=structuredClone(input),normalizedPaths=[];
 for(const [slot,item] of Object.entries(wire)){
  if(Array.isArray(item.aspects)&&item.aspects.length===0){delete item.aspects;normalizedPaths.push(`items.${slot}.aspects`);}
 }
 const expected={...select(original),inputItemsSha256:hash(wire),calculationItemsSha256:hash(active(wire))};
 assert.deepEqual(select(actual),expected,label+': replay projection must equal independent source semantics');
 return {state:label,originalSource:select(original),normalizedPaths,expected,actual:select(actual)};
}
module.exports={assertProjectionOracle};
