'use strict';

const SNAPSHOT_ERROR_CODES = Object.freeze({
  INVALID_OPTIONS: 'INVALID_OPTIONS',
  INVALID_SNAPSHOT: 'INVALID_SNAPSHOT',
  SNAPSHOT_NOT_FOUND: 'SNAPSHOT_NOT_FOUND',
  DUPLICATE_SNAPSHOT: 'DUPLICATE_SNAPSHOT',
  INTEGRITY_MISMATCH: 'INTEGRITY_MISMATCH',
  RESOURCE_MISSING: 'RESOURCE_MISSING',
  RESOURCE_CONFLICT: 'RESOURCE_CONFLICT',
  RESOURCE_LIMIT: 'RESOURCE_LIMIT',
  STORAGE_LIMIT: 'STORAGE_LIMIT',
  STORAGE_IO: 'STORAGE_IO',
  CAPTURE_TIMEOUT: 'CAPTURE_TIMEOUT',
  CAPTURE_CANCELLED: 'CAPTURE_CANCELLED',
  POLICY_BLOCKED: 'POLICY_BLOCKED',
  SENSITIVE_RESPONSE: 'SENSITIVE_RESPONSE',
  REPLAY_MISS: 'REPLAY_MISS',
  MOUNT_INVALID: 'MOUNT_INVALID',
  MOUNT_CLEANUP_FAILED: 'MOUNT_CLEANUP_FAILED',
});

class WebSnapshotError extends Error {
  constructor(code, message, options = {}) {
    super(message, options);
    this.name = 'WebSnapshotError';
    this.code = code;
  }
}

function snapshotError(code, message, cause) {
  return new WebSnapshotError(code, message, cause ? { cause } : {});
}

module.exports = { SNAPSHOT_ERROR_CODES, WebSnapshotError, snapshotError };
