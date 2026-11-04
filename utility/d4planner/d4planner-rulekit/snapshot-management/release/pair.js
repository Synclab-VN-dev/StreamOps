'use strict';
// Release preflight only. A passing capture is never Calculation approval.
const crypto = require('node:crypto');
const hash = value => /^[a-f0-9]{64}$/.test(value || '');
class PairBlocked extends Error {
  constructor(code) { super(code); this.code = code; }
}
function requireGate(ok, code) { if (!ok) throw new PairBlocked(code); }
function fingerprints(identity) {
  requireGate(identity && typeof identity.version === 'string' && identity.version.length > 0,
    'BLOCKED_RUNTIME_IDENTITY');
  const entries = Object.entries(identity.fingerprints || {}).sort(([a], [b]) => a.localeCompare(b));
  requireGate(entries.length > 0 && entries.every(([, value]) => hash(value)), 'BLOCKED_RUNTIME_IDENTITY');
  for (const pattern of [/\/assets\/export-/, /\/game\/data\.min\.json/, /\/game\/data\.enus\.json/]) {
    requireGate(entries.some(([url]) => pattern.test(url)), 'BLOCKED_RUNTIME_IDENTITY');
  }
  return JSON.stringify([identity.version, entries]);
}
function matchCapture(report) {
  requireGate(report?.status === 'COMPLETE' && report.mode === 'all' && report.consistency === 'PASS', 'BLOCKED_CAPTURE');
  requireGate(typeof report.runId === 'string' && report.runId.length > 0 && report.packages?.length === 2, 'BLOCKED_PROVENANCE');
  const calculation = report.packages.find(p => p.kind === 'calculation');
  const ui = report.packages.find(p => p.kind === 'ui');
  requireGate(calculation && ui && calculation.snapshotId !== ui.snapshotId, 'BLOCKED_PROVENANCE');
  for (const p of [calculation, ui]) {
    requireGate(p.runId === report.runId && typeof p.snapshotId === 'string' && p.snapshotId.length > 0 && hash(p.manifestSha256), 'BLOCKED_PROVENANCE');
  }
  requireGate(calculation.compatibility !== 'PATCH_DRIFT', 'BLOCKED_COMPATIBILITY');
  requireGate(ui.validationStatus === 'VALIDATED', 'BLOCKED_UI_VALIDATION');
  const identity = fingerprints(calculation.identity);
  requireGate(identity === fingerprints(ui.identity), 'BLOCKED_PAIR_MISMATCH');
  // Deliberately contains no READY assertion. The caller must separately run the
  // existing Calculation validator/resolver against these exact manifest bytes.
  return Object.freeze({captureRunId: report.runId, calculationSnapshotId: calculation.snapshotId,
    uiSnapshotId: ui.snapshotId, calculationManifestSha256: calculation.manifestSha256,
    uiManifestSha256: ui.manifestSha256,
    runtimeIdentitySha256: crypto.createHash('sha256').update(identity).digest('hex')});
}
module.exports = {matchCapture, PairBlocked};
