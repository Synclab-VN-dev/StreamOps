'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const { sha256 } = require('../../../../browser-infra/src/snapshot/store');
// UI capture/replay destinations, not calculation compatibility bindings.
const UI_ORIGINS = Object.freeze(['https://maxroll.gg', 'https://assets-ng.maxroll.gg',
  'https://planners.maxroll.gg', 'https://fonts.googleapis.com', 'https://fonts.gstatic.com']);
async function verifyUiReceipt(config, manifest, verified) {
  const trust = config.uiTrust;
  if (!trust || trust.schemaVersion !== 'maxroll-ui-trust/v1' ||
      !/^[a-f0-9]{64}$/.test(trust.coverageSha256 || '')) throw Error('Explicit UI trust pins required');
  if (verified.manifestSha256 !== config.manifestSha256) throw Error('UI manifest trust pin mismatch');
  if (manifest.site !== 'maxroll-d4-planner-ui') throw Error('Package is not a dedicated UI capture');
  const bytes = await fs.readFile(path.join(config.snapshotRoot, config.snapshotId, 'ui-coverage.json'));
  if (sha256(bytes) !== trust.coverageSha256) throw Error('UI coverage trust pin mismatch');
  const receipt = JSON.parse(bytes);
  if (receipt.schemaVersion !== 'maxroll-ui-coverage/v1' || receipt.status !== 'CAPTURED_UNVALIDATED' ||
      receipt.calculationStatus !== 'NOT_ASSESSED' ||
      receipt.integrity?.manifestSha256 !== config.manifestSha256 || receipt.version !== manifest.version ||
      !Number.isFinite(Date.parse(receipt.startedAt)) || !Number.isFinite(Date.parse(receipt.finishedAt))) throw Error('Invalid UI provenance receipt');
  const resources = new Map(manifest.resources.map(r => [r.url, r]));
  const identities = Object.entries(receipt.fingerprints || {});
  if (identities.length < 3 || identities.some(([url, hash]) => resources.get(url)?.sha256 !== hash)) throw Error('UI runtime fingerprint mismatch');
  if (manifest.allowedOrigins.some(o => !UI_ORIGINS.includes(o))) throw Error('Unsupported UI origin');
  let status=receipt.status;
  if(trust.validationSha256 !== undefined) {
    if(!/^[a-f0-9]{64}$/.test(trust.validationSha256)) throw Error('Invalid UI validation pin');
    const validationBytes=await fs.readFile(path.join(config.snapshotRoot,config.snapshotId,'ui-validation.json'));
    if(sha256(validationBytes)!==trust.validationSha256) throw Error('UI validation trust pin mismatch');
    const validation=JSON.parse(validationBytes);
    if(validation.schemaVersion!=='maxroll-ui-validation/v1'||validation.status!=='AUTOMATED_VALIDATED'||
       validation.snapshotId!==config.snapshotId||validation.manifestSha256!==config.manifestSha256||
       validation.coverageSha256!==trust.coverageSha256||validation.calculationStatus!=='NOT_ASSESSED') throw Error('Invalid UI validation receipt');
    status=validation.status;
  }
  return { status, calculationStatus: 'NOT_ASSESSED', version: receipt.version,
    coverageSha256: trust.coverageSha256, capturedAt: manifest.capturedAt };
}
module.exports = { UI_ORIGINS, verifyUiReceipt };
