'use strict';
// Closed vocabularies only: never persist Error.message, paths or stderr.
const STAGES = new Set(['COMPOSITION', 'SNAPSHOT_MANAGER', 'CHROMIUM', 'PROVIDER', 'APPLICATION', 'IPC']);
const REASONS = new Set(['ACCESS_DENIED', 'FILE_MISSING', 'INVALID_JSON', 'MANAGER_BUSY', 'LOCK_UNVERIFIED', 'INVALID_SELECTION', 'OWNER_PID_REUSED', 'OWNER_EXITED', 'UNKNOWN']);
function fields(error, stage = 'COMPOSITION') {
  const reasons = {EACCES:'ACCESS_DENIED', EPERM:'ACCESS_DENIED', ENOENT:'FILE_MISSING',
    SNAPSHOT_MANAGER_BUSY:'MANAGER_BUSY', SNAPSHOT_LOCK_OWNERSHIP_UNKNOWN:'LOCK_UNVERIFIED',
    SNAPSHOT_LOCK_OWNERSHIP_LOST:'LOCK_UNVERIFIED', SNAPSHOT_LOCK_SYMLINK:'LOCK_UNVERIFIED',
    SNAPSHOT_SELECTION_INVALID:'INVALID_SELECTION'};
  return {errorCode:'STARTUP_FAILED', startupStage:STAGES.has(stage)?stage:'COMPOSITION',
    startupReason:Object.hasOwn(reasons,error?.code)?reasons[error.code]:(error instanceof SyntaxError?'INVALID_JSON':'UNKNOWN')};
}
module.exports = {STAGES, REASONS, fields};
