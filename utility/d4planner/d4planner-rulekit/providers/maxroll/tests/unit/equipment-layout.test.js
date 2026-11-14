'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {layoutFromCoverage} = require('../../tooling/planner/equipment-layout');
const provenance = {snapshotId:'test',manifestSha256:'a'.repeat(64),coverageSha256:'b'.repeat(64)};
const group = (className,slot,names) => ({className,slot,categories:names.map(name=>({name,entities:['synthetic-item']}))});
const coverage = groups => ({schemaVersion:'maxroll-selectable-coverage/v1',method:'READ_ONLY_NATIVE_CATEGORY_MODEL',groups});
test('layout is taken from each class, including repeated physical ring slots',()=>{
 const result=layoutFromCoverage(coverage([group('Sorcerer',7,['All Items','Staff','Wand']),group('Sorcerer',16,['Ring']),group('Sorcerer',17,['Ring']),group('Barbarian',8,['Two-Handed Mace']),group('Barbarian',9,['Two-Handed Sword'])]),provenance);
 assert.deepEqual(result.classes.map(c=>[c.className,c.slots.map(s=>s.providerSlotId)]),[['Sorcerer',['7','16','17']],['Barbarian',['8','9']]]);
 assert.deepEqual(result.classes[0].slots[0].itemTypes,['Staff','Wand']);
 assert.equal(result.provenance.snapshotId,'test');
});
test('missing coverage fails explicitly instead of inventing a common layout',()=>{
 for(const value of [null,{},coverage([]),coverage([group('Sorcerer',7,['Staff']),group('Sorcerer',7,['Wand'])])])
  assert.throws(()=>layoutFromCoverage(value,provenance),{code:'PLANNER_LAYOUT_UNAVAILABLE'});
});
test('empty categories do not advertise accepted item types',()=>{
 const g=group('Spiritborn',6,['Focus']);g.categories[0].entities=[];
 const result=layoutFromCoverage(coverage([g]),provenance);
 assert.deepEqual(result.classes[0].slots[0].itemTypes,[]);
});
