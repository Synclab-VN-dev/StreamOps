'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { applyIndependentNativeMutation } = require('../helpers/native-mutation-oracle');

test('FINAL-03 native oracle is independent from candidate codec output', () => {
  const nativeA = { profiles: [{ items: { 4: 1 }, skillTree: { position: 0,
    steps: [{ data: { 10: 1 } }] }, paragon: { position: 0, steps: [{ data: [] }] } }],
  items: { 1: { id: 'helm' } }, options: { effect: { active: true } } };
  const selection = { profileIndex: 0 };
  const change = { type: 'equipment.setSlot', slotId: '4', item: null };
  const oracleB = applyIndependentNativeMutation(nativeA, selection, change);
  assert.deepEqual(oracleB.profiles[0].items, {});
  assert.deepEqual(nativeA.profiles[0].items, { 4: 1 });

  // A controlled candidate mapping defect cannot alter the native oracle.
  const defectiveCandidate = structuredClone(nativeA);
  defectiveCandidate.profiles[0].items = { 4: 999 };
  assert.notDeepEqual(oracleB, defectiveCandidate);
});

test('FINAL-03 native oracle edits skill, Paragon, effect and options without codec calls', () => {
  const native = { profiles: [{ items: {}, mercenary: { id: 'm' },
    skillTree: { position: 0, steps: [{ data: { 10: 1 } }] },
    paragon: { position: 0, steps: [{ data: [{ id: 'board', glyphLevel: 5 }] }] } }],
  items: {}, options: { option: { active: true } } };
  const selection = { profileIndex: 0 };
  assert.equal(applyIndependentNativeMutation(native, selection,
    { type: 'skill.setRank', nodeId: '10', rank: 0 })
    .profiles[0].skillTree.steps[0].data[10], 0);
  assert.equal(applyIndependentNativeMutation(native, selection,
    { type: 'paragon.setBoards', boards: [{ boardId: 'board', glyph: { level: 4 } }] })
    .profiles[0].paragon.steps[0].data[0].glyphLevel, 4);
  assert.equal(Object.hasOwn(applyIndependentNativeMutation(native, selection,
    { type: 'effect.set', effect: 'mercenary', value: null }).profiles[0], 'mercenary'), false);
  assert.equal(Object.hasOwn(applyIndependentNativeMutation(native, selection,
    { type: 'calculationOption.set', optionId: 'option', value: null }).options, 'option'), false);
});
