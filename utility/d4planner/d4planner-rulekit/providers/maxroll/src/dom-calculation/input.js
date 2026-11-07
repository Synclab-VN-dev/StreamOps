'use strict';
const { createHash } = require('node:crypto');
const { validateNativeState, serialize, EXPORT_SCHEMA_VERSION } = require('../build-export');
const { fail } = require('./stats');
const digest = value => createHash('sha256').update(serialize(value)).digest('hex');
function nativeInput(build) {
  if (Buffer.byteLength(JSON.stringify(build) ?? '') > 8 * 1024 * 1024) fail('DOM_INVALID_INPUT', 'Build exceeds 8 MiB');
  if (build?.schemaVersion !== EXPORT_SCHEMA_VERSION || build.format !== 'MAXROLL_NATIVE_STATE') {
    fail('DOM_BUILD_FORMAT_UNSUPPORTED', 'Expected maxroll-native-build-export/v1 Native JSON from Planner Export');
  }
  if (build.integrity?.algorithm !== 'sha256' || digest(build.nativeState) !== build.integrity.nativeStateSha256) {
    fail('DOM_INPUT_INTEGRITY', 'Native build integrity mismatch');
  }
  const state = build.nativeState;
  validateNativeState(state);
  if (!state.profiles[state.activeProfile]) fail('DOM_INVALID_INPUT', 'Active profile does not exist');
  for (const profile of state.profiles) if (!Number.isInteger(profile.class) || !Number.isInteger(profile.level)
      || profile.level < 1 || profile.level > 70) fail('DOM_INVALID_INPUT', 'Unsupported class/level');
  return structuredClone(state);
}
module.exports = { nativeInput, digest };
