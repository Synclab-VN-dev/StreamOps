'use strict';
// Test-only cross-execution assertion; expected must come from frozen source observation.
const assert=require('node:assert/strict');
const FIELDS=['inputItemsSha256','calculationItemsSha256','calculationItemCount','omittedSlots'];
function assertProjectionOracle(result,source,required,label){
 const actual=result.provenance?.provider?.runtimeAttestation?.profileReadback?.calculationItemProjection;
 const expected=source.profileReadback?.calculationItemProjection;
 if(!required){assert.equal(expected,undefined,label+': source has no projection policy');assert.equal(actual,undefined,label+': replay has no projection policy');return;}
 assert.ok(expected,label+': independent source projection required');
 assert.ok(actual,label+': replay projection required');
 for(const row of [expected,actual]){
  for(const key of FIELDS.slice(0,2))assert.match(row[key],/^[a-f0-9]{64}$/);
  assert.ok(Number.isInteger(row.calculationItemCount)&&row.calculationItemCount>=0);
  assert.ok(Array.isArray(row.omittedSlots)&&row.omittedSlots.every(x=>typeof x==='string'));
  assert.equal(new Set(row.omittedSlots).size,row.omittedSlots.length);
 }
 const select=row=>Object.fromEntries(FIELDS.map(key=>[key,key==='omittedSlots'?[...row[key]].sort():row[key]]));
 assert.deepEqual(select(actual),select(expected),label+': replay projection must equal independent source');
 return {state:label,expected:select(expected),actual:select(actual)};
}
module.exports={assertProjectionOracle};
