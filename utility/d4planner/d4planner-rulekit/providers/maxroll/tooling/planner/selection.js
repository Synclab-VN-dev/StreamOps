'use strict';
// Read the existing provider capture registry. Never mutate UI/calculation selection.
const fs = require('node:fs/promises');
const path = require('node:path');
const {createHash} = require('node:crypto');

function canonical(value) {
  const sorted = value && typeof value === 'object'
    ? Array.isArray(value) ? value.map(v => JSON.parse(canonical(v)))
      : Object.fromEntries(Object.keys(value).sort().map(k => [k, JSON.parse(canonical(value[k]))]))
    : value;
  return JSON.stringify(sorted).replace(/[\u007f-\uffff]/g, c => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0'));
}
function failure(code) { return Object.assign(new Error(code), {code}); }
async function readSelection(stateRoot, port) {
  if (!path.isAbsolute(stateRoot || '')) throw failure('PLANNER_SNAPSHOT_UNAVAILABLE');
  try {
    const file = path.join(stateRoot, 'capture-state.json');
    const stat = await fs.lstat(file);
    if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 16 * 1024 * 1024) throw Error('state');
    const envelope = JSON.parse(await fs.readFile(file, 'utf8'));
    const data = envelope.payload;
    if (envelope.sha256 !== createHash('sha256').update(canonical(data)).digest('hex') ||
        data.schemaVersion !== 'maxroll-capture-state/v1' || !Number.isSafeInteger(data.revision) || data.revision < 1) throw Error('state');
    if (!data.activeUi) throw failure('PLANNER_SNAPSHOT_UNAVAILABLE');
    const selected = data.packages[data.activeUi];
    const c = selected?.config;
    if (selected?.kind !== 'ui' || selected.validationStatus !== 'VALIDATED' ||
        selected.snapshotId !== data.activeUi || c?.snapshotId !== data.activeUi ||
        selected.manifestSha256 !== c.manifestSha256 || selected.coverageSha256 !== c.uiTrust?.coverageSha256 ||
        selected.validationSha256 !== c.uiTrust?.validationSha256 || !/^[a-f0-9]{64}$/.test(c.manifestSha256) ||
        !/^[a-f0-9]{64}$/.test(c.uiTrust?.validationSha256 || '') || !path.isAbsolute(c.snapshotRoot || '') ||
        (data.runs[selected.runId] && data.runs[selected.runId].status !== 'COMPLETE')) throw Error('selection');
    return {snapshotRoot: c.snapshotRoot, snapshotId: c.snapshotId, manifestSha256: c.manifestSha256, uiTrust: c.uiTrust, port};
  } catch (error) {
    if (error.code === 'ENOENT' || error.code === 'PLANNER_SNAPSHOT_UNAVAILABLE') throw failure('PLANNER_SNAPSHOT_UNAVAILABLE');
    throw failure('PLANNER_SNAPSHOT_UNTRUSTED');
  }
}
module.exports = {readSelection, canonical, failure};
