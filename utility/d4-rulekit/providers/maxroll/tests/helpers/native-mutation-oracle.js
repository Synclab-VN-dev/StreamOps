'use strict';

const assert = require('node:assert/strict');

function activeStep(container, name) {
  const step = container?.steps?.[container.position];
  assert.ok(step && typeof step === 'object', `native ${name} active step is required`);
  return step;
}

// This is deliberately a low-level native-state oracle. It must not import or
// call the canonical codec or mutation mapper under test.
function applyIndependentNativeMutation(nativeState, selection, change) {
  const output = structuredClone(nativeState);
  const profile = output.profiles?.[selection.profileIndex];
  assert.ok(profile, 'selected native profile is required');
  switch (change.type) {
    case 'equipment.setSlot':
      assert.equal(change.item, null, 'oracle currently covers deterministic slot removal');
      assert.ok(Object.hasOwn(profile.items, change.slotId), 'native equipment slot is absent');
      delete profile.items[change.slotId];
      break;
    case 'skill.setRank': {
      const data = activeStep(profile.skillTree, 'skill tree').data;
      assert.ok(Object.hasOwn(data, change.nodeId), 'native skill node is absent');
      data[change.nodeId] = change.rank;
      break;
    }
    case 'paragon.setBoards': {
      const boards = activeStep(profile.paragon, 'Paragon').data;
      for (const changedBoard of change.boards) {
        const board = boards.find(entry => String(entry.id) === String(changedBoard.boardId));
        assert.ok(board, `native Paragon board is absent: ${changedBoard.boardId}`);
        if (changedBoard.glyph) board.glyphLevel = changedBoard.glyph.level;
      }
      break;
    }
    case 'effect.set':
      assert.equal(change.value, null, 'oracle currently covers deterministic effect removal');
      assert.ok(Object.hasOwn(profile, change.effect), 'native effect is absent');
      delete profile[change.effect];
      break;
    case 'calculationOption.set':
      assert.equal(change.value, null, 'oracle currently covers deterministic option removal');
      assert.ok(Object.hasOwn(output.options, change.optionId), 'native option is absent');
      delete output.options[change.optionId];
      break;
    default:
      throw new Error(`native mutation oracle does not support ${change.type}`);
  }
  return output;
}

module.exports = { applyIndependentNativeMutation };
